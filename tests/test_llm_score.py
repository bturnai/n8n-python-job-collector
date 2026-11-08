"""Split, prompt and answer validation for the LLM scorer (no API or database needed)."""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from llm_score import make_split, parse_verdict, posting_message, prompt_version


def labels(n_yes, n_maybe, n_no):
    out = {}
    for decision, n in (("jelentkeznék", n_yes), ("talán", n_maybe), ("nem", n_no)):
        out.update({f"{decision}-{i}": decision for i in range(n)})
    return out


def test_split_keeps_label_shares():
    split = make_split(labels(17, 28, 40), 0.3, seed=42)
    tests = [i for i, part in split.items() if part == "test"]
    assert sum(i.startswith("jelentkeznék") for i in tests) == 5
    assert sum(i.startswith("talán") for i in tests) == 8
    assert sum(i.startswith("nem") for i in tests) == 12


def test_split_is_reproducible_and_seed_dependent():
    pool = labels(10, 10, 10)
    assert make_split(pool, 0.3, seed=1) == make_split(pool, 0.3, seed=1)
    assert make_split(pool, 0.3, seed=1) != make_split(pool, 0.3, seed=2)


def test_prompt_version_changes_with_profile():
    assert prompt_version("v3", "rubric", "profile A") != prompt_version("v3", "rubric", "profile B")
    assert prompt_version("v3", "rubric", "profile A").startswith("v3-")


def test_prompt_files_keep_stored_versions():
    from llm_score import PROFILE_FILE, system_prompt
    if not PROFILE_FILE.exists():
        pytest.skip("eval/profile.md is local only")
    assert prompt_version("v2", *system_prompt("v2")) == "v2-9b6dcbaf"
    assert prompt_version("v3", *system_prompt("v3")) == "v3-cccf4eb2"


def test_posting_message_skips_empty_fields():
    text = posting_message({"title": "Data Engineer", "company": "X", "location": None,
                            "place_label": "Hibrid", "salary_info": "", "techs": None,
                            "description": "SQL"})
    assert text == "Title: Data Engineer\nCompany: X\nWork mode: Hibrid\nDescription: SQL"


def verdict(**changes):
    v = {"pros": ["SQL"], "cons": [], "missing": [], "decision": "talán", "score": 5}
    v.update(changes)
    return json.dumps(v)


def test_parse_verdict_accepts_valid_answer():
    assert parse_verdict(verdict())["score"] == 5


@pytest.mark.parametrize("bad", [verdict(score=0), verdict(score=11), verdict(decision="igen")])
def test_parse_verdict_rejects_out_of_contract(bad):
    with pytest.raises(ValueError):
        parse_verdict(bad)
