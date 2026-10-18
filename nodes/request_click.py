"""Node "Kerelem rogzitese": records a one-click application request.

The daily e-mail has an "I want this" button per job, which opens the n8n webhook
with the job in the query string (id, cim, ceg, url). The request file is picked
up by the evening document-preparation task.
"""
import re

from common import clock_str, day_str, iso_utc, js_slice, js_str, now_local, to_json

# The job ID goes into a file name, so only these characters are kept.
UNSAFE_ID_CHARACTERS = re.compile(r"[^A-Za-z0-9_-]")
MAX_ID_LENGTH = 40


def clean_job_id(raw_id):
    """Make the job ID safe for a file name.

    Example: clean_job_id("44/79?<x>") -> "4479x";  clean_job_id(None) -> "ismeretlen"
    """
    job_id = js_str(raw_id)
    if job_id == "":
        job_id = "ismeretlen"  # "unknown"
    job_id = UNSAFE_ID_CHARACTERS.sub("", job_id)
    return js_slice(job_id, 0, MAX_ID_LENGTH)


def main(items, now=None):
    # 1. The webhook delivers one item; the button's parameters are in "query".
    query = {}
    if len(items) > 0 and items[0]["json"].get("query"):
        query = items[0]["json"]["query"]

    # 2. Time of the click. Only the tests pass `now`, to get a fixed time.
    if now is None:
        now = now_local()
    day = day_str(now)

    # 3. The request record that the evening task reads.
    job_id = clean_job_id(query.get("id"))
    record = {
        "kert": iso_utc(now),  # when it was requested
        "datum": day,
        "forras": "egykattintas",  # source: the one-click button
        "jobId": job_id,
        "pozicio": js_str(query.get("cim")),
        "ceg": js_str(query.get("ceg")),
        "url": js_str(query.get("url")),
        "allapot": "uj",  # status: new
    }

    # 4. One output item. The next n8n nodes save `tartalom` as `filename`, and
    #    use `pozicio` and `ceg` on the confirmation page.
    output = {
        "filename": f"kerelem_{day}_{clock_str(now)}_{job_id}.json",
        "tartalom": to_json(record),
        "pozicio": record["pozicio"],
        "ceg": record["ceg"],
    }
    return [{"json": output}]
