"""Node "Duplikatumok kiszurese": removes duplicates within one run.

The same job can appear twice in a run: from two sources, or re-posted on the
same site under a new ID. The stored `seenKeys` only cover earlier runs; this
node covers the current one.
"""
from common import dedupe_key


def main(items):
    seen = set()
    out = []
    for item in items:
        job = item["json"]
        if job.get("__empty"):
            continue
        key = dedupe_key(job.get("company"), job.get("title"))
        if key == "|" or key in seen:
            continue
        seen.add(key)
        out.append({"json": job})
    return out or [{"json": {"__empty": True}}]
