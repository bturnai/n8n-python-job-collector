"""Tests of the NoFluffJobs and Indeed alert e-mails (alert_mail.py, mail_parse.py).

The small inputs are cut from real alerts (2026-11-12 - 11-14). The tests at the
end read the real .eml files from tests/fixtures/levelek/ (not in git: the mails
hold personal tracking links); they are skipped when the files are missing.
"""
import base64
import email
import json
import pathlib
from datetime import datetime
from email import policy

import pytest

import alert_mail
import mail_parse
from common import TZ

NOW = datetime(2026, 11, 14, 9, 30, tzinfo=TZ)
LETTERS = pathlib.Path(__file__).parent / "fixtures" / "levelek"

INDEED_TEXT = """Indeed-állásértesítő
21 új állás: Data engineer

1-21 állás; 21 állás közül
A feltételeknek megfelelő találatok megtekintése az Indeed oldalán: https://hu.indeed.com/jobs?q=Data+engineer


Data Engineer
Sanofi - Budapest
Contribute to the Data Engineering community and stay up to date with emerging technologies.
Most adták fel
https://hu.indeed.com/rc/clk/dl?jk=03692789080e0ec7&from=ja&qd=abc&tk=xyz

Databricks Data Engineer
Nilfisk Production Kft. - Budapest 1117
Egyszerű jelentkezés
You report to the Head of Data Engineering.
1 napja
https://hu.indeed.com/rc/clk/dl?jk=2f46ec44e078489a&from=ja&qd=abc&tk=xyz

Python Platform Engineer (AI InfoSec)
Revolut - távmunka
5+ years of experience as a software engineer.
Most adták fel
https://hu.indeed.com/rc/clk/dl?jk=815f6cacb9df37e3&from=ja

Senior Data Architect
Esko - Jičín
As a Senior Data Architect, you will define the data foundation of Esko.
1 napja
https://cz.indeed.com/rc/clk/dl?jk=8f5211a8154d86f7&from=ja

Ne oszd meg másokkal ezt az e-mailt
Adatvédelmi szabályzat: https://hu.indeed.com/legal?hl=hu#privacy
"""


def click_link(address):
    """A NoFluffJobs click-counter link around `address`, as in the real mails."""
    code = base64.urlsafe_b64encode(address.encode()).decode().rstrip("=")
    return f"https://mail-link.nofluffjobs.com/click/6af7dda04338d9ce050827ae/{code}/6af371167e7452cf"


def nfj_row(title, salary, company, place, address):
    return (f'<tr class="postings-table__item" style="x"> <td class="postings-table__item-logo">'
            f'<img src="logo.jpg"> </td> <td class="postings-table__item-content">'
            f'<div class="posting-content"> <a href="{click_link(address)}" style="y">'
            f'<h1 class="posting-content__title" style="z"> {title} </h1>'
            f'<div class="salary-tech-container"><span class="salary-label" style="s"> {salary} </span></div>'
            f'<div><span style="c">{company}</span></div>'
            f'<div><span style="c">{place}</span></div> </a> </div> </td> </tr>')


NFJ_HTML = ('<p>Beállított kritériumok: remote hybrid budapest junior</p><table class="postings-table">'
            + nfj_row("Buying Specialist", "900 000 - 1 000 000 HUF", "Tessero", "in Budapest",
                      "https://nofluffjobs.com/hu/job/buying-specialist-tessero-budapest?criteria=&utm_source=email")
            + nfj_row("Junior Financial Analyst -Dutch speaking", "Check Salary Match", "Tech People Hungary",
                      "in Budapest",
                      "https://nofluffjobs.com/hu/job/junior-financial-analyst-dutch-speaking-tech-people-hungary-budapest-1?criteria=")
            + '</table><a href="' + click_link("https://nofluffjobs.com/subscribe?utm_source=email")
            + '">Összes állásajánlat megtekintése</a>')


