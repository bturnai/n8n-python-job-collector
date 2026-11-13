"""A short profile of every posting, extracted by Claude, for the embeddings (RAG).

The embedding of the whole posting text captures its topic ("data job, SQL, BI"), but
Bálint decides on details: seniority, years of experience, language, student status.
This script asks Claude Haiku to pull exactly those out, and stores them in
features.posting_profiles. scripts/embed.py --profiles then embeds the profiles.

    python scripts/posting_profile.py              # new or changed postings, Batch API
    python scripts/posting_profile.py --limit 3    # a few postings, direct calls, to look at

Claude may only copy what the posting says. Every list item is checked against the
posting text, and an item whose words are mostly not in it is dropped (and counted).
"""
import argparse
import hashlib
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from llm_score import batch_id_for, connect, load_env, message_text  # noqa: E402

MODEL = "claude-haiku-5-5"
EFFORT = "low"          # copying facts out of a text needs little thinking

SENIORITY = ["intern or student", "junior or entry level", "mid level", "senior", "lead or manager",
             "not stated"]

SCHEMA = {
    "type": "object",
    "properties": {
        "seniority": {"type": "string", "enum": SENIORITY},
        "years_experience": {"type": "string"},                       # e.g. "3-5", "" if not stated
        "languages": {"type": "array", "items": {"type": "string"}},  # e.g. "English advanced"
        "student_status_required": {"type": "boolean"},
        "requirements": {"type": "array", "items": {"type": "string"}},
        "nice_to_have": {"type": "array", "items": {"type": "string"}},
        "tasks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["seniority", "years_experience", "languages", "student_status_required",
                 "requirements", "nice_to_have", "tasks"],
    "additionalProperties": False,
}

SYSTEM = """You extract facts from one job posting for a job-matching system.
Copy only what the posting states, in the posting's own words. Do not infer, guess or add anything.

- years_experience: only the number or range, e.g. "3-5", "2+", "0"; "" if not stated.
- languages: each required language with its level as written, e.g. "English fluent", "német C1".
- requirements: the hard must-haves only: tools, technologies, degree, field of experience,
  driving licence. At most 8 items, each at most 6 words. No personality traits or soft skills
  ("pro-active", "team player", "good communication").
- nice_to_have: at most 4 items, each at most 6 words, same kind as requirements.
- tasks: the 3 main tasks, each at most 6 words.
Leave out the company description and the benefits.
If something is not stated: "not stated", an empty string, an empty list or false."""

# The list fields that are checked against the posting text.
LIST_FIELDS = ["languages", "requirements", "nice_to_have", "tasks"]


def words(text):
    """The words of a text that count in the check: lower case, at least 4 letters.

    Example: words("SQL és Python, 3+ év") -> ["python"]
    """
    found = []
    for word in re.findall(r"\w+", text.lower()):
        if len(word) >= 4:
            found.append(word)
    return found


def is_in_posting(item, posting_text):
    """True if at least half of the item's words are in the posting text.

    Example: is_in_posting("Python tapasztalat", "... legalább 2 év Python tapasztalat ...") -> True
    An item with no long word at all (e.g. "SQL") is kept: there is nothing to check.
    """
    item_words = words(item)
    if len(item_words) == 0:
        return True
    text = posting_text.lower()
    found = 0
    for word in item_words:
        if word in text:
            found = found + 1
    return found * 2 >= len(item_words)


def check_profile(profile, posting_text):
    """The profile with the made-up list items dropped, and the list of dropped items."""
    checked = dict(profile)
    dropped = []
    for field in LIST_FIELDS:
        kept = []
        for item in profile[field]:
            if is_in_posting(item, posting_text):
                kept.append(item)
            else:
                dropped.append(item)
        checked[field] = kept
    return checked, dropped


