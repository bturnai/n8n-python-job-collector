# n8n job collector with Python Code nodes

A daily job-collection pipeline: n8n schedules the run, downloads job listings
from profession.hu, reads the NoFluffJobs and Indeed job-alert e-mails, and
writes a de-duplicated JSON list for a later review step. Every transformation step is a **Python** Code node, running in
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
  ├─ alert e-mails in levelek/ (NoFluffJobs, Indeed)
  │    take the new data jobs out ────────► mail_parse.py
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

The job-alert mail workflow (`scripts/workflow_mail.py`) has one IMAP trigger
for LinkedIn, NoFluffJobs and Indeed; an If node sends LinkedIn mails down the
old path and saves the other two raw into `levelek/` (`alert_mail.py`), where
the collector reads them in the evening. Indeed's alert has a plain-text part with one block
per job; NoFluffJobs sends only HTML, and its job links go through a click
counter whose real address is base64-encoded (decoded by hand: the sandbox has
no `base64` module). The stored links carry no personal tracking codes. The
alerts hold no full posting text, so these rows have a snippet (Indeed) or no
description (NoFluffJobs). A job that also appears on profession.hu is kept
once, with profession.hu's full text.

The saved mails stay in the folder and are read again every evening; the
seen-list skips what was already collected. One thing showed up only in a test
run inside n8n: on an empty folder the Read Files node does not return zero
items but fails with "No file(s) found", and that stopped the whole run,
profession.hu included. The node now continues on error, and the parser skips
the error item.

LinkedIn alerts are not parsed into rows: a separate evening review reads them
and checks the companies' own career pages. Other small workflows store
application requests from a one-click e-mail button or an e-mail reply
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
API credits, mostly through the Batch API at half price. Since 2026-11-14 the plain
v5 prompt scores the newest postings every evening (`llm_score.py score-new`, run
by `refresh_marts.sh`). The evening review still scores them too, and for two
weeks both scores are kept, to compare them.

### Similar postings as examples (RAG)

I was not that happy with the v5 result; I know the set is small, but I think the
model could have done better, it just needed examples that resemble the posting it
decides on.

At first I only looked at my decisions on the nearest neighbours, and the result
was voted from them. This was clearly not the best (51-59% agreement, about as
much as answering *no* to everything), so later I gave the model the 5 nearest
neighbours, so that it reads their descriptions too and decides based on them
together with the rules.

`scripts/rag.py` finds the neighbours among the tuning postings (local
multilingual-e5-small embeddings in pgvector) and puts them, with my decision on
each, in front of the posting. Held-back postings are never examples, and a
neighbour with similarity 0.99 or higher is skipped, because it is the same
posting posted again.

Claude Haiku 5.5, prompt v5, mean of three runs; the held-back set with the
corrected labels:

| Set | Scorer | Agreement (range) | Recall on *would apply* (range) | Decisions that change between runs |
|---|---|---|---|---|
| Tuning (61) | v5 | 81% (79-82) | 61% (55-64) | 2 of 61 |
| Tuning (61) | v5 + examples | 84% (84-84) | 79% (73-82) | 4 of 61 |
| Held back (25) | v5 | 77% (76-80) | 50% | 3 of 25 |
| Held back (25) | v5 + examples | 83% (80-84) | 67% (50-75) | 1 of 25 |
| Held back (25) | v5, Claude Sonnet 5.5 | 83% (80-84) | 67% (50-75) | 2 of 25 |

With the examples, Haiku's majority vote on the held-back set matched Sonnet's
decision for decision, at about a tenth of the price per run.

The held-back set had 4 *would apply* postings. Haiku with the examples did better
than with the plain v5 prompt. That can be chance, but I saw a similar gain on the
tuning set too, so chance is less likely.

To check this on more postings, I scored all 86 labelled postings leave-one-out:
any other labelled posting could be an example, the way it would run every day.
Claude Haiku 5.5, all 86 postings (15 *would apply*), three runs:

| Scorer | Agreement (range) | Recall on *would apply* (range) | Decisions that change between runs |
|---|---|---|---|
| v5 | 80% (79-80) | 58% (53-60) | 5 of 86 |
| v5 + examples from the tuning postings | 84% (83-84) | 76% (73-80) | 5 of 86 |
| v5 + examples from all labelled postings | 78% (77-78) | 47% | 10 of 86 |

The two example rows differ only in which postings may be examples, and that alone
moved five *would apply* postings to *maybe*. The earlier gain depended on which
five examples happened to be picked.

It surprised me, because I thought the postings scored as close to it would only
strengthen the decision, but it turned out they do not. To me this also shows that
I may not be showing the model the right examples, and that is what leads it
astray, because the examples reinforce a rule. Later I will test it again on a
larger set, and that will show whether the size of the set is the problem.

The plain v5 prompt goes into the daily run. I want to refine RAG later, because I
think this only shows up on a small set.

```bash
python scripts/llm_score.py score --model claude-haiku-5-5 --prompt v5 --run 1 --batch
python scripts/llm_score.py score --prompt v5 --rag --run 1 --batch   # with examples
python scripts/llm_score.py score --prompt v5 --rag --pool all --split all --run 1 --batch  # leave-one-out
python scripts/llm_eval.py                # tuning set: per run, mean, range, majority vote
python scripts/llm_eval.py --split test   # held-back set, only for the final prompt
python scripts/llm_eval.py --split all    # all labelled postings (leave-one-out runs)
```

## Repository layout

```
nodes/      one module per Code node, each with main(items)
scripts/
  sync.py                build the node code; `check` validates and runs every node in the
                         runner sandbox; `push` loads the code into the published workflow
  workflow_collector.py  generates the collector workflow JSON
  workflow_mail.py       generates the job-alert mail workflow JSON
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
  (`tests/fixtures/real/`, git-ignored). The same goes for the real
  NoFluffJobs and Indeed alerts (`tests/fixtures/levelek/*.eml`): their
  links carry personal tracking codes. The committed tests use rows cut
  from those mails.
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
