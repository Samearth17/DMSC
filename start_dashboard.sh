#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "First install: python3 -m venv .venv && .venv/bin/python -m pip install -e '.[all]'"
  exit 1
fi
exec .venv/bin/python -m app.cli serve --open
