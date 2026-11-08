"""Score hand-labelled postings with Claude and store the verdicts in raw.llm_scores.

    python scripts/llm_score.py split                      # fix the train/test split once
    python scripts/llm_score.py score --model claude-haiku-5-5 --limit 10
    python scripts/llm_score.py score --model claude-sonnet-5-5 --batch
    python scripts/llm_score.py score --prompt v2 --run 2 --batch   # repeat a run to measure noise

The prompt is tuned on the train split only; the test split is scored once, at the end.
"""
import argparse
import csv
import hashlib
import json
import os
import pathlib
import random
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
LABELS_FILE = EVAL_DIR / "labels.xlsx"
SPLIT_FILE = EVAL_DIR / "split.csv"
PROFILE_FILE = EVAL_DIR / "profile.md"
ENV_FILE = ROOT / "anthropic.env"

DECISIONS = ["jelentkeznék", "talán", "nem"]
TEST_SHARE = 0.3
PROMPTS_DIR = ROOT / "prompts"
# v2: Hungarian reasons for German postings; Kaggle, thesis, dbt in profile.
# v3: reporting analysts are targets, business analysts stay "talán"; 1-3 years and cut-off text don't lower.
DEFAULT_PROMPT = "v3"

SCHEMA = {
    "type": "object",
    "properties": {
        "pros": {"type": "array", "items": {"type": "string"}},
        "cons": {"type": "array", "items": {"type": "string"}},
        "missing": {"type": "array", "items": {"type": "string"}},
        "decision": {"type": "string", "enum": DECISIONS},
        "score": {"type": "integer"},
    },
    "required": ["pros", "cons", "missing", "decision", "score"],
    "additionalProperties": False,
}


def make_split(labels, test_share, seed):
    """Stratified split: the same share of each decision goes to test. labels: {job_id: decision}."""
    rng = random.Random(seed)
    split = {}
    for decision in DECISIONS:
        ids = sorted(i for i, d in labels.items() if d == decision)
        rng.shuffle(ids)
        n_test = round(len(ids) * test_share)
        for n, job_id in enumerate(ids):
            split[job_id] = "test" if n < n_test else "train"
    return split


def read_labels():
    from openpyxl import load_workbook

    ws = load_workbook(LABELS_FILE, read_only=True).active
    rows = ws.iter_rows(values_only=True)
    header = list(next(rows))
    decision, job_id = header.index("döntés"), header.index("job_id")
    return {r[job_id]: r[decision] for r in rows if r[decision] in DECISIONS}


def read_split():
    with open(SPLIT_FILE, newline="", encoding="utf-8") as f:
        return {r["job_id"]: r for r in csv.DictReader(f)}


