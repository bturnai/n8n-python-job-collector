"""Node "API talalatok feldolgozasa": normalises the remote-job API responses.

Input: the de-duplication state, plus one item per API response - the source
item (`forras`, `url`) merged with the downloaded body (`data`). Output: new,
data-related jobs in the same shape as the profession.hu jobs, at most MAX_NEW.

Each API returns its jobs in its own format; one function per API converts them
to the common fields: id, title, company, location, placeLabel, url, techs,
description, salaryInfo, forras.
"""
import json
import re

from common import collapse_ws, dedupe_key, js_slice, js_str, js_trim, split_state

# Same idea as in filter_new.py, without the Hungarian words ("adat", "riport"):
# these APIs list English-language jobs.
DATA_TITLE_PATTERN = re.compile(
    r"(data|analy|analit|scien|machine learning|\bml\b|\bbi\b"
    r"|business intelligence|python|\bsql\b|report)",
    re.IGNORECASE | re.ASCII,
)
MAX_NEW = 50
DESCRIPTION_LIMIT = 2200
REMOTE = "Tavmunka/Remote"

# RemoteOK sends some text "double encoded": "don’t" arrives as "donâ\x80\x99t".
# The apostrophe ’ is three bytes in UTF-8 (E2 80 99); somewhere upstream these
# bytes were read as three Latin-1 characters (â, \x80, \x99).
# This pattern finds such sequences: one character from Â..ô, then 1-3 from \x80..¿.
MOJIBAKE_PATTERN = re.compile("[Â-ô][\u0080-¿]{1,3}")


def repair_sequence(match):
    """Turn one mis-read sequence back into its character: "â\\x80\\x99" -> "’"."""
    broken = match.group()
    try:
        # Undo the wrong step (back to the original bytes), then read them correctly.
        return broken.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return broken  # not a mis-read sequence after all: leave it as it is


def fix_mojibake(text):
    """Example: fix_mojibake("donâ\\x80\\x99t") -> "don’t"

    re.sub calls repair_sequence for every match and puts its result in place.
    """
    return MOJIBAKE_PATTERN.sub(repair_sequence, text)


def strip_html(html):
    """Plain text from an HTML description, at most DESCRIPTION_LIMIT long."""
    text = re.sub(r"<[^>]+>", " ", js_str(html))  # every tag becomes a space
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&quot;", '"')
    text = text.replace("&#039;", "'")
    text = text.replace("&#39;", "'")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = js_trim(collapse_ws(text))
    return js_slice(text, 0, DESCRIPTION_LIMIT)


def js_value_to_text(value):
    """Print a JSON value the way JavaScript would ("1.0" is "1", None is "null")."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def join_tags(job):
    """Example: {"tags": ["python", "sql"]} -> "python, sql" """
    tags = job.get("tags") or []
    parts = []
    for tag in tags:
        if tag is None:
            parts.append("")  # JavaScript's join prints null as an empty string
        else:
            parts.append(js_value_to_text(tag))
    return ", ".join(parts)


def parse_remotive(body):
    """Remotive: {"jobs": [{"id", "title", "company_name", ...}, ...]}"""
    jobs = []
    for job in body.get("jobs") or []:
        jobs.append({
            "id": "remotive:" + js_value_to_text(job.get("id")),
            "title": job.get("title") or "",
            "company": job.get("company_name") or "",
            "location": job.get("candidate_required_location") or "Remote",
            "placeLabel": REMOTE,
            "url": job.get("url") or "",
            "techs": join_tags(job),
            "description": strip_html(job.get("description")),
            "salaryInfo": job.get("salary") or "",
            "forras": "remotive",
        })
    return jobs


def remoteok_salary(job):
    """Example: {"salary_min": 50000, "salary_max": 70000} -> "50000-70000" """
    if not job.get("salary_min"):
        return ""
    salary_max = "undefined"  # what the JavaScript version printed for a missing value
    if "salary_max" in job:
        salary_max = js_value_to_text(job["salary_max"])
    return js_value_to_text(job["salary_min"]) + "-" + salary_max


def parse_remoteok(body):
    """RemoteOK: a list whose first element is a legal notice, then the jobs."""
    if not isinstance(body, list):
        return []
    jobs = []
    for job in body[1:]:  # [1:] skips the legal notice
        url = job.get("url") or job.get("apply_url") or ""
        jobs.append({
            "id": "remoteok:" + js_value_to_text(job.get("id")),
            "title": fix_mojibake(job.get("position") or ""),
            "company": fix_mojibake(job.get("company") or ""),
            "location": fix_mojibake(job.get("location") or "Remote"),
            "placeLabel": REMOTE,
            "url": url,
            "techs": join_tags(job),
            "description": fix_mojibake(strip_html(job.get("description"))),
            "salaryInfo": remoteok_salary(job),
            "forras": "remoteok",
        })
    return jobs


def parse_arbeitnow(body):
    """Arbeitnow: {"data": [{"slug", "title", "remote", ...}, ...]}; only remote jobs."""
    jobs = []
    for job in body.get("data") or []:
        if not job.get("remote"):
            continue
        jobs.append({
            "id": "arbeitnow:" + js_value_to_text(job.get("slug")),
            "title": job.get("title") or "",
            "company": job.get("company_name") or "",
            "location": job.get("location") or "Remote",
            "placeLabel": REMOTE,
            "url": job.get("url") or "",
            "techs": join_tags(job),
            "description": strip_html(job.get("description")),
            "salaryInfo": "",
            "forras": "arbeitnow",
        })
    return jobs


def read_body(fields):
    """The downloaded JSON as Python data, or None if it is not valid JSON."""
    raw = fields.get("data") or fields.get("body") or "{}"
    if not isinstance(raw, str):
        return raw  # n8n already parsed it
    try:
        return json.loads(raw)
    except ValueError:
        return None  # e.g. an HTML error page instead of JSON


def parse_response(source, body):
    """Send the body to the parser of its API. Unknown or broken bodies give []."""
    if source == "remotive" and isinstance(body, dict):
        return parse_remotive(body)
    if source == "remoteok" and isinstance(body, (dict, list)):
        return parse_remoteok(body)
    if source == "arbeitnow" and isinstance(body, dict):
        return parse_arbeitnow(body)
    return []


def is_new_data_job(job, seen_ids, seen_keys):
    """True if the job was not collected before and its title is data-related."""
    if job["id"] in seen_ids:
        return False
    if dedupe_key(job["company"], job["title"]) in seen_keys:
        return False
    if not DATA_TITLE_PATTERN.search(job["title"]):
        return False
    return True


def main(items):
    # 1. Separate the saved state from the API responses.
    state, responses = split_state(items)
    seen_ids = set(state["seenIds"])
    seen_keys = set(state["seenKeys"])

    # 2. Convert every response to jobs in the common format.
    jobs = []
    for response in responses:
        fields = response["json"]
        body = read_body(fields)
        jobs.extend(parse_response(fields.get("forras"), body))

    # 3. Drop jobs without a link, and repeats within the same API.
    jobs_by_id = {}
    for job in jobs:
        if job["url"] and job["id"] not in jobs_by_id:
            jobs_by_id[job["id"]] = job

    # 4. Keep the new, data-related jobs, at most MAX_NEW of them.
    new_jobs = []
    for job in jobs_by_id.values():
        if is_new_data_job(job, seen_ids, seen_keys):
            new_jobs.append({"json": job})
    return new_jobs[:MAX_NEW]
