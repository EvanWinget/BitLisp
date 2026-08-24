"""Property-based invariants for validation rule 4, duplicates and
multiplicity.

The invariant under test: duplicating any assert, ANNOUNCE, or
reserved condition within its input's condition list never changes
the outcome. Valid stays valid, invalid stays invalid with the same
error, because an assert reads facts and consumes nothing,
announcement facts within one input are a set, and a reserved
condition constrains nothing. The within-list scope is the spec's:
copying a condition to a different input is not duplication, since
the copy reads its own input's fields and creates its own facts,
and vectors/validation/duplicates.json pins the cross-input
counterexamples. The counted sorts, claims and message records, are
deliberately outside this property: their duplication behavior is
pinned by the rule 1 and rule 3 suites.

The generator mixes every landed condition kind over two BitLisp
inputs with dense content collisions, so both outcomes and every
error path of the landed rules appear, and the property duplicates
each idempotent occurrence in place and revalidates.
"""

from bitlisp import (
    Announce,
    AssertAnnouncement,
    AssertLocktimeHeight,
    AssertLocktimeTime,
    AssertSequenceHeight,
    AssertSequenceTime,
    Assure,
    BitLispError,
    CreateOutput,
    Require,
    Reserved,
    Specifier,
    Transaction,
    TxInput,
    TxOutput,
    validate_transaction,
)
from bitlisp.conditions import (
    AssertMyAmount,
    AssertMyOutpoint,
    AssertMyScriptPubKey,
    AssertMyTaproot,
    AssertMyTaptree,
    AssertMyTxid,
)
from bitlisp.secp256k1 import taproot_output_key
from hypothesis import given
from hypothesis import strategies as st
from support import (
    FILLER_INTERNAL_KEY,
    FILLER_MERKLE_ROOT,
    FILLER_TAPLEAF,
    filler_identity,
)

IDEMPOTENT = (
    AssertLocktimeHeight,
    AssertLocktimeTime,
    AssertSequenceHeight,
    AssertSequenceTime,
    AssertMyOutpoint,
    AssertMyTxid,
    AssertMyScriptPubKey,
    AssertMyAmount,
    AssertMyTaproot,
    AssertMyTaptree,
    Announce,
    AssertAnnouncement,
    Reserved,
)

TXID_A = b"\xaa" * 32
TXID_B = b"\xbb" * 32
SCRIPT_A = b"\x51"
SCRIPT_B = b"\x52"
CONTENTS = ((SCRIPT_A, 1), (SCRIPT_B, 1), (SCRIPT_A, 2))


def _outpoint(txid):
    return txid + (0).to_bytes(4, "little")


_TAPROOT_IK = bytes.fromhex(
    "187791b6f712a8ea41c8ecdd0ee77fab3e85263b37e1ec18a3651926b3a6cf27"
)
_TAPROOT_SPK = b"\x51\x20" + taproot_output_key(_TAPROOT_IK, b"")


