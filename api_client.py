"""Thin, defensive client for the Semantic Scholar Graph API.

Handles: pacing between requests, retry/backoff on 429 and 5xx, and paginated
citation fetching. Designed to run unattended for days, so it never raises on
a single bad paper -- callers get None/partial results and log the rest.
"""

import logging
import os
import random
import time
from datetime import date, timedelta

import requests

log = logging.getLogger("api_client")

BASE_URL = "https://api.semanticscholar.org/graph/v1"

# Fields we need on each citing paper: enough for graph node attributes.
CITATION_FIELDS = (
    "isInfluential,"
    "citingPaper.paperId,citingPaper.title,citingPaper.year,"
    "citingPaper.authors,citingPaper.venue,citingPaper.citationCount,"
    "citingPaper.referenceCount,citingPaper.publicationDate,"
    "citingPaper.fieldsOfStudy"
)

PAPER_FIELDS = (
    "paperId,title,year,authors,venue,citationCount,referenceCount,"
    "publicationDate,fieldsOfStudy"
)

BATCH_URL = f"{BASE_URL}/paper/batch"
BATCH_SIZE = 500

# Semantic Scholar enforces "offset + limit must be < 10000" server-side on
# /citations -- plain offset pagination can never retrieve more than the
# first ~10k entries of a paper's citer list, however many it actually has.
# Confirmed live: AIAYN itself has 189,845 citations, only ~7,120 reachable
# this way. iter_citations() below works around it via date bucketing.
OFFSET_CEILING = 9_999
PAGE_LIMIT = 1000

# Wide date bounds for the initial bucket-search range when working around
# the ceiling -- deliberately generic (not tied to any one paper's own
# publication date) so this works for any paper, not just the root. Empty
# buckets outside a paper's actual citation history resolve cheaply (one
# request, zero results, no ceiling hit). Upper bound should track the
# crawler's own CUTOFF_DATE (crawler.py) -- duplicated here to keep this
# module import-independent of crawler.py.
BUCKET_SEARCH_START = date(2000, 1, 1)
BUCKET_SEARCH_END = date(2026, 7, 31)


class GaveUp(Exception):
    """Raised when a single request exhausted its retry budget."""


class OffsetCeilingError(Exception):
    """Raised when a /citations page request hits the offset+limit<10000
    server-side ceiling. Distinct from GaveUp (a transient failure) -- this
    is a permanent, deterministic limit that callers can work around via
    date-bucketed sub-queries (see iter_citations)."""


class AuthError(Exception):
    """Raised on 401/403. Deliberately NOT caught anywhere internally, so it
    propagates all the way up and crashes the run loudly. The alternative --
    treating it as just another non-retryable 4xx that returns None -- would
    make every subsequent request silently return no data, which iter_citations
    can't distinguish from "this paper genuinely has zero citations": an
    invalid/expired key would silently mark thousands of papers as fully
    expanded with 0 results instead of stopping. A loud crash overnight is far
    better than that kind of silent data corruption."""


