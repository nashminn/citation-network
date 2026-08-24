"""SQLite datastore for the citation crawl.

Schema is intentionally minimal: one row per paper, one row per citation edge.
`status` on a paper drives the BFS frontier:
  queued   - discovered, not yet had its own citer list pulled
  expanded - citer list fully pulled; all its citers are now in the DB
  skipped  - discovered via a non-influential citation; recorded but never
             queued for its own expansion (see plan.md: influential-only
             recursion)
"""

import json
import sqlite3
from contextlib import contextmanager

DEFAULT_DB_PATH = "citation_network.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    paper_id        TEXT PRIMARY KEY,
    title           TEXT,
    year            INTEGER,
    authors         TEXT,      -- JSON list of author names
    venue           TEXT,
    citation_count  INTEGER,
    reference_count INTEGER,
    pub_date        TEXT,      -- ISO date string, may be NULL
    depth           INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    fields_of_study TEXT       -- JSON list, e.g. ["Computer Science"]
);

CREATE TABLE IF NOT EXISTS edges (
    citing_id       TEXT NOT NULL,
    cited_id        TEXT NOT NULL,
    is_influential  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (citing_id, cited_id)
);

CREATE INDEX IF NOT EXISTS idx_papers_status_depth ON papers (status, depth);
CREATE INDEX IF NOT EXISTS idx_edges_cited ON edges (cited_id);
"""


@contextmanager
def connect(db_path: str = DEFAULT_DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=OFF;")
    try:
        yield conn
    finally:
        # Fold the WAL back into the main file so the single .db file is
        # self-contained and portable (git/git-lfs only tracks the .db file,
        # not the -wal/-shm sidecar files).
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Migration for DBs created before fields_of_study existed.
    try:
        conn.execute("ALTER TABLE papers ADD COLUMN fields_of_study TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise
    conn.commit()


def is_empty(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) FROM papers").fetchone()
    return row[0] == 0


def insert_paper_if_new(
    conn: sqlite3.Connection,
    paper_id: str,
    title: str | None,
    year: int | None,
    authors: list[str],
    venue: str | None,
    citation_count: int | None,
    reference_count: int | None,
    pub_date: str | None,
    depth: int,
    status: str,
    fields_of_study: list[str] | None = None,
) -> bool:
    """Insert a paper only if it doesn't already exist.

    Returns True if a new row was inserted, False if the paper was already
    known (in which case its existing status/depth is left untouched -- we
    never downgrade an already-expanded or already-queued paper).
    """
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO papers
            (paper_id, title, year, authors, venue, citation_count,
             reference_count, pub_date, depth, status, fields_of_study)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            title,
            year,
            json.dumps(authors or []),
            venue,
            citation_count,
            reference_count,
            pub_date,
            depth,
            status,
            json.dumps(fields_of_study or []),
        ),
    )
    return cur.rowcount > 0


def set_fields_of_study(conn: sqlite3.Connection, paper_id: str, fields_of_study: list[str]) -> None:
    conn.execute(
        "UPDATE papers SET fields_of_study = ? WHERE paper_id = ?",
        (json.dumps(fields_of_study or []), paper_id),
    )


def all_paper_ids(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT paper_id FROM papers").fetchall()]


def add_edge(
    conn: sqlite3.Connection, citing_id: str, cited_id: str, is_influential: bool
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO edges (citing_id, cited_id, is_influential)
        VALUES (?, ?, ?)
        """,
        (citing_id, cited_id, 1 if is_influential else 0),
    )


def mark_status(conn: sqlite3.Connection, paper_id: str, status: str) -> None:
    conn.execute("UPDATE papers SET status = ? WHERE paper_id = ?", (status, paper_id))


def next_queued_batch(conn: sqlite3.Connection, limit: int = 1) -> list[sqlite3.Row]:
    """Fetch the next papers to expand, lowest depth first (strict BFS order)."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT paper_id, depth FROM papers
        WHERE status = 'queued'
        ORDER BY depth ASC, rowid ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.row_factory = None
    return rows


def stats(conn: sqlite3.Connection) -> dict:
    conn.row_factory = sqlite3.Row
    by_status = {
        r["status"]: r["n"]
        for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM papers GROUP BY status"
        ).fetchall()
    }
    by_depth = {
        r["depth"]: r["n"]
        for r in conn.execute(
            "SELECT depth, COUNT(*) AS n FROM papers GROUP BY depth ORDER BY depth"
        ).fetchall()
    }
    total_edges = conn.execute("SELECT COUNT(*) AS n FROM edges").fetchone()["n"]
    conn.row_factory = None
    return {"by_status": by_status, "by_depth": by_depth, "total_edges": total_edges}
