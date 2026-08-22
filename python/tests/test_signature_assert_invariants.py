"""Property-based invariants for the signature assert family.

Each signature assert verifies a self-contained (pubkey, digest,
signature) triple, with the digest built from the carrying input's
own prevout data and the condition's message. The defining
properties mirror the self asserts: environment independence, and
the outcome depending on exactly the bytes the digest commits to.
Signatures are produced by the vendored Bitcoin Core framework
signer, never by bitlisp code, and digests are recomputed here from
the spec's construction so the tests pin the spec rather than the
implementation's own digest helper.
"""

import hashlib
import sys
from functools import cache
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "oracle" / "bitcoincore"))

from bitlisp import (  # noqa: E402
    BitLispError,
    Transaction,
    TxInput,
    TxOutput,
    validate_transaction,
)
from bitlisp.conditions import SIG_BINDINGS, AssertSig  # noqa: E402
from test_framework.key import compute_xonly_pubkey, sign_schnorr  # noqa: E402

SK = (0xC0FFEE00 << 224 | 1).to_bytes(32, "big")
PK = compute_xonly_pubkey(SK)[0]
AUX = b"\x00" * 32
MSG = b"invariant message"

COIN_A = (b"\xaa" * 32, 7, b"\x51\x20" + b"\x22" * 32, 50_000)
COIN_B = (b"\xbb" * 32, 0x01000000, b"\x00\x20" + b"\x22" * 32, 50_000 + 2**32)
COINS = (COIN_A, COIN_B)


# The spec's variant table, restated as a literal so the tags and
# field selections are pinned here independently of the
# implementation. test_spec_table_matches_implementation fails if
# the two tables ever drift.
SPEC_TABLE = {
    0x10: ("BitLisp/sig/my_txid", ("txid",)),
    0x11: ("BitLisp/sig/my_scriptpubkey", ("spk_hash",)),
    0x12: ("BitLisp/sig/my_amount", ("amount8",)),
    0x13: ("BitLisp/sig/my_scriptpubkey_amount", ("spk_hash", "amount8")),
    0x14: ("BitLisp/sig/my_txid_amount", ("txid", "amount8")),
    0x15: ("BitLisp/sig/my_txid_scriptpubkey", ("txid", "spk_hash")),
    0x16: ("BitLisp/sig/raw", ()),
    0x17: ("BitLisp/sig/my_outpoint", ("outpoint",)),
}


def test_spec_table_matches_implementation():
    assert SPEC_TABLE == {
        opcode: (tag, fields) for opcode, (_, tag, fields) in SIG_BINDINGS.items()
    }


def spec_digest(opcode, message, coin):
    """The digest from the spec's construction: tagged hash of the
    binding fields then the message, fields read from the coin and
    the SPEC_TABLE literal, never from the implementation."""
    txid, index, script, amount = coin
    tag, fields = SPEC_TABLE[opcode]
    tag_hash = hashlib.sha256(tag.encode("ascii")).digest()
    data = tag_hash + tag_hash
    for kind in fields:
        if kind == "txid":
            data += txid
        elif kind == "spk_hash":
            data += hashlib.sha256(script).digest()
        elif kind == "amount8":
            data += amount.to_bytes(8, "little")
        else:
            data += txid + index.to_bytes(4, "little")
    return hashlib.sha256(data + message).digest()


# Sixteen distinct signatures exist across the whole suite (eight
# opcodes, two coins, one message). Pure-Python signing is the slow
# step, so each is computed once.
@cache
def signed_condition(opcode, coin, message=MSG):
    return AssertSig(
        opcode, PK, message, sign_schnorr(SK, spec_digest(opcode, message, coin), AUX)
    )


# Pure-Python verification dominates each example, so the example
# counts stay small. The mutation surface is small and discrete
# (eight opcodes, two coins, three operand fields), so modest counts
# still cover it densely.
EXAMPLES = settings(max_examples=25, deadline=None)


opcodes = st.sampled_from(sorted(SIG_BINDINGS))
coins = st.sampled_from(COINS)

# conditions signed for either coin, so satisfied and unsatisfied
# asserts are both dense on every carrying input
sig_conds = st.tuples(opcodes, coins).map(lambda t: signed_condition(*t))
cond_lists = st.lists(sig_conds, max_size=3)

