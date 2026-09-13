"""Stage 9: does the citation network actually branch into other fields?

Motivated by the original project expectation: seeing citing papers branch
out into Medicine, Biology, Mathematics, etc., not just stay within CS/ML.
Stage 7 measured this only as a per-community field table; this stage turns
it into proper figures and adds a direct cross-field citation test, plus a
second Gephi export specifically built to contain field-diverse hub papers
(the k-core=20 subgraph from Stage 8 is CS-only by construction, since it
keeps only the densest citation core and field-diverse papers live in the
sparser periphery that k-core filtering strips away).
"""
import json
from collections import Counter, defaultdict

import matplotlib
import networkx as nx
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from lib import ANALYSIS_DIR, FIGURES_DIR, Timer, append_results_section, db_connection, get_logger, load_cached_graph

log = get_logger("stage9_field_branching")

MAIN_FIELDS = ["Computer Science", "Medicine", "Engineering", "Mathematics", "Physics", "Biology"]
TOP_COMMUNITIES_FOR_CHART = 10
NON_CS_FIELDS = ["Medicine", "Engineering", "Mathematics", "Physics", "Biology"]
TOP_HUBS_PER_FIELD_SUBGRAPH = 100
TOP_CS_BACKBONE_SIZE = 300
TOP_HUB_PAPERS_PER_FIELD_TABLE = 5
OUTPUT_GEXF = ANALYSIS_DIR / "field_focused_subgraph.gexf"


def parse_fields(raw):
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def bucket_field(f):
    """Collapse the long tail of rare fields into 'Other' for the heatmap/chart."""
    return f if f in MAIN_FIELDS else ("Unknown" if f is None else "Other")


