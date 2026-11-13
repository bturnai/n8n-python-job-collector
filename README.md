# n8n job collector with Python Code nodes

A daily job-collection pipeline: n8n schedules the run, downloads job listings
from profession.hu, and writes a de-duplicated JSON list for a later
review step. Every transformation step is a **Python** Code node, running in
n8n's native Python task runner inside Docker.

The Python nodes replaced a working JavaScript version in October 2026. Before
the switch they were verified against it on recorded production data and in a
side-by-side run.

## Architecture

```
n8n (host, launchd)                         n8n-runners (Docker)
────────────────────────────────            ─────────────────────────────
schedule 21:30 / webhook / manual
  ├─ read  latott.json (seen jobs)
  ├─ profession.hu: build URLs ───────────► search_urls.py
  │    download 80 result pages
  │    merge page + request, + state
  │    pick new data jobs ────────────────► filter_new.py
  │    download detail pages
  │    merge job + page
  │    extract posting text ──────────────► extract_text.py
  ├─ drop in-run duplicates ──────────────► dedupe.py
  │    build report + new state ──────────► report.py
  └─ write allasok_<date>.json/.md, latott.json
```

Three remote job APIs (Remotive, RemoteOK, Arbeitnow; `api_urls.py`,
`api_parse.py`) were a second branch until November 2026. In two months only one
of their postings made my shortlist, so the branch is off by default;
`workflow_collector.py --remote-apis` puts it back.

The daily list also reports how many job cards the profession.hu result pages
held. On a normal day that is about a thousand; zero means the pages did not
arrive (blocked or changed), and the list gets an alert that the evening
diagnostics e-mails. This was added after profession.hu's firewall started
blocking requests that imitated a browser, and ten days passed unnoticed.

Separate small workflows store LinkedIn job-alert e-mails (`linkedin_mail.py`)
and application requests from a one-click e-mail button or an e-mail reply
(`request_click.py`, `request_reply.py`). The e-mail sender workflow turns
optional base64 attachments into n8n binary data (`email_attachments.py`).

## Working inside the Python sandbox

n8n's Python runner executes each node in a hardened sandbox. That shaped the code:

| Constraint | Consequence here |
|---|---|
| A node cannot import another file | `scripts/sync.py` inlines `nodes/common.py` into every node |
| No `$getWorkflowStaticData` | The seen-jobs state is a JSON file read and written by n8n nodes, so it is visible and can be backed up |
| No `$('Other node')` references | Merge nodes pair each HTTP response with the item that requested it |
| Only allow-listed stdlib modules (`runner/n8n-task-runners.json`) | No `urllib`: a ten-line `encodeURIComponent`. `strftime()` imports the blocked `time` module internally, so dates are formatted by hand |
| Environment variables are hidden from user code | `TZ` has no effect, so times use `ZoneInfo("Europe/Budapest")` explicitly |
| No classes, `getattr`, `open` | Plain functions and dicts |

### Compatibility with the JavaScript version

The stored state (`seenIds`, `seenKeys`) and the e-mail file names were produced
by JavaScript, and the Python nodes must reproduce them exactly. `common.py`
therefore mirrors a few JavaScript string semantics:

- Slicing, `indexOf` and hashing count UTF-16 code units, so an emoji is two units.
- `\s` and `trim()` cover a different whitespace set than Python's.
- `\b` and `/i` are ASCII-only, which `re.ASCII` reproduces.

Each of these is pinned by a unit test whose expected value was computed with Node.js.

## Scoring postings with an LLM, measured against my own decisions

The pipeline collects postings; the question is which of them I would apply to.
`scripts/llm_score.py` asks Claude for one of three decisions, *would apply*,
*maybe* or *no* (`jelentkeznék` / `talán` / `nem`), plus a 1-10 fit score, pros,
cons and missing requirements. The answer is constrained by a JSON schema
(`output_config.format`) and checked again in code before it is stored in
`raw.llm_scores` (PostgreSQL). The candidate profile, built from my recent CVs,
is part of the system prompt.

### Ground truth

I labelled 86 postings by hand. The labelling sheet (`scripts/make_label_sample.py`)
hides the old Gemini scores, so they could not sway the labels. The labels were
split once, stratified by decision, 70/30 with a fixed seed: 61 postings to tune
the prompt on, 25 held back. The held-back set was scored once, with the final
prompt.

The labels and the profile contain personal data, so they stay local; the code,
the prompts and the tests are in this repository.

### What changed the result

| Step | Why |
|---|---|
| Rules in the prompt, one version per file (`prompts/v2.txt` … `v5.txt`) | Each version is stored with a hash of its text and the profile, so every score points to the exact prompt that produced it |
| Three runs per prompt version | The same prompt moved by up to 10 percentage points between runs on Haiku. One run per version could not tell a better prompt from a lucky run |
| Recall on *would apply* as the main metric | Missing a posting I would apply to costs more than an extra *maybe*. Agreement alone misleads: about half of the postings are *no* |
| Disagreements reviewed by me, rules written from them | v4 and v5 added rules I had applied without writing down: business analyst roles are *no*, an active student status is *no*, a missing tool with an equivalent I know (Teradata for PostgreSQL) is not a gap |

