"""Runs the full vector corpus through the runner as a pytest gate.

This is the same check tools/run_vectors.py performs standalone. It
exists as a test so `pytest` alone is a complete local gate.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import run_vectors  # noqa: E402


def test_vector_corpus_passes():
    assert run_vectors.main() == 0
