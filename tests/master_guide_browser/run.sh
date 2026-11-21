#!/usr/bin/env bash
set -euo pipefail
: "${PRODUCT_REPO:?set candidate checkout}" "${ARTIFACTS:?}" "${PLAYWRIGHT_MODULE:?}"
base=0335f92f5c4e8537428faeb36d3a8d7f092890b9
expected=4a030592cb91a9d8232f0cec9ceeda0cd66f0269881e02b732b3cf313c6f0c94
repo=$(cd "$PRODUCT_REPO" && pwd)
actual=$(git -C "$repo" diff --full-index --binary "$base" -- . ':(exclude)tests/master_guide_browser/**' ':(exclude).github/workflows/master-guide-browser.yml' | sha256sum | cut -d' ' -f1)
[[ "$actual" = "$expected" ]] || { echo "Candidate manifest mismatch: $actual" >&2; exit 2; }
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
mkdir -p "$work"/{home,tmp,html} "$ARTIFACTS"
out=$(cd "$ARTIFACTS" && pwd)
printf 'Base: %s\nCheckout HEAD: %s\nCandidate diff: %s\n' "$base" "$(git -C "$repo" rev-parse HEAD)" "$actual" >"$out/source.txt"
env -i PATH="$PATH" HOME="$work/home" LANG=C.UTF-8 TMPDIR="$work/tmp" DKSS_VALIDATION_TMP="$work/tmp" DKSS_BROWSER_ACCEPTANCE_ISOLATED=1 PYTHONPATH="$repo/tests/history_presentation_browser/guard" PRODUCT_REPO="$repo" HTML_OUT="$work/html" "${PYTHON_EXE:-python}" "$here/render_fixture.py" >"$out/fixture.log" 2>&1
cp "$work/html/routes.json" "$out/routes.json"
browsers=${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}
env -i PATH="$PATH" HOME="$work/home" LANG=C.UTF-8 PRODUCT_REPO="$repo" HTML_OUT="$work/html" ARTIFACTS="$out" PLAYWRIGHT_MODULE="$PLAYWRIGHT_MODULE" PLAYWRIGHT_BROWSERS_PATH="$browsers" CHROMIUM_EXECUTABLE="${CHROMIUM_EXECUTABLE:-}" node "$here/browser.cjs" >"$out/browser.log" 2>&1
