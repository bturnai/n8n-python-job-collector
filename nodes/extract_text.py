"""Node "Hirdetes-szoveg kinyerese": plain text from a profession.hu job page.

Input: one item per selected job - the job card fields merged with the
downloaded detail page (`data`). Output: the job card plus
- `description`: the posting text and its tags, up to where the posting ends;
- `requirements`, `tasks`, `nice_to_have`, `offer`: the posting's sections, as lists;
- `tags`: profession.hu's own requirement tags (language, experience, education);
- `techs`: profession.hu's technology tags, e.g. "PYTHON, SQL, GIT".
"""
import html
import re

HTTP_FIELDS = ["data", "body", "error"]
DESCRIPTION_LIMIT = 10000

DESCRIPTION_HEADINGS = ["Allas leirasa", "Állás leírása"]

# The sections of the posting. The visible heading is free text that the company
# writes ("Requirements", "Elvárások", "What You Will Bring:", ... 16 kinds in 124
# postings), but the HTML under it carries a fixed marker, the same on every page:
#     <div id="requirements" itemprop="requirements"> ... </div>
# So the sections are found by this marker, not by the heading.
SECTIONS = {
    "requirements": "requirements",   # output field: itemprop on the page
    "tasks": "tasks",
    "nice_to_have": "other",
    "offer": "offer",
}

# A section ends where the next one starts, or where the tag lists below the
# posting start (whichever comes first).
SECTION_END_MARKERS = ['<div id="box_', '<li class="sr-only">', "</section>", "<script"]

# Tags that end a line when the HTML is turned into lines: list items, line breaks,
# paragraphs, headings and blocks.
LINE_BREAK_TAG = re.compile(r"</?(li|br|p|h[1-6]|div|tr)\b[^>]*>", re.IGNORECASE)
ANY_TAG = re.compile(r"<[^>]+>")
# Bullet characters some companies type at the start of a line: "• SQL", "- SQL".
BULLET_AT_START = re.compile(r"^[•·▪◦‣●○■□➢►\-*–]+\s*")

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
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&quot;", '"')
    text = text.replace("&#039;", "'")
    text = text.replace("&#39;", "'")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")

    # Collapse every run of whitespace into a single space, then trim the ends.
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def find_first_heading(text, headings):
    """Position of the first heading found in the text, or -1 if none is there."""
    for heading in headings:
        position = text.find(heading)
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
        position = text.find(marker)
        if position >= 0 and (earliest < 0 or position < earliest):
            earliest = position
    return earliest


def html_to_lines(part):
    """Turn a piece of HTML into a list of clean lines, one per list item or line.

    Works for all three ways companies write a section:
    "<ul><li>SQL</li><li>Python</li></ul>"  -> ["SQL", "Python"]
    "• SQL<br/>• Python"                   -> ["SQL", "Python"]
    "<p>We need SQL.</p>"                   -> ["We need SQL."]
    """
    text = LINE_BREAK_TAG.sub("\n", part)
    text = ANY_TAG.sub(" ", text)
    text = html.unescape(text)          # "&amp;" -> "&", "&#039;" -> "'"
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        line = BULLET_AT_START.sub("", line)
        if line != "":
            lines.append(line)
    return lines


def read_section(page, itemprop):
    """The lines of one section, found by its itemprop marker; [] if there is none.

    Example: read_section(page, "requirements") -> ["Magabiztos Python-tudás", "Erős SQL", ...]
    """
    match = re.search(r'itemprop="' + itemprop + r'"[^>]*>', page)
    if match is None:
        return []
    rest = page[match.end():]
    end = len(rest)
    for marker in SECTION_END_MARKERS:
        position = rest.find(marker)
        if position >= 0 and position < end:
            end = position
    return html_to_lines(rest[:end])


def read_tech_tags(page):
    """profession.hu's technology tags as one text; "" if the page has none.

    On the page: <div class="my-auto techStacks"><span class="bullet-wrapper">PYTHON</span>...</div>
    Example: -> "PYTHON, SQL, GIT"
    """
    match = re.search(r'class="my-auto techStacks">(.*?)</div>', page, re.DOTALL)
    if match is None:
        return ""
    tags = []
    for tag in re.findall(r'class="bullet-wrapper">(.*?)</span>', match.group(1), re.DOTALL):
        tag = html.unescape(tag).strip()
        if tag != "":
            tags.append(tag)
    return ", ".join(tags)


def read_requirement_tags(page):
    """profession.hu's requirement tags: language, experience, education.

    On the page: <li class="sr-only"><h3> Elvárások </h3><ul><li> Angol középfok </li>...
    Example: -> ["Angol középfok", "3-5 év tapasztalat", "Főiskola"]
    """
    match = re.search(r"<h3>\s*Elvárások\s*</h3>\s*<ul>(.*?)</ul>", page, re.DOTALL)
    if match is None:
        return []
    return html_to_lines(match.group(1))


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


        job = {}
        for key, value in fields.items():
            if key not in HTTP_FIELDS:
                job[key] = value

        # 2. The page as plain text.
        page = get_page_html(fields)
        text = strip_html(page)

        # 3. The description: from its heading if found, otherwise the whole text,
        #    up to where the posting ends on the page (then the safety limit).
        description = text
        start = find_first_heading(text, DESCRIPTION_HEADINGS)
        if start >= 0:
            description = text[start:]
        end = find_end(description, DESCRIPTION_END_MARKERS)
        if end > 0:
            description = description[:end].strip()
        description = description[:DESCRIPTION_LIMIT]
        if description == "":
            description = "(nem sikerult kinyerni)"  # "could not extract"

        # 4. The sections and the tags, read from the HTML, not from the text.
        job["techs"] = read_tech_tags(page)
        job["description"] = description
        for field, itemprop in SECTIONS.items():
            job[field] = read_section(page, itemprop)
        job["tags"] = read_requirement_tags(page)
        jobs.append({"json": job})
    return jobs
