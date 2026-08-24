# Citation Network — Attention Is All You Need

Recursively builds a citation network rooted at "Attention Is All You Need"
(arXiv:1706.03762) using the Semantic Scholar Graph API, exported as GEXF for
Gephi. See [.claude/plan.md](.claude/plan.md) for the full design rationale,
scale estimates, and day-by-day crawl plan.

**Status**: scaffolding built and offline-tested (synthetic data only). No
real API calls have been made yet — the crawl hasn't started.

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
python crawler.py
```

- Long-running by design — meant to be started once and left running for
  days, not run interactively to completion.
- Safe to interrupt: `Ctrl+C` finishes the current paper, checkpoints, and
  exits cleanly. Re-running `python crawler.py` resumes automatically from
  whatever's still queued in the DB — no flags needed.
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
| `.claude/plan.md` | Full design doc: scope decisions, scale estimates, day-by-day plan |
| `citation_network.db` | Crawl state (git-lfs tracked, not committed until it exists) |
| `citation_network.gexf` | Latest checkpoint export (git-lfs tracked) |
| `logs/crawler.log` | Runtime log (gitignored) |

## Design summary

- **Recursion**: strict breadth-first from the root. Every direct citer of an
  expanded paper is recorded as a node/edge, but only citers whose citation
  was flagged `isInfluential` by Semantic Scholar get queued for their own
  expansion — this keeps the frontier shrinking hop over hop instead of
  exploding combinatorially.
- **Cutoff**: papers published after 2026-07-31 are excluded.
- **Time-boxed, not depth-boxed**: the crawl runs until either the frontier
  is exhausted or you stop it — there's no fixed hop-count limit.

Full rationale and numbers are in [.claude/plan.md](.claude/plan.md).
