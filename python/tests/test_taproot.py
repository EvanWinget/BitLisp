"""The taproot output-key derivation against the official BIP 341
wallet vectors and a differential against Bitcoin Core's
test-framework primitives, plus the rejection branches no real
input can reach.

The two value rejections in the tweak application (a scalar at or
above the group order, a tweaked point at infinity) require
hash-preimage control to trigger through the public derivation, so
they are pinned here with contrived scalars through the application
step directly. This is the recorded exception to the
every-error-path-is-a-vector rule.
"""

import json
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "oracle" / "bitcoincore"))

from bitlisp.secp256k1 import (  # noqa: E402
    G,
    N,
    _tap_tweak_scalar,
    _tweaked_point,
    lift_x,
    point_mul,
    taproot_output_key,
)
from test_framework.key import TaggedHash, tweak_add_pubkey  # noqa: E402

VECTORS_JSON = (
    REPO_ROOT / "vectors" / "upstream" / "bip341" / "wallet-test-vectors.json"
)


def bip341_cases():
    with open(VECTORS_JSON) as fh:
        entries = json.load(fh)["scriptPubKey"]
    cases = []
    for n, entry in enumerate(entries):
        root_hex = entry["intermediary"]["merkleRoot"]
        cases.append(
            pytest.param(
                bytes.fromhex(entry["given"]["internalPubkey"]),
                b"" if root_hex is None else bytes.fromhex(root_hex),
                entry["intermediary"]["tweak"],
                entry["intermediary"]["tweakedPubkey"],
                entry["expected"]["scriptPubKey"],
                id=f"bip341_{n}_{'keypath' if root_hex is None else 'tree'}",
            )
        )
    return cases


@pytest.mark.parametrize("key,root,tweak,outkey,spk", bip341_cases())
def test_official_tweak_scalar(key, root, tweak, outkey, spk):
    assert _tap_tweak_scalar(key, root).to_bytes(32, "big").hex() == tweak


@pytest.mark.parametrize("key,root,tweak,outkey,spk", bip341_cases())
def test_official_output_key(key, root, tweak, outkey, spk):
    assert taproot_output_key(key, root).hex() == outkey


@pytest.mark.parametrize("key,root,tweak,outkey,spk", bip341_cases())
def test_official_script_pubkey(key, root, tweak, outkey, spk):
    assert (b"\x51\x20" + taproot_output_key(key, root)).hex() == spk


# --- the branches no constructible vector reaches --------------------------


def test_tweak_scalar_at_group_order_rejected():
    assert _tweaked_point(G, N) is None


def test_tweak_scalar_below_group_order_accepted():
    # 2G + (N - 1)G = (N + 1)G = G, so the boundary scalar just below
    # the order passes and lands back on the generator.
    assert _tweaked_point(point_mul(2, G), N - 1) == G


def test_tweaked_point_at_infinity_rejected():
    # kG + (N - k)G = NG, the point at infinity.
    k = 5
    assert _tweaked_point(point_mul(k, G), N - k) is None


# --- value defects and width contracts of the public derivation ------------


def _off_curve_key():
    x = next(x for x in range(1, 200) if lift_x(x) is None)
    return x.to_bytes(32, "big")


def test_off_curve_key_returns_none():
    assert taproot_output_key(_off_curve_key(), b"") is None


def test_non_canonical_key_returns_none():
    # An x coordinate at or above the field prime never lifts.
    assert taproot_output_key(b"\xff" * 32, b"") is None


def test_width_contracts_raise():
    with pytest.raises(ValueError):
        taproot_output_key(b"\x00" * 31, b"")
    with pytest.raises(ValueError):
        taproot_output_key(b"\x00" * 33, b"")
    with pytest.raises(ValueError):
        taproot_output_key(b"\x00" * 32, b"\xaa")
    with pytest.raises(ValueError):
        taproot_output_key(b"\x00" * 32, b"\xaa" * 31)
    with pytest.raises(ValueError):
        taproot_output_key(b"\x00" * 32, b"\xaa" * 33)


# --- structural invariant over random inputs -------------------------------


@settings(max_examples=25, deadline=None)
@given(
    st.binary(min_size=32, max_size=32),
    st.one_of(st.just(b""), st.binary(min_size=32, max_size=32)),
)
def test_derivation_matches_core_framework(key, root):
    """Differential: the derivation agrees with the composition of
    Bitcoin Core's test-framework tagged hash and x-only tweak,
    including agreement on the rejected (None) inputs. Random keys
    split roughly evenly between liftable and not, so both sides of
    the lift are exercised."""
    ours = taproot_output_key(key, root)
    theirs = tweak_add_pubkey(key, TaggedHash("TapTweak", key + root))
    assert ours == (None if theirs is None else theirs[0])


@settings(max_examples=10, deadline=None)
@given(
    st.integers(min_value=1, max_value=2**16),
    st.one_of(st.just(b""), st.binary(min_size=32, max_size=32)),
)
def test_derived_key_is_always_a_valid_x_only_key(k, root):
    """Any on-curve internal key derives a 32-byte output key that is
    itself a valid x-only key, so a derived scriptPubKey is always a
    spendable-shaped taproot output."""
    internal_key = point_mul(k, G)[0].to_bytes(32, "big")
    output_key = taproot_output_key(internal_key, root)
    assert output_key is not None
    assert len(output_key) == 32
    assert lift_x(int.from_bytes(output_key, "big")) is not None
