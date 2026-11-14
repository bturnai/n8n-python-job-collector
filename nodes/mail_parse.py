"""Node "Ertesito levelek feldolgozasa": jobs from the saved NoFluffJobs and Indeed alert e-mails.

Input: the de-duplication state, plus one item per saved alert file
(alert_mail.py wrote it, the "Extract from File" node put it under "data").
Output: new, data-related jobs in the same shape as the profession.hu jobs,
at most MAX_NEW; or one "no new job" marker.

The files stay in the folder and are read again every evening. That is fine:
a job collected once is in the seen-list, so it is skipped the next time.

The two sites write their alerts differently:
- Indeed sends a plain-text part; each job is one block of lines (parse_indeed).
- NoFluffJobs sends only HTML; each job is one table row (parse_nofluffjobs).
Neither mail holds the full posting text, only a short snippet (Indeed) or
nothing (NoFluffJobs).
"""
import html
import re

from common import collapse_ws, dedupe_key, js_trim, split_state

# Same words as in filter_new.py. Both alerts send many non-data jobs
# (an Indeed "Data engineer" alert also lists DevOps and welding engineers).
DATA_TITLE_PATTERN = re.compile(
    r"(data|adat|analy|analit|scien|machine learning|\bml\b|\bbi\b"
    r"|business intelligence|python|\bsql\b|report|riport)",
    re.IGNORECASE | re.ASCII,
)
MAX_NEW = 50  # safety limit, see MAX_NEW in filter_new.py

# The place labels the dbt staging model knows (stg_job_postings.sql).
# The alerts do not say hybrid or on-site, so a job is "remote" only when its
# location says so; otherwise "any" (on-site allowed), the cautious choice.
REMOTE = "Tavmunka/Remote"
ANY_PLACE = "Barmilyen (helyszini is)"


def place_label(location):
    """Example: place_label("távmunka") -> "Tavmunka/Remote",  place_label("Budapest") -> "Barmilyen (helyszini is)" """
    lower = location.lower()
    if "távmunka" in lower or "remote" in lower:
        return REMOTE
    return ANY_PLACE


# ---------------------------------------------------------------------------
# Indeed
# ---------------------------------------------------------------------------
# A real job block from the text part of an Indeed alert (2026-11-14):
#
#   Databricks Data Engineer
#   Nilfisk Production Kft. - Budapest 1117
#   Egyszerű jelentkezés
#   You report to the Head of Data Engineering and work closely with Finance, ...
#   1 napja
#   https://hu.indeed.com/rc/clk/dl?jk=2f46ec44e078489a&from=ja&qd=...&tk=...
#
# Line 1 title, line 2 "company - location", the last line the link, the line
# before it the age. "Egyszerű jelentkezés" (easy apply) is optional.

# The host (hu.indeed.com, sometimes cz.indeed.com) and the job key "jk".
INDEED_LINK = re.compile(r"^https://([a-z]+\.indeed\.com)/\S*[?&]jk=([0-9a-f]+)")
INDEED_AGE = re.compile(r"^(Most adták fel|\d+ napja)$")
EASY_APPLY = "Egyszerű jelentkezés"


def split_company_location(line):
    """Example: split_company_location("Nilfisk Production Kft. - Budapest 1117")
    -> ("Nilfisk Production Kft.", "Budapest 1117")

    The last " - " separates them, because a company name may hold one too.
    """
    position = line.rfind(" - ")
    if position < 0:
        return line, ""
    return line[:position], line[position + 3:]


