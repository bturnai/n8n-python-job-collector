"""Node "Hirdetes-szoveg kinyerese": plain text from a profession.hu job page.

Input: one item per selected job - the job card fields merged with the
downloaded detail page (`data`). Output: the job card plus `techs` (the
"required technologies" block) and `description` (the posting text and its tags,
up to where the posting ends on the page).
"""
import re

from common import collapse_ws, js_index_of, js_slice, js_trim

# Fields that come from the HTTP download, not from the job card. They are not
# passed on: the page HTML is large and only the extracted text is needed.
HTTP_FIELDS = ["data", "body", "error"]

# Length limits. The description is NOT cut at a fixed length any more (it was 2200
# until 2026-11-13, and a quarter of the postings lost part of their requirements):
# it ends where the posting ends on the page. 10000 is only a safety limit for a
# page whose end marker is missing.
DESCRIPTION_LIMIT = 10000
TECHS_LIMIT = 300

# Section headings on the job page. Some pages write them without accents.
TECHS_HEADINGS = ["Elvart technologiak", "Elvárt technológiák"]
DESCRIPTION_HEADINGS = ["Allas leirasa", "Állás leírása"]

# Where the posting ends on the page. Before these come the posting and its tags
# ("Teljes munkaidő", "Angol középfok", "Nem kell tapasztalat"); after them the
# company profile, its ratings, similar jobs and the site footer.
DESCRIPTION_END_MARKERS = ["Egyéb adatok és információk", "Egyeb adatok es informaciok",
                           "Hasonló állások", "Hasonlo allasok"]


def strip_html(html):
    """Turn an HTML page into one line of plain text.

    Example: "<p>SQL&amp;Python</p>\\n<p>Remote</p>" -> "SQL&Python Remote"
    """
    text = html

    # Drop <script> and <style> blocks with their content: they are code, not text.
    # [\s\S]*? means "any characters, as few as possible", so the match stops at
    # the first closing tag.
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)

    # Replace every remaining tag (<p>, </div>, <a href="...">) with a space.
    text = re.sub(r"<[^>]+>", " ", text)

    # Turn the common HTML entities back into characters.
    # The order matches the original version, so the output stays identical.
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&quot;", '"')
    text = text.replace("&#039;", "'")
    text = text.replace("&#39;", "'")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")

    # Collapse every run of whitespace into a single space, then trim the ends.
    return js_trim(collapse_ws(text))


def find_first_heading(text, headings):
    """Position of the first heading found in the text, or -1 if none is there."""
    for heading in headings:
        position = js_index_of(text, heading)
        if position >= 0:
            return position
    return -1


def find_end(text, markers):
    """Position of the earliest end marker in the text, or -1 if none is there.

    Example: find_end("posting ... Hasonló állások ... Egyéb adatok és információk", ...)
    returns the position of "Hasonló állások", because it comes first.
    """
    earliest = -1
    for marker in markers:
        position = js_index_of(text, marker)
        if position >= 0 and (earliest < 0 or position < earliest):
            earliest = position
    return earliest


def get_page_html(fields):
    """The downloaded page is in `data`; some HTTP node versions use `body`."""
    if fields.get("data"):
        return fields["data"]
    if fields.get("body"):
        return fields["body"]
    return ""


def main(items):
    jobs = []
    for item in items:
        fields = item["json"]

        # 1. Start from the job card: every field except the HTTP ones.
        job = {}
        for key, value in fields.items():
            if key not in HTTP_FIELDS:
                job[key] = value

        # 2. The page as plain text.
        text = strip_html(get_page_html(fields))

        # 3. The "required technologies" block, if the page has one.
        techs = ""
        start = find_first_heading(text, TECHS_HEADINGS)
        if start >= 0:
            techs = js_slice(text, start, start + TECHS_LIMIT)

        # 4. The description: from its heading if found, otherwise the whole text,
        #    up to where the posting ends on the page (then the safety limit).
        description = text
        start = find_first_heading(text, DESCRIPTION_HEADINGS)
        if start >= 0:
            description = js_slice(text, start)
        end = find_end(description, DESCRIPTION_END_MARKERS)
        if end > 0:
            description = js_trim(js_slice(description, 0, end))
        description = js_slice(description, 0, DESCRIPTION_LIMIT)
        if description == "":
            description = "(nem sikerult kinyerni)"  # "could not extract"

        job["techs"] = techs
        job["description"] = description
        jobs.append({"json": job})
    return jobs
