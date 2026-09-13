"""Stage 1: basic structural statistics. See ANALYSIS_PIPELINE.md."""
import json
import statistics

from lib import Timer, append_results_section, get_logger, load_cached_graph

log = get_logger("stage1_basic_stats")


def main():
    with Timer(log, "load cached graph"):
        g = load_cached_graph()
    log.info(f"graph: {g.vcount():,} vertices, {g.ecount():,} edges")

    n = g.vcount()
    m = g.ecount()
    density = m / (n * (n - 1))
    log.info(f"density: {density:.3e}")

    with Timer(log, "compute in/out degree sequences"):
        indeg = g.indegree()
        outdeg = g.outdegree()

    def summary(seq, name):
        s = {
            "mean": statistics.mean(seq),
            "median": statistics.median(seq),
            "max": max(seq),
            "min": min(seq),
            "stdev": statistics.pstdev(seq),
        }
        log.info(f"{name} degree summary: {json.dumps(s, indent=2)}")
        return s

    indeg_summary = summary(indeg, "in")
    outdeg_summary = summary(outdeg, "out")

    with Timer(log, "compute weakly connected components"):
        components = g.connected_components(mode="weak")
    sizes = sorted((len(c) for c in components), reverse=True)
    giant_size = sizes[0]
    giant_fraction = giant_size / n
    log.info(f"weakly connected components: {len(sizes):,}")
    log.info(f"giant component size: {giant_size:,} ({giant_fraction:.4%} of graph)")
    log.info(f"largest 5 component sizes: {sizes[:5]}")
    log.info(f"number of singleton (size-1) components: {sum(1 for s in sizes if s == 1):,}")

    md = f"""## Stage 1 — Basic structural statistics

**Status:** done

- Nodes: {n:,}
- Edges: {m:,}
- Density: {density:.3e}

**In-degree** (citations received, within this crawled graph): mean
{indeg_summary['mean']:.2f}, median {indeg_summary['median']:.0f}, max
{indeg_summary['max']:,}, stdev {indeg_summary['stdev']:.2f}

**Out-degree** (references made, within this crawled graph): mean
{outdeg_summary['mean']:.2f}, median {outdeg_summary['median']:.0f}, max
{outdeg_summary['max']:,}, stdev {outdeg_summary['stdev']:.2f}

The mean vastly exceeding the median for in-degree, alongside a very large
max relative to the mean, is the first quantitative hint of the heavy-tailed
(scale-free-like) distribution investigated properly in Stage 2.

**Connectivity:**

- Weakly connected components: {len(sizes):,}
- Giant component: {giant_size:,} nodes ({giant_fraction:.2%} of the graph)
- Singleton components (isolated in the undirected sense): {sum(1 for s in sizes if s == 1):,}
- Next 4 largest component sizes: {sizes[1:5]}

Log: `analysis/logs/stage1_basic_stats.log`
"""
    append_results_section(md)
    log.info("Stage 1 complete.")


if __name__ == "__main__":
    main()
