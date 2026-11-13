#!/bin/sh
# Load the daily job files and rebuild every model and test, so both the e-mail mart
# (marts.mart_new_postings) and the parity check's mart are current.
# The evening review runs this before it reads the mart, so the order is always
# collect -> load -> dbt build -> review.
#
# Usage: scripts/refresh_marts.sh DATA_DIR
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DATA_DIR=${1:?usage: refresh_marts.sh DATA_DIR}
DATA_DIR=$(cd "$DATA_DIR" && pwd)   # absolute, because of the cd below

"$ROOT/.venv/bin/python" "$ROOT/scripts/load_postgres.py" "$DATA_DIR"
cd "$ROOT/dbt"
"$ROOT/.venv/bin/dbt" build --quiet
echo "marts rebuilt"

# The daily v5 scoring of the newest postings (writes llm_pontok_<day>.json).
# If it fails, the review still runs, and its e-mail says there was no scoring today.
"$ROOT/.venv/bin/python" "$ROOT/scripts/llm_score.py" score-new --out "$DATA_DIR" \
    || echo "v5 scoring failed (see above)"
