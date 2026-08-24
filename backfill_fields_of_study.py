"""One-off backfill: populate fields_of_study for papers already in the DB
before this field was added to the crawler. Safe to run while the crawler is
NOT running (stop it first -- see README). Uses the /paper/batch endpoint,
so this is cheap: ~15 requests for thousands of papers, not one per paper.
"""

import argparse
import logging

import api_client
import db

log = logging.getLogger("backfill_fields_of_study")


def run(db_path: str) -> None:
    client = api_client.SemanticScholarClient()
    log.info("Backfilling with authenticated=%s", bool(client.api_key))

    with db.connect(db_path) as conn:
        db.init_db(conn)
        paper_ids = db.all_paper_ids(conn)
        log.info("Backfilling fields_of_study for %d papers", len(paper_ids))

        done = 0
        for paper_id, fields_of_study in client.iter_fields_of_study_batches(paper_ids):
            db.set_fields_of_study(conn, paper_id, fields_of_study)
            done += 1
            if done % 500 == 0:
                conn.commit()
                log.info("Backfilled %d/%d", done, len(paper_ids))

        conn.commit()
        log.info("Backfill complete: %d/%d papers updated", done, len(paper_ids))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Backfill fields_of_study for existing papers")
    parser.add_argument("--db", default=db.DEFAULT_DB_PATH)
    args = parser.parse_args()

    run(args.db)
