# Inspecting the crawl DB

`citation_network.db` is safe to read at any time while the crawler is
running — it's in SQLite WAL mode, which supports concurrent readers without
disturbing the writer.

## Quick stats (no extra tools needed)

Using the project's own `db.py` helper (from the project root, with the venv):

```bash
.venv/bin/python -c "
import db
with db.connect('citation_network.db') as conn:
    print(db.stats(conn))
"
```

Returns something like:
```python
{
  'by_status': {'expanded': 25, 'queued': 40210, 'skipped': 812},
  'by_depth': {0: 1, 1: 41048},
  'total_edges': 41048
}
```
- `by_status`: how many papers are `expanded` (done), `queued` (frontier,
  waiting to be expanded), or `skipped` (recorded but deliberately not
  recursed into, per the influential-only rule).
- `by_depth`: how many papers are at each hop distance from AIAYN.
- `total_edges`: total citation edges recorded so far.

## Raw SQL (if you install `sqlite3`)

```bash
sudo apt install sqlite3   # not installed by default on this machine
sqlite3 citation_network.db
```

Useful queries once inside the `sqlite3` shell:

```sql
-- overall counts
SELECT status, COUNT(*) FROM papers GROUP BY status;

-- what's currently in the frontier, oldest first (BFS order)
SELECT paper_id, title, depth FROM papers WHERE status = 'queued' ORDER BY rowid LIMIT 20;

-- most-cited papers discovered so far
SELECT title, citation_count FROM papers ORDER BY citation_count DESC LIMIT 20;

-- how big is the DB getting
.exit
```
```bash
du -h citation_network.db
```

## Watching the crawler live (without touching the DB)

The runtime log is plain text, safe to `tail` anytime:
```bash
tail -f logs/crawler.log
```

## Checking progress without a query

Every checkpoint (every 6h by default, plus on clean exit) overwrites
`citation_network.gexf` — you can open that in Gephi at any time to see a
visual snapshot of progress, without needing to touch the database directly.

## A note on rate limiting

`logs/crawler.log` also shows every time the API responds with `429` (rate
limited) — a healthy run will show occasional ones (the client retries with
backoff automatically), but a very high ratio of 429s to successful
`Expanded` lines suggests the configured pacing (`min_interval` in
`api_client.py`, currently 1.0s with an API key) may need to be loosened
slightly for better effective throughput. Check with:

```bash
grep -c "429 rate-limited" logs/crawler.log
grep -c "Expanded" logs/crawler.log
```
