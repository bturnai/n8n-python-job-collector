# n8n job collector with Python Code nodes

A daily job-collection pipeline: n8n schedules the run, downloads Hungarian and
international job listings, and writes a de-duplicated JSON list for a later
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
  ├─ remote APIs: build URLs ─────────────► api_urls.py
  │    download Remotive / RemoteOK / Arbeitnow
  │    merge response + source, + state
  │    normalise, pick new jobs ──────────► api_parse.py
  ├─ merge both sources
  │    drop in-run duplicates ────────────► dedupe.py
  │    build report + new state ──────────► report.py
  └─ write allasok_<date>.json/.md, latott.json
```

Separate small workflows store LinkedIn job-alert e-mails (`linkedin_mail.py`)
and application requests from a one-click e-mail button or an e-mail reply
(`request_click.py`, `request_reply.py`).

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

## Repository layout

```
nodes/      one module per Code node, each with main(items)
scripts/
  sync.py                build the node code; `check` validates and runs every node in the
                         runner sandbox; `push` loads the code into the published workflow
  workflow_collector.py  generates the collector workflow JSON
  extract_fixtures.py    pulls real node inputs/outputs from stored n8n executions
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