def _pool(own_txid, own_script, other_txid, other_script):
    """Condition candidates for one input. Announcer specifiers,
    requirer specifiers, and payloads collide across the pools of
    both inputs, so generated transactions land on both sides of
    every landed rule, and the never-announced payload keeps the
    announcement error path exercised. The self asserts pair each
    input's own values with the other input's, so satisfied and
    failing asserts are both dense, the taproot assert always
    fails here (neither input script is a taproot script), keeping
    a failing assert's idempotence exercised, and the taptree
    asserts pair the identity build_tx installs with a wrong
    root."""
    return (
        CreateOutput(SCRIPT_A, 1),
        CreateOutput(SCRIPT_B, 1),
        AssertMyOutpoint(_outpoint(own_txid)),
        AssertMyOutpoint(_outpoint(other_txid)),
        AssertMyTxid(own_txid),
        AssertMyTxid(other_txid),
        AssertMyScriptPubKey(own_script),
        AssertMyScriptPubKey(other_script),
        AssertMyAmount(0),
        AssertMyAmount(1),
        AssertMyTaproot(_TAPROOT_IK, b"", _TAPROOT_SPK),
        AssertMyTaptree(FILLER_INTERNAL_KEY, FILLER_MERKLE_ROOT),
        AssertMyTaptree(FILLER_INTERNAL_KEY, FILLER_TAPLEAF),
        AssertLocktimeHeight(600),
        AssertLocktimeHeight(700),
        AssertLocktimeTime(500_000_600),
        AssertSequenceHeight(100),
        AssertSequenceTime(2),
        Announce(b"ns", b"fact"),
        Announce(b"", b"x"),
        AssertAnnouncement(Specifier(2, (SCRIPT_A,)), b"ns", b"fact"),
        AssertAnnouncement(Specifier(2, (other_script,)), b"", b"x"),
        AssertAnnouncement(Specifier(0, ()), b"ns", b"fact"),
        AssertAnnouncement(Specifier(0, ()), b"ns", b"never-announced"),
        Reserved(0x80, 500, ()),
        Reserved(0xFF, 12345, ()),
        Assure(7, Specifier(7, (_outpoint(other_txid),)), b"hi"),
        Require(Specifier(7, (_outpoint(other_txid),)), 7, b"hi"),
        Assure(0, Specifier(0, ()), b"hi"),
        Require(Specifier(0, ()), 0, b"hi"),
    )


POOL_A = _pool(TXID_A, SCRIPT_A, TXID_B, SCRIPT_B)
POOL_B = _pool(TXID_B, SCRIPT_B, TXID_A, SCRIPT_A)

conds_a = st.lists(st.sampled_from(POOL_A), max_size=4)
conds_b = st.lists(st.sampled_from(POOL_B), max_size=4)
outputs = st.lists(st.sampled_from(CONTENTS), min_size=1, max_size=4)
versions = st.sampled_from((1, 2))
locktimes = st.sampled_from((0, 600, 700, 500_000_600))
sequences = st.sampled_from((0xFFFFFFFF, 0xFFFFFFFE, 144, (1 << 22) | 2, 1 << 31))


def build_tx(version, locktime, cond_lists, seq_pair, output_contents):
    """A two-BitLisp-input transaction, the first input funding all
    outputs."""
    out_total = sum(amount for _, amount in output_contents)
    inputs = tuple(
        TxInput(
            txid=txid,
            index=0,
            script_pubkey=script,
            amount=out_total if txid == TXID_A else 0,
            sequence=sequence,
            conditions=tuple(conditions),
            **filler_identity(),
        )
        for txid, script, sequence, conditions in (
            (TXID_A, SCRIPT_A, seq_pair[0], cond_lists[0]),
            (TXID_B, SCRIPT_B, seq_pair[1], cond_lists[1]),
        )
    )
    return Transaction(
        version=version,
        locktime=locktime,
        inputs=inputs,
        outputs=tuple(TxOutput(script, amount) for script, amount in output_contents),
    )


def outcome(tx):
    try:
        validate_transaction(tx)
        return None
    except BitLispError as exc:
        return exc.code


@given(
    versions,
    locktimes,
    conds_a,
    conds_b,
    sequences,
    sequences,
    outputs,
    st.sampled_from((1, 2)),
)
def test_duplicating_idempotent_conditions_never_changes_outcome(
    version, locktime, list_a, list_b, seq_a, seq_b, output_contents, copies
):
    base = outcome(
        build_tx(version, locktime, (list_a, list_b), (seq_a, seq_b), output_contents)
    )
    for which, conditions in ((0, list_a), (1, list_b)):
        for position, condition in enumerate(conditions):
            if not isinstance(condition, IDEMPOTENT):
                continue
            duplicated = (
                conditions[: position + 1]
                + [condition] * copies
                + conditions[position + 1 :]
            )
            cond_lists = (duplicated, list_b) if which == 0 else (list_a, duplicated)
            assert (
                outcome(
                    build_tx(
                        version, locktime, cond_lists, (seq_a, seq_b), output_contents
                    )
                )
                == base
            )
