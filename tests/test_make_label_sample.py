"""Sampling and readable columns for the hand-labelled eval set (no database needed)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from make_label_sample import (band, bullets, experience, language, normalize, pick_sample,
                               seniority, split_sections, tools)


def postings(scores):
    return [{"id": str(i), "score": s} for i, s in enumerate(scores)]


def test_normalize_drops_legal_form_and_case():
    assert normalize("MOL Nyrt.") == normalize("mol") == "mol"
    assert normalize("TESCO-GLOBAL ZRT.") == "tesco global"


def test_score_bands():
    assert [band(s) for s in (None, 1, 4, 5, 9)] == \
        ["unscored", "below 5", "below 5", "5+", "5+"]


def test_all_of_a_band_and_quota_of_others():
    pool = postings([7] * 30 + [2] * 50 + [None] * 50)
    sample = pick_sample(pool, set(), {"5+": None, "below 5": 15, "unscored": 10}, seed=1)
    counts = {}
    for p in sample:
        counts[band(p["score"])] = counts.get(band(p["score"]), 0) + 1
    assert counts == {"5+": 30, "below 5": 15, "unscored": 10}


def test_must_ids_come_on_top_of_quotas():
    pool = postings([2] * 50)
    sample = pick_sample(pool, {"3", "40"}, {"below 5": 5}, seed=1)
    assert {"3", "40"} <= {p["id"] for p in sample}
    assert len(sample) == 7


def test_same_seed_same_sample():
    pool = postings(list(range(1, 10)) * 10)
    quotas = {"5+": 10, "below 5": 10}
    first = [p["id"] for p in pick_sample(pool, set(), quotas, seed=42)]
    assert first == [p["id"] for p in pick_sample(pool, set(), quotas, seed=42)]


def test_bullets_split_run_together_hungarian_list():
    text = ("Adat töltések fejlesztése Mesterséges intelligencia modellek fejlesztésében részvétel "
            "Legalább 2 év tapasztalat Python programozásban.")
    assert bullets(text) == ["Adat töltések fejlesztése",
                             "Mesterséges intelligencia modellek fejlesztésében részvétel",
                             "Legalább 2 év tapasztalat Python programozásban."]


def test_english_and_german_split_only_at_sentence_ends():
    text = "Wir suchen eine Data Engineerin für Bern. Die Lösung soll Daten synchronisieren."
    assert bullets(text, hungarian=False) == ["Wir suchen eine Data Engineerin für Bern.",
                                              "Die Lösung soll Daten synchronisieren."]
    assert bullets("The Department of Biomedical Engineering is part of the Faculty of "
                   "Medicine.", hungarian=False) == [
        "The Department of Biomedical Engineering is part of the Faculty of Medicine."]


def test_written_bullets_and_semicolons_always_split():
    assert bullets("• Térinformatika ismerete; • Programozási ismeretek") == [
        "Térinformatika ismerete", "Programozási ismeretek"]


def test_sections_follow_headings():
    parts = split_sections("Állás leírása Feladatok ETL fejlesztése Elvárások SQL tudás "
                           "Előnyt jelent dbt Amit kínálunk Home office")
    assert parts == {"tasks": "ETL fejlesztése", "requirements": "SQL tudás",
                     "nice": "dbt", "other": "Home office"}


def test_profession_tags():
    techs = ("Elvárt technológiák SQL PYTHON GIT Biztosított eszközök Laptop "
             "Elvárások Angol középfok 1-3 év tapasztalat Főiskola")
    assert tools(techs) == "SQL PYTHON GIT"
    assert experience(techs, "") == "1-3 év tapasztalat"
    assert language(techs, "") == "Angol középfok"


def test_experience_and_seniority_from_text():
    assert experience(None, "You have at least 3 years of Python") == "at least 3 years (szövegből)"
    assert seniority("Senior Data Engineer") == "senior"
    assert seniority("Data Analyst Intern") == "junior"
    assert seniority("Data Engineer") == ""
