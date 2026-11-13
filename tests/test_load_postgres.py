"""The JSON-to-row mapping of the PostgreSQL loader (no database needed)."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import load_postgres


def daily(*jobs):
    return {"datum": "2026-11-01", "allasok": list(jobs)}


def job(**fields):
    base = {"id": "remoteok:1", "forras": "remoteok", "title": "Data Engineer", "company": "Acme",
            "location": "Budapest", "placeLabel": "Hibrid", "url": "https://example.com/1",
            "salaryInfo": "", "techs": "python, sql", "description": "Build pipelines.",
            "score": None, "verdict": ""}
    return {**base, **fields}


def test_maps_fields_to_columns():
    [row] = load_postgres.to_rows(daily(job()), "allasok_2026-11-01.json")
    assert row["id"] == "remoteok:1"
    assert row["source"] == "remoteok"
    assert row["place_label"] == "Hibrid"
    assert row["collected_on"] == "2026-11-01"
    assert row["source_file"] == "allasok_2026-11-01.json"


def test_empty_strings_become_null():
    [row] = load_postgres.to_rows(daily(job(salaryInfo="", company="")), "f.json")
    assert row["salary_info"] is None
    assert row["company"] is None


def test_payload_keeps_the_original_record():
    original = job(score=7, verdict="Jó egyezés")
    [row] = load_postgres.to_rows(daily(original), "f.json")
    assert json.loads(row["payload"]) == original


def test_half_emoji_is_replaced():
    # The collector cuts descriptions at 2200 UTF-16 units, which can split an emoji.
    [row] = load_postgres.to_rows(daily(job(description="videó \ud83d")), "f.json")
    assert row["description"] == "videó �"
    assert "\\ud83d" not in row["payload"]
    row["payload"].encode("utf-8")


def test_directory_expands_to_daily_files_in_date_order(tmp_path):
    for name in ("allasok_2026-11-01.json", "allasok_2026-10-31.json", "allasok_2026-10-31.md"):
        (tmp_path / name).write_text("{}")
    assert [p.name for p in load_postgres.expand([str(tmp_path)])] == [
        "allasok_2026-10-31.json", "allasok_2026-11-01.json"]


def test_one_row_per_posting():
    rows = load_postgres.to_rows(daily(job(id="a:1"), job(id="a:2")), "f.json")
    assert [r["id"] for r in rows] == ["a:1", "a:2"]


# --- refetching the texts cut at 2200 characters ---------------------------------

def test_refetch_replaces_only_a_longer_version_of_the_same_text():
    import refetch_texts
    assert refetch_texts.is_longer_version("Feladatok: SQL, Pyt", "Feladatok: SQL, Python, Excel")
    assert not refetch_texts.is_longer_version("Feladatok: SQL", "Egészen más hirdetés, hosszabban")
    assert not refetch_texts.is_longer_version("Feladatok: SQL, Python", "Feladatok: SQL")
