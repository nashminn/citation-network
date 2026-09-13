"""Stage 7: community detection. See ANALYSIS_PIPELINE.md."""
import json
from collections import Counter

from lib import Timer, append_results_section, get_logger, load_cached_graph

log = get_logger("stage7_community_detection")

TOP_COMMUNITIES = 10
TOP_FIELDS_PER_COMMUNITY = 5


def main():
    with Timer(log, "load cached graph"):
        g = load_cached_graph()

    with Timer(log, "build undirected projection"):
        g_undirected = g.as_undirected(mode="collapse")

    with Timer(log, "run Louvain community detection (community_multilevel)"):
        communities = g_undirected.community_multilevel()

    log.info(f"communities found: {len(communities)}")
    log.info(f"modularity: {communities.modularity:.4f}")

    sizes = sorted(((i, len(c)) for i, c in enumerate(communities)), key=lambda x: -x[1])
    log.info(f"largest {TOP_COMMUNITIES} community sizes: {[s for _, s in sizes[:TOP_COMMUNITIES]]}")

    fields_raw = g.vs["fields_of_study"]

    def parse_fields(raw):
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    community_summaries = []
    with Timer(log, f"summarize dominant fields for top {TOP_COMMUNITIES} communities"):
        for comm_idx, size in sizes[:TOP_COMMUNITIES]:
            member_idx = communities[comm_idx]
            field_counter = Counter()
            for idx in member_idx:
                for f in parse_fields(fields_raw[idx]):
                    field_counter[f] += 1
            top_fields = field_counter.most_common(TOP_FIELDS_PER_COMMUNITY)
            community_summaries.append({"community_id": comm_idx, "size": size, "top_fields": top_fields})
            log.info(f"community {comm_idx} (size {size:,}): top fields = {top_fields}")

    largest_size = sizes[0][1]
    n = g.vcount()
    log.info(f"largest community holds {largest_size/n:.1%} of all nodes")

    table_rows = "\n".join(
        f"| {s['community_id']} | {s['size']:,} | {', '.join(f'{f} ({c})' for f, c in s['top_fields']) or '(no fields_of_study data)'} |"
        for s in community_summaries
    )

    md = f"""## Stage 7 — Community detection

**Status:** done

- Method: Louvain (`community_multilevel`) on the undirected projection
- Communities found: {len(communities):,}
- Modularity: **{communities.modularity:.4f}**
- Largest community: {largest_size:,} nodes ({largest_size/n:.1%} of the graph)

**Top {TOP_COMMUNITIES} communities by size, with their dominant `fields_of_study` values:**

| Community ID | Size | Top fields |
|---|---|---|
{table_rows}

This both validates cluster structure against known subfields (dominant
fields should look topically coherent within a community, not random) and
gives a principled candidate for Stage 8's Gephi visualization — e.g.
rendering just the largest community, or the top few communities colored
distinctly, rather than the full 1M-node graph.

Log: `analysis/logs/stage7_community_detection.log`
"""
    append_results_section(md)
    log.info("Stage 7 complete.")


if __name__ == "__main__":
    main()
