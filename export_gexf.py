"""Export the SQLite citation graph to GEXF for Gephi.

Usable standalone (`python export_gexf.py`) at any time without stopping the
crawler -- SQLite's WAL mode makes this safe to read concurrently.
"""

import argparse
import json
import logging

import networkx as nx

import db

log = logging.getLogger("export_gexf")

DEFAULT_OUTPUT = "citation_network.gexf"


def export(db_path: str, output_path: str) -> tuple[int, int]:
    graph = nx.DiGraph()

    with db.connect(db_path) as conn:
        conn.row_factory = None
        for row in conn.execute(
            """
            SELECT paper_id, title, year, authors, venue, citation_count,
                   reference_count, pub_date, depth, status
            FROM papers
            """
        ):
            (
                paper_id,
                title,
                year,
                authors_json,
                venue,
                citation_count,
                reference_count,
                pub_date,
                depth,
                status,
            ) = row
            authors = ", ".join(json.loads(authors_json or "[]"))
            graph.add_node(
                paper_id,
                title=title or "",
                year=year if year is not None else -1,
                authors=authors,
                venue=venue or "",
                citation_count=citation_count if citation_count is not None else -1,
                reference_count=reference_count if reference_count is not None else -1,
                pub_date=pub_date or "",
                depth=depth,
                expanded=(status == "expanded"),
            )

        for citing_id, cited_id, is_influential in conn.execute(
            "SELECT citing_id, cited_id, is_influential FROM edges"
        ):
            # Only add an edge if both endpoints made it into the graph
            # (both survive the publication-date cutoff filter at crawl time).
            if citing_id in graph and cited_id in graph:
                graph.add_edge(citing_id, cited_id, is_influential=bool(is_influential))

    nx.write_gexf(graph, output_path)
    return graph.number_of_nodes(), graph.number_of_edges()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Export citation_network.db to GEXF")
    parser.add_argument("--db", default=db.DEFAULT_DB_PATH)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    n_nodes, n_edges = export(args.db, args.output)
    log.info("Wrote %s: %d nodes, %d edges", args.output, n_nodes, n_edges)
