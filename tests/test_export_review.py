import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import export_review  # noqa: E402

ROW = ("3051161", "Business Analyst", "Hiflylabs Zrt.", "Pest megye", "hybrid",
       "profession.hu", "https://www.profession.hu/allas/x", None, "Állás leírása ...", None)


def test_review_item_keeps_the_old_field_names():
    item = export_review.review_item(ROW)
    assert item == {"id": "3051161", "title": "Business Analyst", "company": "Hiflylabs Zrt.",
                    "location": "Pest megye", "placeLabel": "Hibrid/Home office",
                    "url": "https://www.profession.hu/allas/x", "salaryInfo": "",
                    "forras": "profession.hu", "techs": "", "description": "Állás leírása ..."}


def test_unknown_work_mode_gives_empty_label():
    row = ROW[:4] + ("unknown",) + ROW[5:]
    assert export_review.review_item(row)["placeLabel"] == ""


def test_review_file_has_no_v5_scores_and_keeps_the_alerts():
    content = export_review.review_file("2026-11-16", [ROW], ["profession.hu: 0 hirdetes"])
    assert content["datum"] == "2026-11-16"
    assert content["forras"] == "adatbazis"
    assert content["riasztasok"] == ["profession.hu: 0 hirdetes"]
    assert len(content["allasok"]) == 1
    assert "v5" not in json.dumps(content)        # the review must score on its own first


def test_collector_alerts_without_file(tmp_path):
    assert export_review.collector_alerts(tmp_path, "2026-11-16") == []


def test_collector_alerts_from_the_collector_file(tmp_path):
    (tmp_path / "allasok_2026-11-16.json").write_text(
        json.dumps({"riasztasok": ["x"], "allasok": []}), encoding="utf-8")
    assert export_review.collector_alerts(tmp_path, "2026-11-16") == ["x"]
