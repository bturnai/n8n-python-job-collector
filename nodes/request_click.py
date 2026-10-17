"""Node "Kerelem rogzitese": records a one-click application request.

The daily e-mail has an "I want this" button per job, which opens the n8n webhook
with the job in the query string (id, cim, ceg, url). The request file is picked
up by the evening document-preparation task.
"""
import re

from common import clock_str, day_str, iso_utc, js_slice, js_str, now_local, to_json


def main(items, now=None):
    moment = now or now_local()
    query = (items[0]["json"].get("query") if items else None) or {}
    day = day_str(moment)
    clock = clock_str(moment)
    job_id = js_slice(re.sub(r"[^A-Za-z0-9_-]", "", js_str(query.get("id")) or "ismeretlen"), 0, 40)

    record = {
        "kert": iso_utc(moment), "datum": day, "forras": "egykattintas",
        "jobId": job_id, "pozicio": js_str(query.get("cim")), "ceg": js_str(query.get("ceg")),
        "url": js_str(query.get("url")), "allapot": "uj",
    }
    return [{"json": {
        "filename": f"kerelem_{day}_{clock}_{job_id}.json",
        "tartalom": to_json(record),
        "pozicio": record["pozicio"], "ceg": record["ceg"],
    }}]
