"""Parity with the JavaScript nodes on recorded production data.

The fixtures come from `scripts/extract_fixtures.py` and hold real scraped
listings and e-mails, so they are not in the repository; the tests skip
without them. Each test feeds a Python node the same input the JavaScript node
received (rebuilt into the new workflow's merged-item shape) and expects the
same output.
"""
import json
import pathlib
from datetime import datetime

import pytest

import api_parse
import dedupe
import extract_text
import filter_new
import linkedin_mail
import report
import request_click
import search_urls
from common import TZ

REAL = pathlib.Path(__file__).parent / "fixtures" / "real"
STATE_FILE = REAL / "allasfigyelo_staticdata_2026-10-17.json"
# 372: test copy started from the current state. 366: the 2026-10-16 production
# run; the current state is its result, so its input is that minus its additions.
COLLECTOR_RUNS = ["allastesztdock1_372", "allasfigyelo0001_366"]


def load(name):
    path = REAL / f"{name}.json"
    if not path.exists():
        pytest.skip(f"real fixture {path.name} not present")
    return json.loads(path.read_text())


def current_state():
    if not STATE_FILE.exists():
        pytest.skip("state fixture not present")
    return json.loads(STATE_FILE.read_text())["global"]


def pre_run_state(name, run):
    state = current_state()
    if name == "allastesztdock1_372":
        return state
    added = run["nodes"]["Duplikatumok kiszurese"]["output"]
    n_ids = sum(1 for item in added if item["json"].get("id"))
    return {"seenIds": state["seenIds"][:-n_ids], "seenKeys": state["seenKeys"][:-len(added)]}


def state_item(state):
    return {"json": {"data": state}}


def outputs(run, node):
    return run["all_outputs"][node]


def merge_by_position(left, right):
    return [{"json": {**a["json"], **b["json"]}} for a, b in zip(left, right)]


def as_json(items):
    return [item["json"] for item in items]


@pytest.fixture(params=COLLECTOR_RUNS)
def collector(request):
    run = load(request.param)
    return request.param, run, pre_run_state(request.param, run)


def test_search_urls(collector):
    _, run, _ = collector
    assert as_json(search_urls.main([])) == as_json(outputs(run, "Keresesi URL-ek"))


def test_filter_new(collector):
    _, run, state = collector
    pages = merge_by_position(outputs(run, "Keresesi URL-ek"),
                              outputs(run, "Talalati oldalak letoltese"))
    result = filter_new.main([state_item(state)] + pages)
    assert as_json(result) == as_json(outputs(run, "Uj allasok szurese"))


def test_extract_text(collector):
    _, run, _ = collector
    jobs = merge_by_position(outputs(run, "Uj allasok szurese"),
                             outputs(run, "Reszletes oldal letoltese"))
    assert as_json(extract_text.main(jobs)) == as_json(outputs(run, "Hirdetes-szoveg kinyerese"))


def test_api_parse(collector):
    _, run, state = collector
    responses = merge_by_position(outputs(run, "Remote API URL-ek"),
                                  outputs(run, "Remote API-k letoltese"))
    expected = as_json(outputs(run, "API talalatok feldolgozasa"))
    # Intentional difference: RemoteOK's double-encoded UTF-8 is repaired.
    for job in expected:
        if job["forras"] == "remoteok":
            for field in ("title", "company", "location", "description"):
                job[field] = api_parse.fix_mojibake(job[field])
    assert as_json(api_parse.main([state_item(state)] + responses)) == expected


def test_dedupe(collector):
    _, run, _ = collector
    result = dedupe.main(outputs(run, "Forrasok egyesitese"))
    # Intentional difference (2026-11-10): the page statistics are passed on in
    # an extra marker when no kept job carries them. Drop it before comparing.
    result = [i for i in result if not (i["json"].get("__empty") and len(result) > 1)]
    assert as_json(result) == as_json(outputs(run, "Duplikatumok kiszurese"))


def test_report(collector):
    name, run, state = collector
    expected = outputs(run, "Riport osszeallitasa")[0]["json"]
    run_day = datetime.strptime(expected["datum"], "%Y-%m-%d").replace(hour=21, tzinfo=TZ)
    items = [state_item(state)] + outputs(run, "Duplikatumok kiszurese")
    result = report.main(items, now=run_day)[0]["json"]

    new_state = json.loads(result.pop("latottTartalom"))
    # Intentional difference (2026-11-10): the list also reports the page
    # statistics and alerts. Remove them before comparing with the original.
    # (The recorded input comes from the old dedupe, which dropped the statistics.)
    listing = json.loads(result["jsonTartalom"])
    listing.pop("riasztasok")
    listing.pop("forrasok")
    result["jsonTartalom"] = report.to_json(listing)
    result["markdown"] = result["markdown"].split("\n**Riasztas:**")[0]
    assert result == expected
    if name == "allasfigyelo0001_366":
        # The production state after this run is exactly what n8n stored.
        assert new_state == current_state()


def test_recorded_run_reaches_report_without_alert(collector):
    # The new dedupe passes the page statistics on, so a normal recorded day
    # (result pages full of jobs) must not raise an alert.
    _, run, state = collector
    deduped = dedupe.main(outputs(run, "Forrasok egyesitese"))
    out = report.main([state_item(state)] + deduped)[0]["json"]
    listing = json.loads(out["jsonTartalom"])
    assert listing["riasztasok"] == []
    assert listing["forrasok"]["profession.hu"]["talalatiKartyak"] > 0


def test_linkedin_mail():
    run = load("linkedinmail0001_374")
    node = run["nodes"]["Level kimentese"]
    day = node["output"][0]["json"]["filename"].split("_")[1]
    now = datetime.strptime(day, "%Y-%m-%d").replace(hour=12, tzinfo=TZ)
    assert as_json(linkedin_mail.main(node["input"], now=now)) == as_json(node["output"])


def test_request_click():
    run = load("kerelem0000001_380")
    node = run["nodes"]["Kerelem rogzitese"]
    expected = node["output"][0]["json"]
    kert = json.loads(expected["tartalom"])["kert"]
    now = datetime.fromisoformat(kert.replace("Z", "+00:00")).astimezone(TZ)
    assert as_json(request_click.main(node["input"], now=now)) == [expected]
