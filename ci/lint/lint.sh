#!/usr/bin/env bash
# Repository lint driver. Run from anywhere inside the repo:
#
#   ci/lint/lint.sh
#
# Needs codespell and ruff on PATH at the versions pinned in
# ci/lint/requirements.txt. A venv created with
# `pip install -r ci/lint/requirements.txt` provides both.
set -o errexit -o nounset -o pipefail

cd "$(git rev-parse --show-toplevel)"

FAILED=0
fail() {
    echo "FAIL: $1" >&2
    FAILED=1
}

# vectors/upstream/ holds third-party material stored verbatim and is
# exempt from every text check.
THIRD_PARTY_PATHSPECS=(':!vectors/upstream/*')
TEXT_PATHSPECS=('*.md' '*.py' '*.sh' '*.yml' '*.yaml' '*.toml' '*.txt' "${THIRD_PARTY_PATHSPECS[@]}")

echo "== codespell =="
if ! git ls-files "${TEXT_PATHSPECS[@]}" |
    xargs codespell --ignore-words=ci/lint/codespell-ignore-words.txt; then
    fail "codespell (typos listed above, false positives go in ci/lint/codespell-ignore-words.txt)"
fi

echo "== ruff =="
if ! git ls-files '*.py' "${THIRD_PARTY_PATHSPECS[@]}" | xargs ruff check --quiet; then
    fail "ruff"
fi

echo "== ruff format =="
if ! git ls-files '*.py' "${THIRD_PARTY_PATHSPECS[@]}" | xargs ruff format --check --quiet; then
    fail "ruff format (run: git ls-files '*.py' | xargs ruff format)"
fi

echo "== whitespace =="
if git grep -In $'[ \t]$' -- "${TEXT_PATHSPECS[@]}"; then
    fail "trailing whitespace on the lines listed above"
fi
if git grep -In $'\t' -- "${TEXT_PATHSPECS[@]}"; then
    fail "tab characters on the lines listed above (indent with spaces)"
fi

echo "== prose style =="
if ! python3 ci/lint/lint_prose.py; then
    fail "prose style"
fi

if [ "$FAILED" -ne 0 ]; then
    echo "lint: at least one check failed" >&2
    exit 1
fi
echo "lint: all checks passed"
