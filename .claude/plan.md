# Citation Network — Plan

## Goal
Build a citation network rooted at "Attention is All You Need" (paper 0), using the
Semantic Scholar Academic Graph API, with data up to July 2026. Output a format
importable into Gephi for visualization.

## Confirmed scope (final, after recursive-expansion + influence-filtering discussion)
- **Network scope**: Recursive breadth-first expansion — not just paper 0's direct
  citers, but citers-of-citers-of-citers, etc. ("go all in").
- **Depth**: Uncapped hop count. Bounded by a time budget (5 days baseline; may
  extend to 10 — see Time budget note below) rather than a fixed depth.
- **Recursion filter — influential citations only**: Semantic Scholar tags each
  citation with `isInfluential` (their classifier's judgment of whether the
  citing paper substantively builds on the cited one, vs. a passing/background
  mention). Every direct citer of a paper is still recorded as a node/edge
  (complete immediate neighborhood), but only citers flagged `isInfluential=true`
  get added to the BFS recursion frontier (i.e. only their own citer lists get
  expanded further). No additional citation-count floor on top of this — kept
  to one clean, principled filter.
- **Why this matters**: this replaces the earlier "fully enumerate every hub"
  approach. Fetching a citer list already returns `isInfluential` per entry at
  no extra request cost, so listing cost is unchanged, but the recursion
  frontier shrinks ~5–7x per hop (assuming a ~15–20% influential rate, to be
  measured on day 1), turning "stuck around hop-1/hop-2" into plausible reach
  into hop-3/hop-4+ within the time budget.
- **Checkpointing**: Daily checkpoint + partial GEXF export, so an importable
  snapshot exists every day regardless of whether the full crawl finishes.
- **Output format**: GEXF (Gephi's native format, carries node attributes like
  title, year, authors, citation count, `isInfluential` (on edges), and an
  `expanded` flag directly).
- **API key**: Not yet obtained. Execution starts once the user provides the key.

