import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import posting_profile as pp  # noqa: E402

POSTING = "Elvárások: legalább 2 év Python tapasztalat, angol középfok. Feladatok: riportok készítése."


def test_words_keeps_long_words_only():
    assert pp.words("SQL és Python, 3+ év") == ["python"]


def test_item_from_the_posting_is_kept():
    assert pp.is_in_posting("Python tapasztalat", POSTING)
    assert pp.is_in_posting("SQL", POSTING)            # no long word: nothing to check


def test_made_up_item_is_dropped():
    assert not pp.is_in_posting("Kubernetes és Terraform ismeret", POSTING)


def test_check_profile_counts_dropped_items():
    profile = {"seniority": "junior or entry level", "years_experience": "2",
               "languages": ["angol középfok"], "student_status_required": False,
               "requirements": ["Python tapasztalat", "Kubernetes és Terraform ismeret"],
               "nice_to_have": [], "tasks": ["riportok készítése"]}
    checked, dropped = pp.check_profile(profile, POSTING)
    assert dropped == ["Kubernetes és Terraform ismeret"]
    assert checked["requirements"] == ["Python tapasztalat"]
    assert profile["requirements"] == ["Python tapasztalat", "Kubernetes és Terraform ismeret"]


def test_profile_text_lines():
    profile = {"seniority": "senior", "years_experience": "3-5", "languages": ["angol felsőfok"],
               "student_status_required": False, "requirements": ["SAP", "pénzügyi riportolás"],
               "nice_to_have": ["Power BI"], "tasks": ["controlling riportok"]}
    assert pp.profile_text("Senior Financial Analyst", profile) == (
        "Title: Senior Financial Analyst\n"
        "Seniority: senior | Experience: 3-5 years | Languages: angol felsőfok | Student status: no\n"
        "Requirements: SAP; pénzügyi riportolás\n"
        "Tasks: controlling riportok\n"
        "Nice to have: Power BI")
