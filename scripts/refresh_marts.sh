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

"$ROOT/.venv/bin/python" "$ROOT/scripts/load_postgres.py" "$DATA_DIR"
cd "$ROOT/dbt"
"$ROOT/.venv/bin/dbt" build --quiet
echo "marts rebuilt"
