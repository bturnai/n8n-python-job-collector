import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import embed  # noqa: E402


def test_text_is_title_and_description_with_e5_prefix():
    assert embed.embedding_text("Junior Data Analyst", "SQL, Power BI") == \
        "query: Junior Data Analyst\n\nSQL, Power BI"


def test_missing_description_keeps_title_only():
    assert embed.embedding_text("Data Engineer", None) == "query: Data Engineer"


def test_changed_text_changes_hash():
    a = embed.text_sha(embed.embedding_text("Data Analyst", "SQL"))
    b = embed.text_sha(embed.embedding_text("Data Analyst", "SQL, Python"))
    assert a != b and len(a) == 16
