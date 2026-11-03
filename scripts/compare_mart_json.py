"""Parity check while the evening review moves from the JSON file to the mart.

Applies the mart's relevance rule independently in Python to one day's JSON file
and compares the result with marts.mart_relevant_postings for that day. The rule
(dbt/models/marts): fully remote, or any work mode in the Budapest area.

Usage:
  python scripts/compare_mart_json.py DATE DATA_DIR      e.g. 2026-10-29 ../allasfigyelo
Exit code 0 when the two sets match, 1 when they differ.
"""
import json
import os
import pathlib
import sys

WORK_MODES = {"Tavmunka/Remote": "remote", "Hibrid/Home office": "hybrid",
              "Barmilyen (helyszini is)": "any"}


def is_relevant(job):
    """The mart's rule, written again from the JSON fields."""
    location = (job.get("location") or "").lower()
    budapest_area = "budapest" in location or location.startswith("pest megye")
    return WORK_MODES.get(job.get("placeLabel")) == "remote" or budapest_area


def json_ids(path):
    daily = json.loads(path.read_text(encoding="utf-8"))
    return {job["id"] for job in daily["allasok"] if is_relevant(job)}


def mart_ids(day):
    import psycopg

    with psycopg.connect(os.environ.get("DATABASE_URL", "dbname=jobs")) as conn:
        rows = conn.execute("select job_id from marts.mart_relevant_postings "
                            "where collected_on = %s", (day,)).fetchall()
    return {job_id for (job_id,) in rows}


def main(day, data_dir):
    path = pathlib.Path(data_dir) / f"allasok_{day}.json"
    if not path.exists():
        print(f"{day}: no JSON file")
        return 1
    from_json, from_mart = json_ids(path), mart_ids(day)
    if from_json == from_mart:
        print(f"{day}: match, {len(from_mart)} relevant postings in both")
        return 0
    print(f"{day}: DIFFERENCE, JSON {len(from_json)} vs mart {len(from_mart)}")
    for job_id in sorted(from_json - from_mart):
        print(f"  only in JSON: {job_id}")
    for job_id in sorted(from_mart - from_json):
        print(f"  only in mart: {job_id}")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
