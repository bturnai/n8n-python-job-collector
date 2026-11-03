"""Load the daily job files (allasok_YYYY-MM-DD.json) into PostgreSQL, unchanged.

Each posting becomes one row of raw.job_postings (sql/001_create_raw_job_postings.sql).
Loading is idempotent: a posting already in the table (same id) is skipped, so a
file can be loaded again without creating duplicates. Each file is one transaction.

Usage:
  python scripts/load_postgres.py FILE [FILE ...]
  DATABASE_URL="dbname=jobs host=localhost" python scripts/load_postgres.py FILE

Default connection: dbname=jobs on the local server.
"""
import json
import os
import pathlib
import re
import sys

# Half of a UTF-16 surrogate pair, e.g. an emoji cut in two by the collector's
# 2200-character limit on descriptions. Not valid UTF-8, so PostgreSQL rejects it.
LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")

INSERT = """
INSERT INTO raw.job_postings
    (id, source, title, company, location, place_label, url, salary_info,
     techs, description, collected_on, source_file, payload)
VALUES
    (%(id)s, %(source)s, %(title)s, %(company)s, %(location)s, %(place_label)s, %(url)s,
     %(salary_info)s, %(techs)s, %(description)s, %(collected_on)s, %(source_file)s,
     %(payload)s)
ON CONFLICT (id) DO NOTHING
"""


def clean(obj):
    """Replace lone surrogates with U+FFFD in every string of a record."""
    if isinstance(obj, str):
        return LONE_SURROGATE.sub("�", obj)
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    return obj


def to_rows(daily, source_file):
    """Map one daily file to table rows. Empty strings become NULL."""
    def value(job, key):
        v = job.get(key)
        return v if v not in ("", None) else None

    rows = []
    for job in map(clean, daily["allasok"]):
        rows.append({
            "id": job["id"],
            "source": job["forras"],
            "title": job["title"],
            "company": value(job, "company"),
            "location": value(job, "location"),
            "place_label": value(job, "placeLabel"),
            "url": value(job, "url"),
            "salary_info": value(job, "salaryInfo"),
            "techs": value(job, "techs"),
            "description": value(job, "description"),
            "collected_on": daily["datum"],
            "source_file": source_file,
            "payload": json.dumps(job, ensure_ascii=False),
        })
    return rows


def load_file(conn, path):
    """Insert one file's postings; return (inserted, skipped)."""
    daily = json.loads(path.read_text(encoding="utf-8"))
    rows = to_rows(daily, path.name)
    inserted = 0
    with conn.transaction(), conn.cursor() as cur:
        for row in rows:
            cur.execute(INSERT, row)
            inserted += cur.rowcount
    return inserted, len(rows) - inserted


def main(paths):
    import psycopg

    dsn = os.environ.get("DATABASE_URL", "dbname=jobs")
    total_in = total_skip = 0
    with psycopg.connect(dsn) as conn:
        for path in map(pathlib.Path, paths):
            inserted, skipped = load_file(conn, path)
            total_in += inserted
            total_skip += skipped
            print(f"{path.name}: {inserted} inserted, {skipped} already present")
    print(f"Total: {total_in} inserted, {total_skip} already present")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
