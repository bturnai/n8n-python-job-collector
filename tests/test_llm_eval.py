"""Metrics and the Gemini threshold fit for the LLM scoring eval."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from llm_eval import fit_thresholds, majority, metrics, to_decision


def test_metrics_counts_the_costly_miss():
    m = metrics([("jelentkeznék", "jelentkeznék"), ("jelentkeznék", "nem"),
                 ("talán", "talán"), ("nem", "talán")])
    assert m["accuracy"] == 0.5
    assert m["yes_recall"] == 0.5
    assert m["yes_missed"] == 1
    assert m["confusion"][("nem", "talán")] == 1


def test_to_decision_bands():
    assert [to_decision(s, 7, 4) for s in (9, 7, 6, 4, 3)] == \
        ["jelentkeznék", "jelentkeznék", "talán", "talán", "nem"]


def test_fit_thresholds_recovers_clean_bands():
    pairs = [("jelentkeznék", 8), ("jelentkeznék", 9), ("talán", 5), ("talán", 6),
             ("nem", 2), ("nem", 3)]
    high, low = fit_thresholds(pairs)
    assert all(to_decision(s, high, low) == l for l, s in pairs)


def test_majority_vote_and_hopeful_tie_break():
    assert majority(["nem", "talán", "nem"]) == "nem"
    assert majority(["nem", "talán", "jelentkeznék"]) == "jelentkeznék"
    assert majority(["talán", "nem"]) == "talán"
