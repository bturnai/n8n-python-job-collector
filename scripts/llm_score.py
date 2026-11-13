"""Score hand-labelled postings with Claude and store the verdicts in raw.llm_scores.

What it does:
  split  - divides Bálint's hand-labelled postings into a train set (to tune the
           prompt on) and a test set (scored once, at the end). Run once.
  score  - sends postings to Claude with the scoring prompt and stores each answer
           (decision, score, pros, cons, missing) in PostgreSQL.
  score-new - the daily run: scores the newest day's postings (marts.mart_new_postings)
           with the plain v5 prompt and writes llm_pontok_<day>.json for the evening review.

    python scripts/llm_score.py split                                   # once
    python scripts/llm_score.py score --model claude-haiku-5-5 --limit 10
    python scripts/llm_score.py score --prompt v5 --run 2 --batch       # repeat a run
    python scripts/llm_score.py score --prompt v5 --rag --batch         # with RAG examples
    python scripts/llm_score.py score-new --out ../allasfigyelo         # every evening

The comparison with the hand labels is in scripts/llm_eval.py.
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
EVAL_DIR = ROOT / "eval"                   # local only: the labels are personal data
LABELS_FILE = EVAL_DIR / "labels.xlsx"     # Bálint's hand labels
SPLIT_FILE = EVAL_DIR / "split.csv"        # which posting is train and which is test
PROFILE_FILE = EVAL_DIR / "profile.md"     # his profile, built from his CVs
ENV_FILE = ROOT / "anthropic.env"          # the API key (git-ignored)
PROMPTS_DIR = ROOT / "prompts"             # the scoring rules, one file per version

# The three answers the model may give.
DECISIONS = ["jelentkeznék", "talán", "nem"]

# 30% of the labelled postings are held back as the test set.
TEST_SHARE = 0.3

# The prompt version used when --prompt is not given. v5 is the one chosen by the eval
# (prompts/v2.txt ... v5.txt; what changed between them is in the README).
DEFAULT_PROMPT = "v5"

# The shape the model's answer must have (a JSON schema). The API makes the model
# answer in exactly this shape, so the answer can always be read by code.
SCHEMA = {
    "type": "object",
    "properties": {
        "pros": {"type": "array", "items": {"type": "string"}},      # reasons for
        "cons": {"type": "array", "items": {"type": "string"}},      # reasons against
        "missing": {"type": "array", "items": {"type": "string"}},   # requirements he lacks
        "decision": {"type": "string", "enum": DECISIONS},           # only these three values
        "score": {"type": "integer"},                                # fit, 1-10
    },
    "required": ["pros", "cons", "missing", "decision", "score"],
    "additionalProperties": False,
}


# --- The train / test split ----------------------------------------------------

def make_split(labels, test_share, seed):
    """Divide the labelled postings into train and test.

    labels: {job_id: decision}, for example {"3038064": "talán", ...}
    Returns {job_id: "train" or "test"}.

    The split is stratified: the same share of each decision goes to test. With a
    plain random split, the few "jelentkeznék" postings could all end up on one side.
    The seed makes it reproducible: the same seed always gives the same split.
    """
    rnd = random.Random(seed)
    
    split={}
    for decision in DECISIONS:
        ids=[]
        for job_id, label in labels.items():
            if label == decision:
                ids.append(job_id)
        ids.sort()
        rnd.shuffle(ids)
        
        test_edge= round(len(ids) * test_share)
        
        count=0
        for job_id in ids:
            if (count< test_edge):
                split[job_id] = "test"
            else:
                split[job_id] = "train"
            count+=1
    
    return split


def read_labels():
    """Bálint's hand labels from eval/labels.xlsx: {job_id: decision}."""
    from openpyxl import load_workbook

    sheet = load_workbook(LABELS_FILE, read_only=True).active
    rows = sheet.iter_rows(values_only=True)
    header = list(next(rows))                 # the first row holds the column names
    decision_column = header.index("döntés")
    id_column = header.index("job_id")

    labels = {}
    for row in rows:
        decision = row[decision_column]
        if decision in DECISIONS:             # rows he has not labelled yet are skipped
            labels[row[id_column]] = decision
    return labels


