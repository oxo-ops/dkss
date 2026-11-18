#!/usr/bin/env bash
set -euo pipefail
: "${GITHUB_SHA:?required}" "${PLAYWRIGHT_MODULE:?required}" "${ARTIFACTS:?required}"
[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]]
[[ -z "$(git status --porcelain)" ]]
PY=$(command -v python); NODE=$(command -v node)
mkdir -p "$ARTIFACTS"
printf '%s\n' "$GITHUB_SHA" > "$ARTIFACTS/head.txt"
env -i PATH="$PATH" HOME="$HOME" "$PY" tests/dashboard_mobile_priority/render_fixture.py --repo "$PWD" --out "$ARTIFACTS/fixture"
env -i PATH="$PATH" HOME="$HOME" PLAYWRIGHT_MODULE="$PLAYWRIGHT_MODULE" "$NODE" tests/dashboard_mobile_priority/browser.cjs "$ARTIFACTS/fixture" "$ARTIFACTS/results"
