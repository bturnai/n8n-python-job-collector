"""The evening review's input from the database: napi_allasok_<day>.json.

Until 2026-11-16 the evening review read the collector's JSON file (allasok_<day>.json).
Now it reads the same day's relevant postings from marts.mart_relevant_postings, so
every source that reaches the database is in one place (profession.hu, NoFluffJobs,
Indeed, and later LinkedIn and the company job boards). The fields keep the names of
the old file, so the review's instructions hardly change.

    python scripts/export_review.py 2026-11-16 ../allasfigyelo

The v5 scores are NOT in this file on purpose: the review scores the postings itself
first, and reads llm_pontok_<day>.json only after that (two independent opinions).
"""
import json
import os
import pathlib
import sys

# The work modes of the mart, back to the labels of the old JSON file.
PLACE_LABELS = {"remote": "Tavmunka/Remote", "hybrid": "Hibrid/Home office",
                "any": "Barmilyen (helyszini is)"}


def review_item(row):
    """One posting in the old JSON shape.

    row: (job_id, title, company, location, work_mode, source, url, techs, description,
          salary_info), as the query in main() returns it.
    Example: ("3051161", "Business Analyst", "Hiflylabs Zrt.", "Pest megye", "hybrid",
              "profession.hu", "https://...", "", "Állás leírása ...", "")
          -> {"id": "3051161", "title": "Business Analyst", ..., "placeLabel": "Hibrid/Home office",
              "forras": "profession.hu", ...}
    """
    job_id, title, company, location, work_mode, source, url, techs, description, salary = row
    place = PLACE_LABELS.get(work_mode, "")
    return {"id": job_id, "title": title, "company": company or "", "location": location or "",
            "placeLabel": place, "url": url or "", "salaryInfo": salary or "", "forras": source,
            "techs": techs or "", "description": description or ""}


def review_file(day, rows, alerts):
    """The whole file as a dict. alerts: the collector's warnings of that day (riasztasok)."""
    postings = []
    for row in rows:
        postings.append(review_item(row))
    return {"datum": day, "forras": "adatbazis", "riasztasok": alerts, "allasok": postings}


def collector_alerts(data_dir, day):
    """The warnings in the collector's own file (e.g. "profession.hu: 0 hirdetes"), or []."""
    path = pathlib.Path(data_dir) / f"allasok_{day}.json"
    if not path.exists():
        return []
    daily = json.loads(path.read_text(encoding="utf-8"))
    return daily.get("riasztasok") or []


def main(day, data_dir):
    import psycopg

    with psycopg.connect(os.environ.get("DATABASE_URL", "dbname=jobs")) as conn:
        rows = conn.execute(
            """
            select 
                m.job_id,
                m.title,
                m.company,
                m.location,
                m.work_mode,
                m.source,
                m.url,
                m.techs_raw,
                m.description,
                r.salary_info
            from
                marts.mart_relevant_postings m
            join 
                raw.job_postings r 
            on 
                r.id = m.job_id
            where
                m.collected_on = %s
            order by 
                m.source,
                m.company,
                m.title
            """, (day,)).fetchall()
    content = review_file(day, rows, collector_alerts(data_dir, day))
    path = pathlib.Path(data_dir) / f"napi_allasok_{day}.json"
    path.write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {path.name}: {len(content['allasok'])} postings")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
