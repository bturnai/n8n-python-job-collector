"""Node "Uj allasok szurese": parses profession.hu result pages into job cards.

Input: the de-duplication state, plus one item per downloaded result page. Each
page item carries the HTML (`data`) merged with the search item that requested
it (`placeLabel`), so a job keeps the location filter it was found under.

Keeps the jobs that are not seen before (by ID or by company|title) and whose
title looks data-related. At most MAX_NEW go on to the detail-page download.
"""
import re

from common import decode_entities, dedupe_key, split_state

TITLE_RE = re.compile(
    r"(data|adat|analy|analit|scien|machine learning|\bml\b|\bbi\b"
    r"|business intelligence|python|\bsql\b|report|riport)",
    re.IGNORECASE | re.ASCII,  # JavaScript's \b and /i are ASCII-only
)
MAX_NEW = 16
CARD_RE = re.compile(r'<li class="advertisement-result-list-item"([^>]*)>')


def _attr(attrs, name):
    match = re.search(name + r'="([^"]*)"', attrs)
    return match.group(1) if match else ""


def main(items):
    state, pages = split_state(items)
    seen_ids = set(state["seenIds"])
    seen_keys = set(state["seenKeys"])

    found = {}
    total_cards = 0
    for page in pages:
        page_json = page["json"]
        html = page_json.get("data") or page_json.get("body") or ""
        place_label = page_json.get("placeLabel") or ""
        for card in CARD_RE.finditer(html):
            total_cards += 1
            attrs = card.group(1)
            job_id = _attr(attrs, "data-prof-id") or _attr(attrs, "data-item-id")
            if not job_id or job_id in found:
                continue
            title = decode_entities(
                _attr(attrs, "data-item-name") or _attr(attrs, "data-prof-name"))
            title = re.sub(r"\}\Z", "", title)
            link = decode_entities(_attr(attrs, "data-link"))
            if not link:
                continue
            found[job_id] = {
                "id": job_id,
                "title": title,
                "company": decode_entities(_attr(attrs, "data-affiliation")),
                "location": decode_entities(_attr(attrs, "data-location-id")).replace("_", " "),
                "category": decode_entities(_attr(attrs, "data-category1")),
                "salaryInfo": decode_entities(_attr(attrs, "data-item-variant")),
                "placeLabel": place_label,
                "url": link,
            }

    jobs = list(found.values())
    fresh = [
        job for job in jobs
        if job["id"] not in seen_ids
        and dedupe_key(job["company"], job["title"]) not in seen_keys
        and TITLE_RE.search(job["title"])
    ]
    selected = fresh[:MAX_NEW]
    stats = {"totalCards": total_cards, "unique": len(jobs),
             "fresh": len(fresh), "selected": len(selected)}

    if not selected:
        # Downstream nodes skip this marker; an empty output would stop the branch.
        return [{"json": {"__empty": True, "stats": stats}}]
    return [{"json": {**job, "forras": "profession.hu", "stats": stats}} for job in selected]
