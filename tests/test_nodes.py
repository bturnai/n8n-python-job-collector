"""Unit tests on small synthetic inputs.

Reference values marked "JS" were computed with Node.js from the original
JavaScript expressions, so they pin the behaviour the stored state depends on.
"""
import json
from datetime import datetime

import dedupe
import email_attachments
import extract_text
import filter_new
import report
import request_click
from common import TZ, collapse_ws, dedupe_key, iso_utc, js_hash, js_index_of, js_slice, js_trim, to_json

NOW = datetime(2026, 10, 17, 21, 30, 5, 123456, tzinfo=TZ)


def card(job_id, title, company="Acme Kft.", link=None):
    link = link or f"https://www.profession.hu/allas/{job_id}"
    return (f'<li class="advertisement-result-list-item" data-prof-id="{job_id}" '
            f'data-item-name="{title}" data-affiliation="{company}" data-link="{link}" '
            f'data-location-id="Budapest_V._kerulet">')


def state(ids=(), keys=()):
    return {"json": {"data": {"seenIds": list(ids), "seenKeys": list(keys)}}}


# --- JavaScript string semantics ------------------------------------------

def test_hash_matches_javascript():
    assert js_hash("Data Analyst|2026-10-17|Szia 😀 árvíztűrő") == "b9c32e60"  # JS
    assert js_hash("") == "00001505"  # JS
    assert js_hash("x" * 5000) == "85308505"  # JS


def test_slice_and_index_count_utf16_units():
    text = "Állás 😀 ok"
    assert js_slice(text, 0, 8) == "Állás 😀"  # JS
    assert to_json(js_slice(text, 0, 7)) == '"Állás \\ud83d"'  # JS: half an emoji
    assert js_index_of("😀😀 Állás leírása itt", "Állás leírása") == 5  # JS


def test_whitespace_follows_javascript():
    # JS: NBSP and BOM are whitespace, U+0085 is not.
    assert js_trim(collapse_ws("  a ﻿ b\u0085c  ")) == "a b\u0085c"
    assert dedupe_key("  ACME\tKft. ", "Data   Analyst") == "acme kft. |data analyst"


def test_iso_utc_has_milliseconds():
    assert iso_utc(NOW) == "2026-10-17T19:30:05.123Z"


# --- profession.hu cards --------------------------------------------------

def test_filter_new_skips_seen_jobs_by_id_and_by_key():
    page = {"json": {"placeLabel": "Tavmunka/Remote", "data": "".join([
        card("1", "Data Analyst"),
        card("2", "Junior Data Engineer", company="Seen Kft."),
        card("3", "Python fejleszto"),
        card("4", "Raktaros"),  # not data-related
    ])}}
    result = filter_new.main([state(ids=["1"], keys=["seen kft.|junior data engineer"]), page])
    assert [item["json"]["id"] for item in result] == ["3"]
    job = result[0]["json"]
    assert job["placeLabel"] == "Tavmunka/Remote"
    assert job["location"] == "Budapest V. kerulet"
    assert job["stats"] == {"totalCards": 4, "unique": 4, "fresh": 1, "selected": 1}


def test_filter_new_word_boundary_is_ascii_like_javascript():
    # JS: /\bml\b/i matches in "éML" because é is not an ASCII word character.
    page = {"json": {"data": card("1", "éML mérnök") + card("2", "HTML coder")}}
    assert [i["json"]["id"] for i in filter_new.main([page])] == ["1"]


def test_filter_new_caps_the_selection():
    count = filter_new.MAX_NEW + 10
    page = {"json": {"data": "".join(card(str(i), f"Data role {i}") for i in range(count))}}
    result = filter_new.main([page])
    assert len(result) == filter_new.MAX_NEW
    assert result[0]["json"]["stats"]["fresh"] == count


def test_filter_new_returns_marker_when_nothing_is_new():
    result = filter_new.main([state(ids=["1"]), {"json": {"data": card("1", "Data Analyst")}}])
    assert result == [{"json": {"__empty": True, "stats": {
        "totalCards": 1, "unique": 1, "fresh": 0, "selected": 0}}}]


def test_extract_text_finds_the_description_and_drops_http_fields():
    html = ("<html><script>var x=1;</script><h2>Állás leírása</h2><p>Riportok&nbsp;készítése</p>"
            "</html>")
    item = {"json": {"id": "7", "title": "Data Analyst", "data": html, "error": None}}
    job = extract_text.main([item])[0]["json"]
    assert "data" not in job and "error" not in job
    assert job["description"].startswith("Állás leírása Riportok készítése")


