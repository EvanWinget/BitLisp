"""The BIP 340 module against the official vectors, byte-for-byte."""

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from bitlisp.secp256k1 import G, N, P, lift_x, point_mul, verify  # noqa: E402

VECTORS_CSV = REPO_ROOT / "vectors" / "upstream" / "bip340" / "test-vectors.csv"


def bip340_cases():
    with open(VECTORS_CSV, newline="") as fh:
        return [
            pytest.param(
                bytes.fromhex(row["public key"]),
                bytes.fromhex(row["message"]),
                bytes.fromhex(row["signature"]),
                row["verification result"] == "TRUE",
                id=f"bip340_{row['index']}_{row['comment'] or 'valid'}",
            )
            for row in csv.DictReader(fh)
        ]


@pytest.mark.parametrize("pubkey,msg,sig,expected", bip340_cases())
def test_official_vectors(pubkey, msg, sig, expected):
    assert verify(pubkey, msg, sig) is expected


# Vector 0 of the official file: a known-good triple for local edits.
PK0 = bytes.fromhex("F9308A019258C31049344F85F89D5229B531C845836F99B08601F113BCE036F9")
MSG0 = bytes(32)
SIG0 = bytes.fromhex(
    "E907831F80848D1069A5371B402410364BDF1C5F8307B0084C55F1CE2DCA8215"
    "25F66A4A85EA8B71E482A74F382D2CE5EBEEE8FDB2172F477DF4900D310536C0"
)


def flip_byte(data, index):
    corrupted = bytearray(data)
    corrupted[index] ^= 0x01
    return bytes(corrupted)


def test_valid_triple_accepts():
    assert verify(PK0, MSG0, SIG0) is True


def test_single_byte_corruption_rejects():
    # One corrupted byte in each region of the triple: the r half of
    # the signature, the s half, the pubkey, and the message.
    assert verify(PK0, MSG0, flip_byte(SIG0, 0)) is False
    assert verify(PK0, MSG0, flip_byte(SIG0, 63)) is False
    assert verify(flip_byte(PK0, 0), MSG0, SIG0) is False
    assert verify(PK0, flip_byte(MSG0, 31), SIG0) is False


def test_widths_are_the_callers_contract():
    with pytest.raises(ValueError):
        verify(PK0[:31], MSG0, SIG0)
    with pytest.raises(ValueError):
        verify(PK0, MSG0, SIG0[:63])
    # The message width is deliberately unconstrained here: the
    # operator layer owns BitLisp's exactly-32-bytes rule.
    assert verify(PK0, b"", SIG0) is False


def test_lift_x_rejects_non_canonical_and_off_curve():
    # The field prime is not a canonical x coordinate.
    assert lift_x(P) is None
    # x = 5 has no curve point (5^3 + 7 is not a quadratic residue).
    assert lift_x(5) is None
    # The generator's x lifts back to the generator, whose y is even.
    assert lift_x(G[0]) == G


def test_group_order():
    # n * G is the point at infinity, the defining property of the
    # group order, and (n - 1) * G is the generator's negation.
    assert point_mul(N, G) is None
    assert point_mul(N - 1, G) == (G[0], P - G[1])