class SemanticScholarClient:
    def __init__(
        self,
        api_key: str | None = None,
        min_interval: float | None = None,
        max_retry_seconds: float = 1800.0,
    ):
        self.api_key = api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
        # Conservative default pacing when unauthenticated: the shared public
        # pool is contested in practice (we've observed 429s on a single
        # unauthenticated call). Tighten automatically once a key is set.
        # 1.0s (exactly the documented "1 RPS" introductory limit) measured
        # ~40% 429 rate in practice on a live run -- 1.5s gives real headroom
        # instead of living right on the boundary.
        if min_interval is not None:
            self.min_interval = min_interval
        else:
            self.min_interval = 1.5 if self.api_key else 3.0
        # Time-based, not attempt-count-based: a real internet outage should
        # be outlasted rather than given up on after a handful of quick
        # retries. Default 30 minutes -- long enough to survive a real
        # outage during an unattended overnight run, without waiting forever
        # on something that's genuinely broken.
        self.max_retry_seconds = max_retry_seconds
        self._last_request_time = 0.0
        self.session = requests.Session()
        if self.api_key:
            self.session.headers["x-api-key"] = self.api_key

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        remaining = self.min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_time = time.monotonic()

    def _get(self, url: str, params: dict) -> dict | None:
        """GET with pacing + retry/backoff. Retries for up to
        max_retry_seconds (default 30 min) on transient errors before
        raising GaveUp. Returns None on other permanent (non-auth,
        non-ceiling) failures."""
        start = time.monotonic()
        attempt = 0
        while time.monotonic() - start < self.max_retry_seconds:
            self._pace()
            try:
                resp = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as exc:
                attempt += 1
                backoff = min(2**attempt, 60) + random.uniform(0, 1)
                log.warning("Network error (%s), retry %d in %.1fs", exc, attempt, backoff)
                time.sleep(backoff)
                continue

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                backoff = float(retry_after) if retry_after else min(2**attempt * 5, 120)
                backoff += random.uniform(0, 1)
                attempt += 1
                log.info("429 rate-limited, retry %d in %.1fs", attempt, backoff)
                time.sleep(backoff)
                continue

            if 500 <= resp.status_code < 600:
                backoff = min(2**attempt, 60) + random.uniform(0, 1)
                attempt += 1
                log.warning(
                    "Server error %d, retry %d in %.1fs", resp.status_code, attempt, backoff
                )
                time.sleep(backoff)
                continue

            if resp.status_code in (401, 403):
                # Deliberately fatal -- see AuthError docstring. Treating
                # this as retryable-forever would also be wrong (an invalid
                # key doesn't fix itself), so it isn't handled above either.
                raise AuthError(f"{resp.status_code} for {url}: {resp.text[:200]}")

            if resp.status_code == 400 and "offset" in resp.text.lower():
                # Hit the pagination ceiling. Distinct from other permanent
                # failures below: the caller (iter_citations) can work
                # around this specific case via date bucketing, so it needs
                # its own signal rather than the generic None.
                raise OffsetCeilingError(resp.text[:200])

            # Other 4xx: not retryable (bad paper id, etc.) -- also permanent.
            log.error("Non-retryable error %d for %s: %s", resp.status_code, url, resp.text[:200])
            return None

        # Retry budget exhausted on a *retryable* error (network/429/5xx).
        # This is transient, not a real stopping point -- the caller must
        # not treat this the same as "no more data for this paper".
        log.error(
            "Exhausted %.0fs retry budget for %s -- treating as transient failure",
            self.max_retry_seconds,
            url,
        )
        raise GaveUp(f"Exhausted {self.max_retry_seconds:.0f}s retry budget for {url}")

    def _post(self, url: str, params: dict, json_body: dict) -> list | None:
        """POST with the same pacing + retry/backoff as _get."""
        start = time.monotonic()
        attempt = 0
        while time.monotonic() - start < self.max_retry_seconds:
            self._pace()
            try:
                resp = self.session.post(url, params=params, json=json_body, timeout=30)
            except requests.RequestException as exc:
                attempt += 1
                backoff = min(2**attempt, 60) + random.uniform(0, 1)
                log.warning("Network error (%s), retry %d in %.1fs", exc, attempt, backoff)
                time.sleep(backoff)
                continue

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                backoff = float(retry_after) if retry_after else min(2**attempt * 5, 120)
                backoff += random.uniform(0, 1)
                attempt += 1
                log.info("429 rate-limited, retry %d in %.1fs", attempt, backoff)
                time.sleep(backoff)
                continue

            if 500 <= resp.status_code < 600:
                backoff = min(2**attempt, 60) + random.uniform(0, 1)
                attempt += 1
                log.warning(
                    "Server error %d, retry %d in %.1fs", resp.status_code, attempt, backoff
                )
                time.sleep(backoff)
                continue

            if resp.status_code in (401, 403):
                raise AuthError(f"{resp.status_code} for {url}: {resp.text[:200]}")

            log.error("Non-retryable error %d for %s: %s", resp.status_code, url, resp.text[:200])
            return None

        log.error(
            "Exhausted %.0fs retry budget for %s -- treating as transient failure",
            self.max_retry_seconds,
            url,
        )
        raise GaveUp(f"Exhausted {self.max_retry_seconds:.0f}s retry budget for {url}")

        log.error("Exhausted retries for %s -- treating as transient failure", url)
        raise GaveUp(f"Exhausted retries for {url}")

    def iter_fields_of_study_batches(self, paper_ids: list[str]):
        """Yields (paper_id, fields_of_study list) pairs for every id, using
        the /paper/batch endpoint (up to BATCH_SIZE ids per request)."""
        for i in range(0, len(paper_ids), BATCH_SIZE):
            chunk = paper_ids[i : i + BATCH_SIZE]
            data = self._post(
                BATCH_URL, {"fields": "paperId,fieldsOfStudy"}, {"ids": chunk}
            )
            if data is None:
                log.error("Batch fetch failed for chunk starting at index %d, skipping", i)
                continue
            for item in data:
                if item and item.get("paperId"):
                    yield item["paperId"], (item.get("fieldsOfStudy") or [])

    def resolve_paper(self, paper_id: str) -> dict | None:
        """paper_id can be a Semantic Scholar id, or a prefixed external id
        like 'arXiv:1706.03762'."""
        return self._get(f"{BASE_URL}/paper/{paper_id}", {"fields": PAPER_FIELDS})

    def _paginate_citations_page(self, paper_id: str, date_range: str | None = None):
        """Yields citation dicts for one offset-paginated sweep, optionally
        scoped to a `publicationDateOrYear` range. Raises OffsetCeilingError
        if the ceiling is hit partway through -- callers decide how to
        handle that (see iter_citations). Returns cleanly (no more items) on
        any other permanent failure or once truly exhausted."""
        offset = 0
        while True:
            if offset > OFFSET_CEILING:
                raise OffsetCeilingError(f"offset {offset} exceeds ceiling for {paper_id}")
            params = {"fields": CITATION_FIELDS, "offset": offset, "limit": PAGE_LIMIT}
            if date_range:
                params["publicationDateOrYear"] = date_range
            data = self._get(f"{BASE_URL}/paper/{paper_id}/citations", params)
            if data is None:
                return
            items = data.get("data", [])
            for item in items:
                yield item
            if len(items) < PAGE_LIMIT or "next" not in data:
                return
            offset += PAGE_LIMIT

    def _iter_citations_bucketed(self, paper_id: str, start: date, end: date):
        """Recursively halves the [start, end] date range until each bucket's
        citations fit under the offset ceiling, fetching each independently.
        Buckets are non-overlapping, so any duplication with the initial
        unscoped attempt in iter_citations is harmless (DB layer dedups on
        paper_id / edge pairs)."""
        date_range = f"{start.isoformat()}:{end.isoformat()}"
        try:
            yield from self._paginate_citations_page(paper_id, date_range=date_range)
            return
        except OffsetCeilingError:
            pass  # this bucket alone still has >~10k citations -- split further

        if start >= end:
            log.error(
                "%s: date range %s cannot be split further -- some citations in "
                "this single-day window will be missed",
                paper_id,
                date_range,
            )
            return

        mid = start + (end - start) // 2
        yield from self._iter_citations_bucketed(paper_id, start, mid)
        yield from self._iter_citations_bucketed(paper_id, mid + timedelta(days=1), end)

    def iter_citations(self, paper_id: str):
        """Yields citation dicts (each with 'isInfluential' and 'citingPaper')
        for the given paper -- ALL of them, working around the 10k offset
        ceiling via date-bucketed sub-queries when a paper has enough
        citations to hit it (in practice, so far: just the root paper, but
        this applies to any paper, e.g. a hub-level paper found deeper in
        the graph)."""
        try:
            yield from self._paginate_citations_page(paper_id)
            return  # completed via plain pagination, ceiling never hit
        except OffsetCeilingError:
            log.warning(
                "%s hit the offset ceiling on plain pagination, switching to "
                "date-bucketed fetch for the complete list",
                paper_id,
            )
        yield from self._iter_citations_bucketed(paper_id, BUCKET_SEARCH_START, BUCKET_SEARCH_END)
