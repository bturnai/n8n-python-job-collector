"""Node "API talalatok feldolgozasa": normalises the remote-job API responses.

Input: the de-duplication state, plus one item per API response - the source
item (`forras`, `url`) merged with the downloaded body (`data`). Output: new,
data-related jobs in the same shape as the profession.hu jobs, at most MAX_NEW.
"""
import json
import re

from common import collapse_ws, dedupe_key, js_slice, js_str, js_trim, split_state

TITLE_RE = re.compile(
    r"(data|analy|analit|scien|machine learning|\bml\b|\bbi\b"
    r"|business intelligence|python|\bsql\b|report)",
    re.IGNORECASE | re.ASCII,
)
MAX_NEW = 16
DESCRIPTION_LIMIT = 2200
REMOTE = "Tavmunka/Remote"
# UTF-8 bytes that were decoded as Latin-1 somewhere upstream ("donâ\x80\x99t").
MOJIBAKE_RE = re.compile("[Â-ô][\u0080-¿]{1,3}")


def fix_mojibake(text):
    def repair(match):
        try:
            return match.group().encode("latin-1").decode("utf-8")
        except UnicodeError:
            return match.group()
    return MOJIBAKE_RE.sub(repair, text)


def strip_html(html):
    text = re.sub(r"<[^>]+>", " ", js_str(html))
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
            .replace("&#039;", "'").replace("&#39;", "'")
            .replace("&lt;", "<").replace("&gt;", ">"))
    return js_slice(js_trim(collapse_ws(text)), 0, DESCRIPTION_LIMIT)


def _template(value):
    """How a JavaScript template literal (or String()) prints a JSON value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _tags(job):
    # Array.prototype.join prints null as an empty string.
    return ", ".join("" if tag is None else _template(tag) for tag in job.get("tags") or [])


def _remotive(body):
    for job in body.get("jobs") or []:
        yield {
            "id": f"remotive:{_template(job.get('id'))}",
            "title": job.get("title") or "", "company": job.get("company_name") or "",
            "location": job.get("candidate_required_location") or "Remote",
            "placeLabel": REMOTE, "url": job.get("url") or "", "techs": _tags(job),
            "description": strip_html(job.get("description")),
            "salaryInfo": job.get("salary") or "", "forras": "remotive",
        }


def _remoteok(body):
    # The first element is the API's legal notice, not a job.
    for job in (body[1:] if isinstance(body, list) else []):
        salary = ""
        if job.get("salary_min"):
            salary_max = _template(job["salary_max"]) if "salary_max" in job else "undefined"
            salary = f"{_template(job['salary_min'])}-{salary_max}"
        yield {
            "id": f"remoteok:{_template(job.get('id'))}",
            "title": fix_mojibake(job.get("position") or ""),
            "company": fix_mojibake(job.get("company") or ""),
            "location": fix_mojibake(job.get("location") or "Remote"),
            "placeLabel": REMOTE, "url": job.get("url") or job.get("apply_url") or "",
            "techs": _tags(job),
            "description": fix_mojibake(strip_html(job.get("description"))),
            "salaryInfo": salary, "forras": "remoteok",
        }


def _arbeitnow(body):
    for job in body.get("data") or []:
        if not job.get("remote"):
            continue
        yield {
            "id": f"arbeitnow:{_template(job.get('slug'))}",
            "title": job.get("title") or "", "company": job.get("company_name") or "",
            "location": job.get("location") or "Remote", "placeLabel": REMOTE,
            "url": job.get("url") or "", "techs": _tags(job),
            "description": strip_html(job.get("description")),
            "salaryInfo": "", "forras": "arbeitnow",
        }


PARSERS = {"remotive": _remotive, "remoteok": _remoteok, "arbeitnow": _arbeitnow}


def main(items):
    state, responses = split_state(items)
    seen_ids = set(state["seenIds"])
    seen_keys = set(state["seenKeys"])

    jobs = []
    for response in responses:
        data = response["json"]
        raw = data.get("data") or data.get("body") or "{}"
        try:
            body = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            continue
        parser = PARSERS.get(data.get("forras") or "?")
        if parser and isinstance(body, (dict, list)):
            if isinstance(body, dict) or parser is _remoteok:
                jobs.extend(parser(body))

    unique = {}
    for job in jobs:
        if job["url"] and job["id"] not in unique:
            unique[job["id"]] = job

    fresh = [
        job for job in unique.values()
        if job["id"] not in seen_ids
        and dedupe_key(job["company"], job["title"]) not in seen_keys
        and TITLE_RE.search(job["title"])
    ]
    return [{"json": job} for job in fresh[:MAX_NEW]]
