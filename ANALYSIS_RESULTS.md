# Analysis Results

Execution log and results for stages 1-7 of ANALYSIS_PIPELINE.md. Each section is appended as its stage completes.

## Stage 0 — Load & clean

**Status:** done

- Papers loaded: 1,020,536
- Edges loaded (raw): 3,036,024
- Self-citations found: 0
- Reciprocal citation pairs (A cites B and B cites A): 555
- Papers with NULL year: 18,840
- Papers with year in the future (> 2026): 0
- Dangling edges dropped (endpoint not in `papers` table): 0
- Final graph: 1,020,536 vertices, 3,036,024 edges
- Cached to `analysis/cache/graph.pkl` for reuse by stages 1-7

Self-citations and reciprocal pairs were kept in the graph (not removed) —
flagged here for the report, not silently dropped. Dangling edges were
necessarily dropped since they can't be represented in the graph.

Log: `analysis/logs/stage0_load_clean.log`

## Stage 1 — Basic structural statistics

**Status:** done

- Nodes: 1,020,536
- Edges: 3,036,024
- Density: 2.915e-06

**In-degree** (citations received, within this crawled graph): mean
2.97, median 0, max
159,874, stdev 212.57

**Out-degree** (references made, within this crawled graph): mean
2.97, median 2, max
114, stdev 3.18

The mean vastly exceeding the median for in-degree, alongside a very large
max relative to the mean, is the first quantitative hint of the heavy-tailed
(scale-free-like) distribution investigated properly in Stage 2.

**Connectivity:**

- Weakly connected components: 1
- Giant component: 1,020,536 nodes (100.00% of the graph)
- Singleton components (isolated in the undirected sense): 0
- Next 4 largest component sizes: []

Log: `analysis/logs/stage1_basic_stats.log`

## Stage 2 — Degree distribution & scale-free test

**Status:** done

**Caveat first:** out-degree is artificially capped by the crawler's
per-paper reference-fetch limit (max observed out-degree: 114, vs.
max in-degree 159,874). Out-degree distribution below is reported for
completeness but should **not** be interpreted as an organic/natural
distribution — the scale-free test focuses on in-degree only, which is not
subject to this cap (a paper's citation count within the crawl isn't limited
by anything the crawler imposed).

- Nodes with in-degree 0 (never cited within this crawl): 983,144 (96.3%)
- Nodes with out-degree 0 (no crawled references): 1 (0.0%)

**In-degree power-law fit** (via `powerlaw` package, Clauset-Shalizi-Newman method):

- α (scaling exponent) = 2.206
- x_min (fit starts at degree ≥) = 158.0

**Distribution comparison** (log-likelihood ratio test; R > 0 favors power
law, p < 0.1 means the comparison is meaningful rather than inconclusive):

