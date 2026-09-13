"""Stage 8: pick a filtered subgraph and export it for the one Gephi visualization.

See ANALYSIS_PIPELINE.md. This script does NOT touch Gephi itself — it
prepares a small, tractable .gexf. Layout + coloring + image export happens
in the Gephi GUI afterward (fast at this size, unlike the full 1M-node graph).
"""
import json

import igraph as ig
import networkx as nx

from lib import ANALYSIS_DIR, Timer, append_results_section, db_connection, get_logger, load_cached_graph

log = get_logger("stage8_gephi_subgraph")

TARGET_MIN_NODES = 1000
TARGET_MAX_NODES = 6000
OUTPUT_GEXF = ANALYSIS_DIR / "filtered_subgraph.gexf"


def main():
    with Timer(log, "load cached graph"):
        g = load_cached_graph()

    with Timer(log, "build undirected projection"):
        g_undirected = g.as_undirected(mode="collapse")

    with Timer(log, "compute k-core decomposition (coreness)"):
        coreness = g_undirected.coreness()

    import numpy as np

    coreness = np.array(coreness)
    unique_k = sorted(set(coreness.tolist()), reverse=True)
    log.info(f"coreness range: max={unique_k[0]}, distinct values={len(unique_k)}")

    chosen_k = None
    for k in unique_k:
        count = int((coreness >= k).sum())
        log.info(f"k={k}: {count:,} nodes at or above this core")
        if chosen_k is None and TARGET_MIN_NODES <= count <= TARGET_MAX_NODES:
            chosen_k = k
    if chosen_k is None:
        # fall back: pick the k giving the smallest count that's still >= TARGET_MIN_NODES
        candidates = [k for k in unique_k if int((coreness >= k).sum()) >= TARGET_MIN_NODES]
        chosen_k = min(candidates, key=lambda k: int((coreness >= k).sum())) if candidates else unique_k[-1]

    keep_mask = coreness >= chosen_k
    keep_idx = np.nonzero(keep_mask)[0]
    log.info(f"chosen k-core threshold: k={chosen_k}, subgraph size: {len(keep_idx):,} nodes")

    with Timer(log, "build induced directed subgraph (preserving citation direction)"):
        keep_set = set(keep_idx.tolist())
        edge_list = g.get_edgelist()
        sub_edges = [(u, v) for u, v in edge_list if u in keep_set and v in keep_set]
    log.info(f"induced subgraph: {len(keep_idx):,} nodes, {len(sub_edges):,} edges")

    # relabel to a contiguous range for the subgraph
    old_to_new = {old: new for new, old in enumerate(sorted(keep_idx.tolist()))}
    sub_g_ig = ig.Graph(n=len(keep_idx), edges=[(old_to_new[u], old_to_new[v]) for u, v in sub_edges], directed=True)

    with Timer(log, "run Louvain on the filtered subgraph's undirected projection (local coloring)"):
        sub_undirected = sub_g_ig.as_undirected(mode="collapse")
        sub_communities = sub_undirected.community_multilevel()
    log.info(f"local communities in filtered subgraph: {len(sub_communities)}, modularity={sub_communities.modularity:.4f}")
    community_of = {}
    for comm_id, members in enumerate(sub_communities):
        for m in members:
            community_of[m] = comm_id

    old_indices_sorted = sorted(keep_idx.tolist())
    paper_ids = [g.vs[old_idx]["paper_id"] for old_idx in old_indices_sorted]
    years = [g.vs[old_idx]["year"] for old_idx in old_indices_sorted]
    citation_counts = [g.vs[old_idx]["citation_count"] for old_idx in old_indices_sorted]
    global_indeg = g.indegree()
    global_indegrees = [global_indeg[old_idx] for old_idx in old_indices_sorted]
    local_indeg = sub_g_ig.indegree()

    with Timer(log, "look up titles from DB in batches"):
        conn = db_connection()
        title_by_id = {}
        batch_size = 500
        for i in range(0, len(paper_ids), batch_size):
            batch = paper_ids[i : i + batch_size]
            placeholders = ",".join("?" * len(batch))
            rows = conn.execute(
                f"SELECT paper_id, title FROM papers WHERE paper_id IN ({placeholders})", batch
            ).fetchall()
            title_by_id.update(dict(rows))

    with Timer(log, "build networkx DiGraph with attributes and write GEXF"):
        G = nx.DiGraph()
        for new_idx, pid in enumerate(paper_ids):
            title = title_by_id.get(pid) or pid
            G.add_node(
                pid,
                label=title,
                year=years[new_idx] if years[new_idx] is not None else 0,
                citation_count=citation_counts[new_idx] if citation_counts[new_idx] is not None else 0,
                global_indegree=global_indegrees[new_idx],
                local_indegree=local_indeg[new_idx],
                coreness=int(coreness[old_indices_sorted[new_idx]]),
                community=community_of.get(new_idx, -1),
            )
        for u, v in sub_g_ig.get_edgelist():
            G.add_edge(paper_ids[u], paper_ids[v])
        nx.write_gexf(G, OUTPUT_GEXF)
    log.info(f"wrote {OUTPUT_GEXF} ({OUTPUT_GEXF.stat().st_size / 1e3:.1f} KB)")

    result = {
        "chosen_k_core": int(chosen_k),
        "subgraph_nodes": len(keep_idx),
        "subgraph_edges": len(sub_edges),
        "local_communities": len(sub_communities),
        "local_modularity": sub_communities.modularity,
    }
    log.info(f"summary: {json.dumps(result, indent=2)}")

    md = f"""## Stage 8 — Filtered subgraph for the one Gephi visualization

**Status:** done (subgraph exported; Gephi layout/export is a manual follow-up)

- Selection method: k-core decomposition on the undirected projection,
  thresholded at **k={chosen_k}** — chosen as the smallest k giving a
  subgraph between {TARGET_MIN_NODES:,} and {TARGET_MAX_NODES:,} nodes.
- Filtered subgraph: **{result['subgraph_nodes']:,} nodes, {result['subgraph_edges']:,} edges**
  (directed, citation direction preserved) — small enough for Gephi to
  import and lay out in minutes, unlike the full 1,020,536-node graph.
- Local re-clustering (Louvain on this subgraph alone, for coloring):
  {result['local_communities']} communities, modularity {result['local_modularity']:.4f}
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
"""
    append_results_section(md)
    log.info("Stage 8 complete (subgraph export done; Gephi steps are manual).")


if __name__ == "__main__":
    main()
