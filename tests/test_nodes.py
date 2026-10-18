"""Unit tests on small synthetic inputs.

Reference values marked "JS" were computed with Node.js from the original
JavaScript expressions, so they pin the behaviour the stored state depends on.
"""
import json
from datetime import datetime

import api_parse
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
    page = {"json": {"data": "".join(card(str(i), f"Data role {i}") for i in range(30))}}
    result = filter_new.main([page])
    assert len(result) == filter_new.MAX_NEW == 16
    assert result[0]["json"]["stats"]["fresh"] == 30


def test_filter_new_returns_marker_when_nothing_is_new():
    result = filter_new.main([state(ids=["1"]), {"json": {"data": card("1", "Data Analyst")}}])
    assert result == [{"json": {"__empty": True, "stats": {
        "totalCards": 1, "unique": 1, "fresh": 0, "selected": 0}}}]


def test_extract_text_finds_sections_and_drops_http_fields():
    html = ("<html><script>var x=1;</script><h2>Állás leírása</h2><p>Riportok&nbsp;készítése</p>"
            "<h3>Elvárt technológiák</h3><p>SQL, Python</p></html>")
    item = {"json": {"id": "7", "title": "Data Analyst", "data": html, "error": None}}
    job = extract_text.main([item])[0]["json"]
    assert "data" not in job and "error" not in job
    assert job["description"].startswith("Állás leírása Riportok készítése")
    assert job["techs"] == "Elvárt technológiák SQL, Python"


# --- remote APIs ------------------------------------------------------------

def api_item(source, body):
    return {"json": {"forras": source, "data": json.dumps(body)}}


def test_api_parse_normalises_sources_and_repairs_remoteok_text():
    remoteok = [{"legal": "notice"}, {"id": 5, "position": "Data Scientist", "company": "Co",
                                      "url": "https://r/5", "description": "<p>donâ\x80\x99t</p>",
                                      "salary_min": 50000, "salary_max": 70000, "tags": ["python", None]}]
    arbeitnow = {"data": [{"slug": "a", "title": "BI Analyst", "company_name": "X", "url": "https://a",
                           "remote": True},
                          {"slug": "b", "title": "Data Engineer", "company_name": "Y", "url": "https://b",
                           "remote": False}]}
    result = api_parse.main([api_item("remoteok", remoteok), api_item("arbeitnow", arbeitnow)])
    jobs = {item["json"]["id"]: item["json"] for item in result}
    assert set(jobs) == {"remoteok:5", "arbeitnow:a"}
    assert jobs["remoteok:5"]["description"] == "don’t"
    assert jobs["remoteok:5"]["salaryInfo"] == "50000-70000"
    assert jobs["remoteok:5"]["techs"] == "python, "


def test_api_parse_ignores_broken_bodies():
    assert api_parse.main([{"json": {"forras": "remotive", "data": "<html>error</html>"}}]) == []


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
    assert json.loads(out["latottTartalom"]) == {"seenIds": ["1", "9"], "seenKeys": ["a|x", "b|data analyst"]}


def test_report_without_new_jobs_has_empty_list():
    # The JavaScript version listed the "__empty" marker as one blank job.
    out = report.main([state(), {"json": {"__empty": True}}], now=NOW)[0]["json"]
    assert json.loads(out["jsonTartalom"])["allasok"] == []
    assert "Nem volt uj hirdetes" in out["markdown"]


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