## Scale reality (why this is bounded by time, not raw depth)
Citation graphs are power-law distributed. Rough estimates at 1 req/s (the
Semantic Scholar API key's introductory rate limit), now factoring in
influential-only recursion:

| Hop | Recursion frontier (rough est.) | Cumulative time @ 1 req/s |
|---|---|---|
| 1 | ~150k–200k listed → ~15k–40k flagged influential, queued for recursion | Hours (listing) |
| 2 | Those ~15k–40k expanded → next influential frontier ~2k–8k | Well under a day |
| 3 | ~2k–8k expanded → next frontier ~300–1,600 | Within days 2–3 |
| 4 | ~300–1,600 expanded → next frontier ~50–300 | Within days 3–5 |
| 5+ | Continues shrinking — plausible to reach within a 5–10 day budget | |

These ratios are estimates — the real influential-citation rate for AIAYN and
its descendants isn't verified yet and will be measured on day 1, which should
immediately correct these numbers. Directionally, this is a much better shape
than the earlier brute-force full-enumeration plan, which was realistically
stuck partway through hop-2 even with 10 days.

**Time budget note**: 5 days vs. 10 days was left open pending day-1 throughput
data (see prior discussion) — extending to 10 days roughly doubles reach at a
given rate limit, but the bigger lever is requesting a rate-limit increase from
Semantic Scholar after establishing usage on the introductory key, since that
scales every day's reach multiplicatively rather than just adding more days.

## Semantic Scholar API key
- **Cost**: $0 — the Graph API is free.
- **How to get one**: https://www.semanticscholar.org/product/api → "Request an
  API key" form. Key arrives by email.
- **Rate limits**: introductory limit is **1 request/second on all endpoints**.
  Higher limits can be requested later.
- Confirmed live: even a single unauthenticated request hit a 429 during testing
  — the shared public pool is heavily contended in practice. A key is effectively
  required.
- Form-filling guidance already given to user for: affiliation, application use
  (recommended "Private"), 50-word usage description, endpoints list
  (`/paper/{id}`, `/paper/{id}/citations`, `/paper/{id}/references`,
  `/paper/batch`), and requests/day estimate.

## Day-by-day plan (once API key is provided)

| Day | Focus | Details |
|---|---|---|
| 1 | Setup + hop-1 | Verify API key and real achieved rate. Build crawler: SQLite datastore (papers table + edges table + `expanded`/`isInfluential` fields), rate limiter with exponential backoff, BFS frontier queue, logging. Seed AIAYN (via arXiv:1706.03762), pull its direct citer list (~150–200k papers, all recorded as nodes/edges), measure the real influential-citation rate, and queue only the influential subset (~15k–40k) for recursion. |
| 2 | Hop-2 expansion | Expand the ~15k–40k influential hop-1 papers' citer lists. All their citers recorded as nodes/edges; only influential ones queued further. Daily checkpoint export. |
| 3 | Hop-3 expansion | Frontier now shrunk to roughly ~2k–8k. Should clear comfortably within the day, discovering hop-4 candidates. Daily checkpoint export. |
| 4 | Hop-4+ expansion | Frontier continues shrinking (~300–1,600). Depending on how the real influential rate compares to the estimate, may reach hop-5. Daily checkpoint export. |
| 5 | Stop, export, verify (or continue if extending to 10 days) | If holding at 5 days: stop crawl regardless of frontier state, run final GEXF export, sanity-check node/edge counts, open in Gephi to confirm clean import. Unexpanded nodes tagged `expanded=false`. If extending to 10: continue the same shrinking-frontier pattern, likely exhausting the reachable influential subgraph well before day 10, at which point the crawl may finish naturally rather than being cut off. |

## Architecture
- **Datastore**: SQLite, not JSON — needed for potentially large row counts,
  resumability, and crash safety across a multi-day run.
  - `papers` table: paperId (PK), title, year, authors, venue, citationCount,
    referenceCount, publicationDate, depth, expanded (bool), fieldsOfStudy
    (JSON list, added after the initial build + backfilled for the 7,148
    papers already crawled at that point via `/paper/batch`, ~15 requests)
  - `edges` table: citing_id, cited_id, isInfluential (bool)
- **Execution model**: standalone long-lived Python process on the user's
  machine (e.g. via `nohup`/`tmux`), not something run inside a single chat
  session. Must be startable, resumable, and safe to walk away from.
- **BFS order**: strict breadth-first, recursing only through edges flagged
  `isInfluential=true` (non-influential citers are still recorded as
  nodes/edges but never queued for their own expansion). This keeps the
  frontier shrinking hop over hop, and means the crawl may reach a natural
  end (frontier exhausted) rather than always being cut off by the time
  budget.
- **Known technical wrinkle (Day 1 spike)**: Semantic Scholar's citations
  endpoint pagination has practical ceilings for extremely high-citation
  papers (AIAYN, BERT, GPT-3, etc. all exceed typical offset-pagination
  limits). Needs testing against the live API and a workaround (e.g.
  date-range bucketing of citations) rather than assuming plain
  offset/limit pagination scales to 150k+ results.
- **Filter**: publication date ≤ 2026-07-31.
- **Daily checkpoint**: end-of-day GEXF snapshot exported from the live
  SQLite state, without pausing the crawl.

## Status: scaffolding built (code written, no API calls made yet)
Implemented, offline-tested (synthetic data, zero network calls), no crawl started:
- `db.py` — SQLite schema (`papers`, `edges`) + helpers. WAL mode, with an
  explicit `wal_checkpoint(TRUNCATE)` on every connection close so the `.db`
  file is always a single self-contained file (needed for git portability —
  see Windows section below).
- `api_client.py` — Semantic Scholar client: paced requests (conservative
  ~3s/request by default while unauthenticated, tightens to 1s/request
  automatically if `SEMANTIC_SCHOLAR_API_KEY` is set), retry/backoff on
  429/5xx, paginated citation fetching, defensive handling of the offset
  pagination ceiling on huge-citation papers.
- `crawler.py` — main BFS loop. Seeds from `arXiv:1706.03762`, strict
  breadth-first expansion, influential-only recursion, 2026-07-31 cutoff
  filter, periodic checkpoint export (default every 6h), clean Ctrl+C/SIGTERM
  handling (finishes current paper, checkpoints, exits).
- `export_gexf.py` — SQLite → GEXF, standalone-runnable at any time.
- `.gitattributes` — `*.db` and `*.gexf` routed through Git LFS (plain git
  will hard-reject any file over 100MB on push, and this DB is expected to
  exceed that once the crawl progresses past hop-1).
- `.gitignore` — excludes `.venv/`, `__pycache__/`, log files, and stray
  `-wal`/`-shm` sidecar files (should never exist post-clean-shutdown, but
  ignored as a safety net).

**Not started**: no API calls against the real crawl have been made. Waiting
on the user before starting the actual run.

## Continuing from a different machine (Windows, at home)
Since the SQLite DB is the crawl's entire state, `git pull` + rerun is the
resume mechanism across machines. Notes for the Windows side:

- **Git LFS**: install via `winget install GitHub.GitLFS` (or the installer
  from git-lfs.com), then run `git lfs install` once. Without this, `git
  pull` will fetch LFS *pointer* files instead of the actual `.db`/`.gexf`
  content.
- **Python env**: `python -m venv .venv` then `.venv\Scripts\activate`
  (PowerShell: `.venv\Scripts\Activate.ps1`), then
  `pip install -r requirements.txt`.
- **API key env var** (if/when obtained): PowerShell —
  `$env:SEMANTIC_SCHOLAR_API_KEY="..."` (session-only) or
  `setx SEMANTIC_SCHOLAR_API_KEY "..."` (persistent, new terminals only).
- **Running long-lived on Windows**: there's no `nohup`/`tmux` equivalent
  built in. Simplest options: (a) use WSL if available — closest to this
  Linux dev environment, supports `nohup`/nohup-style backgrounding; or (b)
  plain Windows — just leave a terminal window open running
  `python crawler.py` (closing the window kills it; minimizing is fine).
  Ctrl+C triggers the same clean-shutdown/checkpoint path either way.
- **Critical**: never `git add`/`commit` the `.db` file while the crawler is
  running. Stop it first (Ctrl+C, wait for the "Checkpoint written" log line
  confirming clean shutdown), *then* commit. Committing mid-run risks
  capturing an inconsistent snapshot.
- **Resuming**: `git pull`, then just `python crawler.py` again — it reads
  the DB's `queued` rows and continues the BFS from exactly where it left
  off. No flags needed.

## Open items / what's needed before proceeding
1. **API key** — obtained (arrived faster than the quoted 1–2 week backlog).
   Set via `.env`, picked up automatically by `api_client.py`.
2. **Language** — Python, confirmed.

## Future consideration: relaxing the influential-only filter (not yet decided)
If the influential-only crawl reaches a natural end (frontier exhausted) in a
reasonable timeframe, the user is considering a follow-up "risk run" that
expands into some or all of the currently-`skipped` papers too, for a denser
graph. Not started — purely a design note for later.

- **Isolation approach (recommended)**: once the current crawl finishes, copy
  `citation_network.db` → `citation_network_full.db` and rename
  `citation_network.gexf` → `citation_network_influential_only.gexf` before
  touching anything further. Run any follow-up crawl against the copy via
  `crawler.py --db citation_network_full.db --gexf-output
  citation_network_full.gexf` (both flags already exist). Keeps the finished,
  safe dataset completely untouched — no shared-column/shared-code-path risk
  to the good result.
- **Two different meanings of "ignore the filter", with very different risk**:
  - *Option A — one-time re-queue*: `UPDATE papers SET status='queued' WHERE
    status='skipped'` on the copy. Future newly-discovered papers still get
    filtered by `isInfluential` as before. Bounded, finite extra work.
  - *Option B — true unrestricted mode*: a new `--ignore-influential` crawler
    flag that queues everything discovered from that point on, indefinitely.
    This reopens the original combinatorial-explosion risk the influential
    filter was specifically added to avoid (see "Scale reality" above) —
    could mean days/weeks again, not hours.
  - Leaning toward Option A as the actual "safe risk" if/when this is
    revisited.
