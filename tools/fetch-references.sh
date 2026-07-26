#!/usr/bin/env bash
# Clones upstream reference repos into git-ignored references/ for
# HUMAN BROWSING ONLY.
#
# Policy (CLAUDE.md): references/ is opened only in divergence-triage
# sessions, never implementation sessions. Code is never copied from
# it. Oracles used by tests are the released wheels pinned in
# pyproject.toml, not these checkouts.
set -o errexit -o nounset -o pipefail

cd "$(git rev-parse --show-toplevel)"
mkdir -p references

clone() {
    local url="$1" dir="$2"
    if [ -d "references/${dir}/.git" ]; then
        echo "references/${dir}: already cloned, leaving as is"
    else
        git clone --depth=50 "${url}" "references/${dir}"
    fi
}

clone https://github.com/Chia-Network/clvm.git clvm
clone https://github.com/Chia-Network/clvm_rs.git clvm_rs
clone https://github.com/Chia-Network/chia_rs.git chia_rs

echo
echo "Done. These checkouts are git-ignored and are not a build input."
