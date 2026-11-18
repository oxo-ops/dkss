#!/usr/bin/env bash
set -euo pipefail
: "${GITHUB_SHA:?required}" "${PLAYWRIGHT_MODULE:?required}" "${ARTIFACTS:?required}"
[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]]
[[ -z "$(git status --porcelain)" ]]
PY=$(command -v python); NODE=$(command -v node)
mkdir -p "$ARTIFACTS"
env -i PATH="$PATH" HOME="$HOME" PYTHONPATH="$PWD" "$PY" -m unittest discover -s tests -p test_dashboard_office_actions.py -v
printf '%s\n' "$GITHUB_SHA" > "$ARTIFACTS/head.txt"
env -i PATH="$PATH" HOME="$HOME" "$PY" tests/dashboard_mobile_priority/render_fixture.py --repo "$PWD" --out "$ARTIFACTS/fixture"
env -i PATH="$PATH" HOME="$HOME" PLAYWRIGHT_MODULE="$PLAYWRIGHT_MODULE" "$NODE" tests/dashboard_mobile_priority/browser.cjs "$ARTIFACTS/fixture" "$ARTIFACTS/results"
TEST_TMP=$(mktemp -d)
trap 'rm -rf "$TEST_TMP"' EXIT
mkdir -p "$ARTIFACTS/full-html" "$ARTIFACTS/full-results"
env -i PATH="$PATH" HOME="$TEST_TMP" TMPDIR="$TEST_TMP" AWS_EC2_METADATA_DISABLED=true PRODUCT_REPO="$PWD" HTML_OUT="$ARTIFACTS/full-html" "$PY" tests/dashboard_mobile_priority/render_full.py
env -i PATH="$PATH" HOME="$TEST_TMP" TMPDIR="$TEST_TMP" PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright" PRODUCT_REPO="$PWD" HTML_OUT="$ARTIFACTS/full-html" ARTIFACTS="$ARTIFACTS/full-results" PLAYWRIGHT_MODULE="$PLAYWRIGHT_MODULE" "$NODE" tests/dashboard_mobile_priority/full_browser.cjs
