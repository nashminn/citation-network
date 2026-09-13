# Network Science Analysis Pipeline

Course project pipeline for the crawled citation network, structured around
*Network Science* (Barabási & Albert). Goal: extract quantitative insights
from the full graph using scripts, and use Gephi only to produce a single
legible visualization at the end — not as the analysis engine.

## Data on hand

`data/db/citation_network_v3.db` (SQLite), matching the "final converged" crawl:

- `papers` — 1,020,536 rows: `paper_id`, `title`, `year`, `authors` (JSON),
  `venue`, `citation_count`, `reference_count`, `pub_date`, `depth`,
  `fields_of_study` (JSON). Year range observed: 1939–2026.
- `edges` — 3,036,024 rows: `citing_id`, `cited_id`, `is_influential`
  (Semantic Scholar's ML-flagged "highly influential citation" signal).

Two distinct notions of "citation count" exist and should not be conflated:
`papers.citation_count` (the paper's *total* citation count from Semantic
Scholar, including citations outside this crawl) vs. in-degree *within this
graph* (only citations from papers that were also crawled). Report should be
explicit about which one a given statistic uses.

## Tooling split

| Tool | Role |
|---|---|
| Python (`igraph`) | All heavy computation on the full 1M-node graph. `igraph` is C-backed and far more memory/time-efficient than `networkx` at this scale. |
| Python (`networkx`) | Already installed in `.venv`. Fine for prototyping on filtered/small subgraphs, not the full graph. |
| `powerlaw` package | Power-law fitting + comparison against alternative distributions (log-normal, exponential), using the Clauset–Shalizi–Newman method the book cites. |
| Gephi | One visualization, at the very end, on a filtered subgraph small enough to lay out in minutes. Not used for computing statistics. |

### Environment setup needed

`numpy`, `scipy`, `pandas`, `matplotlib`, `python-igraph`, `powerlaw` are not
yet installed in `.venv` (only `requests` and `networkx` are). Add and
install before Stage 0.

## Stage 0 — Load & clean

- Build an `igraph.Graph(directed=True)` directly from the `edges` table
  (map `paper_id` strings to integer vertex indices), attaching `year`,
  `citation_count`, `fields_of_study` as vertex attributes.
- Sanity checks worth running once, since they catch crawl artifacts before
  they contaminate every later stage:
  - Self-citations (`citing_id == cited_id`).
  - Reciprocal edges (A cites B *and* B cites A) — for a citation graph this
    should be near-zero; more than a handful signals a data issue (or same-year
    cross-citation, worth a quick look either way).
  - Papers with `year` in the future relative to the crawl date, or `NULL`
    year — decide whether to drop or keep them (they'll skew any
    time-ordered analysis in Stage 3).
  - Nodes with zero out-degree *and* zero in-degree shouldn't exist (every
    node should be attached via at least one crawled edge) — confirms the
    export didn't include orphans.

## Stage 1 — Basic structural statistics

- Node/edge counts, density.
- In-degree and out-degree distributions (summary stats: mean, median, max).
- Weakly connected components — report giant component size as a fraction
  of the whole graph (citation graphs are directed, so "connected" here
  means weakly connected).

Fast on `igraph` even at full scale; a good warm-up that also produces your
first report-ready numbers.

## Stage 2 — Degree distribution & scale-free test (Ch. 4)

- Log-log plot of the in-degree distribution.
- Fit a power law with the `powerlaw` package, estimate `x_min` and the
  scaling exponent `γ`.
- Run `powerlaw`'s built-in comparison against log-normal and exponential
  alternatives (likelihood-ratio test) — don't just eyeball the log-log plot
  and declare scale-free; the book is explicit that this needs to be tested
  statistically.

## Stage 3 — Preferential attachment, measured empirically (Ch. 5)