environments = st.tuples(
    st.sampled_from((0, 2, 0xFFFFFFFF)),
    st.sampled_from((0, 500_000_600)),
    st.sampled_from((0xFFFFFFFF, 144)),
    st.sampled_from(("none", "after", "before")),
)


def build_tx(coin, conds, env):
    """One BitLisp input carrying only signature asserts, an
    unclaimed zero output, and an environment the family must never
    read."""
    txid, index, script, amount = coin
    version, locktime, sequence, extra_position = env
    inputs = [
        TxInput(
            txid=txid,
            index=index,
            script_pubkey=script,
            amount=amount,
            sequence=sequence,
            conditions=tuple(conds),
            tapleaf=b"\x0a" * 32,
            merkle_root=b"\x0b" * 32,
            internal_key=b"\x0c" * 32,
        )
    ]
    if extra_position != "none":
        extra = TxInput(
            txid=b"\xcc" * 32,
            index=0,
            script_pubkey=b"\x52",
            amount=7,
            sequence=0xFFFFFFFF,
            conditions=None,
        )
        if extra_position == "before":
            inputs.insert(0, extra)
        else:
            inputs.append(extra)
    return Transaction(version, locktime, tuple(inputs), (TxOutput(b"\x51", 0),))


def outcome(tx):
    try:
        validate_transaction(tx)
        return None
    except BitLispError as exc:
        return exc.code


@EXAMPLES
@given(coins, cond_lists, environments, environments)
def test_outcome_is_environment_independent(coin, conds, env_a, env_b):
    """The family outcome depends only on the conditions and the
    carrying input's own prevout data. Version, locktime, sequence,
    and unrelated inputs never change it."""
    assert outcome(build_tx(coin, conds, env_a)) == outcome(
        build_tx(coin, conds, env_b)
    )


@EXAMPLES
@given(opcodes, coins, coins, environments)
def test_single_triple_outcome_matches_binding(opcode, signed_for, carried_by, env):
    """A lone triple signed for one coin is satisfied exactly when
    the carrying input's digest fields match that coin's. RAW binds
    nothing, so it is satisfied on every carrier."""
    cond = signed_condition(opcode, signed_for)
    satisfied = spec_digest(opcode, MSG, signed_for) == spec_digest(
        opcode, MSG, carried_by
    )
    got = outcome(build_tx(carried_by, [cond], env))
    assert got == (None if satisfied else "unsatisfied_sig_assert")


@EXAMPLES
@given(
    opcodes,
    coins,
    st.sampled_from(("pubkey", "message", "signature")),
    st.data(),
    environments,
)
def test_operand_byte_flip_rejects(opcode, coin, field, data, env):
    """Metamorphic: flipping any byte of a satisfied triple's
    pubkey, message, or signature causes rejection."""
    cond = signed_condition(opcode, coin)
    assert outcome(build_tx(coin, [cond], env)) is None
    value = getattr(cond, field)
    index = data.draw(st.integers(0, len(value) - 1))
    flipped = value[:index] + bytes([value[index] ^ 0x01]) + value[index + 1 :]
    mutated = AssertSig(
        opcode,
        flipped if field == "pubkey" else cond.pubkey,
        flipped if field == "message" else cond.message,
        flipped if field == "signature" else cond.signature,
    )
    assert outcome(build_tx(coin, [mutated], env)) == "unsatisfied_sig_assert"


@EXAMPLES
@given(opcodes, opcodes, coins, environments)
def test_variant_separation(opcode_signed, opcode_emitted, coin, env):
    """A satisfied triple re-emitted at any other family opcode is
    rejected: the per-variant tags never share a digest."""
    cond = signed_condition(opcode_signed, coin)
    moved = AssertSig(opcode_emitted, cond.pubkey, cond.message, cond.signature)
    got = outcome(build_tx(coin, [moved], env))
    assert got == (
        None if opcode_emitted == opcode_signed else "unsatisfied_sig_assert"
    )


@EXAMPLES
@given(coins, cond_lists, st.integers(0, 2), environments)
def test_in_place_duplication_never_changes_outcome(coin, conds, position, env):
    """Rule 4: duplicating any signature assert within its input's
    condition list changes nothing, valid stays valid and invalid
    stays invalid."""
    if not conds:
        return
    duplicated = list(conds)
    duplicated.insert(0, conds[position % len(conds)])
    assert outcome(build_tx(coin, conds, env)) == outcome(
        build_tx(coin, duplicated, env)
    )
