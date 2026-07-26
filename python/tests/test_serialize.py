"""Serialization properties, checked against the oracle byte-for-byte."""

import io
import sys
from pathlib import Path

import pytest
from clvm import SExp
from clvm.serialize import sexp_to_stream
from hypothesis import given
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from bitlisp import (  # noqa: E402
    BitLispError,
    atom_to_int,
    deserialize,
    int_to_atom,
    serialize,
)

# Atom sizes cross all three of: the one-byte form, the one-byte
# length prefix, and the two-byte length prefix.
atoms = st.binary(max_size=300)
nodes = st.recursive(atoms, lambda children: st.tuples(children, children))


def to_clvm(node):
    if isinstance(node, bytes):
        return SExp.to(node)
    return SExp.to((to_clvm(node[0]), to_clvm(node[1])))


@given(nodes)
def test_roundtrip_identity(node):
    assert deserialize(serialize(node)) == node


@given(nodes)
def test_serializer_matches_oracle(node):
    buf = io.BytesIO()
    sexp_to_stream(to_clvm(node), buf)
    assert serialize(node) == buf.getvalue()


@given(nodes)
def test_trailing_byte_rejected(node):
    with pytest.raises(BitLispError) as excinfo:
        deserialize(serialize(node) + b"\x80")
    assert excinfo.value.code == "bad_encoding"


@given(nodes)
def test_truncation_rejected(node):
    data = serialize(node)
    with pytest.raises(BitLispError) as excinfo:
        deserialize(data[:-1])
    assert excinfo.value.code == "bad_encoding"


@given(st.integers(min_value=-(2**256), max_value=2**256))
def test_int_codec_matches_oracle(value):
    assert int_to_atom(value) == SExp.to(value).atom
    assert atom_to_int(int_to_atom(value)) == value


def test_int_codec_negative_power_boundaries():
    assert int_to_atom(-128) == b"\x80"
    assert int_to_atom(-32768) == b"\x80\x00"
    assert int_to_atom(128) == b"\x00\x80"
    assert int_to_atom(0) == b""