- Using `year` (or `pub_date` where available) as a proxy for arrival time,
  reconstruct, for each edge, the in-degree of the cited paper *at the time
  the citation occurred* (counting only earlier-dated citing papers already
  in the graph).
- Bin cited papers by that in-degree `k` and measure the empirical
  attachment kernel Π(k) — the rate at which degree-k nodes acquire new
  citations. Plot Π(k) vs. k on log-log axes; the BA model predicts a
  roughly linear relationship (Π(k) ∝ k).
- Caveat to note explicitly in the writeup: this is a BFS-crawled snapshot,
  not a true historical growth log, and `year` resolution is coarse — so
  treat this as an approximation of the mechanism, not a precise
  reconstruction.

## Stage 4 — Small-world properties (Ch. 3)

- Average clustering coefficient (`igraph` has this built in).
- Average shortest path length / diameter — **do not** compute all-pairs
  shortest paths at 1M nodes; use `igraph`'s sampling-based approximation
  (BFS from a few thousand random source nodes in the giant component).
- Compare both numbers against an Erdős–Rényi (or configuration-model)
  random graph with the same node count and average degree, generated with
  `igraph`, to show the small-world effect concretely rather than asserting it.

## Stage 5 — Hubs and inequality

- Top 20–50 papers by in-degree (and separately by `citation_count`, to see
  whether the two rankings diverge) — pull titles for the report.
- Gini coefficient (or a Lorenz curve) of the citation distribution — a
  single clean number quantifying "rich get richer."

## Stage 6 — Robustness / the "Achilles' heel" (Ch. 8)

- Simulate two node-removal strategies on the giant component: random
  removal and targeted removal (highest-degree-first).
- After each removal step, track the size of the remaining largest
  connected component as a fraction of the original.
- Plot both curves together — the gap between them (robust under random
  failure, fragile under targeted attack) is the book's signature result for
  scale-free networks, and it's visually strong for a report/presentation.

## Stage 7 — Community detection

- Run Louvain (`igraph`'s `community_multilevel`) on an undirected
  projection of the graph.
- Cross-reference each community's dominant `fields_of_study` values as a
  sanity check that clusters correspond to actual subfields rather than
  crawl artifacts.
- This step also produces the principled way to choose *what* to visualize
  in Stage 8 (e.g., "the largest community" or "communities above size N").

## Stage 8 — The one Gephi visualization

- Pick a filtered subgraph using results from earlier stages — candidates:
  top-N papers by in-degree plus their direct neighbors, the largest
  community from Stage 7, or a k-core (via `igraph`'s `coreness()`) at a
  threshold that yields on the order of a few thousand nodes.
- Export that subgraph alone to a small `.gexf` (via `igraph` or
  `networkx`) — small enough that Gephi's import and ForceAtlas2 finish in
  minutes, not days.
- Import into Gephi, run ForceAtlas2 to convergence, color by community,
  export the final image.

## Suggested execution order

1. Environment setup (install missing packages).
2. Stage 0 (load + clean) — do this once, cache the built graph (e.g.
   `igraph`'s native binary format) so later stages don't re-parse the DB.
3. Stages 1–2 — fast, and produce your first concrete report numbers.
4. Stages 4–6 — still fast on `igraph`, no temporal reconstruction needed.
5. Stage 3 — more involved (temporal reconstruction), do this once the
   quicker wins are banked.
6. Stage 7 — community detection, informs Stage 8's subgraph choice.
7. Stage 8 last — the only stage that touches Gephi.

## Deliverables checklist

- [ ] Cleaned, loaded graph (cached) + data-quality notes
- [ ] Degree distribution plot + power-law fit (γ, comparison test)
- [ ] Preferential attachment Π(k) plot
- [ ] Clustering coefficient + avg path length, vs. random-graph baseline
- [ ] Hub list + Gini coefficient
- [ ] Robustness curves (random vs. targeted attack)
- [ ] Community detection summary
- [ ] One Gephi visualization of a filtered subgraph