def state(ids=(), keys=()):
    return {"json": {"data": {"seenIds": list(ids), "seenKeys": list(keys)}}}


def saved(source, text="", page=""):
    """One saved alert file as the "Extract from File" node passes it on."""
    return {"json": {"data": {"forras": source, "szoveg": text, "html": page}}}


# --- Indeed -----------------------------------------------------------------

def test_indeed_jobs_from_the_text_part():
    jobs = mail_parse.parse_indeed(INDEED_TEXT)
    assert [job["id"] for job in jobs] == [
        "indeed:03692789080e0ec7", "indeed:2f46ec44e078489a",
        "indeed:815f6cacb9df37e3", "indeed:8f5211a8154d86f7"]
    nilfisk = jobs[1]
    assert nilfisk["title"] == "Databricks Data Engineer"
    assert nilfisk["company"] == "Nilfisk Production Kft."
    assert nilfisk["location"] == "Budapest 1117"
    # "Egyszerű jelentkezés" and "1 napja" are labels, not part of the snippet.
    assert nilfisk["description"] == "You report to the Head of Data Engineering."
    assert nilfisk["url"] == "https://hu.indeed.com/viewjob?jk=2f46ec44e078489a"
    assert nilfisk["forras"] == "indeed"
    assert nilfisk["placeLabel"] == "Barmilyen (helyszini is)"


def test_indeed_remote_job_and_other_country_host():
    jobs = mail_parse.parse_indeed(INDEED_TEXT)
    assert jobs[2]["placeLabel"] == "Tavmunka/Remote"
    assert jobs[3]["url"] == "https://cz.indeed.com/viewjob?jk=8f5211a8154d86f7"


def test_indeed_windows_line_endings():
    jobs = mail_parse.parse_indeed(INDEED_TEXT.replace("\n", "\r\n"))
    assert len(jobs) == 4


def test_split_company_location_uses_the_last_dash():
    assert mail_parse.split_company_location("Nilfisk Production Kft. - Budapest 1117") == (
        "Nilfisk Production Kft.", "Budapest 1117")
    assert mail_parse.split_company_location("A - B Kft. - Budapest") == ("A - B Kft.", "Budapest")
    assert mail_parse.split_company_location("Acme") == ("Acme", "")


# --- NoFluffJobs ------------------------------------------------------------

def test_decode_base64url_matches_the_base64_module():
    for text in ["https://nofluffjobs.com/hu", "a", "ab", "abc", "árvíztűrő ?criteria=&x=1"]:
        code = base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
        assert mail_parse.decode_base64url(code) == text
    assert mail_parse.decode_base64url("aHR0cHM6Ly9ub2ZsdWZmam9icy5jb20vaHU") == "https://nofluffjobs.com/hu"
    assert mail_parse.decode_base64url("not base64!") == ""


def test_nofluffjobs_address_drops_the_tracking_part():
    link = click_link("https://nofluffjobs.com/hu/job/buying-specialist-tessero-budapest?criteria=&utm_source=email")
    assert mail_parse.nofluffjobs_address(link) == "https://nofluffjobs.com/hu/job/buying-specialist-tessero-budapest"
    # Links that are not job links: subscribe page, phone number.
    assert mail_parse.nofluffjobs_address(click_link("https://nofluffjobs.com/subscribe")) == ""
    assert mail_parse.nofluffjobs_address("tel:+36%2030%20155%200341") == ""


def test_nofluffjobs_jobs_from_the_html():
    jobs = mail_parse.parse_nofluffjobs(NFJ_HTML)
    assert len(jobs) == 2
    first = jobs[0]
    assert first == {
        "id": "nofluffjobs:buying-specialist-tessero-budapest",
        "title": "Buying Specialist",
        "company": "Tessero",
        "location": "Budapest",
        "placeLabel": "Barmilyen (helyszini is)",
        "url": "https://nofluffjobs.com/hu/job/buying-specialist-tessero-budapest",
        "techs": "",
        "description": "",
        "salaryInfo": "900 000 - 1 000 000 HUF",
        "forras": "nofluffjobs",
    }
    # "Check Salary Match" is a button text, not a salary.
    assert jobs[1]["salaryInfo"] == ""
    assert jobs[1]["company"] == "Tech People Hungary"