| Comparison | R | p | Verdict |
|---|---|---|---|
| power law vs. lognormal | -1.384 | 0.4093 | inconclusive (p > 0.1, can't distinguish) |
| power law vs. exponential | 1747.657 | 0.0000 | power law favored |
| power law vs. truncated power law | -0.343 | 0.4077 | inconclusive (p > 0.1, can't distinguish) |

Figures: `analysis/figures/indegree_loglog.png`, `analysis/figures/outdegree_loglog.png`

Log: `analysis/logs/stage2_degree_distribution.log`

## Stage 3 — Preferential attachment, measured empirically

**Status:** done

**Method:** pooled Jeong-Neda-Barabasi estimator. For each year, cited nodes
are "eligible" once their own publication year has arrived; for each
citation event, the cited node's in-degree accumulated *strictly before*
that year is recorded. Π(k) = (total citation events landing on degree-k
nodes) / (total node-years spent at degree k), pooled across all
48 distinct years in the data.

**Caveat:** restricted to edges where both citing and cited papers have a
known publication year — 2,987,408 / 3,036,024
edges (98.4%). Year granularity
is yearly, not exact dates, so citations within the same year are treated as
simultaneous (a coarser resolution than the crawl could in principle
support if exact dates were used).

**Result:**

- Log-log slope of Π(k) vs. k: **0.705** (± 0.016)
- R² = 0.866, p = 3.65e-140
- Interpretation: sub-linear attachment (slope < 1) — weaker rich-get-richer effect than the BA model assumes

Figure: `analysis/figures/preferential_attachment.png` (empirical Π(k),
fitted slope, and a slope=1 reference line for comparison)

Log: `analysis/logs/stage3_preferential_attachment.log`

## Stage 4 — Small-world properties

**Status:** done

- Average clustering coefficient (undirected projection): **0.00031**
- Giant component: 1,020,536 nodes, 3,035,469 edges
- Average shortest path length (sampled, 300 random sources): **4.018**
- Max distance observed in the sample (lower bound on diameter): 10

**Erdős–Rényi baseline** (same node count and edge count, for comparison):

- ER clustering coefficient: 0.000005
- ER avg shortest path length (sampled): 7.970
- ER theoretical estimate, ln(N)/ln(⟨k⟩): 7.759

**Small-world verdict:** clustering coefficient is **57×** higher
than the random-graph baseline
with average path length shorter than the random baseline
— the classic small-world signature (high clustering, short paths), consistent with the book.

Log: `analysis/logs/stage4_small_world.log`

## Stage 5 — Hubs and citation inequality

**Status:** done

- Gini coefficient of in-degree (within-crawl citations): **0.9925** (0 = perfectly equal, 1 = maximally unequal)
- Gini coefficient of `citation_count` (global Semantic Scholar count): 0.8443
- Share of total in-crawl citations held by the top 1% of papers: **86.8%**
- Overlap between top-25 by in-crawl in-degree and top-25 by global citation_count: 9/25
  (a divergence here would mean this specific crawl's hub structure doesn't
  fully mirror global citation prominence — expected to some degree since
  in-degree only counts citations from other crawled papers)

**Top 15 papers by in-crawl in-degree:**

1. `204e3073870fae3d05bcbc2f6a8e263d9b72e776` — in-degree 159,874 — "Attention is All you Need"
2. `df2b0e26d0599ce3e70df8a9da02e51594e0e992` — in-degree 96,128 — "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding"
3. `268d347e8a55b5eb82fb5e7d2f800e33c75ab18a` — in-degree 58,543 — "An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale"
4. `6f870f7f02a8c59c3e23f407f3ef00dd1dcf8fc4` — in-degree 47,087 — "Learning Transferable Visual Models From Natural Language Supervision"
5. `6296aa7cab06eaf058f7291040b320b5a83c0091` — in-degree 26,136 — "Generative Adversarial Networks"
6. `c10075b3746a9f3dd5811970e93c8ca3ad39b39d` — in-degree 23,894 — "High-Resolution Image Synthesis with Latent Diffusion Models"
7. `4f2eda8077dc7a69bb2b4e0a1a086cf054adb3f9` — in-degree 22,629 — "EfficientNet: Rethinking Model Scaling for Convolutional Neural Networks"
8. `6c4b76232bb72897685d19b3d264c6ee3005bc2b` — in-degree 22,477 — "Exploring the Limits of Transfer Learning with a Unified Text-to-Text Transformer"
9. `962dc29fdc3fbdc5930a10aba114050b82fe5a3e` — in-degree 16,849 — "End-to-End Object Detection with Transformers"
10. `6351ebb4a3287f5f3e1273464b3b91e5df5a16d7` — in-degree 10,871 — "Masked Autoencoders Are Scalable Vision Learners"
11. `633e2fbfc0b21e959a244100937c5853afca4853` — in-degree 10,526 — "Score-Based Generative Modeling through Stochastic Differential Equations"
12. `395de0bd3837fdf4b4b5e5f04835bcc69c279481` — in-degree 10,300 — "BART: Denoising Sequence-to-Sequence Pre-training for Natural Language Generation, Translation, and Comprehension"
13. `3aed4648f7857c1d5e9b1da4c3afaf97463138c3` — in-degree 9,410 — "YOLOv7: Trainable Bag-of-Freebies Sets New State-of-the-Art for Real-Time Object Detectors"
14. `8899094797e82c5c185a0893896320ef77f60e64` — in-degree 8,957 — "Non-local Neural Networks"
15. `a54b56af24bb4873ed0163b77df63b92bd018ddc` — in-degree 8,940 — "DistilBERT, a distilled version of BERT: smaller, faster, cheaper and lighter"

A Gini coefficient this high, concentrated in a small fraction of nodes, is
the direct quantitative signature of the "rich get richer" dynamic the book
attributes to preferential attachment (Stage 3) and is what produces the
heavy-tailed degree distribution measured in Stage 2.

Log: `analysis/logs/stage5_hubs_inequality.log`

## Stage 6 — Robustness / the "Achilles' heel"

**Status:** done

Simulated removing up to 90% of nodes from the (undirected projection of
the) giant component, under two strategies: random removal, and targeted
removal of the highest-degree nodes first. At each checkpoint, the giant
component size is re-measured as a fraction of whatever graph remains.

- After removing 90% of nodes **randomly**, giant component retains
  **18.1%** of the remaining graph.
- After removing 90% of nodes **by targeted attack**, giant component
  retains only **0.0%** of the remaining graph.
- Fraction of nodes needed to break the giant component below 50% —
  random removal: 69%;
  targeted removal: 2%

This is the book's signature scale-free-network result: **robust under
random failure, fragile under targeted attack**. The gap between the two
curves (see figure) is the direct consequence of the hub structure
quantified in Stage 5 — removing a small number of high-degree hubs does
disproportionate damage to overall connectivity, while removing random
(mostly low-degree) nodes barely affects it.

Figure: `analysis/figures/robustness.png`

Log: `analysis/logs/stage6_robustness.log`

## Stage 7 — Community detection

**Status:** done

- Method: Louvain (`community_multilevel`) on the undirected projection
- Communities found: 77
- Modularity: **0.6334**
- Largest community: 141,721 nodes (13.9% of the graph)

**Top 10 communities by size, with their dominant `fields_of_study` values:**

| Community ID | Size | Top fields |
|---|---|---|
| 1 | 141,721 | Computer Science (77394), Medicine (24275), Engineering (8040), Physics (2125), Biology (1021) |
| 2 | 141,544 | Computer Science (112853), Medicine (5999), Mathematics (3251), Engineering (1841), Biology (957) |
| 0 | 121,965 | Computer Science (79313), Medicine (13421), Engineering (2963), Mathematics (2304), Biology (1482) |
| 10 | 107,055 | Computer Science (89671), Medicine (6745), Engineering (6597), Mathematics (2711), Physics (1362) |
| 6 | 50,848 | Computer Science (28793), Medicine (14400), Biology (4481), Physics (2952), Mathematics (2008) |
| 7 | 50,674 | Computer Science (26529), Medicine (4983), Mathematics (1606), Engineering (1495), Physics (1068) |
| 17 | 37,776 | Computer Science (28529), Mathematics (3889), Medicine (2283), Engineering (1441), Physics (643) |
| 23 | 33,370 | Computer Science (25893), Mathematics (4469), Medicine (2537), Engineering (1074), Physics (795) |
| 26 | 30,349 | Computer Science (21475), Medicine (3550), Mathematics (1872), Engineering (1142), Physics (490) |
| 11 | 29,373 | Computer Science (21390), Medicine (2125), Engineering (1247), Mathematics (312), Physics (245) |

This both validates cluster structure against known subfields (dominant
fields should look topically coherent within a community, not random) and
gives a principled candidate for Stage 8's Gephi visualization — e.g.
rendering just the largest community, or the top few communities colored
distinctly, rather than the full 1M-node graph.

Log: `analysis/logs/stage7_community_detection.log`

## Stage 8 — Filtered subgraph for the one Gephi visualization

**Status:** done (subgraph exported; Gephi layout/export is a manual follow-up)

- Selection method: k-core decomposition on the undirected projection,
  thresholded at **k=20** — chosen as the smallest k giving a
  subgraph between 1,000 and 6,000 nodes.
- Filtered subgraph: **1,057 nodes, 20,891 edges**
  (directed, citation direction preserved) — small enough for Gephi to
  import and lay out in minutes, unlike the full 1,020,536-node graph.
- Local re-clustering (Louvain on this subgraph alone, for coloring):
  6 communities, modularity 0.4264
- Node attributes included: `label` (title), `year`, `citation_count`
  (global), `global_indegree` (from the full graph), `local_indegree`
  (within this subgraph), `coreness`, `community` (local cluster id)
- Exported to: `analysis/filtered_subgraph.gexf`

**Next step (manual, in Gephi):**

1. File → Open → `analysis/filtered_subgraph.gexf`
2. Run ForceAtlas2 (Layout panel) — should converge in well under a minute
   at this size. Stop it once it visually settles.
3. Appearance panel → Nodes → Partition → color by `community`
4. Appearance panel → Nodes → Ranking → size by `global_indegree` (or
   `local_indegree`) to make hubs visually prominent
5. Preview tab → adjust as desired → Export → PNG/SVG/PDF

Log: `analysis/logs/stage8_gephi_subgraph.log`

## Stage 9 — Field branching: does the citation network actually cross disciplines?

**Status:** done

Motivated by the original project expectation of seeing the network branch
into fields like Medicine, Biology, and Mathematics — not just stay within
CS/ML. Dominant field per paper is taken as the first field Semantic
Scholar lists for it (its own primary-field ordering); the long tail of
rare fields is bucketed as "Other".

**Overall field-membership distribution** (a paper may carry more than one
field tag; 780,812/1,020,536 papers, 76.5%, carry any
field tag at all):

| Field | Papers tagged | Share |
|---|---|---|
| Computer Science | 687,650 | 88.1% |
| Medicine | 111,654 | 14.3% |
| Engineering | 45,217 | 5.8% |
| Mathematics | 31,742 | 4.1% |
| Physics | 19,998 | 2.6% |
| Biology | 13,072 | 1.7% |
| Economics | 1,930 | 0.2% |
| Psychology | 816 | 0.1% |
| Materials Science | 243 | 0.0% |
| Sociology | 215 | 0.0% |

Figure: `analysis/figures/field_distribution.png`

**Field composition of the 10 largest citation communities** (100% stacked
by field-tag share within each community) shows every major community has
the same shape: a Computer Science core with a Medicine shoulder and thin
Engineering/Mathematics/Physics/Biology tails — there is no community that
is Medicine- or Biology-dominant.

Figure: `analysis/figures/community_field_composition.png`

**Cross-field citation flow**: assigning each paper a single primary field
(its first-listed Semantic Scholar tag) and tallying every directed
citation edge by (citing field → cited field) gives a measure of how much
citation crosses field boundaries. Naively, **26.31%**
of all 3,036,024 edges connect papers with different primary-field
buckets — but that figure treats "Unknown" (no field tag at all) as its
own bucket, so an edge between an untagged paper and a Computer Science
paper counts as "cross-field" even though it reflects missing metadata,
not genuine interdisciplinary citation. Restricting to the
**2,560,719 edges (84.3% of all edges)**
where *both* the citing and cited paper have a known, non-"Unknown"
primary field gives a cleaner measure: among those,
**13.37%** cross primary-field boundaries. This is
the number reported in the write-up. The rest are within-field citations,
overwhelmingly CS→CS given how large CS is in this dataset.

Figure: `analysis/figures/cross_field_citation_heatmap.png`

**Top 5 Medicine papers by in-crawl in-degree:**

1. `98926d43356e87c22c82efc132dcaaac1ff40ebe` (in-degree 1,965) — "Robust deep learning based protein sequence design using ProteinMPNN"
2. `eb8c0df75993c1c19c51cde9345e45fc260f661c` (in-degree 1,365) — "De novo design of protein structure and function with RFdiffusion"
3. `698baad0cc98285b33e204c74e463e3840a64294` (in-degree 1,282) — "Quantum error correction below the surface code threshold"
4. `24aa57dae649b6683d8f5bc8deaf2ff549cdacc4` (in-degree 1,235) — "Transformers in Medical Imaging: A Survey"
5. `db10636e62862c9a4bd3e75012ae0273492ec125` (in-degree 1,015) — "EEG Conformer: Convolutional Transformer for EEG Decoding and Visualization"

**Top 5 Engineering papers by in-crawl in-degree:**

1. `6296aa7cab06eaf058f7291040b320b5a83c0091` (in-degree 26,136) — "Generative Adversarial Networks"
2. `a02fbaf22237a1aedacb1320b6007cd70c1fe6ec` (in-degree 8,074) — "Robust Speech Recognition via Large-Scale Weak Supervision"
3. `7a9a708ca61c14886aa0dcd6d13dac7879713f5f` (in-degree 4,984) — "SwinIR: Image Restoration Using Swin Transformer"
4. `22f4683316a6b4144d4fe025372dc4024d334148` (in-degree 1,136) — "Inf-Net: Automatic COVID-19 Lung Infection Segmentation From CT Images"
5. `2bbffec6395d3a8f81f5fe9137f7e078bd0f0336` (in-degree 1,110) — "Activating More Pixels in Image Super-Resolution Transformer"

**Top 5 Mathematics papers by in-crawl in-degree:**

1. `6c4b76232bb72897685d19b3d264c6ee3005bc2b` (in-degree 22,477) — "Exploring the Limits of Transfer Learning with a Unified Text-to-Text Transformer"
2. `3a58efcc4558727cc5c131c44923635da4524f33` (in-degree 3,687) — "Relational inductive biases, deep learning, and graph networks"
3. `6a9d69fb35414b8461573df333dba800f254519f` (in-degree 2,996) — "Temporal Fusion Transformers for Interpretable Multi-horizon Time Series Forecasting"
4. `ce4f001c1d8ddb9a95cf54e14240ef02c44bd329` (in-degree 1,696) — "Attention, Learn to Solve Routing Problems!"
5. `9cf6f42806a35fd1d410dbc34d8e8df73a29d094` (in-degree 930) — "Maximum Likelihood Training of Score-Based Diffusion Models"

**Top 5 Physics papers by in-crawl in-degree:**

1. `d8b65198c37ada92cada81fe315508fc5bdbab8f` (in-degree 1,382) — "Graph Networks as a Universal Machine Learning Framework for Molecules and Crystals"
2. `93c9ea575192ce229900d9320623edbd647cdd63` (in-degree 718) — "A comprehensive and fair comparison of two neural operators (with practical extensions) based on FAIR data"
3. `6c260fb515bd0a75b4c49bd40ab7a7cf9c9262f5` (in-degree 290) — "MQT Bench: Benchmarking Software and Design Automation Tools for Quantum Computing"
4. `66e0888b6cdb4fd48e2187aa838ea249dcc45dbf` (in-degree 214) — "Particle Transformer for Jet Tagging"
5. `cd7077ce7f80d6d21c2c53355731cd919e6e8305` (in-degree 156) — "Learning Smooth and Expressive Interatomic Potentials for Physical Property Prediction"

**Top 5 Biology papers by in-crawl in-degree:**

1. `c520d8a888355f7abb7728b2e2510fe7bc63f814` (in-degree 611) — "Large Scale Foundation Model on Single-cell Transcriptomics"
2. `0f4780f3f42dbe9755d54495ae17244cc88a7483` (in-degree 459) — "DNABERT-2: Efficient Foundation Model and Benchmark For Multi-Species Genome"
3. `2824f18b3aeaae51b3fbe0d629c9b8a728da86d7` (in-degree 401) — "High-resolution image reconstruction with latent diffusion models from human brain activity"
4. `043e5e0cf3129284683260976c10d98c7f121f35` (in-degree 398) — "Transformer protein language models are unsupervised structure learners"
5. `8b127b9c7e37f075559ed5a51428527205dcf3f5` (in-degree 348) — "Direct-fit to nature: an evolutionary perspective on biological (and artificial) neural networks"

**Field-focused Gephi subgraph** — the Stage 8 k-core=20 subgraph is
CS-only by construction: k-core filtering keeps only the densest citation
core, and field-diverse papers (a Medicine paper citing a foundational ML
paper once, say) live in the sparser periphery that k-core filtering
strips away. To actually visualize field branching, this stage builds a
second, deliberately field-diverse node set instead: the top
300 CS papers by in-degree (the backbone), unioned with
the top 100 papers by in-degree *within* each of
Medicine/Engineering/Mathematics/Physics/Biology, with edges induced from
the full graph.

- Field-focused subgraph: **800 nodes, 2,812 edges**
- Field composition of this subgraph:

| Field | Nodes |
|---|---|
| Computer Science | 300 |
| Engineering | 100 |
| Mathematics | 100 |
| Biology | 100 |
| Medicine | 100 |
| Physics | 100 |

Exported to: `analysis/field_focused_subgraph.gexf` — open in Gephi, run
ForceAtlas2, then color by the `dominant_field` node attribute (Partition)
and size by `global_indegree` (Ranking) to visualize field branching
directly, the same workflow as Stage 8.

Log: `analysis/logs/stage9_field_branching.log`

