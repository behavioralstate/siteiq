#!/usr/bin/env bash
# Run schema validation tests (Fase 1). Requires python3 + jsonschema + pytest
# (installed per-user: pip3 install --user --break-system-packages jsonschema pytest).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pytest backend/tests/test_schemas.py -v