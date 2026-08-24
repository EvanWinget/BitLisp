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

# vectors/upstream/ and tools/oracle/bitcoincore/ hold third-party
# material stored verbatim and are exempt from every text check.
THIRD_PARTY_PATHSPECS=(':!vectors/upstream/*' ':!tools/oracle/bitcoincore/*')
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
    fail "ruff format (run: git ls-files '*.py' ':!vectors/upstream/*' ':!tools/oracle/bitcoincore/*' | xargs ruff format)"
fi

# The vendored Bitcoin Core files must stay byte-identical to the
# snapshot their README records, so a formatter or editor pass over
# the tree cannot silently break the verbatim guarantee. Two loud
# failures replace silent ones: an empty checksum list means the
# README table no longer parses, and the tracked file set must be
# exactly the checksummed rows plus the ours-not-upstream list, so
# a file added, removed, or renamed without a README row fails.
# Files on the ours list are written by this project, change
# through ordinary review, and carry no checksum row.
echo "== oracle provenance =="
ORACLE_DIR=tools/oracle/bitcoincore
ORACLE_ROW_RE='^\| `test_framework/[^`]+` \| `[^`]+` \| `[0-9a-f]{64}` \|$'
ORACLE_OURS="COPYING README.md test_framework/__init__.py test_framework/crypto/__init__.py test_framework/util.py"
CHECKSUMS=$(grep -E "$ORACLE_ROW_RE" "$ORACLE_DIR/README.md" |
    while IFS='|' read -r _ file _ sha _; do
        echo "${sha//[\` ]/}  $ORACLE_DIR/${file//[\` ]/}"
    done)
if [ -z "$CHECKSUMS" ]; then
    fail "oracle provenance: no checksum rows parsed from $ORACLE_DIR/README.md, the table was reshaped"
else
    if ! echo "$CHECKSUMS" | shasum -a 256 --check --quiet; then
        fail "oracle provenance: the files listed above differ from the sha256 their README records"
    fi
    EXPECTED=$( { echo "$CHECKSUMS" | awk '{print $2}'
        for f in $ORACLE_OURS; do echo "$ORACLE_DIR/$f"; done; } | sort)
    if ! git ls-files "$ORACLE_DIR" | sort | diff - <(echo "$EXPECTED") >&2; then
        fail "oracle provenance: tracked files under $ORACLE_DIR do not match the README checksum rows plus the ours-not-upstream list (mismatch above: < tracked, > expected)"
    fi
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
