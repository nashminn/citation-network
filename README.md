# Citation Network — Attention Is All You Need

Recursively builds a citation network rooted at "Attention Is All You Need"
(arXiv:1706.03762) using the Semantic Scholar Graph API, exported as GEXF for
Gephi. See [.claude/plan.md](.claude/plan.md) for the full design rationale,
scale estimates, and day-by-day crawl plan.

**Status**: the crawl reached full convergence at **1,020,536 papers /
3,036,024 edges**, run with `--ignore-influential` against
`citation_network_v3.db` (git-lfs tracked, committed) and checkpointed along
the way at depth 1 (643,732 nodes) and depth 2 (886,531 nodes) via
`snapshot_depth.py`. This is the dataset behind `ANALYSIS_RESULTS.md` and
the `analysis/` pipeline (see "Analysis pipeline" below) — if you just want
to reproduce the analysis/figures, you don't need to re-run the crawl at
all, since the finished database is already committed.

An earlier, much smaller influential-only run (7,199 papers / 7,224 edges,
`citation_network.db`) and an isolated `citation_network_full.db` also exist
from earlier iterations of this project (see Design summary below for what
`--ignore-influential` means) — both superseded by the v3 crawl above.

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

### Reproducing the v3 dataset (the one the analysis pipeline uses)

Plain `python crawler.py` (no flags) targets the small, historical
`citation_network.db` described in Design summary below — it will **not**
reproduce the 1,020,536-node dataset the analysis pipeline and
`ANALYSIS_RESULTS.md` are built on. That dataset was produced with:

```bash
source .env
python crawler.py --db citation_network_v3.db --gexf-output citation_network_v3.gexf --ignore-influential
```

run alongside a snapshot watcher in a second terminal, which polls the DB
and takes a checkpoint once the whole crawl converges (queue empties):

```bash
python snapshot_depth.py --db citation_network_v3.db --note "full convergence"
```

(`--depth 1` / `--depth 2` instead of omitting `--depth` is how the
intermediate depth-1/depth-2 checkpoints mentioned in Status above were
taken, if you want those too — see `python snapshot_depth.py --help`.)

This crawl runs for **about a week** of real time due to API rate limits —
it isn't something you'd casually rerun just to reproduce the analysis. If
that's your goal, skip straight to "Analysis pipeline" below and use the
already-committed `citation_network_v3.db`.

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

## Analysis pipeline

Once `citation_network_v3.db` is populated — either by pulling it via Git
LFS (the finished database is already committed, see Git LFS setup above)
or by running the crawl yourself (previous section) — the `analysis/`
folder reproduces every number, figure, and table in
`ANALYSIS_RESULTS.md`, in seconds to minutes rather than the hours a
1M-node graph takes in Gephi directly. See `ANALYSIS_PIPELINE.md` for the
full design rationale (it maps each stage to a chapter of Barabási's
*Network Science*).

```bash
source .venv/bin/activate     # requirements.txt also covers igraph, powerlaw, pandas, matplotlib
cd analysis
python stage0_load_clean.py           # builds + caches an igraph.Graph (analysis/cache/graph.pkl, gitignored)
python stage1_basic_stats.py
python stage2_degree_distribution.py
python stage3_preferential_attachment.py
python stage4_small_world.py
python stage5_hubs_inequality.py
python stage6_robustness.py
python stage7_community_detection.py
python stage8_gephi_subgraph.py       # writes filtered_subgraph.gexf
python stage9_field_branching.py      # writes field_focused_subgraph.gexf + its figures
```

Run `stage0` first — every later stage loads its cached graph rather than
re-parsing the database. The rest don't depend on each other and can run in
any order, though the numbering matches both the order they were originally
run in and the write-up structure in `ANALYSIS_RESULTS.md`. Each stage:

- logs progress to `analysis/logs/<stage>.log` (gitignored)
- appends a results section to `ANALYSIS_RESULTS.md`
- writes any figures to `analysis/figures/`