Tuning set (61 postings, Claude Haiku 5.5 unless noted, mean of three runs):

| Prompt | Agreement (range) | Recall on *would apply* (range) | Decisions that change between runs |
|---|---|---|---|
| v2 | 60% (57-64) | 39% (27-55) | 13 of 61 |
| v3 | 56% (51-61) | 48% (36-64) | 12 of 61 |
| v4 | 80% (79-80) | 45% | 6 of 61 |
| v5 | 81% (79-82) | 61% (55-64) | 2 of 61 |
| v5, Claude Sonnet 5.5 | 79% (75-84) | 67% (45-82) | 8 of 61 |

### Result on the held-back postings

25 postings, prompt v5, mean of three runs:

| Scorer | Agreement | Recall on *would apply* | *Would apply* answered *no* |
|---|---|---|---|
| Old Gemini scores (19 of 25 scored) | 42% | 50% | 2 |
| Claude Haiku 5.5 | 73% | 40% | 1 |
| Claude Sonnet 5.5 | 79% | 53% | 1 |

After the test was scored, one held-back label turned out to break a rule I had
set on the tuning set before the test: a student job labelled *would apply*,
although an active student status means *no* for me. With that label corrected,
Haiku reaches 77% and Sonnet 83% agreement, and neither model answers *no* to a
posting I would apply to. The table above keeps the original labels because the
error was found only where a model disagreed; a label error the model happened
to share would not have been found. All eight label changes are logged locally
with their reasons.

Haiku scored 81% on the tuning set and 73% on the held-back set; Sonnet scored
79% on both. The prompt rules were written from Haiku's mistakes on the tuning
set, so part of Haiku's tuning score did not carry over. Sonnet was not used for
tuning.

Limits: 25 held-back postings means one posting moves agreement by 4 points, and
the ground truth is one person's decisions. The whole eval cost about 2 USD in
API credits, mostly through the Batch API at half price. The scorer is not part
of the daily run yet; the evening review still scores the postings.

```bash
python scripts/llm_score.py score --model claude-haiku-5-5 --prompt v5 --run 1 --batch
python scripts/llm_eval.py                # tuning set: per run, mean, range, majority vote
python scripts/llm_eval.py --split test   # held-back set, only for the final prompt
```

## Repository layout

```
nodes/      one module per Code node, each with main(items)
scripts/
  sync.py                build the node code; `check` validates and runs every node in the
                         runner sandbox; `push` loads the code into the published workflow
  workflow_collector.py  generates the collector workflow JSON
  extract_fixtures.py    pulls real node inputs/outputs from stored n8n executions
  make_label_sample.py   draws the hand-labelling sheet for the LLM eval
  llm_score.py           scores postings with Claude (direct calls or Batch API)
  llm_eval.py            compares stored verdicts with the hand labels
  embed.py               embeds postings locally (multilingual-e5-small) into pgvector
  rag.py                 picks the most similar labelled train postings as examples
prompts/    the scoring prompt, one file per version
sql/        PostgreSQL tables (raw postings, LLM verdicts, posting embeddings)
runner/     docker-compose.yml and the runner's allow-list for the external task runner
tests/      unit tests and parity tests
```

## Testing

```bash
python -m pytest              # unit tests; parity tests run when local fixtures exist
python scripts/sync.py check  # sandbox: static analysis, then a real run of each node
```

- **Unit tests** use small synthetic inputs, including edge cases: the selection
  cap, ASCII word boundaries, emoji at slice boundaries, the 3000-entry state
  limit and an empty day.
- **Parity tests** feed each Python node the exact input its JavaScript
  predecessor received in production runs, and expect the same output. The
  recorded data contains scraped listings and e-mails, so it stays local
  (`tests/fixtures/real/`, git-ignored).
- **Sandbox check:** the sandbox's static analyzer misses things that fail only
  at run time, such as `strftime()` importing `time`. So `check` also executes
  every node in the runner container the way the runner does.

Before switching over, both versions ran side by side from the same starting
state. The job lists, the report and the updated state were identical. The only
difference was an intended fix: RemoteOK sends double-encoded UTF-8
(`donâ€™t`), which the Python version repairs.

## Running the task runner

n8n runs on the host in external runner mode (`N8N_RUNNERS_MODE=external`, plus a
shared `N8N_RUNNERS_AUTH_TOKEN`). The runner container connects to the task
broker through `host.docker.internal`, so the broker stays bound to
`127.0.0.1`.

```bash
docker compose -f runner/docker-compose.yml up -d
```

The image tag must match the n8n version.