def system_prompt(name):
    rubric = (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")
    profile = PROFILE_FILE.read_text(encoding="utf-8").replace(" [CONFIRM]", "")
    return rubric, profile


def prompt_version(name, rubric, profile):
    digest = hashlib.sha256((rubric + profile).encode("utf-8")).hexdigest()[:8]
    return f"{name}-{digest}"


def posting_message(p):
    fields = [("Title", p["title"]), ("Company", p["company"]), ("Location", p["location"]),
              ("Work mode", p["place_label"]), ("Salary", p["salary_info"]),
              ("Tags", p["techs"]), ("Description", p["description"])]
    return "\n".join(f"{name}: {value}" for name, value in fields if value)


def parse_verdict(text):
    """Validate the model's JSON; raises ValueError on anything outside the contract."""
    verdict = json.loads(text)
    if verdict["decision"] not in DECISIONS:
        raise ValueError(f"unknown decision {verdict['decision']!r}")
    if not 1 <= verdict["score"] <= 10:
        raise ValueError(f"score out of range: {verdict['score']}")
    return verdict


def load_env():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name:
            os.environ.setdefault(name, value)


def connect():
    import psycopg

    return psycopg.connect(os.environ.get("DATABASE_URL", "dbname=jobs"))


def load_postings(conn, ids):
    rows = conn.execute(
        """select id, title, company, location, place_label, salary_info, techs, description
           from raw.job_postings where id = any(%s)""", (list(ids),)).fetchall()
    keys = ["id", "title", "company", "location", "place_label", "salary_info", "techs", "description"]
    return [dict(zip(keys, r)) for r in rows]


def request_params(model, effort, rubric, profile, posting):
    return {
        "model": model,
        "max_tokens": 8000,
        "system": [{"type": "text", "text": rubric},
                   {"type": "text", "text": profile, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": posting_message(posting)}],
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
    }


def message_text(msg):
    if msg.stop_reason != "end_turn":
        raise ValueError(f"stop_reason {msg.stop_reason}")
    return next(b.text for b in msg.content if b.type == "text")


def save(conn, job_id, model, version, effort, run, verdict, usage, batch_id=None):
    conn.execute(
        """insert into raw.llm_scores (job_id, model, prompt_version, effort, run, decision, score,
                                       pros, cons, missing, input_tokens, output_tokens, batch_id)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (job_id, model, prompt_version, effort, run) do update set
               decision = excluded.decision, score = excluded.score, pros = excluded.pros,
               cons = excluded.cons, missing = excluded.missing,
               input_tokens = excluded.input_tokens, output_tokens = excluded.output_tokens,
               batch_id = excluded.batch_id, scored_at = now()""",
        (job_id, model, version, effort, run, verdict["decision"], verdict["score"],
         json.dumps(verdict["pros"], ensure_ascii=False), json.dumps(verdict["cons"], ensure_ascii=False),
         json.dumps(verdict["missing"], ensure_ascii=False),
         usage.input_tokens + (usage.cache_read_input_tokens or 0) + (usage.cache_creation_input_tokens or 0),
         usage.output_tokens, batch_id))


def score_sync(client, conn, postings, model, effort, run, rubric, profile, version):
    for p in postings:
        msg = client.messages.create(**request_params(model, effort, rubric, profile, p))
        try:
            verdict = parse_verdict(message_text(msg))
        except (ValueError, KeyError, StopIteration) as e:
            print(f"  {p['id']}: invalid answer ({e})", file=sys.stderr)
            continue
        save(conn, p["id"], model, version, effort, run, verdict, msg.usage)
        conn.commit()
        print(f"  {p['id']}: {verdict['decision']} {verdict['score']} "
              f"({msg.usage.input_tokens}+{msg.usage.output_tokens} tokens)")


def score_batch(client, conn, postings, model, effort, run, rubric, profile, version):
    from anthropic.types.messages.batch_create_params import Request

    batch = client.messages.batches.create(requests=[
        Request(custom_id=re.sub(r"[^A-Za-z0-9_-]", "_", p["id"])[:64],
                params=request_params(model, effort, rubric, profile, p))
        for p in postings])
    print(f"batch {batch.id} submitted; polling every 60 s", flush=True)
    by_custom_id = {re.sub(r"[^A-Za-z0-9_-]", "_", p["id"])[:64]: p["id"] for p in postings}
    while client.messages.batches.retrieve(batch.id).processing_status != "ended":
        time.sleep(60)
    for result in client.messages.batches.results(batch.id):
        job_id = by_custom_id[result.custom_id]
        if result.result.type != "succeeded":
            print(f"  {job_id}: {result.result.type}", file=sys.stderr)
            continue
        msg = result.result.message
        try:
            verdict = parse_verdict(message_text(msg))
        except (ValueError, KeyError, StopIteration) as e:
            print(f"  {job_id}: invalid answer ({e})", file=sys.stderr)
            continue
        save(conn, job_id, model, version, effort, run, verdict, msg.usage, batch.id)
    conn.commit()


def cmd_split(args):
    if SPLIT_FILE.exists() and not args.force:
        sys.exit(f"{SPLIT_FILE.name} already exists; the split is fixed (use --force to redo it)")
    labels = read_labels()
    split = make_split(labels, TEST_SHARE, args.seed)
    with open(SPLIT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["job_id", "label", "split"])
        for job_id in sorted(split):
            writer.writerow([job_id, labels[job_id], split[job_id]])
    counts = {}
    for job_id, part in split.items():
        counts[(part, labels[job_id])] = counts.get((part, labels[job_id]), 0) + 1
    for part in ("train", "test"):
        print(part, {d: counts.get((part, d), 0) for d in DECISIONS})


def cmd_score(args):
    import anthropic

    load_env()
    split = read_split()
    ids = sorted(i for i, r in split.items() if r["split"] == args.split)
    if args.limit:
        ids = random.Random(args.seed).sample(ids, min(args.limit, len(ids)))
    rubric, profile = system_prompt(args.prompt)
    version = prompt_version(args.prompt, rubric, profile)
    client = anthropic.Anthropic()
    with connect() as conn:
        postings = load_postings(conn, ids)
        print(f"{len(postings)} {args.split} postings, {args.model}, effort {args.effort}, "
              f"{version}, run {args.run}", flush=True)
        score = score_batch if args.batch else score_sync
        score(client, conn, postings, args.model, args.effort, args.run, rubric, profile, version)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_split = sub.add_parser("split")
    p_split.add_argument("--seed", type=int, default=42)
    p_split.add_argument("--force", action="store_true")
    p_score = sub.add_parser("score")
    p_score.add_argument("--model", default="claude-haiku-5-5")
    p_score.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    p_score.add_argument("--prompt", default=DEFAULT_PROMPT, help="file name in prompts/, without .txt")
    p_score.add_argument("--run", type=int, default=1, help="repeat index; keeps earlier runs")
    p_score.add_argument("--split", default="train", choices=["train", "test"])
    p_score.add_argument("--limit", type=int)
    p_score.add_argument("--seed", type=int, default=42)
    p_score.add_argument("--batch", action="store_true")
    args = parser.parse_args()
    {"split": cmd_split, "score": cmd_score}[args.cmd](args)


if __name__ == "__main__":
    main()
