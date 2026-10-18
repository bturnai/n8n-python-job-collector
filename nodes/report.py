"""Node "Riport osszeallitasa": writes the day's raw job list and updates the state.

n8n only collects; the evening Claude Code review scores every job against the
real CV. So each job leaves here unscored (`score: null`, `pontozatlan: true`),
and every collected job is marked as seen so it is not collected again.

Output fields, each written to a file by the following nodes:
  markdown      -> allasok_<date>.md    (short human-readable note)
  jsonTartalom  -> allasok_<date>.json  (read by the evening review)
  latottTartalom -> latott.json         (the updated de-duplication state)
"""
from common import day_str, dedupe_key, js_str, now_local, split_state, to_json

# We remember at most this many job IDs (and keys). Older ones are dropped,
# so the state file does not grow forever.
STATE_LIMIT = 3000


def add_new_values(old_values, new_values):
    """Return the old values followed by the new ones, without duplicates.

    The order is kept, and only the newest STATE_LIMIT values remain.
    Example: add_new_values(["a", "b"], ["b", "c"])  ->  ["a", "b", "c"]
    """
    result = []
    already_added = set()  # a set answers "is it already in?" quickly
    for value in old_values + new_values:
        if value not in already_added:
            result.append(value)
            already_added.add(value)
    return result[-STATE_LIMIT:]  # the last STATE_LIMIT items are the newest


def to_review_job(job):
    """Convert one collected job to the format the evening review reads.

    The score fields stay empty: n8n only collects, the review scores.
    `job.get("title") or ""` gives "" when the field is missing or None.
    """
    return {
        "id": js_str(job.get("id")),
        "score": None,
        "verdict": "",
        "reason": "Elopontozas nincs - az esti atnezes ertekeli.",
        "gap": "",
        "title": job.get("title") or "",
        "company": job.get("company") or "",
        "location": job.get("location") or "",
        "placeLabel": job.get("placeLabel") or "",
        "url": job.get("url") or "",
        "salaryInfo": job.get("salaryInfo") or "",
        "forras": job.get("forras") or "profession.hu",
        "techs": job.get("techs") or "",
        "description": job.get("description") or "",
    }


def build_markdown(day, job_count):
    """The short note saved next to the JSON list."""
    if job_count > 0:
        return (f"# Allasfigyelo - nyers lista\n\n**Datum:** {day}\n\n"
                f"{job_count} uj hirdetes gyujtve. Az ertekelest az esti atnezes vegzi.\n")
    return f"# Allasfigyelo\n\n**Datum:** {day}\n\nNem volt uj hirdetes.\n"


def main(items, now=None):
    # 1. Separate the saved state from the jobs found in this run.
    state, rest = split_state(items)
    jobs = []
    for item in rest:
        job = item["json"]
        if job.get("__empty"):
            continue  # the "no new job" marker of an earlier node, not a real job
        jobs.append(job)

    # 2. Today's date. Only the tests pass `now`, to get a fixed date.
    if now is None:
        now = now_local()
    day = day_str(now)

    # 3. The job list for the evening review.
    collected = []
    for job in jobs:
        collected.append(to_review_job(job))

    # 4. Remember every collected job, so the next run skips it.
    new_ids = []
    new_keys = []
    for job in jobs:
        if job.get("id"):
            new_ids.append(js_str(job.get("id")))
        key = dedupe_key(job.get("company"), job.get("title"))
        if key != "|":  # "|" means both company and title were empty
            new_keys.append(key)
    new_state = {
        "seenIds": add_new_values(state["seenIds"], new_ids),
        "seenKeys": add_new_values(state["seenKeys"], new_keys),
    }

    # 5. One output item. The next n8n nodes write each text field to a file.
    job_list = {
        "datum": day,
        "atnezett": len(collected),
        "hiba": False,
        "pontozatlan": True,
        "allasok": collected,
    }
    output = {
        "markdown": build_markdown(day, len(collected)),
        "datum": day,
        "filename": f"allasok_{day}.md",
        # hits, reviewed, talalatok: left over from the old version that scored jobs
        # inside n8n. Nothing reads them; they keep the output identical to the
        # JavaScript original until the switch-over is done.
        "hits": 0,
        "reviewed": 0,
        "talalatok": [],
        "hiba": False,
        "pontozatlan": True,
        "jsonFilename": f"allasok_{day}.json",
        "jsonTartalom": to_json(job_list),
        "latottTartalom": to_json(new_state),
    }
    return [{"json": output}]