def main():
    with Timer(log, "load cached graph"):
        g = load_cached_graph()

    n = g.vcount()
    fields_raw = g.vs["fields_of_study"]
    parsed_fields = [parse_fields(r) for r in fields_raw]

    # dominant field per paper = first field listed by Semantic Scholar (its own primary-field ordering)
    with Timer(log, "assign dominant field per paper"):
        dominant_field = [bucket_field(pf[0]) if pf else "Unknown" for pf in parsed_fields]
        dominant_counter = Counter(dominant_field)
    log.info(f"dominant-field distribution: {dominant_counter.most_common()}")

    # ---------- Figure 1: overall field-membership distribution (multi-label) ----------
    with Timer(log, "compute overall field-membership counts (multi-label)"):
        membership_counter = Counter()
        n_with_fields = 0
        for pf in parsed_fields:
            if not pf:
                continue
            n_with_fields += 1
            for f in pf:
                membership_counter[f] += 1
    top_membership = membership_counter.most_common(10)
    log.info(f"papers with any field tag: {n_with_fields:,}/{n:,} ({n_with_fields/n:.1%})")
    log.info(f"top field memberships: {top_membership}")

    with Timer(log, "plot field-distribution bar chart"):
        fig, ax = plt.subplots(figsize=(6.5, 4))
        labels = [f for f, _ in top_membership]
        counts = [c for _, c in top_membership]
        shares = [c / n_with_fields for c in counts]
        bars = ax.barh(labels[::-1], shares[::-1], color="#4C72B0")
        ax.set_xlabel("share of papers tagged with this field")
        ax.set_title("Field-of-study membership across the crawled network\n(a paper may carry more than one field tag)")
        ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0%}")
        for bar, c in zip(bars, counts[::-1]):
            ax.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height() / 2, f"{c:,}", va="center", fontsize=8)
        fig.tight_layout()
        fig.savefig(FIGURES_DIR / "field_distribution.png", dpi=150)
        plt.close(fig)

    # ---------- Figure 2: field composition per top community (100% stacked bar) ----------
    with Timer(log, "build undirected projection"):
        g_undirected = g.as_undirected(mode="collapse")

    with Timer(log, "run Louvain community detection (recomputed for this stage)"):
        communities = g_undirected.community_multilevel()
    sizes = sorted(((i, len(c)) for i, c in enumerate(communities)), key=lambda x: -x[1])
    top_comms = sizes[:TOP_COMMUNITIES_FOR_CHART]

    with Timer(log, "tally field composition for top communities"):
        comm_field_counts = {}
        for comm_idx, size in top_comms:
            counter = Counter()
            for idx in communities[comm_idx]:
                for f in parsed_fields[idx]:
                    counter[bucket_field(f)] += 1
            comm_field_counts[comm_idx] = counter

    with Timer(log, "plot per-community field composition (100% stacked bar)"):
        fig, ax = plt.subplots(figsize=(8, 5))
        x = np.arange(len(top_comms))
        comm_labels = [f"C{cid}" for cid, _ in top_comms]
        bottoms = np.zeros(len(top_comms))
        colors = plt.cm.tab10(np.linspace(0, 1, len(MAIN_FIELDS)))
        for field, color in zip(MAIN_FIELDS, colors):
            fracs = []
            for cid, size in top_comms:
                total_tags = sum(comm_field_counts[cid].values()) or 1
                fracs.append(comm_field_counts[cid].get(field, 0) / total_tags)
            ax.bar(x, fracs, bottom=bottoms, label=field, color=color, width=0.65)
            bottoms += np.array(fracs)
        ax.set_xticks(x)
        ax.set_xticklabels(comm_labels)
        for xi, (cid, size) in zip(x, top_comms):
            ax.text(xi, 1.02, f"n={size:,}", ha="center", va="bottom", fontsize=7, rotation=90)
        ax.set_ylim(0, 1.25)
        ax.set_ylabel("share of field tags within community")
        ax.set_title("Field composition of the 10 largest citation communities")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, fontsize=8)
        fig.tight_layout()
        fig.savefig(FIGURES_DIR / "community_field_composition.png", dpi=150)
        plt.close(fig)

    # ---------- Figure 3: cross-field citation heatmap ----------
    heatmap_fields = MAIN_FIELDS + ["Other", "Unknown"]
    field_to_idx = {f: i for i, f in enumerate(heatmap_fields)}
    with Timer(log, "build cross-field citation matrix (directed: citing field -> cited field)"):
        matrix = np.zeros((len(heatmap_fields), len(heatmap_fields)), dtype=np.int64)
        for u, v in g.get_edgelist():
            matrix[field_to_idx[dominant_field[u]], field_to_idx[dominant_field[v]]] += 1
    log.info(f"cross-field citation matrix (rows=citing, cols=cited):\n{matrix}")

    with Timer(log, "plot cross-field citation heatmap"):
        fig, ax = plt.subplots(figsize=(6.5, 5.5))
        log_matrix = np.log10(matrix + 1)
        im = ax.imshow(log_matrix, cmap="viridis")
        ax.set_xticks(range(len(heatmap_fields)))
        ax.set_xticklabels(heatmap_fields, rotation=45, ha="right")
        ax.set_yticks(range(len(heatmap_fields)))
        ax.set_yticklabels(heatmap_fields)
        ax.set_xlabel("cited paper's primary field")
        ax.set_ylabel("citing paper's primary field")
        ax.set_title("Cross-field citation flow (log10 edge count)")
        for i in range(len(heatmap_fields)):
            for j in range(len(heatmap_fields)):
                if matrix[i, j] > 0:
                    ax.text(j, i, f"{matrix[i, j]:,}", ha="center", va="center",
                             color="white" if log_matrix[i, j] < log_matrix.max() * 0.6 else "black", fontsize=6)
        fig.colorbar(im, label="log10(edge count + 1)")
        fig.tight_layout()
        fig.savefig(FIGURES_DIR / "cross_field_citation_heatmap.png", dpi=150)
        plt.close(fig)

    off_diagonal_total = matrix.sum() - np.trace(matrix)
    off_diagonal_share = off_diagonal_total / matrix.sum()
    log.info(f"share of ALL citation edges crossing between different primary-field buckets "
              f"(includes Unknown/Other as their own buckets): {off_diagonal_share:.2%}")

    # Restrict to edges where BOTH endpoints have a genuine, known field tag (excludes
    # Unknown/Other) -- an Unknown<->CS edge is missing metadata, not evidence of a real
    # cross-disciplinary citation, so it should not count toward a "branching" statistic.
    known_idx = list(range(len(MAIN_FIELDS)))  # MAIN_FIELDS is the first len(MAIN_FIELDS) entries of heatmap_fields
    known_matrix = matrix[np.ix_(known_idx, known_idx)]
    known_total = known_matrix.sum()
    known_off_diagonal = known_total - np.trace(known_matrix)
    known_cross_field_share = known_off_diagonal / known_total
    known_share_of_all_edges = known_total / matrix.sum()
    log.info(f"edges where BOTH endpoints have a known (non-Unknown/Other) primary field: "
              f"{known_total:,} ({known_share_of_all_edges:.1%} of all edges)")
    log.info(f"among those, share crossing primary-field boundaries: {known_cross_field_share:.2%}")

    # ---------- top hub papers per non-CS field (for the report narrative) ----------
    indeg = np.array(g.indegree())
    paper_ids = g.vs["paper_id"]
    field_hub_tables = {}
    with Timer(log, "find top hub papers per non-CS field and look up titles"):
        conn = db_connection()
        all_top_ids = []
        per_field_top_idx = {}
        for field in NON_CS_FIELDS:
            idx_for_field = np.array([i for i in range(n) if dominant_field[i] == field])
            if len(idx_for_field) == 0:
                per_field_top_idx[field] = []
                continue
            top_idx = idx_for_field[np.argsort(indeg[idx_for_field])[::-1][:TOP_HUB_PAPERS_PER_FIELD_TABLE]]
            per_field_top_idx[field] = top_idx.tolist()
            all_top_ids.extend(paper_ids[i] for i in top_idx)
        placeholders = ",".join("?" * len(all_top_ids)) if all_top_ids else ""
        title_by_id = {}
        if all_top_ids:
            rows = conn.execute(f"SELECT paper_id, title FROM papers WHERE paper_id IN ({placeholders})", all_top_ids).fetchall()
            title_by_id = dict(rows)
        for field in NON_CS_FIELDS:
            field_hub_tables[field] = [
                (paper_ids[i], int(indeg[i]), title_by_id.get(paper_ids[i], "(no title)")) for i in per_field_top_idx[field]
            ]

    # ---------- Figure/artifact 4: field-focused Gephi subgraph ----------
    with Timer(log, "select field-diverse node set for the field-focused subgraph"):
        node_set = set()
        cs_idx = np.array([i for i in range(n) if dominant_field[i] == "Computer Science"])
        cs_top = cs_idx[np.argsort(indeg[cs_idx])[::-1][:TOP_CS_BACKBONE_SIZE]]
        node_set.update(cs_top.tolist())
        for field in NON_CS_FIELDS:
            idx_for_field = np.array([i for i in range(n) if dominant_field[i] == field])
            if len(idx_for_field) == 0:
                continue
            top_idx = idx_for_field[np.argsort(indeg[idx_for_field])[::-1][:TOP_HUBS_PER_FIELD_SUBGRAPH]]
            node_set.update(top_idx.tolist())
    log.info(f"field-focused node set size: {len(node_set):,}")

    with Timer(log, "induce subgraph edges from the full graph"):
        node_list = sorted(node_set)
        old_to_new = {old: new for new, old in enumerate(node_list)}
        edge_list = [(old_to_new[u], old_to_new[v]) for u, v in g.get_edgelist() if u in node_set and v in node_set]
    log.info(f"field-focused subgraph: {len(node_list):,} nodes, {len(edge_list):,} edges")

    import igraph as ig

    sub_g_ig = ig.Graph(n=len(node_list), edges=edge_list, directed=True)
    local_indeg = sub_g_ig.indegree()

    with Timer(log, "look up titles for field-focused subgraph nodes"):
        sub_paper_ids = [paper_ids[i] for i in node_list]
        title_by_id_sub = {}
        batch_size = 500
        for i in range(0, len(sub_paper_ids), batch_size):
            batch = sub_paper_ids[i : i + batch_size]
            placeholders = ",".join("?" * len(batch))
            rows = conn.execute(f"SELECT paper_id, title FROM papers WHERE paper_id IN ({placeholders})", batch).fetchall()
            title_by_id_sub.update(dict(rows))

    with Timer(log, "build networkx DiGraph and write field-focused GEXF"):
        G = nx.DiGraph()
        years = g.vs["year"]
        citation_counts = g.vs["citation_count"]
        for new_idx, old_idx in enumerate(node_list):
            pid = paper_ids[old_idx]
            title = title_by_id_sub.get(pid) or pid
            G.add_node(
                pid,
                label=title,
                year=years[old_idx] if years[old_idx] is not None else 0,
                citation_count=citation_counts[old_idx] if citation_counts[old_idx] is not None else 0,
                global_indegree=int(indeg[old_idx]),
                local_indegree=int(local_indeg[new_idx]),
                dominant_field=dominant_field[old_idx],
            )
        for u, v in edge_list:
            G.add_edge(sub_paper_ids[u], sub_paper_ids[v])
        nx.write_gexf(G, OUTPUT_GEXF)
    log.info(f"wrote {OUTPUT_GEXF} ({OUTPUT_GEXF.stat().st_size / 1e3:.1f} KB)")

    field_counts_in_subgraph = Counter(dominant_field[i] for i in node_list)
    log.info(f"field composition of field-focused subgraph: {field_counts_in_subgraph.most_common()}")

    # ---------- write results section ----------
    membership_table = "\n".join(f"| {f} | {c:,} | {c/n_with_fields:.1%} |" for f, c in top_membership)
    hub_tables_md = "\n\n".join(
        f"**Top {TOP_HUB_PAPERS_PER_FIELD_TABLE} {field} papers by in-crawl in-degree:**\n\n"
        + "\n".join(f"{rank+1}. `{pid}` (in-degree {ind:,}) — \"{title}\"" for rank, (pid, ind, title) in enumerate(rows))
        for field, rows in field_hub_tables.items() if rows
    )
    subgraph_field_table = "\n".join(
        f"| {f} | {c:,} |" for f, c in field_counts_in_subgraph.most_common()
    )

    md = f"""## Stage 9 — Field branching: does the citation network actually cross disciplines?

**Status:** done

Motivated by the original project expectation of seeing the network branch
into fields like Medicine, Biology, and Mathematics — not just stay within
CS/ML. Dominant field per paper is taken as the first field Semantic
Scholar lists for it (its own primary-field ordering); the long tail of
rare fields is bucketed as "Other".

**Overall field-membership distribution** (a paper may carry more than one
field tag; {n_with_fields:,}/{n:,} papers, {n_with_fields/n:.1%}, carry any
field tag at all):

| Field | Papers tagged | Share |
|---|---|---|
{membership_table}

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
citation crosses field boundaries. Naively, **{off_diagonal_share:.2%}**
of all {matrix.sum():,} edges connect papers with different primary-field
buckets — but that figure treats "Unknown" (no field tag at all) as its
own bucket, so an edge between an untagged paper and a Computer Science
paper counts as "cross-field" even though it reflects missing metadata,
not genuine interdisciplinary citation. Restricting to the
**{known_total:,} edges ({known_share_of_all_edges:.1%} of all edges)**
where *both* the citing and cited paper have a known, non-"Unknown"
primary field gives a cleaner measure: among those,
**{known_cross_field_share:.2%}** cross primary-field boundaries. This is
the number reported in the write-up. The rest are within-field citations,
overwhelmingly CS→CS given how large CS is in this dataset.

Figure: `analysis/figures/cross_field_citation_heatmap.png`

{hub_tables_md}

**Field-focused Gephi subgraph** — the Stage 8 k-core=20 subgraph is
CS-only by construction: k-core filtering keeps only the densest citation
core, and field-diverse papers (a Medicine paper citing a foundational ML
paper once, say) live in the sparser periphery that k-core filtering
strips away. To actually visualize field branching, this stage builds a
second, deliberately field-diverse node set instead: the top
{TOP_CS_BACKBONE_SIZE} CS papers by in-degree (the backbone), unioned with
the top {TOP_HUBS_PER_FIELD_SUBGRAPH} papers by in-degree *within* each of
Medicine/Engineering/Mathematics/Physics/Biology, with edges induced from
the full graph.

- Field-focused subgraph: **{len(node_list):,} nodes, {len(edge_list):,} edges**
- Field composition of this subgraph:

| Field | Nodes |
|---|---|
{subgraph_field_table}

Exported to: `analysis/field_focused_subgraph.gexf` — open in Gephi, run
ForceAtlas2, then color by the `dominant_field` node attribute (Partition)
and size by `global_indegree` (Ranking) to visualize field branching
directly, the same workflow as Stage 8.

Log: `analysis/logs/stage9_field_branching.log`
"""
    append_results_section(md)
    log.info("Stage 9 complete.")


if __name__ == "__main__":
    main()