def read_split():
    """eval/split.csv as {job_id: {"job_id": ..., "label": ..., "split": "train"/"test"}}."""
    split = {}
    with open(SPLIT_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            split[row["job_id"]] = row
    return split


# --- The prompt ------------------------------------------------------------------

def system_prompt(name):
    """The two parts of the system prompt: the rules (prompts/<name>.txt) and his profile."""
    rubric = (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")
    profile = PROFILE_FILE.read_text(encoding="utf-8").replace(" [CONFIRM]", "")
    return rubric, profile


def prompt_version(name, rubric, profile):
    """A name for the exact prompt, stored next to every score: for example "v5-2d1d54b2".

    The 8 characters are a fingerprint (hash) of the text. If even one character
    changes, the fingerprint changes, so every stored score points to the exact
    prompt that produced it.
    """
    text= rubric + profile 
    version = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    
    return f"{name}-{version}"


def posting_message(posting):
    """The posting as text, one field per line. Empty fields are left out.

    For example:
        Title: iREMS BI Developer
        Company: iREMS Hungary Kft.
        Location: Pest megye
        Description: ...
    """
    fields = [("Title", posting["title"]),
                ("Company", posting["company"]),
                ("Location", posting["location"]),
                ("Work mode", posting["place_label"]),
                ("Salary", posting["salary_info"]),
                ("Tags", posting["techs"]),
                ("Description", posting["description"])]
    lines = []
    for name, value in fields:
        if value:                              # skips None and ""
            lines.append(f"{name}: {value}")
    return "\n".join(lines)


def user_message(posting, examples=""):
    """The user message: the posting to score.

    With RAG, the examples block (scripts/rag.py) comes first, then the posting.
    """
    if examples=="":
        return posting_message(posting)
    examples += "\n\n"
    examples+= "Posting to decide on:\n" 
    examples+= posting_message(posting)
    
    return examples


def request_params(model, effort, rubric, profile, posting, examples=""):
    """Everything one API request needs, as a dict."""
    prompt={"model": model,
            "max_tokens": 8000,
            "system": 
            [
                {
                    "type":"text",
                    "text":rubric
                },
                {
                    "type":"text",
                    "text":profile,
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            "messages": 
            [
                {
                    "role": "user",
                    "content": user_message(posting, examples),
                }
            ],
            "output_config": 
            {
                "effort": effort,
                "format":
                {
                    "type": "json_schema", 
                    "schema": SCHEMA
                }
            }
            }
    return prompt



def message_text(message):
    """The text of the model's answer.

    stop_reason "end_turn" means the model finished its answer. Anything else (for
    example "max_tokens": it ran out of room) means the answer may be cut off.
    """
    if message.stop_reason != "end_turn":
        raise ValueError(f"stop_reason {message.stop_reason}")
    
    for row in message.content:

        if row.type== "text":
            return row.text
            
    raise ValueError("no text block in the answer")


def parse_verdict(text):
    """The model's JSON answer as a dict. Raises ValueError if it breaks the rules.

    The API already enforces SCHEMA, but the code checks again: the score range is
    not in the schema, and a stored wrong value would silently spoil the eval.
    """
    text=json.loads(text)
    if text["decision"] not in DECISIONS:
        raise ValueError(f"{text["decision"]} is not acceptable decision")
    if text["score"]<1 or text["score"]>10:
        raise ValueError(f"{text["score"]} outside the acceptable range")
    
    return text


# --- The database ------------------------------------------------------------------

def load_env():
    """Read the API key from anthropic.env into the environment, without printing it."""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name:
            os.environ.setdefault(name, value)


def connect():
    import psycopg

    return psycopg.connect(os.environ.get("DATABASE_URL", "dbname=jobs"))


def load_postings(conn, ids):
    """The postings with these ids, from raw.job_postings, as a list of dicts.

    The rows come back in the database's order, not necessarily in the order of ids.
    """
    rows = conn.execute(
        """
        select 
            id,
            title,
            company,
            location,
            place_label,
            salary_info,
            techs,
            description
        from
            raw.job_postings 
        where 
            id = any(%s)
        """, (list(ids),)).fetchall()
    keys = ["id", "title", "company", "location", "place_label", "salary_info", "techs", "description"]
    postings = []
    for row in rows:
        postings.append(dict(zip(keys, row)))   # zip pairs each key with its value
    return postings


def total_input_tokens(usage):
    """Every input token of one request, also the ones read from or written to the cache.

    usage: message.usage. The two cache fields are None when there was no cache.
    For example: input 200, cache read 800, cache creation None -> 1000
    """
    total=usage.input_tokens
    if usage.cache_creation_input_tokens is not None:
        total += usage.cache_creation_input_tokens
    if usage.cache_read_input_tokens is not None:
        total+=usage.cache_read_input_tokens
    return total


def save(conn, job_id, model, version, effort, run, verdict, usage, batch_id=None):
    """Store one verdict in raw.llm_scores.

    One row per (posting, model, prompt version, effort, run). If that row already
    exists (the same run scored again), it is overwritten, not added a second time:
    running the same thing twice never creates duplicates.
    """
    input_tokens = total_input_tokens(usage)

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
         json.dumps(verdict["pros"], ensure_ascii=False),
         json.dumps(verdict["cons"], ensure_ascii=False),
         json.dumps(verdict["missing"], ensure_ascii=False),
         input_tokens, usage.output_tokens, batch_id))


# --- Scoring: one by one, or as a batch ------------------------------------------------

def score_sync(client, conn, postings, model, effort, run, rubric, profile, version, examples):
    """Score the postings one by one: each request waits for its answer. Full price."""
    for posting in postings:
        params = request_params(model, effort, rubric, profile, posting, examples.get(posting["id"], ""))
        message = client.messages.create(**params)   # ** passes the dict's items as arguments
        try:
            verdict = parse_verdict(message_text(message))
        except (ValueError, KeyError) as error:
            print(f"  {posting['id']}: invalid answer ({error})", file=sys.stderr)
            continue
        save(conn, posting["id"], model, version, effort, run, verdict, message.usage)
        conn.commit()
        print(f"  {posting['id']}: {verdict['decision']} {verdict['score']} "
              f"({message.usage.input_tokens}+{message.usage.output_tokens} tokens)")


def batch_id_for(job_id):
    """A request id the Batch API accepts: only letters, digits, _ and -, at most 64 long.

    Some job ids have other characters, e.g. "remoteok:1136222" -> "remoteok_1136222".
    """
    result = ""
    for ch in job_id:
        if (ch.isascii() and ch.isalnum()) or ch == "_" or ch == "-":
            result = result + ch
        else:
            result = result + "_"
    return result[:64]


def score_batch(client, conn, postings, model, effort, run, rubric, profile, version, examples):
    """Score all postings in one batch: half price, but the answers come back later.

    1. Send every request at once.  2. Wait until the batch has ended.
    3. Read the results and store them.
    """
    # Step 1: send every request at once.
    requests = []
    job_id_by_request = {}
    for posting in postings:
        params = request_params(model, effort, rubric, profile, posting, examples.get(posting["id"], ""))
        request_id = batch_id_for(posting["id"])
        # One batch request: its id and the same params a direct call would get.
        requests.append({"custom_id": request_id, "params": params})
        job_id_by_request[request_id] = posting["id"]
    batch = client.messages.batches.create(requests=requests)
    print(f"batch {batch.id} submitted; polling every 60 s", flush=True)

    # Step 2: ask every minute whether the batch has finished.
    while client.messages.batches.retrieve(batch.id).processing_status != "ended":
        time.sleep(60)

    # Step 3: the results, in any order; the request id says which posting each is.
    for result in client.messages.batches.results(batch.id):
        job_id = job_id_by_request[result.custom_id]
        if result.result.type != "succeeded":   # errored, canceled or expired: not billed
            print(f"  {job_id}: {result.result.type}", file=sys.stderr)
            continue
        message = result.result.message
        try:
            verdict = parse_verdict(message_text(message))
        except (ValueError, KeyError) as error:
            print(f"  {job_id}: invalid answer ({error})", file=sys.stderr)
            continue
        save(conn, job_id, model, version, effort, run, verdict, message.usage, batch.id)
    conn.commit()


# --- The two commands ----------------------------------------------------------------

def cmd_split(args):
    """python scripts/llm_score.py split: write eval/split.csv once."""
    if SPLIT_FILE.exists() and not args.force:
        sys.exit(f"{SPLIT_FILE.name} already exists; the split is fixed (use --force to redo it)")
    labels = read_labels()
    split = make_split(labels, TEST_SHARE, args.seed)
    with open(SPLIT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["job_id", "label", "split"])
        for job_id in sorted(split):
            writer.writerow([job_id, labels[job_id], split[job_id]])

    # Print how many postings of each decision went to each side.
    for part in ("train", "test"):
        counts = {}
        for decision in DECISIONS:
            counts[decision] = 0
        for job_id, side in split.items():
            if side == part:
                counts[labels[job_id]] = counts[labels[job_id]] + 1
        print(part, counts)


# A made-up answer in the shape of SCHEMA, so --dry-run can show the reading step too.
SAMPLE_ANSWER = ('{"pros": ["Power BI, SQL"], "cons": ["Pest megye, nem Budapest"], '
                 '"missing": ["iREMS"], "decision": "talán", "score": 5}')


def show_requests(postings, args, rubric, profile, examples):
    """--dry-run: print what would be sent, without calling the API (no cost, nothing stored)."""
    for posting in postings:
        params = request_params(args.model, args.effort, rubric, profile, posting,
                                examples.get(posting["id"], ""))
        print(f"\n===== {posting['id']}: {posting['title']}")
        print(f"system: rules {len(params['system'][0]['text'])} characters, "
              f"profile {len(params['system'][1]['text'])} characters")
        for message in params["messages"]:
            print(f"--- {message['role']} message ---")
            print(message["content"])
    print("\n--- reading a sample answer ---")
    print(parse_verdict(SAMPLE_ANSWER))


def cmd_score(args):
    """python scripts/llm_score.py score: score the train (or test) postings."""
    import anthropic

    load_env()
    split = read_split()

    # The postings of the chosen set (train by default; "all" = every labelled posting).
    ids = []
    for job_id, row in split.items():
        if args.split == "all" or row["split"] == args.split:
            ids.append(job_id)
    ids.sort()
    if args.limit:                             # a small random sample, e.g. to try a prompt
        ids = random.Random(args.seed).sample(ids, min(args.limit, len(ids)))
    if args.job_id:                            # only this one posting
        ids = [args.job_id]

    rubric, profile = system_prompt(args.prompt)
    version = prompt_version(args.prompt, rubric, profile)   # e.g. "v5-2d1d54b2"
    if args.rag:
        # A separate name, so RAG runs never overwrite the plain runs: the rows are keyed
        # by (job_id, model, prompt_version, effort, run).
        version += "--rag"
        if args.pool == "all":
            version += "-all"                  # e.g. "v5-2d1d54b2--rag-all"

    with connect() as conn:
        postings = load_postings(conn, ids)

        # With --rag, every posting gets its own examples block; without it, none.
        examples = {}
        if args.rag:
            import rag
            examples = rag.examples_for_all(conn, postings, split, args.pool)

        print(f"{len(postings)} {args.split} postings, {args.model}, effort {args.effort}, "
              f"{version}, run {args.run}", flush=True)
        if args.dry_run:
            show_requests(postings, args, rubric, profile, examples)
            return

        client = anthropic.Anthropic()         # reads the API key from the environment
        if args.batch:
            score_batch(client, conn, postings, args.model, args.effort, args.run,
                        rubric, profile, version, examples)
        else:
            score_sync(client, conn, postings, args.model, args.effort, args.run,
                       rubric, profile, version, examples)


# --- The daily run ---------------------------------------------------------------------

# The daily scores get their own version name, like the RAG runs: if a daily posting is
# labelled later, its daily score must not count as an eval run.
DAILY_SUFFIX = "--daily"
DAILY_MODEL = "claude-haiku-5-5"
DAILY_EFFORT = "medium"
DAILY_RUN = 1


def not_yet_scored(ids, scored_ids):
    """The ids that have no daily score yet, in the same order.

    Example: not_yet_scored(["a", "b", "c"], ["b"]) -> ["a", "c"]
    If the evening review runs twice, the second run pays for nothing.
    """
    todo = []
    for job_id in ids:
        if job_id not in scored_ids:
            todo.append(job_id)
    return todo


def daily_file(day, version, scores, ids, error=None):
    """The content of llm_pontok_<day>.json, as a dict.

    scores: {job_id: (decision, score, missing)} from raw.llm_scores
    ids:    every posting of the day; the ones without a score go to "kihagyva"
            (skipped: an invalid answer, or the run stopped before them)
    error:  the error text if the run failed, otherwise None

    Example:
        {"datum": "2026-11-14", "prompt": "v5-2d1d54b2--daily", "hiba": None,
         "allasok": [{"id": "3049577", "dontes": "nem", "pont": 3,
                      "hianyzik": ["3-5 év tapasztalat"]}],
         "kihagyva": []}
    """
    postings = []
    skipped = []
    for job_id in ids:
        if job_id in scores:
            decision, score, missing = scores[job_id]
            postings.append({"id": job_id, "dontes": decision, "pont": score, "hianyzik": missing})
        else:
            skipped.append(job_id)
    return {"datum": day, "prompt": version, "hiba": error, "allasok": postings, "kihagyva": skipped}


def cmd_score_new(args):
    """python scripts/llm_score.py score-new --out DIR: score the newest day's postings."""
    import anthropic

    load_env()
    rubric, profile = system_prompt(DEFAULT_PROMPT)
    version = prompt_version(DEFAULT_PROMPT, rubric, profile) + DAILY_SUFFIX
    day = ""
    ids = []
    error = None

    with connect() as conn:
        try:
            # Step 1: the newest day's postings (Budapest area or remote).
            rows = conn.execute(
                "select job_id, collected_on from marts.mart_new_postings order by job_id").fetchall()
            for job_id, collected_on in rows:
                ids.append(job_id)
                day = str(collected_on)

            # Step 2: the ones without a daily score yet.
            scored_ids = []
            for row in conn.execute(
                    """select job_id from raw.llm_scores
                       where model = %s and prompt_version = %s and effort = %s and run = %s
                         and job_id = any(%s)""",
                    (DAILY_MODEL, version, DAILY_EFFORT, DAILY_RUN, ids)).fetchall():
                scored_ids.append(row[0])
            todo = not_yet_scored(ids, scored_ids)
            print(f"{day}: {len(ids)} new postings, {len(todo)} to score with {version}", flush=True)

            # Step 3: score them one by one (direct calls: the evening review waits for this).
            if len(todo) > 0:
                client = anthropic.Anthropic()
                score_sync(client, conn, load_postings(conn, todo), DAILY_MODEL, DAILY_EFFORT,
                           DAILY_RUN, rubric, profile, version, {})
        except Exception as problem:            # an API or database error: note it, go on
            conn.rollback()
            error = f"{type(problem).__name__}: {problem}"
            print(f"scoring stopped: {error}", file=sys.stderr)

        # Step 4: every daily score of these postings, also the ones from an earlier run.
        scores = {}
        if len(ids) > 0:
            for job_id, decision, score, missing in conn.execute(
                    """select job_id, decision, score, missing from raw.llm_scores
                       where model = %s and prompt_version = %s and effort = %s and run = %s
                         and job_id = any(%s)""",
                    (DAILY_MODEL, version, DAILY_EFFORT, DAILY_RUN, ids)).fetchall():
                scores[job_id] = (decision, score, missing)

    # Step 5: the file the evening review reads. Written even after an error, so the
    # review can say in the e-mail that there was no scoring today.
    if day == "":
        day = time.strftime("%Y-%m-%d")
    content = daily_file(day, version, scores, ids, error)
    path = pathlib.Path(args.out) / f"llm_pontok_{day}.json"
    path.write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {path.name}: {len(content['allasok'])} scored, {len(content['kihagyva'])} skipped")
    if error:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="cmd", required=True)

    split_command = commands.add_parser("split")
    split_command.add_argument("--seed", type=int, default=42)
    split_command.add_argument("--force", action="store_true")

    score_command = commands.add_parser("score")
    score_command.add_argument("--model", default="claude-haiku-5-5")
    score_command.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    score_command.add_argument("--prompt", default=DEFAULT_PROMPT, help="file name in prompts/, without .txt")
    score_command.add_argument("--run", type=int, default=1, help="repeat index; keeps earlier runs")
    score_command.add_argument("--split", default="train", choices=["train", "test", "all"])
    score_command.add_argument("--limit", type=int)
    score_command.add_argument("--seed", type=int, default=42)
    score_command.add_argument("--batch", action="store_true", help="Batch API: half price, slower")
    score_command.add_argument("--job-id", help="score only this posting")
    score_command.add_argument("--dry-run", action="store_true",
                               help="print the requests instead of sending them (no cost)")
    score_command.add_argument("--rag", action="store_true",
                               help="show the most similar labelled train postings as examples")
    score_command.add_argument("--pool", default="train", choices=["train", "all"],
                               help="with --rag: examples from the train set only, or from every "
                                    "labelled posting except the one scored (leave-one-out)")

    new_command = commands.add_parser("score-new")
    new_command.add_argument("--out", required=True, help="folder of the daily files (allasfigyelo)")

    args = parser.parse_args()
    if args.cmd == "split":
        cmd_split(args)
    elif args.cmd == "score-new":
        cmd_score_new(args)
    else:
        cmd_score(args)


if __name__ == "__main__":
    main()