def test_clean_text_decodes_entities():
    assert mail_parse.clean_text(" <b>R&amp;D</b>  Analyst ") == "R&D Analyst"


# --- The collector node -------------------------------------------------------

def test_main_keeps_new_data_jobs_only():
    output = mail_parse.main([
        state(ids=["indeed:03692789080e0ec7"], keys=["esko|senior data architect"]),
        saved("indeed", text=INDEED_TEXT),
        saved("nofluffjobs", page=NFJ_HTML),
    ])
    ids = [item["json"]["id"] for item in output]
    # Sanofi: seen by id. Esko: seen by company|title. Buying Specialist: not a data title.
    assert ids == ["indeed:2f46ec44e078489a", "indeed:815f6cacb9df37e3",
                   "nofluffjobs:junior-financial-analyst-dutch-speaking-tech-people-hungary-budapest-1"]


def test_main_keeps_a_job_once_when_two_mails_repeat_it():
    output = mail_parse.main([state(), saved("indeed", text=INDEED_TEXT), saved("indeed", text=INDEED_TEXT)])
    assert len(output) == 4


def test_main_sends_a_marker_when_the_folder_is_empty():
    # The file nodes pass on an empty item (no file) or an error item.
    output = mail_parse.main([state(), {"json": {}}, {"json": {"error": "No binary data"}}])
    assert output == [{"json": {"__empty": True}}]


def test_main_skips_unknown_senders():
    assert mail_parse.main([state(), saved("egyeb", text=INDEED_TEXT)]) == [{"json": {"__empty": True}}]


# --- Saving the mail ------------------------------------------------------------

def imap_item(sender, subject="2 új állásajánlat", text="", page=""):
    return {"json": {"subject": subject, "date": "2026-11-14T04:03:44.000Z", "text": text,
                     "textHtml": page, "from": {"value": [{"address": sender}]}}}


def test_alert_mail_names_the_file_after_the_site():
    output = alert_mail.main([imap_item("notifications@nofluffjobs.com", page=NFJ_HTML),
                              imap_item("donotreply@jobalert.indeed.com", text=INDEED_TEXT)], now=NOW)
    names = [item["json"]["filename"] for item in output]
    assert names[0].startswith("nofluffjobs_2026-11-14_") and names[0].endswith(".json")
    assert names[1].startswith("indeed_2026-11-14_")
    record = json.loads(output[1]["json"]["tartalom"])
    assert record["forras"] == "indeed"
    assert record["felado"] == "donotreply@jobalert.indeed.com"
    assert record["szoveg"] == INDEED_TEXT


def test_alert_mail_same_mail_same_file():
    first = alert_mail.main([imap_item("notifications@nofluffjobs.com", page=NFJ_HTML)], now=NOW)
    again = alert_mail.main([imap_item("notifications@nofluffjobs.com", page=NFJ_HTML)], now=NOW)
    assert first == again


def test_saved_mail_goes_through_the_parser():
    """alert_mail output -> file -> mail_parse: the same jobs as parsing directly."""
    output = alert_mail.main([imap_item("donotreply@jobalert.indeed.com", text=INDEED_TEXT)], now=NOW)
    record = json.loads(output[0]["json"]["tartalom"])
    jobs = mail_parse.main([state(), {"json": {"data": record}}])
    assert len(jobs) == 4


# --- Real mails (skipped without the local .eml files) ---------------------------