def profile_text(title, profile):
    """The profile as one text, the input of the embedding.

    Example:
        Title: Senior Financial Analyst
        Seniority: senior | Experience: 3-5 years | Languages: angol felsőfok | Student status: no
        Requirements: SAP; pénzügyi riportolás
        Tasks: controlling riportok
        Nice to have: Power BI
    """
    experience = "not stated"
    if profile["years_experience"]:
        experience = profile["years_experience"] + " years"
    languages = "; ".join(profile["languages"]) or "not stated"
    student = "yes" if profile["student_status_required"] else "no"
    lines = [f"Title: {title}",
             f"Seniority: {profile['seniority']} | Experience: {experience} | "
             f"Languages: {languages} | Student status: {student}",
             "Requirements: " + "; ".join(profile["requirements"]),
             "Tasks: " + "; ".join(profile["tasks"]),
             "Nice to have: " + "; ".join(profile["nice_to_have"])]
    return "\n".join(lines)


def text_sha(title, description):
    return hashlib.sha256(f"{title}\n\n{description or ''}".encode("utf-8")).hexdigest()[:16]


def request_params(title, description):
    return {
        "model": MODEL,
        "max_tokens": 4000,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": f"Title: {title}\n\n{description or ''}"}],
        "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
    }


def save(conn, job_id, profile, dropped, sha):
    conn.execute(
        """insert into features.posting_profiles (job_id, model, profile, dropped, text_sha)
           values (%s, %s, %s, %s, %s)
           on conflict (job_id) do update set model = excluded.model, profile = excluded.profile,
               dropped = excluded.dropped, text_sha = excluded.text_sha, created_at = now()""",
        (job_id, MODEL, json.dumps(profile, ensure_ascii=False), dropped, sha))


def store_answer(conn, posting, message):
    """Check one answer and store it. Returns the number of dropped items, or None."""
    job_id, title, description = posting
    try:
        profile = json.loads(message_text(message))
    except (ValueError, KeyError) as error:
        print(f"  {job_id}: invalid answer ({error})", file=sys.stderr)
        return None
    checked, dropped = check_profile(profile, f"{title}\n{description or ''}")
    save(conn, job_id, checked, len(dropped), text_sha(title, description))
    return dropped


def main():
    import anthropic

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="only this many postings, with direct calls")
    args = parser.parse_args()
    load_env()
    client = anthropic.Anthropic()

    with connect() as conn:
        # Step 1: the postings without a profile, or whose text changed since.
        done = dict(conn.execute("select job_id, text_sha from features.posting_profiles").fetchall())
        todo = []
        for job_id, title, description in conn.execute(
                "select id, title, description from raw.job_postings order by id").fetchall():
            if done.get(job_id) != text_sha(title, description):
                todo.append((job_id, title, description))
        print(f"{len(todo)} postings to profile", flush=True)

        # Step 2a: a few, one by one, to look at the result.
        if args.limit:
            for posting in todo[:args.limit]:
                message = client.messages.create(**request_params(posting[1], posting[2]))
                dropped = store_answer(conn, posting, message)
                conn.commit()
                print(f"  {posting[0]}: dropped {dropped}")
            return

        # Step 2b: all of them in one batch (half price).
        requests = []
        posting_by_request = {}
        for posting in todo:
            request_id = batch_id_for(posting[0])
            requests.append({"custom_id": request_id, "params": request_params(posting[1], posting[2])})
            posting_by_request[request_id] = posting
        if len(requests) == 0:
            return
        batch = client.messages.batches.create(requests=requests)
        print(f"batch {batch.id} submitted; polling every 60 s", flush=True)
        while client.messages.batches.retrieve(batch.id).processing_status != "ended":
            time.sleep(60)

        # Step 3: store the answers.
        stored = 0
        dropped_total = 0
        for result in client.messages.batches.results(batch.id):
            posting = posting_by_request[result.custom_id]
            if result.result.type != "succeeded":
                print(f"  {posting[0]}: {result.result.type}", file=sys.stderr)
                continue
            dropped = store_answer(conn, posting, result.result.message)
            if dropped is not None:
                stored = stored + 1
                dropped_total = dropped_total + len(dropped)
        conn.commit()
        print(f"stored {stored} profiles; {dropped_total} items dropped as not in the posting")


if __name__ == "__main__":
    main()
