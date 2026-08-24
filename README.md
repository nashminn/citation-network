# Citation Network — Attention Is All You Need

Recursively builds a citation network rooted at "Attention Is All You Need"
(arXiv:1706.03762) using the Semantic Scholar Graph API, exported as GEXF for
Gephi. See [.claude/plan.md](.claude/plan.md) for the full design rationale,
scale estimates, and day-by-day crawl plan.

**Status**: the influential-only crawl is complete — frontier naturally
exhausted, 7,199 papers / 7,224 edges, saved as `citation_network.db` /
`citation_network_influential_only.gexf`. A second, higher-risk unrestricted
pass ("Option B" — see Design summary below) is available via
`--ignore-influential`, running against an isolated copy
(`citation_network_full.db`) so the finished dataset can't be affected.

## Setup

### 1. Git LFS
The SQLite DB and GEXF exports are tracked via Git LFS (`.gitattributes`) —
they're expected to exceed GitHub's 100MB plain-git file limit once the crawl
progresses past the first hop. Install it **once per machine**, before your
first commit or pull involving `.db`/`.gexf` files:

```bash
# Linux (Debian/Ubuntu)
sudo apt install git-lfs
git lfs install            # once per machine, this repo needs it
```

```powershell
# Windows
winget install GitHub.GitLFS
git lfs install
```

Without this, `git pull` fetches LFS *pointer* files instead of the actual
data, and `git add` on tracked file types will fail if LFS isn't active.

### 2. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. API key
Copy `.env.example` to `.env` and paste your real key in:

```bash
cp .env.example .env
# edit .env, replace the placeholder with your actual key
```

`.env` is gitignored (never committed — it's a secret, and it doesn't sync
across machines via git). Before every run, source it so the key is in your
shell's environment:

```bash
source .env
python crawler.py
```

The crawler reads `SEMANTIC_SCHOLAR_API_KEY` from the environment
automatically and tightens its request pacing (from ~3s/request down to
1s/request) the moment it sees a key — no code changes needed. If you ever
run without sourcing `.env` first, it just falls back to the slower
unauthenticated pacing rather than failing.

On Windows, `.env`'s `export ...` syntax isn't natively sourceable in
PowerShell — set the variable directly instead:
```powershell
$env:SEMANTIC_SCHOLAR_API_KEY="..."            # session-only
setx SEMANTIC_SCHOLAR_API_KEY "..."            # persistent, new terminals only
```

## Running

```bash
source .venv/bin/activate    # networkx/requests live in the venv, not system python
source .env                  # loads SEMANTIC_SCHOLAR_API_KEY
python crawler.py
```

Or without activating the venv, in one line each time:
```bash
source .env
.venv/bin/python crawler.py
```

Plain `python3 crawler.py` (system Python, no venv) will fail with
`ModuleNotFoundError: No module named 'networkx'` — the venv isn't optional.

- Long-running by design — meant to be started once and left running for
  days, not run interactively to completion.
- **To stop it**: press `Ctrl+C` in the terminal it's running in (or
  `kill <pid>` if backgrounded via `nohup`). It finishes the paper currently
  in progress, writes a final GEXF checkpoint, and exits cleanly — wait for
  the "Checkpoint written" log line before closing the terminal or powering
  off, rather than killing the process/terminal outright.
- **To resume**: run the same command again (`source .env && python
  crawler.py`) — it picks up automatically from whatever's still `queued` in
  `citation_network.db`. No flags needed.
- On Linux, background it with `nohup python crawler.py &` or run it in
  `tmux`/`screen`.
- On Windows there's no direct `nohup` equivalent: either use WSL (closest to
  this dev environment), or just leave a terminal window open running
  `python crawler.py` (minimizing is fine, closing the window kills it).
- Checkpoints (a fresh `citation_network.gexf` export) are written
  automatically every 6 hours by default (`--checkpoint-hours` to change),
  and once more on exit.
- To export a GEXF snapshot manually at any time, without stopping the
  crawler: `python export_gexf.py`.

### Running the unrestricted ("Option B") pass

A separate, isolated run that ignores the `isInfluential` filter entirely —
every newly-discovered citer gets queued for its own expansion, not just
influential ones. This reopens the combinatorial-explosion risk the filter
was added to avoid (could run for days, not ~78 minutes like the influential-
only crawl did) — see `.claude/plan.md`'s "Future consideration" section for
the full tradeoff writeup.

It runs against `citation_network_full.db`, a separate file from
`citation_network.db` — the finished influential-only dataset is never
touched by this, regardless of how the unrestricted run goes:

```bash
source .env
python crawler.py --db citation_network_full.db --gexf-output citation_network_full.gexf --ignore-influential
```

Same stop/resume/checkpoint behavior as the normal run — just pointed at the
different DB/output files, with the flag set.

## Committing / syncing across machines

The SQLite DB (`citation_network.db`) is the crawl's entire state — `git
pull` + rerun is how you resume on a different machine.

**Never commit while the crawler is running.** Stop it first (`Ctrl+C`, wait
for the "Checkpoint written" log line confirming clean shutdown), *then*
`git add` / `git commit`. Committing mid-run risks capturing an inconsistent
snapshot.

## Files

| File | Purpose |
|---|---|
| `crawler.py` | Main entry point — the long-running BFS crawl |
| `db.py` | SQLite schema (`papers`, `edges`) and data-access helpers |
| `api_client.py` | Semantic Scholar HTTP client: pacing, retry/backoff, pagination |
| `export_gexf.py` | SQLite → GEXF export, standalone-runnable |
| `backfill_fields_of_study.py` | One-off: backfill `fields_of_study` for papers crawled before that field existed |
| `INSPECTING_DB.md` | How to query/inspect the DB and log while the crawler runs |
| `.claude/plan.md` | Full design doc: scope decisions, scale estimates, day-by-day plan |
| `citation_network.db` | Finished influential-only crawl state (git-lfs tracked) |
| `citation_network_influential_only.gexf` | Finished influential-only export (git-lfs tracked) |
| `citation_network_full.db` | Isolated copy for the unrestricted ("Option B") pass (git-lfs tracked) |
| `citation_network_full.gexf` | Unrestricted pass's checkpoint export, once that run produces one |
| `logs/crawler.log` | Runtime log (gitignored) |

## Design summary

- **Recursion**: strict breadth-first from the root. Every direct citer of an
  expanded paper is recorded as a node/edge, but only citers whose citation
  was flagged `isInfluential` by Semantic Scholar get queued for their own
  expansion — this keeps the frontier shrinking hop over hop instead of
  exploding combinatorially. In practice this ran to full completion (frontier
  naturally exhausted) in ~78 minutes: 7,199 papers, 7,224 edges.
- **`--ignore-influential` ("Option B")**: an opt-in override that queues
  every discovered citer regardless of the flag, for a denser but much
  riskier graph. Always run against an isolated DB copy (`--db`), never the
  finished dataset.
- **Cutoff**: papers published after 2026-07-31 are excluded.
- **Time-boxed, not depth-boxed**: the crawl runs until either the frontier
  is exhausted or you stop it — there's no fixed hop-count limit.

Full rationale and numbers are in [.claude/plan.md](.claude/plan.md).
