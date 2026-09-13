"""Stage 4: small-world properties (Ch. 3). See ANALYSIS_PIPELINE.md."""
import json
import time

import numpy as np

from lib import Timer, append_results_section, get_logger, load_cached_graph

log = get_logger("stage4_small_world")

N_SAMPLE_SOURCES = 300
RANDOM_SEED = 42
PROGRESS_EVERY = 25


def sampled_path_lengths(graph, sources, label):
    """BFS from each source, logging progress every PROGRESS_EVERY sources
    so a long run stays observable instead of a silent black box."""
    path_lengths = []
    max_seen = 0
    start = time.monotonic()
    for i, src in enumerate(sources, 1):
        dists = graph.distances(source=[src], mode="out")[0]
        finite = [d for d in dists if d != float("inf") and d > 0]
        path_lengths.extend(finite)
        if finite:
            max_seen = max(max_seen, max(finite))
        if i % PROGRESS_EVERY == 0 or i == len(sources):
            elapsed = time.monotonic() - start
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(sources) - i) / rate if rate > 0 else float("inf")
            log.info(
                f"{label}: {i}/{len(sources)} sources done "
                f"({elapsed:.1f}s elapsed, ~{eta:.1f}s remaining)"
            )
    return path_lengths, max_seen


def main():
    with Timer(log, "load cached graph"):
        g = load_cached_graph()

    n, m = g.vcount(), g.ecount()

    with Timer(log, "compute global transitivity (clustering coefficient) on undirected projection"):
        g_undirected = g.as_undirected(mode="collapse")
        clustering = g_undirected.transitivity_undirected(mode="zero")
    log.info(f"average clustering coefficient (undirected projection): {clustering:.5f}")

    with Timer(log, "restrict to giant weakly-connected component"):
        components = g_undirected.connected_components(mode="weak")
        giant = components.giant()
    log.info(f"giant component: {giant.vcount():,} nodes, {giant.ecount():,} edges")

    with Timer(log, f"approximate avg path length via BFS sampling ({N_SAMPLE_SOURCES} sources)"):
        rng = np.random.default_rng(RANDOM_SEED)
        n_giant = giant.vcount()
        sample_size = min(N_SAMPLE_SOURCES, n_giant)
        sources = rng.choice(n_giant, size=sample_size, replace=False)
        path_lengths, max_seen = sampled_path_lengths(giant, sources, "giant-component BFS")
        avg_path_length = float(np.mean(path_lengths))
        log.info(f"sampled avg shortest path length: {avg_path_length:.3f} (over {len(path_lengths):,} pairs)")
        log.info(f"observed max distance in sample (lower bound on diameter): {max_seen}")

    # --- random graph baseline: Erdos-Renyi with same N, same edge count ---
    import igraph as ig

    with Timer(log, "build Erdos-Renyi baseline graph (same N, M)"):
        er = ig.Graph.Erdos_Renyi(n=giant.vcount(), m=giant.ecount(), directed=False)
        er_clustering = er.transitivity_undirected(mode="zero")

    with Timer(log, "approximate ER avg path length via BFS sampling"):
        er_sources = rng.choice(er.vcount(), size=sample_size, replace=False)
        er_path_lengths, _ = sampled_path_lengths(er, er_sources, "ER-baseline BFS")
        er_avg_path_length = float(np.mean(er_path_lengths)) if er_path_lengths else float("nan")

    log.info(f"ER baseline clustering: {er_clustering:.5f}")
    log.info(f"ER baseline avg path length (sampled): {er_avg_path_length:.3f}")

    # theoretical ER expectation: <L> ~ ln(N) / ln(<k>)
    avg_degree = 2 * giant.ecount() / giant.vcount()
    theoretical_er_L = np.log(giant.vcount()) / np.log(avg_degree) if avg_degree > 1 else float("nan")
    log.info(f"theoretical ER small-world estimate ln(N)/ln(<k>): {theoretical_er_L:.3f}")

    result = {
        "clustering_coefficient": clustering,
        "giant_component_nodes": giant.vcount(),
        "giant_component_edges": giant.ecount(),
        "avg_path_length_sampled": avg_path_length,
        "max_distance_observed_in_sample": max_seen,
        "er_clustering_coefficient": er_clustering,
        "er_avg_path_length_sampled": er_avg_path_length,
        "theoretical_er_avg_path_length": theoretical_er_L,
    }
    log.info(f"summary: {json.dumps(result, indent=2)}")

    clustering_ratio = clustering / er_clustering if er_clustering > 0 else float("inf")

    md = f"""## Stage 4 — Small-world properties

**Status:** done

- Average clustering coefficient (undirected projection): **{clustering:.5f}**
- Giant component: {giant.vcount():,} nodes, {giant.ecount():,} edges
- Average shortest path length (sampled, {N_SAMPLE_SOURCES:,} random sources): **{avg_path_length:.3f}**
- Max distance observed in the sample (lower bound on diameter): {max_seen}

**Erdős–Rényi baseline** (same node count and edge count, for comparison):

- ER clustering coefficient: {er_clustering:.6f}
- ER avg shortest path length (sampled): {er_avg_path_length:.3f}
- ER theoretical estimate, ln(N)/ln(⟨k⟩): {theoretical_er_L:.3f}

**Small-world verdict:** clustering coefficient is **{clustering_ratio:.0f}×** higher
than the random-graph baseline
{'while average path length is comparable' if abs(avg_path_length - er_avg_path_length) < 1 else 'with average path length ' + ('longer' if avg_path_length > er_avg_path_length else 'shorter') + ' than the random baseline'}
— {'the classic small-world signature (high clustering, short paths), consistent with the book' if clustering_ratio > 10 else 'a modest small-world signature'}.

Log: `analysis/logs/stage4_small_world.log`
"""
    append_results_section(md)
    log.info("Stage 4 complete.")


if __name__ == "__main__":
    main()
