# Run 3: complete root citer list, influential-only recursion

Implementation plan for the rerun confirmed with the user: fetch AIAYN's
**complete** ~189,845 direct citers (fixing the 10,000-offset pagination
ceiling bug), then recurse using the normal influential-only rule (no
`--ignore-influential`). Runs against a **new, separate DB** — neither
`citation_network.db` (finished, safe) nor `citation_network_full.db`
(Option B, stopped mid-run) are touched.

Design only — nothing implemented yet.

## The bug, restated
Semantic Scholar's `/paper/{id}/citations` enforces `offset + limit < 10000`
server-side. Plain offset pagination can never retrieve more than the first
~10,000 entries of a paper's citer list, no matter how many citations it
actually has. AIAYN has 189,845 — we only ever got 7,120 (≈3.75%).

## The fix: date-bucketed fetching
Confirmed live that `/citations` accepts a `publicationDateOrYear` range
filter (e.g. `publicationDateOrYear=2017-01-01:2017-12-31`), which scopes
results to that window. Each independently-filtered window has its own
(much smaller) result count, so it can be paginated fully without hitting
the 10k ceiling — as long as the window is narrow enough.

**Algorithm** (recursive interval splitting):
```
def fetch_bucketed(paper_id, start_date, end_date):
    # Try to fully paginate this date range.
    # If pagination completes without hitting the offset ceiling: done,
    #   all citations in [start_date, end_date] retrieved.
    # If it hits the ceiling partway through this range: the range has
    #   too many citations for one bucket. Split it in half by date and
    #   recurse into each half separately.
    #   e.g. [2023-01-01, 2023-12-31] -> [2023-01-01,2023-06-30] + [2023-07-01,2023-12-31]
    # Bottom out (should essentially never be needed) at day-level ranges.
```
- Initial call: `fetch_bucketed(root_id, "2017-01-01", "2026-07-31")` (AIAYN's
  publication year through the crawl's cutoff date).
- Citation volume is not evenly distributed across AIAYN's lifetime (growth
  has accelerated year over year), so expect early buckets (2017-2020) to
  resolve in one shot, and recent years (2023-2026) to need splitting into
  quarters or months.
- No dedup logic needed beyond what already exists: `db.insert_paper_if_new`
  and `db.add_edge` are already `INSERT OR IGNORE`, so any overlap at bucket
  boundaries is harmless.

## Where this plugs into the existing code
- **`api_client.py`**: add a new method (e.g. `iter_citations_complete`)
  that wraps the existing `iter_citations` pagination logic with the
  recursive date-splitting above. Keep the existing simple/fast path for
  papers that don't need it.
- **When to trigger bucketing**: the existing `OFFSET_CEILING` detection in
  `_get`/`iter_citations` already tells us exactly when plain pagination
  hits the wall. Simplest approach: attempt normal pagination first; if it
  hits the ceiling, fall back to bucketed fetching for the same paper rather
  than requiring an upfront citation-count check. Minor inefficiency (the
  exhausted first ~9-10 pages get re-covered by the buckets) only affects
  the rare very-high-citation papers (expected to be just the root, maybe a
  couple of others) — acceptable tradeoff for not having to plumb a
  citation-count hint through every call site.
- **`crawler.py`**: no change to the recursion rule itself — this run does
  *not* pass `--ignore-influential`, so it behaves exactly like the original
  safe crawl, just starting from a complete root citer list instead of a
  truncated one.
- **Defensive scope**: apply the same bucketing fallback to *any* paper that
  hits the ceiling during expansion, not just the root — in case a hub-level
  paper (BERT/GPT-family scale) turns up deeper in the graph later.

## Running it (once implemented)
```bash
source .env
python crawler.py --db citation_network_v3.db --gexf-output citation_network_v3.gexf
```
New `--db`/`--gexf-output` paths — a fresh file, auto-created on first run
(no manual DB creation needed). Neither existing DB is opened or modified by
this command.

## Expected impact on scale/timing
The root's citer count goes from 7,120 to ~189,845 (≈26.7x). The influential
rate observed so far (≈5.6%) is a small-paper-count estimate from the
truncated set and may not hold at full scale — recurring the "how long will
this take" analysis after the root's full list is fetched (fast, roughly
tens of buckets = tens of requests) will give a much better estimate before
committing to the full recursive run.

## Status
Bucketing implemented in `api_client.py` (`iter_citations` /
`_iter_citations_bucketed` / `_paginate_citations_page`) and validated live:
a bounded test against the real root paper confirmed the ceiling-hit ->
bucketed-fallback handoff triggers correctly and surfaces papers beyond the
old 7,120 limit (9,000 unique IDs within the first 15,000 items pulled).

Code-reviewed against three explicit requirements before the overnight run:
- **≥1.5s between requests**: confirmed structural, not just default value
  -- every network call goes through `_get`/`_post`, both call `_pace()`
  first thing in their loop, on every attempt including retries.
- **isInfluential-gated recursion**: confirmed default (`ignore_influential`
  defaults to `False`); just don't pass `--ignore-influential`.
- **No arbitrary result cap**: confirmed no hidden truncation anywhere in
  the pagination/BFS logic; the only real limit is the intentional
  2026-07-31 cutoff date (in scope, not a bug).

## Reliability hardening (added ahead of the unattended overnight run)
Prompted by "what could halt this overnight" review:
- **Time-based retry budget (30 min)**: `max_retries` (attempt-count based)
  replaced with `max_retry_seconds=1800.0` in `SemanticScholarClient`. A
  real internet outage is now outlasted for up to 30 minutes per request
  before `GaveUp` is raised, instead of giving up after ~4-10 minutes of
  attempt-count-based backoff.
- **AuthError on 401/403**: previously collapsed into the generic
  non-retryable-4xx path, which silently returns `None` -- meaning an
  expired/invalid API key would have caused every subsequent request to
  silently return "no citations," marking thousands of papers as fully
  expanded with zero data instead of surfacing the problem. Now raises a
  dedicated `AuthError`, deliberately uncaught anywhere, so it crashes
  loudly instead of corrupting data silently overnight.
- **SQLite `busy_timeout=30000`**: added in `db.py`'s `connect()`. Defends
  against a "database is locked" crash if anything else briefly touches the
  DB file while the crawler holds a lock (e.g. an inspection query timed
  badly).
- **Checkpoint export failures are non-fatal**: `crawler.py`'s `checkpoint()`
  now catches and logs any exception (disk full, IO error, etc.) instead of
  letting a single failed periodic GEXF export kill an otherwise-healthy
  multi-hour crawl. The DB remains the source of truth either way.

## Known residual risks (procedural, not code)
- **Run it via `nohup`/`tmux`, not a plain foreground terminal.** A closed
  laptop lid, SSH disconnect, or terminal app crash sends SIGHUP, which
  kills a plain foreground Python process immediately -- none of the
  in-process resilience above helps against that.
- **System memory is already under some pressure** (checked before this
  run: 15GB total, ~10GB used, ~5GB swap already in use). `export_gexf.py`
  builds the entire graph in memory before writing GEXF, so periodic
  checkpoints (every 6h by default) could add a real memory spike if the
  graph grows very large overnight. Disk space is not a concern (140GB
  free). Not changed -- flagged for awareness, not acted on.
- Very first `seed_if_needed()` call (resolving the root paper) is only
  relevant on a brand-new DB and isn't wrapped in extra retry logic beyond
  the client's own 30-min budget -- if it fails, it fails loudly and early
  (within the first ~30 min of starting), not silently deep into the night.
