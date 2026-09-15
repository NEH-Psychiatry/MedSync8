#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Debian images ship a PyJWT without a RECORD file; pip cannot uninstall it
# and aborts the whole install. Reinstall it standalone first.
pip install -q --ignore-installed pyjwt >/dev/null 2>&1 || true

# Legacy Streamlit calculator deps + lint/test tooling.
pip install -q -r "$CLAUDE_PROJECT_DIR/requirements.txt"
pip install -q flake8 pytest

# FastAPI/RAG backend test deps (stub embedder; no torch download).
if [ -f "$CLAUDE_PROJECT_DIR/backend/requirements-test.txt" ]; then
  pip install -q -r "$CLAUDE_PROJECT_DIR/backend/requirements-test.txt"
fi