def real_mails():
    """The .eml files as the n8n IMAP node passes them on (subject, from, text, textHtml)."""
    items = []
    for path in sorted(LETTERS.glob("*.eml")):
        message = email.message_from_binary_file(path.open("rb"), policy=policy.default)
        plain = message.get_body(("plain",))
        page = message.get_body(("html",))
        items.append({"json": {
            "subject": message["Subject"], "date": message["Date"],
            "from": {"value": [{"address": message["From"].addresses[0].addr_spec}]},
            "text": plain.get_content() if plain else "",
            "textHtml": page.get_content() if page else "",
        }})
    return items


@pytest.mark.skipif(not list(LETTERS.glob("*.eml")), reason="no real alert mails in tests/fixtures/levelek")
def test_real_mails():
    saved_files = alert_mail.main(real_mails(), now=NOW)
    records = [json.loads(item["json"]["tartalom"]) for item in saved_files]

    # Each mail's subject says how many jobs it lists ("21 új állás", "2 új állásajánlat").
    counts = {}
    for record in records:
        jobs = mail_parse.parse_mail(record)
        counts[record["targy"].strip()[:30]] = len(jobs)
        for job in jobs:
            assert job["id"] and job["title"] and job["company"] and job["url"].startswith("https://")
            assert "tk=" not in job["url"] and "mail-link" not in job["url"]
    assert sorted(counts.values()) == [1, 2, 21, 23]

    # One row checked field by field against the mail.
    sanofi = None
    for record in records:
        for job in mail_parse.parse_mail(record):
            if job["id"] == "indeed:03692789080e0ec7":
                sanofi = job
    assert sanofi["title"] == "Data Engineer"
    assert sanofi["company"] == "Sanofi"
    assert sanofi["location"] == "Budapest"
    assert sanofi["url"] == "https://hu.indeed.com/viewjob?jk=03692789080e0ec7"


# --- From mail to database row ----------------------------------------------------

def mail_to_rows(records):
    """The evening path: mail_parse -> dedupe -> report -> load_postgres.to_rows."""
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
    import dedupe
    import load_postgres
    import report

    files = []
    for record in records:
        files.append({"json": {"data": record}})
    jobs = mail_parse.main([state()] + files)
    kept = dedupe.main(jobs)
    output = report.main([state()] + kept, now=NOW)[0]["json"]
    daily = json.loads(output["jsonTartalom"])
    return load_postgres.to_rows(daily, output["jsonFilename"])


def test_alert_job_becomes_a_database_row():
    rows = mail_to_rows([{"forras": "indeed", "szoveg": INDEED_TEXT, "html": ""}])
    nilfisk = None
    for row in rows:
        if row["id"] == "indeed:2f46ec44e078489a":
            nilfisk = row
    assert nilfisk["source"] == "indeed"
    assert nilfisk["title"] == "Databricks Data Engineer"
    assert nilfisk["company"] == "Nilfisk Production Kft."
    assert nilfisk["location"] == "Budapest 1117"
    assert nilfisk["place_label"] == "Barmilyen (helyszini is)"
    assert nilfisk["url"] == "https://hu.indeed.com/viewjob?jk=2f46ec44e078489a"
    assert nilfisk["salary_info"] is None
    assert nilfisk["collected_on"] == "2026-11-14"
    assert nilfisk["source_file"] == "allasok_2026-11-14.json"


@pytest.mark.skipif(not list(LETTERS.glob("*.eml")), reason="no real alert mails in tests/fixtures/levelek")
def test_real_mails_become_database_rows():
    saved_files = alert_mail.main(real_mails(), now=NOW)
    records = []
    for item in saved_files:
        records.append(json.loads(item["json"]["tartalom"]))
    rows = mail_to_rows(records)
    sources = set()
    for row in rows:
        sources.add(row["source"])
    # 14 data jobs in the four mails: 13 from Indeed, 1 from NoFluffJobs.
    assert len(rows) == 14
    assert sources == {"indeed", "nofluffjobs"}
