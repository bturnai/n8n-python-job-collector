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


def test_user_message_puts_examples_before_the_posting():
    from llm_score import user_message
    posting = {"title": "Data Engineer", "company": "X", "location": None, "place_label": None,
               "salary_info": None, "techs": None, "description": "SQL"}
    assert user_message(posting) == posting_message(posting)
    text = user_message(posting, "EXAMPLES")
    assert text.startswith("EXAMPLES\n\nPosting to decide on:\nTitle: Data Engineer")


# --- the parts of a request, the database row and the batch loop ---------------------

def test_request_puts_rules_in_system_and_posting_in_a_user_message():
    from llm_score import request_params
    posting = {"title": "Data Engineer", "company": "X", "location": None, "place_label": None,
               "salary_info": None, "techs": None, "description": "SQL"}
    params = request_params("claude-haiku-5-5", "medium", "RULES", "PROFILE", posting)
    assert [part["text"] for part in params["system"]] == ["RULES", "PROFILE"]
    assert params["messages"] == [{"role": "user", "content": posting_message(posting)}]


class FakeUsage:
    input_tokens = 100
    output_tokens = 20
    cache_read_input_tokens = 900
    cache_creation_input_tokens = None


class FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def commit(self):
        pass


def test_save_overwrites_a_rerun_instead_of_adding_a_row():
    from llm_score import save
    conn = FakeConnection()
    verdict = {"decision": "talán", "score": 5, "pros": ["SQL"], "cons": [], "missing": []}
    save(conn, "3038064", "claude-haiku-5-5", "v5-2d1d54b2", "medium", 1, verdict, FakeUsage())
    sql, params = conn.statements[0]
    assert "on conflict (job_id, model, prompt_version, effort, run) do update set" in sql
    assert params[10] == 1000          # input tokens include the ones read from the cache


def test_batch_waits_until_ended_then_stores_results(monkeypatch):
    import llm_score
    from types import SimpleNamespace as Obj

    statuses = ["in_progress", "in_progress", "ended"]
    answer = Obj(stop_reason="end_turn", usage=FakeUsage(), content=[Obj(
        type="text", text='{"pros": [], "cons": [], "missing": [], "decision": "nem", "score": 2}')])

    class FakeBatches:
        def create(self, requests):
            return Obj(id="batch_1")

        def retrieve(self, batch_id):
            return Obj(processing_status=statuses.pop(0))

        def results(self, batch_id):
            return [Obj(custom_id="remoteok_1", result=Obj(type="succeeded", message=answer))]

    client = Obj(messages=Obj(batches=FakeBatches()))
    sleeps = []
    monkeypatch.setattr(llm_score.time, "sleep", lambda seconds: sleeps.append(seconds))
    conn = FakeConnection()
    posting = {"id": "remoteok:1", "title": "T", "company": None, "location": None,
               "place_label": None, "salary_info": None, "techs": None, "description": None}
    llm_score.score_batch(client, conn, [posting], "claude-haiku-5-5", "medium", 1,
                          "RULES", "PROFILE", "v5-x", {})
    assert sleeps == [60, 60]           # asked three times, waited twice
    assert conn.statements[0][1][0] == "remoteok:1"   # stored under the real job id
