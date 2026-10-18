"""Node "Hirdetes-szoveg kinyerese": plain text from a profession.hu job page.

Input: one item per selected job - the job card fields merged with the
downloaded detail page (`data`). Output: the job card plus `techs` (the
"required technologies" block) and `description` (the posting text, capped).
"""
import re

from common import collapse_ws, js_index_of, js_slice, js_trim

# Fields that come from the HTTP download, not from the job card. They are not
# passed on: the page HTML is large and only the extracted text is needed.
HTTP_FIELDS = ["data", "body", "error"]

# Length limits, so that the evening review does not get needlessly long text.
DESCRIPTION_LIMIT = 2200
TECHS_LIMIT = 300

# Section headings on the job page. Some pages write them without accents.
TECHS_HEADINGS = ["Elvart technologiak", "Elvárt technológiák"]
DESCRIPTION_HEADINGS = ["Allas leirasa", "Állás leírása"]


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

        # 4. The description: from its heading if found, otherwise the whole text.
        description = text
        start = find_first_heading(text, DESCRIPTION_HEADINGS)
        if start >= 0:
            description = js_slice(text, start)
        description = js_slice(description, 0, DESCRIPTION_LIMIT)
        if description == "":
            description = "(nem sikerult kinyerni)"  # "could not extract"

        job["techs"] = techs
        job["description"] = description
        jobs.append({"json": job})
    return jobs
