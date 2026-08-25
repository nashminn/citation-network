"""Watches the live crawl DB and, the moment depth-1 is fully expanded
(before depth-2 expansion begins changing anything further), takes a safe
point-in-time snapshot -- both a DB copy and a GEXF export -- so the
"depth-1 complete" milestone is preserved even though the live crawl keeps
running past it into depth-2.

Uses SQLite's online backup API (not a plain file copy), which is safe to
run concurrently against a WAL-mode DB that's still being actively written
to by the crawler -- it produces a consistent snapshot regardless of
in-flight writes, unlike copying the raw file.

Safe to run alongside the live crawler process; never opens the live DB for
writing, only reads (for polling) and backs it up (read-only source side).
"""

import argparse
import logging
import sqlite3
import time

import export_gexf

log = logging.getLogger("snapshot_depth1")


def depth1_remaining(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA busy_timeout=30000;")
        row = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE depth = 1 AND status = 'queued'"
        ).fetchone()
        return row[0]
    finally:
        conn.close()


def safe_snapshot(source_db_path: str, dest_db_path: str) -> None:
    """Point-in-time copy via SQLite's backup API -- safe against a
    concurrent writer, unlike a plain file copy (which could catch the
    source mid-write or miss recent writes still sitting in the -wal file
    that hasn't been checkpointed into the main .db file yet)."""
    src = sqlite3.connect(source_db_path)
    dest = sqlite3.connect(dest_db_path)
    try:
        src.backup(dest)
    finally:
        src.close()
        dest.close()


def run(db_path: str, snapshot_db: str, snapshot_gexf: str, poll_seconds: float) -> None:
    log.info("Watching %s for depth-1 completion (polling every %.0fs)", db_path, poll_seconds)
    while True:
        remaining = depth1_remaining(db_path)
        log.info("%d depth-1 papers still queued", remaining)
        if remaining == 0:
            break
        time.sleep(poll_seconds)

    log.info("Depth-1 complete. Snapshotting to %s", snapshot_db)
    safe_snapshot(db_path, snapshot_db)
    n_nodes, n_edges = export_gexf.export(snapshot_db, snapshot_gexf)
    log.info("Snapshot done: %s (%d nodes, %d edges)", snapshot_gexf, n_nodes, n_edges)
    # Deliberately the only stdout output -- everything else above only went
    # to the log file, so this line is the one real signal that this is done.
    print(f"DEPTH-1 SNAPSHOT COMPLETE: {snapshot_gexf} ({n_nodes} nodes, {n_edges} edges)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Snapshot the DB once depth-1 fully expands")
    parser.add_argument("--db", default="citation_network_v3.db")
    parser.add_argument("--snapshot-db", default="citation_network_v3_depth1.db")
    parser.add_argument("--snapshot-gexf", default="citation_network_v3_depth1.gexf")
    parser.add_argument("--poll-seconds", type=float, default=300.0)
    parser.add_argument("--log-file", default="logs/snapshot_depth1.log")
    args = parser.parse_args()

    import os

    os.makedirs(os.path.dirname(args.log_file) or ".", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(args.log_file)],  # stdout stays quiet until the final print
    )

    run(args.db, args.snapshot_db, args.snapshot_gexf, args.poll_seconds)
