"""Node "Duplikatumok kiszurese": removes duplicates within one run.

The same job can appear twice in a run: from two sources, or re-posted on the
same site under a new ID. The stored `seenKeys` only cover earlier runs; this
node covers the current one.

Two jobs count as the same when their company and title match (see
`dedupe_key` in common.py). The first one is kept.
"""
from common import dedupe_key


def main(items):
    keys_already_kept = set()
    kept_jobs = []

    for item in items:
        job = item["json"]

        # Skip the "no new job" marker: it is not a real job.
        if job.get("__empty"):
            continue

        key = dedupe_key(job.get("company"), job.get("title"))

        # "|" means both company and title were empty: nothing to compare by.
        if key == "|":
            continue
        if key in keys_already_kept:
            continue

        keys_already_kept.add(key)
        kept_jobs.append({"json": job})

    # An n8n node with no output stops the rest of the workflow, so instead of an
    # empty list we send a marker item that the next node recognises.
    if len(kept_jobs) == 0:
        return [{"json": {"__empty": True}}]
    return kept_jobs
