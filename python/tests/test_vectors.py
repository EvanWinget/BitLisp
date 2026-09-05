"""Runs the full vector corpus through the runner as a pytest gate.

This is the same check tools/run_vectors.py performs standalone. It
exists as a test so `pytest` alone is a complete local gate.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import run_vectors  # noqa: E402


def test_vector_corpus_passes():
    assert run_vectors.main() == 0


def test_a_verdict_outranks_an_earlier_escape():
    # A case that raises outside the error taxonomy does not end the
    # file: a later case's verdict is the file's verdict. Only a file
    # with no verdict at all reports the escape.
    def judge(case):
        if case["name"] == "escapes":
            raise IndexError("list index out of range")
        raise run_vectors.VectorError("expected valid, got an error")

    run_suite = run_vectors._make_suite_runner(judge)
    with pytest.raises(run_vectors.VectorError, match="judged") as caught:
        run_suite({"cases": [{"name": "escapes"}, {"name": "judged"}]}, "f.json")
    assert not isinstance(caught.value, run_vectors.MalformedCase)
    with pytest.raises(run_vectors.MalformedCase, match="escapes") as caught:
        run_suite({"cases": [{"name": "escapes"}]}, "f.json")
    assert isinstance(caught.value.__cause__, IndexError)