# The structure of a real profession.hu page (3029414 and 3030341, shortened): the
# visible headings are free text, the itemprop markers under them are fixed.
PAGE = (
    '<section><h2>Állás leírása</h2>'
    '<div id="box_fobb-feladatok-munkak" class="box-container"><h2><span class="title">'
    'What You would do at KPMG:</span></h2><div id="tasks" itemprop="tasks">'
    '<ul><li>source-to-target mapping</li><li>data cleansing &amp; reconciliation</li></ul>'
    '</div></div>'
    '<div id="box_az-allashoz-tartozo-elvarasok" class="box"><h3> Requirements </h3>'
    '<div id="requirements" itemprop="requirements">'
    '• Secondary school certificate<br/>• Minimum of 2 years’ experience </div></div>'
    '<div id="box_amit-kinalunk" class="box"><h3>Amit kínálunk</h3>'
    '<div id="offer" itemprop="offer"><div><p>Hibrid munkavégzés</p></div></div></div>'
    '<li class="sr-only"><h3> Elvárt technológiák </h3><ul><li> SQL PYTHON </li></ul></li>'
    '<li class="sr-only"><h3> Elvárások </h3><ul><li> Angol középfok </li>'
    '<li> 3-5 év tapasztalat </li><li> Főiskola </li></ul></li></section>'
    '<div class="my-auto techStacks"> <span class="bullet-wrapper">SQL</span>'
    ' <span class="bullet-wrapper">PYTHON</span> </div>'
    '<h2>Egyéb adatok és információk</h2>'
)


def test_extract_text_reads_the_sections_by_their_marker_not_their_heading():
    job = extract_text.main([{"json": {"id": "1", "data": PAGE}}])[0]["json"]
    assert job["tasks"] == ["source-to-target mapping", "data cleansing & reconciliation"]
    # line breaks and typed bullets instead of a list
    assert job["requirements"] == ["Secondary school certificate", "Minimum of 2 years’ experience"]
    # a paragraph inside an extra <div>
    assert job["offer"] == ["Hibrid munkavégzés"]
    # a section the page does not have
    assert job["nice_to_have"] == []


def test_extract_text_reads_the_tags_without_a_length_limit():
    job = extract_text.main([{"json": {"id": "1", "data": PAGE}}])[0]["json"]
    assert job["techs"] == "SQL, PYTHON"
    assert job["tags"] == ["Angol középfok", "3-5 év tapasztalat", "Főiskola"]


def test_extract_text_without_sections_gives_empty_fields():
    job = extract_text.main([{"json": {"__empty": True}}])[0]["json"]
    assert job["techs"] == ""
    for field in ["requirements", "tasks", "nice_to_have", "offer", "tags"]:
        assert job[field] == []



def test_extract_text_keeps_the_whole_posting_and_drops_the_page_footer():
    # Before 2026-11-13 the description was cut at 2200 characters, which lost the
    # requirements of long postings. Now it ends where the posting ends on the page.
    requirements = "Elvárások " + "SQL és Python tapasztalat. " * 120     # about 3200 characters
    html = ("<h2>Állás leírása</h2><p>Feladatok Riportok</p><p>" + requirements + "</p>"
            "<p>Teljes munkaidő Angol középfok Nem kell tapasztalat</p>"
            "<h2>Egyéb adatok és információk</h2><p>Cégprofil, értékelések</p>"
            "<h2>Hasonló állások</h2><p>Másik állás</p>")
    job = extract_text.main([{"json": {"id": "8", "data": html}}])[0]["json"]
    assert len(job["description"]) > 2200
    assert job["description"].endswith("Teljes munkaidő Angol középfok Nem kell tapasztalat")
    assert "Cégprofil" not in job["description"]


def test_extract_text_safety_limit_without_end_marker():
    html = "<h2>Állás leírása</h2><p>" + "x" * 20000 + "</p>"
    job = extract_text.main([{"json": {"id": "9", "data": html}}])[0]["json"]
    assert len(job["description"]) == extract_text.DESCRIPTION_LIMIT

# --- de-duplication and report -------------------------------------------------

def test_dedupe_keeps_first_of_same_company_and_title():
    items = [{"json": {"id": "1", "company": "A", "title": "Data Analyst"}},
             {"json": {"id": "2", "company": "a", "title": "data  analyst"}},
             {"json": {"__empty": True}}]
    assert [i["json"]["id"] for i in dedupe.main(items)] == ["1"]
    assert dedupe.main([{"json": {"__empty": True}}]) == [{"json": {"__empty": True}}]


def test_report_lists_jobs_unscored_and_extends_state():
    jobs = [{"json": {"id": "9", "title": "Data Analyst", "company": "B", "url": "https://x"}}]
    out = report.main([state(ids=["1"], keys=["a|x"])] + jobs, now=NOW)[0]["json"]
    listing = json.loads(out["jsonTartalom"])
    assert out["jsonFilename"] == "allasok_2026-10-17.json"
    assert listing["atnezett"] == 1 and listing["allasok"][0]["score"] is None
    assert listing["allasok"][0]["requirements"] == []      # no sections: empty list
    assert json.loads(out["latottTartalom"]) == {"seenIds": ["1", "9"], "seenKeys": ["a|x", "b|data analyst"]}


def test_report_without_new_jobs_has_empty_list():
    # The JavaScript version listed the "__empty" marker as one blank job.
    out = report.main([state(), {"json": {"__empty": True}}], now=NOW)[0]["json"]
    assert json.loads(out["jsonTartalom"])["allasok"] == []
    assert "Nem volt uj hirdetes" in out["markdown"]


