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

STATE_LIMIT = 3000


def _ordered_union(existing, additions):
    merged = dict.fromkeys(existing)  # keeps insertion order, like a JS Set
    for value in additions:
        merged.setdefault(value, None)
    return list(merged)[-STATE_LIMIT:]


def main(items, now=None):
    state, rest = split_state(items)
    jobs = [item["json"] for item in rest if not item["json"].get("__empty")]
    day = day_str(now or now_local())

    collected = [{
        "id": js_str(job.get("id")), "score": None, "verdict": "",
        "reason": "Elopontozas nincs - az esti atnezes ertekeli.",
        "gap": "", "title": job.get("title") or "", "company": job.get("company") or "",
        "location": job.get("location") or "", "placeLabel": job.get("placeLabel") or "",
        "url": job.get("url") or "", "salaryInfo": job.get("salaryInfo") or "",
        "forras": job.get("forras") or "profession.hu", "techs": job.get("techs") or "",
        "description": job.get("description") or "",
    } for job in jobs]

    new_ids = [js_str(job.get("id")) for job in jobs if job.get("id")]
    new_keys = [key for key in (dedupe_key(job.get("company"), job.get("title")) for job in jobs)
                if key != "|"]
    new_state = {
        "seenIds": _ordered_union(state["seenIds"], new_ids),
        "seenKeys": _ordered_union(state["seenKeys"], new_keys),
    }

    if collected:
        markdown = (f"# Allasfigyelo - nyers lista\n\n**Datum:** {day}\n\n"
                    f"{len(collected)} uj hirdetes gyujtve. Az ertekelest az esti atnezes vegzi.\n")
    else:
        markdown = f"# Allasfigyelo\n\n**Datum:** {day}\n\nNem volt uj hirdetes.\n"

    return [{"json": {
        "markdown": markdown, "datum": day, "filename": f"allasok_{day}.md",
        "hits": 0, "reviewed": 0, "talalatok": [], "hiba": False, "pontozatlan": True,
        "jsonFilename": f"allasok_{day}.json",
        "jsonTartalom": to_json({"datum": day, "atnezett": len(collected), "hiba": False,
                                 "pontozatlan": True, "allasok": collected}),
        "latottTartalom": to_json(new_state),
    }}]
