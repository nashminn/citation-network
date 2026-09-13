"""Stage 0: load the citation graph into igraph, run data-quality checks, cache it.

Prerequisite for stages 1-7. See ANALYSIS_PIPELINE.md.
"""
import datetime
import json
import pickle

import igraph as ig

from lib import (
    CACHE_DIR,
    GRAPH_CACHE_PATH,
    Timer,
    append_results_section,
    db_connection,
    get_logger,
)

log = get_logger("stage0_load_clean")


def main():
    conn = db_connection()
    cur = conn.cursor()

    with Timer(log, "load papers"):
        cur.execute(
            "SELECT paper_id, year, citation_count, fields_of_study FROM papers"
        )
        rows = cur.fetchall()
    log.info(f"papers loaded: {len(rows):,}")

    paper_ids = [r[0] for r in rows]
    id_to_idx = {pid: i for i, pid in enumerate(paper_ids)}
    years = [r[1] for r in rows]
    citation_counts = [r[2] for r in rows]
    fields = [r[3] for r in rows]

    with Timer(log, "load edges"):
        cur.execute("SELECT citing_id, cited_id, is_influential FROM edges")
        edge_rows = cur.fetchall()
    log.info(f"edges loaded: {len(edge_rows):,}")

    # --- data quality checks (on raw edge rows, before building the graph) ---
    self_citations = [e for e in edge_rows if e[0] == e[1]]
    log.info(f"self-citations found: {len(self_citations):,}")

    edge_id_set = {(e[0], e[1]) for e in edge_rows}
    reciprocal_pairs = 0
    for citing, cited, _ in edge_rows:
        if citing != cited and (cited, citing) in edge_id_set:
            reciprocal_pairs += 1
    reciprocal_pairs //= 2  # each reciprocal pair counted twice
    log.info(f"reciprocal citation pairs (A cites B and B cites A): {reciprocal_pairs:,}")

    missing_year = sum(1 for y in years if y is None)
    current_year = datetime.date.today().year
    future_year = sum(1 for y in years if y is not None and y > current_year)
    log.info(f"papers with NULL year: {missing_year:,}")
    log.info(f"papers with year in the future ({current_year=}): {future_year:,}")

    # edges referencing paper_ids not present in papers table (dangling refs)
    dangling = [e for e in edge_rows if e[0] not in id_to_idx or e[1] not in id_to_idx]
    log.info(f"edges with a dangling endpoint (not in papers table): {len(dangling):,}")

    # --- build igraph graph (drop dangling edges, keep self-citations/reciprocals as-is) ---
    with Timer(log, "build igraph Graph"):
        clean_edges = [
            (id_to_idx[c], id_to_idx[d])
            for c, d, _ in edge_rows
            if c in id_to_idx and d in id_to_idx
        ]
        influential = [
            bool(inf)
            for c, d, inf in edge_rows
            if c in id_to_idx and d in id_to_idx
        ]
        g = ig.Graph(
            n=len(paper_ids),
            edges=clean_edges,
            directed=True,
        )
        g.vs["paper_id"] = paper_ids
        g.vs["year"] = years
        g.vs["citation_count"] = citation_counts
        g.vs["fields_of_study"] = fields
        g.es["is_influential"] = influential

    log.info(f"graph built: {g.vcount():,} vertices, {g.ecount():,} edges")

    with Timer(log, "cache graph to disk"):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(GRAPH_CACHE_PATH, "wb") as f:
            pickle.dump(g, f, protocol=pickle.HIGHEST_PROTOCOL)
    log.info(f"cached to {GRAPH_CACHE_PATH} ({GRAPH_CACHE_PATH.stat().st_size / 1e6:.1f} MB)")

    quality = {
        "papers_total": len(rows),
        "edges_total": len(edge_rows),
        "self_citations": len(self_citations),
        "reciprocal_citation_pairs": reciprocal_pairs,
        "papers_missing_year": missing_year,
        "papers_future_year": future_year,
        "dangling_edges_dropped": len(dangling),
        "graph_vertices": g.vcount(),
        "graph_edges": g.ecount(),
    }
    log.info(f"summary: {json.dumps(quality, indent=2)}")

    md = f"""## Stage 0 — Load & clean

**Status:** done

- Papers loaded: {quality['papers_total']:,}
- Edges loaded (raw): {quality['edges_total']:,}
- Self-citations found: {quality['self_citations']:,}
- Reciprocal citation pairs (A cites B and B cites A): {quality['reciprocal_citation_pairs']:,}
- Papers with NULL year: {quality['papers_missing_year']:,}
- Papers with year in the future (> {current_year}): {quality['papers_future_year']:,}
- Dangling edges dropped (endpoint not in `papers` table): {quality['dangling_edges_dropped']:,}
- Final graph: {quality['graph_vertices']:,} vertices, {quality['graph_edges']:,} edges
- Cached to `analysis/cache/graph.pkl` for reuse by stages 1-7

Self-citations and reciprocal pairs were kept in the graph (not removed) —
flagged here for the report, not silently dropped. Dangling edges were
necessarily dropped since they can't be represented in the graph.

Log: `analysis/logs/stage0_load_clean.log`
"""
    append_results_section(md)
    log.info("Stage 0 complete.")


if __name__ == "__main__":
    main()