**Gephi visualization.** `stage8` and `stage9` each write a small `.gexf`
subgraph — `analysis/filtered_subgraph.gexf` (the densest k-core, 1,057
nodes) and `analysis/field_focused_subgraph.gexf` (a deliberately
field-balanced sample, 800 nodes) — small enough to lay out interactively,
unlike the full graph. Open either in Gephi, run ForceAtlas2 (Layout
panel), color by the `community` or `dominant_field` node attribute
(Appearance → Partition), size by `global_indegree` (Appearance → Ranking),
then export from the Preview tab. `analysis/both.png` is a finished example
of this for `filtered_subgraph.gexf`; `analysis/figures/field_focused_subgraph.png`
is a (non-Gephi) equivalent for the other. If you instead want to open the
full `citation_network_v3.gexf` directly in Gephi, see
`IMPORTING_TO_GEPHI.md` first — it's not a casual open without a lot of RAM,
which is exactly why this pipeline exists.

## Committing / syncing across machines

The SQLite DB (`citation_network.db` / `citation_network_v3.db`, depending
on which crawl you're running) is that crawl's entire state — `git pull` +
rerun is how you resume on a different machine.

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
| `snapshot_depth.py` | Background watcher: polls a running crawl and snapshots the DB/GEXF once a given `--depth` (or, with no `--depth`, full convergence) is reached |
| `snapshot_depth1.py` | Earlier, depth-1-only version of the above (superseded by `snapshot_depth.py --depth 1`, kept for history) |
| `INSPECTING_DB.md` | How to query/inspect the DB and log while the crawler runs |
| `IMPORTING_TO_GEPHI.md` | Troubleshooting large-GEXF imports directly into Gephi (memory limits, which file to try first) |
| `.claude/plan.md` | Full design doc: scope decisions, scale estimates, day-by-day plan |
| `citation_network_v3.db` | **The dataset used throughout `analysis/` and `ANALYSIS_RESULTS.md`**: the final converged crawl, 1,020,536 papers / 3,036,024 edges (git-lfs tracked) |
| `citation_network.db` | Finished influential-only crawl state from an earlier, smaller run (git-lfs tracked) |
| `citation_network_influential_only.gexf` | Finished influential-only export (git-lfs tracked) |
| `citation_network_full.db` | Isolated copy for the unrestricted ("Option B") pass (git-lfs tracked) |
| `citation_network_full.gexf` | Unrestricted pass's checkpoint export, once that run produces one |
| `citation_network_v3.gexf` | Full GEXF export of `citation_network_v3.db` — **not committed** (1.4GB); regenerate with `export_gexf.py --db citation_network_v3.db --output citation_network_v3.gexf` |
| `ANALYSIS_PIPELINE.md` | Design doc for the `analysis/` pipeline — maps each stage to a chapter of Barabási's *Network Science* |
| `ANALYSIS_RESULTS.md` | Logged, stage-by-stage results from the analysis pipeline (see "Analysis pipeline" above) |
| `analysis/lib.py`, `analysis/stage0..stage9_*.py` | The analysis pipeline itself — see "Analysis pipeline" above |
| `analysis/figures/` | Generated plots (degree distribution, preferential attachment, robustness, field-branching) |
| `analysis/cache/` | Pickled `igraph.Graph`, regenerated by `stage0` — gitignored |
| `analysis/both.png` | Finished Gephi export of `analysis/filtered_subgraph.gexf` (community-colored, k-core-20 subgraph) |
| `analysis/filtered_subgraph.gexf`, `analysis/field_focused_subgraph.gexf` | Small, Gephi-ready subgraphs written by `stage8`/`stage9` |
| `logs/crawler.log` | Runtime log (gitignored) |
| `analysis/logs/*.log` | Per-stage analysis pipeline logs (gitignored) |

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
