"""Node "Uj allasok szurese": parses profession.hu result pages into job cards.

Input: the de-duplication state, plus one item per downloaded result page. Each
page item carries the HTML (`data`) merged with the search item that requested
it (`placeLabel`), so a job keeps the location filter it was found under.

Keeps the jobs that are not seen before (by ID or by company|title) and whose
title looks data-related. At most MAX_NEW go on to the detail-page download.
"""
import re

from common import decode_entities, dedupe_key, split_state

# A title counts as data-related if it contains any of these words.
# \b is a word boundary: "\bml\b" matches "ML engineer" but not "HTML".
# re.ASCII: JavaScript's \b only knows English letters, so in "éML" it still
# finds "ML". Without re.ASCII, Python would treat "é" as a letter and miss it.
DATA_TITLE_PATTERN = re.compile(
    r"(data|adat|analy|analit|scien|machine learning|\bml\b|\bbi\b"
    r"|business intelligence|python|\bsql\b|report|riport)",
    re.IGNORECASE | re.ASCII,
)

# At most this many new jobs per run. Each one means a detail-page download,
# 1.2 seconds apart, so the site is not flooded with requests.
MAX_NEW = 16

# Every job on a result page is one <li class="advertisement-result-list-item" ...>
# element; the part in brackets captures its attributes (data-prof-id="..." etc.).
JOB_CARD_PATTERN = re.compile(r'<li class="advertisement-result-list-item"([^>]*)>')


def read_attribute(attributes, name):
    """The value of one HTML attribute, or "" if it is missing.

    Example: read_attribute('data-prof-id="123" data-link="/x"', "data-prof-id") -> "123"
    """
    match = re.search(name + r'="([^"]*)"', attributes)
    if match:
        return match.group(1)
    return ""


def first_attribute(attributes, name, fallback_name):
    """Like read_attribute, but tries a second attribute name if the first is empty."""
    value = read_attribute(attributes, name)
    if value == "":
        value = read_attribute(attributes, fallback_name)
    return value


def get_page_html(fields):
    """The downloaded page is in `data`; some HTTP node versions use `body`."""
    if fields.get("data"):
        return fields["data"]
    if fields.get("body"):
        return fields["body"]
    return ""


def parse_job_card(attributes, place_label):
    """Build one job from a card's attributes. Returns None if it has no link."""
    title = decode_entities(first_attribute(attributes, "data-item-name", "data-prof-name"))
    # Some titles end with a stray "}" from the page's markup.
    if title.endswith("}"):
        title = title[:-1]

    link = decode_entities(read_attribute(attributes, "data-link"))
    if link == "":
        return None

    location = decode_entities(read_attribute(attributes, "data-location-id"))
    return {
        "id": first_attribute(attributes, "data-prof-id", "data-item-id"),
        "title": title,
        "company": decode_entities(read_attribute(attributes, "data-affiliation")),
        "location": location.replace("_", " "),  # "Budapest_V." -> "Budapest V."
        "category": decode_entities(read_attribute(attributes, "data-category1")),
        "salaryInfo": decode_entities(read_attribute(attributes, "data-item-variant")),
        "placeLabel": place_label,
        "url": link,
    }


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
    # 1. Separate the saved state from the downloaded pages.
    state, pages = split_state(items)
    seen_ids = set(state["seenIds"])
    seen_keys = set(state["seenKeys"])

    # 2. Collect every job card from every page. A job can show up on several
    #    pages (it matches several keywords); only its first appearance is kept.
    jobs_by_id = {}
    total_cards = 0
    for page in pages:
        html = get_page_html(page["json"])
        place_label = page["json"].get("placeLabel") or ""

        for card_match in JOB_CARD_PATTERN.finditer(html):
            total_cards += 1
            attributes = card_match.group(1)

            job_id = first_attribute(attributes, "data-prof-id", "data-item-id")
            if job_id == "" or job_id in jobs_by_id:
                continue

            job = parse_job_card(attributes, place_label)
            if job is not None:
                jobs_by_id[job_id] = job

    # 3. Keep the new, data-related jobs, at most MAX_NEW of them.
    all_jobs = list(jobs_by_id.values())
    new_jobs = []
    for job in all_jobs:
        if is_new_data_job(job, seen_ids, seen_keys):
            new_jobs.append(job)
    selected = new_jobs[:MAX_NEW]

    stats = {
        "totalCards": total_cards,  # cards on all pages, repeats included
        "unique": len(all_jobs),
        "fresh": len(new_jobs),
        "selected": len(selected),
    }

    # 4. No new job: send a marker item, because an n8n node with no output
    #    stops the rest of the workflow. The dedupe node drops the marker.
    if len(selected) == 0:
        return [{"json": {"__empty": True, "stats": stats}}]

    output = []
    for job in selected:
        item = dict(job)  # a copy, so the original job dict is not modified
        item["forras"] = "profession.hu"
        item["stats"] = stats
        output.append({"json": item})
    return output
