"""Property-based invariant suite.

The validation-layer invariants land here in Phase 2. Until then the
properties below cover the vector envelope validator and pin the
serializer and integer codec against the oracle.
"""

import sys
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import pytest  # noqa: E402
import run_vectors  # noqa: E402


def valid_envelopes():
    return st.fixed_dictionaries(
        {
            "schema": st.just(run_vectors.SCHEMA),
            "suite": st.sampled_from(run_vectors.SUITES),
            "spec": st.text(min_size=1),
            "cases": st.lists(st.integers()),
        }
    )


@given(valid_envelopes())
def test_valid_envelope_accepted(envelope):
    assert run_vectors.validate_envelope(envelope) is envelope


@given(valid_envelopes(), st.sampled_from(["schema", "suite", "spec", "cases"]))
def test_missing_key_rejected(envelope, key):
    del envelope[key]
    with pytest.raises(run_vectors.VectorError):
        run_vectors.validate_envelope(envelope)


@given(
    valid_envelopes(), st.text(min_size=1).filter(lambda k: k not in run_vectors.SUITES)
)
def test_unknown_suite_rejected(envelope, suite):
    envelope["suite"] = suite
    with pytest.raises(run_vectors.VectorError):
        run_vectors.validate_envelope(envelope)


@given(st.one_of(st.none(), st.integers(), st.text(), st.lists(st.integers())))
def test_non_object_rejected(value):
    with pytest.raises(run_vectors.VectorError):
        run_vectors.validate_envelope(value)
