import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import rag  # noqa: E402

ANALYST = {"title": "Junior Data Analyst", "description": "SQL, Power BI"}
BA = {"title": "Business Analyst", "description": "Requirements, workshops"}


# --- exercise 1 -------------------------------------------------------------

def test_format_example_has_number_label_title_description():
    assert rag.format_example(1, ANALYST, "jelentkeznék") == (
        "Example 1, his decision: jelentkeznék\n"
        "Title: Junior Data Analyst\n"
        "Description: SQL, Power BI")


def test_format_example_cuts_long_description():
    posting = {"title": "Data Engineer", "description": "x" * (rag.EXAMPLE_CHARS + 500)}
    text = rag.format_example(2, posting, "talán")
    assert text.endswith("Description: " + "x" * rag.EXAMPLE_CHARS)


def test_format_example_without_description():
    posting = {"title": "Data Engineer", "description": None}
    assert rag.format_example(3, posting, "nem").endswith("Description: ")


# --- exercise 2 -------------------------------------------------------------

def test_format_examples_numbers_from_one_with_header():
    block = rag.format_examples([(ANALYST, "jelentkeznék"), (BA, "nem")])
    assert block == (
        rag.HEADER + "\n\n"
        + rag.format_example(1, ANALYST, "jelentkeznék") + "\n\n"
        + rag.format_example(2, BA, "nem"))


def test_format_examples_empty_list_gives_no_block():
    assert rag.format_examples([]) == ""


# --- exercise 3 -------------------------------------------------------------

NEIGHBOURS = [("a", 1.000), ("b", 0.95), ("c", 0.93), ("d", 0.92), ("e", 0.91), ("f", 0.90)]


def test_pick_examples_skips_near_duplicates_and_keeps_k():
    # "a" (1.000) is practically the same posting, so it never becomes an example.
    assert rag.pick_examples(NEIGHBOURS, k=3) == ["b", "c", "d"]


def test_pick_examples_with_fewer_neighbours_than_k():
    assert rag.pick_examples(NEIGHBOURS[1:3], k=5) == ["b", "c"]


# --- exercise 4 -------------------------------------------------------------

def test_examples_come_only_from_the_train_set(monkeypatch):
    import embed
    import llm_score

    split = {"tr1": {"label": "nem", "split": "train"},
             "tr2": {"label": "talán", "split": "train"},
             "te1": {"label": "jelentkeznék", "split": "test"}}
    asked = {}

    def fake_nearest(conn, job_id, candidates, k):
        asked["candidates"] = sorted(candidates)
        return [("tr2", 0.95), ("tr1", 0.93)]

    def fake_load_postings(conn, ids):
        return [{"id": i, "title": f"Title {i}", "description": "text"} for i in ids]

    monkeypatch.setattr(embed, "nearest", fake_nearest)
    monkeypatch.setattr(llm_score, "load_postings", fake_load_postings)
    block = rag.examples_for(None, "te1", split)
    assert asked["candidates"] == ["tr1", "tr2"]          # the test posting is never a candidate
    assert "Example 1, his decision: talán\nTitle: Title tr2" in block


# --- leave-one-out pool -------------------------------------------------------

def test_pool_all_offers_every_labelled_posting(monkeypatch):
    import embed
    import llm_score

    split = {"tr1": {"label": "nem", "split": "train"},
             "te1": {"label": "jelentkeznék", "split": "test"},
             "te2": {"label": "talán", "split": "test"}}
    asked = {}

    def fake_nearest(conn, job_id, candidates, k):
        asked["candidates"] = list(candidates)
        return [("te2", 0.95)]

    def fake_load_postings(conn, ids):
        return [{"id": i, "title": f"Title {i}", "description": "text"} for i in ids]

    monkeypatch.setattr(embed, "nearest", fake_nearest)
    monkeypatch.setattr(llm_score, "load_postings", fake_load_postings)
    block = rag.examples_for(None, "te1", split, pool="all")
    # every labelled posting is offered; nearest() itself leaves out te1
    assert asked["candidates"] == ["te1", "te2", "tr1"]
    assert "his decision: talán\nTitle: Title te2" in block