def test_dedupe_passes_on_page_stats_when_only_api_jobs_are_kept():
    stats = {"totalCards": 0, "unique": 0, "fresh": 0, "selected": 0}
    items = [{"json": {"__empty": True, "stats": stats}},
             {"json": {"id": "remoteok:1", "company": "A", "title": "Data Analyst"}}]
    out = dedupe.main(items)
    assert [i["json"].get("id") for i in out] == ["remoteok:1", None]
    assert out[-1]["json"] == {"__empty": True, "stats": stats}
    # No job at all: the marker itself carries the stats.
    assert dedupe.main(items[:1]) == [{"json": {"__empty": True, "stats": stats}}]


def test_report_alerts_when_result_pages_hold_no_jobs():
    blocked = {"json": {"__empty": True, "stats": {"totalCards": 0}}}
    listing = json.loads(report.main([state(), blocked], now=NOW)[0]["json"]["jsonTartalom"])
    assert listing["forrasok"] == {"profession.hu": {"talalatiKartyak": 0}}
    assert len(listing["riasztasok"]) == 1 and "blokkol" in listing["riasztasok"][0]


def test_report_has_no_alert_on_a_quiet_day():
    quiet = {"json": {"__empty": True, "stats": {"totalCards": 1031}}}
    out = report.main([state(), quiet], now=NOW)[0]["json"]
    assert json.loads(out["jsonTartalom"])["riasztasok"] == []
    assert "Riasztas" not in out["markdown"]


def test_report_state_has_no_repeats():
    assert report.add_new_values(["a", "b"], ["b", "c", "c"]) == ["a", "b", "c"]
    # A job collected again (e.g. by two overlapping runs) must not be stored twice.
    jobs = [{"json": {"id": "1", "title": "Data Analyst", "company": "A"}}]
    out = report.main([state(ids=["1"], keys=["a|data analyst"])] + jobs, now=NOW)[0]["json"]
    assert json.loads(out["latottTartalom"]) == {"seenIds": ["1"], "seenKeys": ["a|data analyst"]}


def test_report_state_keeps_the_newest_3000():
    old = [str(i) for i in range(3000)]
    out = report.main([state(ids=old), {"json": {"id": "new", "title": "T", "company": "C"}}], now=NOW)
    ids = json.loads(out[0]["json"]["latottTartalom"])["seenIds"]
    assert len(ids) == 3000 and ids[0] == "1" and ids[-1] == "new"


# --- application requests -------------------------------------------------------

def test_request_click_sanitises_the_id():
    query = {"id": "44/79?<x>", "cim": "Data Analyst", "ceg": "Givaudan", "url": "https://g"}
    out = request_click.main([{"json": {"query": query}}], now=NOW)[0]["json"]
    assert out["filename"] == "kerelem_2026-10-17_213005_4479x.json"
    assert json.loads(out["tartalom"])["kert"] == "2026-10-17T19:30:05.123Z"


# --- e-mail attachments ---------------------------------------------------------

def test_email_attachments_move_to_binary():
    body = {"to": "a@example.com", "subject": "S", "html": "<p>x</p>", "attachments": [
        {"filename": "cv.docx", "mimeType": "application/x-docx", "content": "UEsDBA=="},
        {"filename": "empty.txt", "content": ""},  # skipped, but keeps its index
        "not an attachment",
        {"content": "dGVzenQ="},
    ]}
    out = email_attachments.main([{"json": {"body": body}}])[0]
    assert out["json"] == {"body": {"to": "a@example.com", "subject": "S", "html": "<p>x</p>"},
                           "attachmentKeys": "att0,att3"}
    assert out["binary"]["att0"] == {"data": "UEsDBA==", "mimeType": "application/x-docx",
                                     "fileName": "cv.docx"}
    assert out["binary"]["att3"]["fileName"] == "csatolmany_3"
    assert out["binary"]["att3"]["mimeType"] == "application/octet-stream"
    assert "attachments" in body  # the incoming item is not modified


def test_email_without_attachments():
    out = email_attachments.main([{"json": {"body": {"to": "a@example.com", "html": "x"}}}])[0]
    assert out == {"json": {"body": {"to": "a@example.com", "html": "x"}, "attachmentKeys": ""},
                   "binary": {}}


def test_is_new_data_job():
    jobs = [
        {"id": "2973971", "title": "Data Analyst", "company": "B", "url": "https://x"},
        {"id": "9", "title": "CE Data Analyst", "company": "   Tesco", "url": "https://x"},
        {"id": "9", "title": "Babysitter", "company": "B", "url": "https://x"},
        {"id": "9", "title": "Junior Data Scientist", "company": "HiflyLabs"},
    ]
    seen_ids = ["2973971", "8"]
    seen_keys = {dedupe_key("   Tesco", "CE Data Analyst")}

    assert filter_new.is_new_data_job(jobs[0], seen_ids, seen_keys) is False
    assert filter_new.is_new_data_job(jobs[1], seen_ids, seen_keys) is False
    assert filter_new.is_new_data_job(jobs[2], seen_ids, seen_keys) is False
    assert filter_new.is_new_data_job(jobs[3], seen_ids, seen_keys) is True