def parse_indeed(text):
    """Jobs from the plain-text part of an Indeed alert."""
    jobs = []
    text = text.replace("\r\n", "\n")
    for block in text.split("\n\n"):
        # The non-empty lines of the block, without spaces at the ends.
        lines = []
        for line in block.split("\n"):
            line = js_trim(line)
            if line != "":
                lines.append(line)

        # A job block has at least: title, company - location, link.
        if len(lines) < 3:
            continue
        link = INDEED_LINK.match(lines[-1])
        if link is None:
            continue  # e.g. the header or the footer of the mail
        host = link.group(1)
        job_key = link.group(2)

        company, location = split_company_location(lines[1])

        # The lines between "company - location" and the link: the snippet,
        # and maybe the "easy apply" label and the age.
        snippet_lines = []
        for line in lines[2:-1]:
            if line == EASY_APPLY or INDEED_AGE.match(line):
                continue
            snippet_lines.append(line)

        jobs.append({
            "id": "indeed:" + job_key,
            "title": lines[0],
            "company": company,
            "location": location,
            "placeLabel": place_label(location),
            # The link in the mail carries personal tracking codes; this one does not.
            "url": f"https://{host}/viewjob?jk={job_key}",
            "techs": "",
            "description": " ".join(snippet_lines),
            "salaryInfo": "",
            "forras": "indeed",
        })
    return jobs


# ---------------------------------------------------------------------------
# NoFluffJobs
# ---------------------------------------------------------------------------
# A real job row from a NoFluffJobs alert (2026-11-13), shortened:
#
#   <tr class="postings-table__item" ...>
#     <td ...><img src="...logo..."></td>
#     <td ...><div class="posting-content">
#       <a href="https://mail-link.nofluffjobs.com/click/6af6.../aHR0cHM6Ly9ub2Zs.../6af3...">
#         <h1 class="posting-content__title">Buying Specialist</h1>
#         <div class="salary-tech-container"><span class="salary-label">900 000 - 1 000 000 HUF</span></div>
#         <div><span>Tessero</span></div>
#         <div><span>in Budapest</span></div>
#       </a>
#     </div></td>
#   </tr>
#
# The link goes through NoFluffJobs' click counter. Its fifth part ("aHR0...")
# is the real address, base64-encoded (see decode_base64url).

ROW_START = '<tr class="postings-table__item"'
LINK_AND_CONTENT = re.compile(r'<a href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
TITLE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL)
SALARY = re.compile(r'class="salary-label"[^>]*>(.*?)</span>', re.DOTALL)
TAG = re.compile(r"<[^>]+>")

# The 64 letters of "base64url", in order: letter number 0 is "A", 63 is "_".
BASE64URL_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def decode_base64url(code):
    """Example: decode_base64url("aHR0cHM6Ly9ub2ZsdWZmam9icy5jb20vaHU") -> "https://nofluffjobs.com/hu"

    The sandbox does not allow the base64 module, so it is done by hand:
    every letter stands for a number 0-63, that is 6 bits. Written one after
    the other, every 8 bits make one byte of the text. Leftover bits at the
    end (fewer than 8) are padding. Returns "" if a letter is not base64url.
    """
    bits = ""
    for letter in code.rstrip("="):
        number = BASE64URL_LETTERS.find(letter)
        if number < 0:
            return ""
        bits += f"{number:06b}"  # 06b: binary, 6 digits, 0-padded

    data = bytearray()
    for start in range(0, len(bits) - 7, 8):
        data.append(int(bits[start:start + 8], 2))  # 8 binary digits -> 0..255
    return data.decode("utf-8", "replace")


def nofluffjobs_address(click_link):
    """The posting's own address, without the tracking part.

    Example: "https://mail-link.nofluffjobs.com/click/6af6/aHR0cHM6Ly9ub2ZsdWZmam9icy5jb20vaHUvam9iL2J1eWluZy1zcGVjaWFsaXN0LXRlc3Nlcm8tYnVkYXBlc3Q_Y3JpdGVyaWE9/6af3"
    -> "https://nofluffjobs.com/hu/job/buying-specialist-tessero-budapest"
    Returns "" if the link is not a job link.
    """
    parts = click_link.split("/")
    # ["https:", "", "mail-link.nofluffjobs.com", "click", "6af6", "aHR0...", "6af3"]
    if len(parts) < 6 or parts[3] != "click":
        return ""
    address = decode_base64url(parts[5])
    address = address.split("?")[0]  # drop "?criteria=&utm_source=email..."
    if not address.startswith("https://nofluffjobs.com/") or "/job/" not in address:
        return ""
    return address


