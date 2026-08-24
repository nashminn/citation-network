"""Recursive breadth-first citation crawler, rooted at "Attention Is All You
Need" (arXiv:1706.03762).

Long-running by design: meant to be started once (e.g. via `nohup` on Linux,
or left running in a terminal / `pythonw` on Windows -- see plan.md for
platform notes) and left for days. Safe to interrupt (Ctrl+C) and re-run --
it resumes from whatever's `queued` in the SQLite DB.

Recursion rule (see plan.md): every direct citer of an expanded paper is
recorded as a node/edge, but only citers whose citation was flagged
`isInfluential` by Semantic Scholar get queued for their own expansion.
Publication-date cutoff: 2026-07-31.
"""

import argparse
import logging
import signal
import time
from datetime import date

import api_client
import db
import export_gexf

log = logging.getLogger("crawler")

ROOT_ARXIV_ID = "arXiv:1706.03762"  # Attention Is All You Need
CUTOFF_DATE = date(2026, 7, 31)
MAX_CONSECUTIVE_FAILURES = 5  # give up on a specific paper after this many in a row

_stop_requested = False


def _handle_signal(signum, frame):
    global _stop_requested
    log.info("Signal %s received, will stop after the current paper finishes", signum)
    _stop_requested = True


def _passes_cutoff(pub_date: str | None, year: int | None) -> bool:
    if pub_date:
        try:
            y, m, d = (int(x) for x in pub_date.split("-"))
            return date(y, m, d) <= CUTOFF_DATE
        except (ValueError, TypeError):
            pass
    if year is not None:
        return year <= CUTOFF_DATE.year
    # No date info at all -- don't drop it, we can't tell.
    return True


def seed_if_needed(conn, client: api_client.SemanticScholarClient) -> None:
    if not db.is_empty(conn):
        return
    log.info("Empty DB, resolving root paper %s", ROOT_ARXIV_ID)
    paper = client.resolve_paper(ROOT_ARXIV_ID)
    if paper is None:
        raise RuntimeError(f"Could not resolve root paper {ROOT_ARXIV_ID}")
    db.insert_paper_if_new(
        conn,
        paper_id=paper["paperId"],
        title=paper.get("title"),
        year=paper.get("year"),
        authors=[a.get("name", "") for a in (paper.get("authors") or [])],
        venue=paper.get("venue"),
        citation_count=paper.get("citationCount"),
        reference_count=paper.get("referenceCount"),
        pub_date=paper.get("publicationDate"),
        depth=0,
        status="queued",
    )
    conn.commit()
    log.info("Seeded root paper %s (%s)", paper["paperId"], paper.get("title"))


def expand_one(conn, client: api_client.SemanticScholarClient, paper_id: str, depth: int) -> int:
    """Pull the full citer list for one paper. Returns count of new papers added.

    If a transient failure (network/429/5xx exhausted its retries) interrupts
    pagination partway through, whatever pages were already processed are
    kept, but `paper_id` is deliberately left `queued` (not `expanded`) so
    it's picked up and finished on a later pass rather than silently treated
    as fully expanded with partial data.
    """
    new_count = 0
    interrupted = False
    try:
        for citation in client.iter_citations(paper_id):
            citing = citation.get("citingPaper")
            if not citing or not citing.get("paperId"):
                continue
            pub_date = citing.get("publicationDate")
            year = citing.get("year")
            if not _passes_cutoff(pub_date, year):
                continue

            is_influential = bool(citation.get("isInfluential"))
            status = "queued" if is_influential else "skipped"
            inserted = db.insert_paper_if_new(
                conn,
                paper_id=citing["paperId"],
                title=citing.get("title"),
                year=year,
                authors=[a.get("name", "") for a in (citing.get("authors") or [])],
                venue=citing.get("venue"),
                citation_count=citing.get("citationCount"),
                reference_count=citing.get("referenceCount"),
                pub_date=pub_date,
                depth=depth + 1,
                status=status,
            )
            db.add_edge(
                conn, citing_id=citing["paperId"], cited_id=paper_id, is_influential=is_influential
            )
            if inserted:
                new_count += 1
    except api_client.GaveUp as exc:
        log.warning(
            "Transient failure expanding %s, leaving it queued for retry: %s", paper_id, exc
        )
        interrupted = True

    if not interrupted:
        db.mark_status(conn, paper_id, "expanded")
    conn.commit()
    return new_count, interrupted


def checkpoint(db_path: str, output_path: str) -> None:
    n_nodes, n_edges = export_gexf.export(db_path, output_path)
    log.info("Checkpoint written to %s (%d nodes, %d edges)", output_path, n_nodes, n_edges)


def run(db_path: str, checkpoint_hours: float, gexf_output: str) -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    client = api_client.SemanticScholarClient()
    log.info(
        "Starting crawler (authenticated=%s, min_interval=%.1fs)",
        bool(client.api_key),
        client.min_interval,
    )

    with db.connect(db_path) as conn:
        db.init_db(conn)
        seed_if_needed(conn, client)

        last_checkpoint = time.monotonic()
        checkpoint_interval = checkpoint_hours * 3600
        processed = 0
        consecutive_failures: dict[str, int] = {}

        while not _stop_requested:
            batch = db.next_queued_batch(conn, limit=1)
            if not batch:
                log.info("Frontier exhausted -- crawl complete.")
                break
            paper_id, depth = batch[0]["paper_id"], batch[0]["depth"]
            new_count, interrupted = expand_one(conn, client, paper_id, depth)

            if interrupted:
                fails = consecutive_failures.get(paper_id, 0) + 1
                consecutive_failures[paper_id] = fails
                if fails >= MAX_CONSECUTIVE_FAILURES:
                    log.error(
                        "%s failed %d times in a row, marking as 'error' and moving on",
                        paper_id,
                        fails,
                    )
                    db.mark_status(conn, paper_id, "error")
                    conn.commit()
                    del consecutive_failures[paper_id]
                continue
            else:
                consecutive_failures.pop(paper_id, None)

            processed += 1
            log.info(
                "Expanded %s (depth %d): +%d new papers [%d processed this run]",
                paper_id,
                depth,
                new_count,
                processed,
            )

            if processed % 50 == 0:
                log.info("Stats: %s", db.stats(conn))

            if time.monotonic() - last_checkpoint >= checkpoint_interval:
                checkpoint(db_path, gexf_output)
                last_checkpoint = time.monotonic()

        checkpoint(db_path, gexf_output)
        log.info("Final stats: %s", db.stats(conn))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recursive citation network crawler")
    parser.add_argument("--db", default=db.DEFAULT_DB_PATH)
    parser.add_argument("--checkpoint-hours", type=float, default=6.0)
    parser.add_argument("--gexf-output", default=export_gexf.DEFAULT_OUTPUT)
    parser.add_argument("--log-file", default="logs/crawler.log")
    args = parser.parse_args()

    import os

    os.makedirs(os.path.dirname(args.log_file) or ".", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(args.log_file), logging.StreamHandler()],
    )

    run(args.db, args.checkpoint_hours, args.gexf_output)
