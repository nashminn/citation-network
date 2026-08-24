"""Thin, defensive client for the Semantic Scholar Graph API.

Handles: pacing between requests, retry/backoff on 429 and 5xx, and paginated
citation fetching. Designed to run unattended for days, so it never raises on
a single bad paper -- callers get None/partial results and log the rest.
"""

import logging
import os
import random
import time

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

# Semantic Scholar's offset-based pagination on /citations has historically
# refused to page past this point for extremely high-citation papers. If we
# hit it, we stop and mark the paper partially-expanded rather than looping.
OFFSET_CEILING = 9_999
PAGE_LIMIT = 1000


class GaveUp(Exception):
    """Raised when a single request exhausted its retry budget."""


class SemanticScholarClient:
    def __init__(
        self,
        api_key: str | None = None,
        min_interval: float | None = None,
        max_retries: int = 8,
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
        self.max_retries = max_retries
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
        """GET with pacing + retry/backoff. Returns None if retries exhausted."""
        attempt = 0
        while attempt <= self.max_retries:
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

            if resp.status_code == 400 and "offset" in resp.text.lower():
                # Hit the pagination ceiling for a very high-citation paper.
                # This is a legitimate, permanent stop -- not a transient
                # failure -- so we return None rather than raising GaveUp.
                log.warning("Offset ceiling hit for %s: %s", url, resp.text[:200])
                return None

            # Other 4xx: not retryable (bad paper id, etc.) -- also permanent.
            log.error("Non-retryable error %d for %s: %s", resp.status_code, url, resp.text[:200])
            return None

        # Retries exhausted on a *retryable* error (network/429/5xx). This is
        # transient, not a real stopping point -- the caller must not treat
        # this the same as "no more data for this paper".
        log.error("Exhausted retries for %s -- treating as transient failure", url)
        raise GaveUp(f"Exhausted retries for {url}")

    def _post(self, url: str, params: dict, json_body: dict) -> list | None:
        """POST with the same pacing + retry/backoff as _get."""
        attempt = 0
        while attempt <= self.max_retries:
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

            log.error("Non-retryable error %d for %s: %s", resp.status_code, url, resp.text[:200])
            return None

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

    def iter_citations(self, paper_id: str):
        """Yields citation dicts (each with 'isInfluential' and 'citingPaper')
        for the given paper, paginating until exhausted or the offset ceiling
        is hit. Yields nothing further if the ceiling is hit (caller should
        treat the paper as partially expanded)."""
        offset = 0
        while True:
            if offset > OFFSET_CEILING:
                log.warning("Stopping pagination for %s at offset ceiling", paper_id)
                return
            data = self._get(
                f"{BASE_URL}/paper/{paper_id}/citations",
                {"fields": CITATION_FIELDS, "offset": offset, "limit": PAGE_LIMIT},
            )
            if data is None:
                return
            items = data.get("data", [])
            for item in items:
                yield item
            if len(items) < PAGE_LIMIT or "next" not in data:
                return
            offset += PAGE_LIMIT
