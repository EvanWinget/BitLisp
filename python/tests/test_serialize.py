"""Serialization properties, checked against the oracle byte-for-byte."""

import io
import sys
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

# The oracle wheels are the `oracles` extra, not `dev`: skip cleanly
# instead of failing collection when only `dev` is installed.
clvm = pytest.importorskip("clvm")
from clvm import SExp  # noqa: E402
from clvm.serialize import sexp_to_stream  # noqa: E402

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


# The hypothesis strategy tops out in the 0xc0 form. The upper length
# forms are covered here deterministically: each length is the floor
# of its form (the smallest length the form may canonically encode),
# checked byte-for-byte against the oracle and round-tripped. The
# 0xf8 floor (128 MiB) is exercised for header canonicality by the
# rejection vectors instead of materializing the atom.
@pytest.mark.parametrize(
    ("length", "prefix"),
    [(0x40, 0xC0), (0x2000, 0xE0), (0x100000, 0xF0)],
)
def test_length_form_floors_roundtrip_and_match_oracle(length, prefix):
    atom = b"\xaa" * length
    encoded = serialize(atom)
    assert encoded[0] & prefix == prefix
    assert deserialize(encoded) == atom
    buf = io.BytesIO()
    sexp_to_stream(SExp.to(atom), buf)
    assert encoded == buf.getvalue()


@pytest.mark.parametrize("bad_input", [bytearray(b"\x80"), memoryview(b"\x80")])
def test_non_bytes_input_rejected(bad_input):
    with pytest.raises(BitLispError) as excinfo:
        deserialize(bad_input)
    assert excinfo.value.code == "bad_encoding"
