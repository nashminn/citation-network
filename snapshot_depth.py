"""Watches the live crawl DB and, the moment a given depth layer is fully
expanded (before the next depth's expansion changes the live files further),
takes a safe point-in-time snapshot -- DB backup + GEXF export -- commits it,
and pushes it. Generalization of snapshot_depth1.py (kept as-is, historical)
for any depth -- e.g. depth-2, depth-3, etc.

Uses SQLite's online backup API (not a plain file copy), which is safe to
run concurrently against a WAL-mode DB that's still being actively written
to by the crawler -- it produces a consistent snapshot regardless of
in-flight writes, unlike copying the raw file.

Safe to run alongside the live crawler process; never opens the live DB for
writing, only reads (for polling) and backs it up (read-only source side).
"""

import argparse
import logging
import os
import subprocess
import sqlite3
import time

import export_gexf

log = logging.getLogger("snapshot_depth")


def depth_remaining(db_path: str, depth: int) -> int:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA busy_timeout=30000;")
        row = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE depth = ? AND status = 'queued'", (depth,)
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


def git_commit_and_push(files: list[str], commit_message: str) -> bool:
    """Commit the given (already-safe-on-disk) files and push to origin/main.
    Logs and returns False on any failure rather than raising -- the local
    snapshot files are already safely written regardless of whether this
    step succeeds (e.g. a git-LFS storage quota bump for a large snapshot),
    so a git/network hiccup here shouldn't look like the snapshot itself
    failed."""
    try:
        add = subprocess.run(["git", "add", *files], capture_output=True, text=True)
        if add.returncode != 0:
            log.error("git add failed: %s", add.stdout + add.stderr)
            return False

        commit = subprocess.run(
            ["git", "commit", "-m", commit_message], capture_output=True, text=True
        )
        if commit.returncode != 0:
            log.error("git commit failed: %s", commit.stdout + commit.stderr)
            return False
        log.info("git commit succeeded")

        push = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
        if push.returncode != 0:
            log.error("git push failed: %s", push.stdout + push.stderr)
            return False
        log.info("git push succeeded")
        return True
    except Exception:
        log.exception("git commit/push step failed")
        return False


def run(
    db_path: str,
    depth: int,
    snapshot_db: str,
    snapshot_gexf: str,
    poll_seconds: float,
    note: str | None = None,
) -> None:
    log.info(
        "Watching %s for depth-%d completion (polling every %.0fs)", db_path, depth, poll_seconds
    )
    while True:
        remaining = depth_remaining(db_path, depth)
        log.info("%d depth-%d papers still queued", remaining, depth)
        if remaining == 0:
            break
        time.sleep(poll_seconds)

    log.info("Depth-%d complete. Snapshotting to %s", depth, snapshot_db)
    safe_snapshot(db_path, snapshot_db)
    n_nodes, n_edges = export_gexf.export(snapshot_db, snapshot_gexf)
    log.info("Snapshot done: %s (%d nodes, %d edges)", snapshot_gexf, n_nodes, n_edges)

    commit_message = (
        f"feat: add depth-{depth} complete snapshot ({n_nodes} nodes, {n_edges} edges)\n\n"
        f"Isolated snapshot taken automatically the moment depth-{depth} finished "
        "expanding, before the next depth continued changing the live DB/GEXF further."
    )
    if note:
        commit_message += f"\n\n{note}"
    pushed = git_commit_and_push([snapshot_db, snapshot_gexf], commit_message)

    # Deliberately the only stdout output -- everything else above only went
    # to the log file, so this line is the one real signal that this is done.
    status = "committed + pushed" if pushed else "commit/push FAILED, see log"
    print(
        f"DEPTH-{depth} SNAPSHOT COMPLETE: {snapshot_gexf} "
        f"({n_nodes} nodes, {n_edges} edges) -- {status}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Snapshot the DB once a given depth fully expands")
    parser.add_argument("--db", default="citation_network_v3.db")
    parser.add_argument("--depth", type=int, required=True)
    parser.add_argument("--snapshot-db", default=None)
    parser.add_argument("--snapshot-gexf", default=None)
    parser.add_argument("--poll-seconds", type=float, default=300.0)
    parser.add_argument("--log-file", default=None)
    parser.add_argument(
        "--note", default=None, help="Extra paragraph appended to the auto-generated commit message"
    )
    args = parser.parse_args()

    snapshot_db = args.snapshot_db or f"citation_network_v3_depth{args.depth}.db"
    snapshot_gexf = args.snapshot_gexf or f"citation_network_v3_depth{args.depth}.gexf"
    log_file = args.log_file or f"logs/snapshot_depth{args.depth}.log"

    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_file)],  # stdout stays quiet until the final print
    )

    run(args.db, args.depth, snapshot_db, snapshot_gexf, args.poll_seconds, note=args.note)