def clean_text(fragment):
    """HTML fragment -> plain text: tags out, entities decoded, spaces tidied.

    Example: clean_text(" <b>R&amp;D</b>  Analyst ") -> "R&D Analyst"
    """
    text = TAG.sub(" ", fragment)
    text = html.unescape(text)
    return js_trim(collapse_ws(text))


def text_pieces(fragment):
    """The separate texts of an HTML fragment, in order.

    Example: text_pieces("<h1>Buying Specialist</h1><span>Tessero</span><span>in Budapest</span>")
    -> ["Buying Specialist", "Tessero", "in Budapest"]
    """
    pieces = []
    for piece in TAG.split(fragment):
        piece = clean_text(piece)
        if piece != "":
            pieces.append(piece)
    return pieces


def parse_nofluffjobs(page):
    """Jobs from the HTML of a NoFluffJobs alert."""
    jobs = []
    rows = page.split(ROW_START)
    for row in rows[1:]:  # rows[0] is the part of the mail before the first job
        link = LINK_AND_CONTENT.search(row)
        if link is None:
            continue
        url = nofluffjobs_address(link.group(1))
        if url == "":
            continue
        content = link.group(2)

        title_match = TITLE.search(content)
        if title_match is None:
            continue
        title = clean_text(title_match.group(1))

        # Only a real amount counts as salary; "Fizetés az első interjún"
        # (salary at the first interview) or "Check Salary Match" do not.
        salary = ""
        salary_match = SALARY.search(content)
        if salary_match is not None:
            salary_text = clean_text(salary_match.group(1))
            if re.search(r"\d", salary_text):
                salary = salary_text

        # The last two texts of the link are the company and "in <place>".
        pieces = text_pieces(content)
        if len(pieces) < 3:
            continue
        company = pieces[-2]
        location = pieces[-1]
        if location.startswith("in "):
            location = location[3:]

        jobs.append({
            "id": "nofluffjobs:" + url.split("/job/")[1],
            "title": title,
            "company": company,
            "location": location,
            "placeLabel": place_label(location),
            "url": url,
            "techs": "",
            "description": "",
            "salaryInfo": salary,
            "forras": "nofluffjobs",
        })
    return jobs


# ---------------------------------------------------------------------------
# The node
# ---------------------------------------------------------------------------

def parse_mail(mail):
    """Send a saved mail to the parser of its site. Unknown mails give []."""
    if mail.get("forras") == "indeed":
        return parse_indeed(mail.get("szoveg") or "")
    if mail.get("forras") == "nofluffjobs":
        return parse_nofluffjobs(mail.get("html") or "")
    return []


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
    # 1. Separate the saved state from the mail files.
    state, mail_items = split_state(items)
    seen_ids = set(state["seenIds"])
    seen_keys = set(state["seenKeys"])

    # 2. Every mail -> jobs. An item without a saved mail under "data" is skipped:
    #    when the folder is empty, the file nodes pass on an empty or error item.
    jobs = []
    for item in mail_items:
        mail = item["json"].get("data")
        if not isinstance(mail, dict):
            continue
        jobs.extend(parse_mail(mail))

    # 3. The same job comes in several mails (Indeed repeats them for days): keep one.
    jobs_by_id = {}
    for job in jobs:
        if job["id"] not in jobs_by_id:
            jobs_by_id[job["id"]] = job

    # 4. Keep the new, data-related jobs, at most MAX_NEW of them.
    new_jobs = []
    for job in jobs_by_id.values():
        if is_new_data_job(job, seen_ids, seen_keys):
            new_jobs.append({"json": job})

    # An n8n node with no output stops its branch, so send a marker instead.
    if len(new_jobs) == 0:
        return [{"json": {"__empty": True}}]
    return new_jobs[:MAX_NEW]
