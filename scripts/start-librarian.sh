#!/bin/sh
# Install dependencies once with: python3 -m venv .venv && .venv/bin/pip install -e .
# Provider credentials remain in the existing .env/environment.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
python_bin=${BIBLIOTHECARY_PYTHON:-"$project_dir/.venv/bin/python"}
if [ ! -x "$python_bin" ]; then
  echo 'Set BIBLIOTHECARY_PYTHON or install this checkout into .venv first.' >&2
  exit 1
fi
exec "$python_bin" -m bibliothecary telegram --explain 'Simplified Chinese' "$@"
