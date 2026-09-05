"""Property-based invariants for the seal family.

Each seal compares its operand against a quantity derived from the
assembled transaction: SEAL its txid, SEAL_OUTPUTS its outputs
hash. Both derivations are recomputed here through the vendored
Bitcoin Core framework's transaction classes, never through
bitlisp's own serialization, so every operand below pins the spec's
derivation against the code Core itself trusts for wire encoding.
The behavioral invariants pin the family's defining asymmetry:
SEAL_OUTPUTS is a function of the output slots alone, SEAL of every
non-witness byte, and neither is a function of anything else.
"""

import hashlib
import sys
from dataclasses import replace
from pathlib import Path

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from support import filler_identity

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
from bitlisp.conditions import Seal, SealOutputs  # noqa: E402
from test_framework.messages import (  # noqa: E402
    COutPoint,
    CTransaction,
    CTxIn,
    CTxOut,
)

EXAMPLES = settings(max_examples=50, deadline=None)


def oracle_txid(tx):
    """The txid by the Core framework's serialization, double-SHA256
    of the transaction without witness data."""
    core = CTransaction()
    core.version = tx.version
    core.nLockTime = tx.locktime
    for tx_input in tx.inputs:
        core.vin.append(
            CTxIn(
                COutPoint(int.from_bytes(tx_input.txid, "little"), tx_input.index),
                tx_input.script_sig,
                tx_input.sequence,
            )
        )
    for output in tx.outputs:
        core.vout.append(CTxOut(output.amount, output.script_pubkey))
    serialized = core.serialize_without_witness()
    return hashlib.sha256(hashlib.sha256(serialized).digest()).digest()


def oracle_outputs_hash(tx):
    """The outputs hash by the Core framework's CTxOut serialization,
    the sha_outputs value of a taproot sighash."""
    return hashlib.sha256(
        b"".join(CTxOut(o.amount, o.script_pubkey).serialize() for o in tx.outputs)
    ).digest()


# The 253-byte entries put a two-byte compact-size length prefix in
# both derivations, the first length the one-byte encoding cannot
# carry, so the oracle cross-check exercises that branch.
SCRIPTS = (
    b"",
    b"\x51",
    b"\x00\x14" + b"\xbb" * 20,
    b"\x51\x20" + b"\x22" * 32,
    b"\x6a" + b"\xcc" * 252,
)
SCRIPT_SIGS = (b"", b"\x00", b"\x47" + b"\xdd" * 71, b"\xdd" * 253)
AMOUNTS = (0, 1, 546, 2**32)

# A truncated comparison passes every flip below its cut, so
# metamorphic flips always cover the first, a middle, and the last
# operand byte rather than one sampled position.
FLIP_POSITIONS = (0, 15, 31)

output_specs = st.tuples(st.sampled_from(SCRIPTS), st.sampled_from(AMOUNTS))
input_specs = st.tuples(
    st.binary(min_size=32, max_size=32),
    st.sampled_from(SCRIPT_SIGS),
    st.sampled_from((0, 144, 0xFFFFFFFE, 0xFFFFFFFF)),
)
versions = st.sampled_from((0, 1, 2, 0x80000002, 0xFFFFFFFF))
locktimes = st.sampled_from((0, 499_999_999, 500_000_000, 0xFFFFFFFF))
carrier_indexes = st.integers(min_value=0, max_value=2)


def build_tx(version, locktime, inputs, outputs, conds, txid_prefix=b"\x01"):
    """The first input is the BitLisp input carrying conds and funds
    every output. Input txids take a caller-chosen first byte so two
    generated transactions can be guaranteed outpoint-disjoint."""
    total_out = sum(amount for _, amount in outputs)
    built = tuple(
        TxInput(
            txid=txid_prefix + txid[1:],
            index=n,
            script_pubkey=b"\x51",
            amount=total_out if n == 0 else 0,
            sequence=sequence,
            conditions=tuple(conds) if n == 0 else None,
            script_sig=script_sig,
            **filler_identity(),
        )
        for n, (txid, script_sig, sequence) in enumerate(inputs)
    )
    return Transaction(
        version=version,
        locktime=locktime,
        inputs=built,
        outputs=tuple(TxOutput(script, amount) for script, amount in outputs),
    )


transactions = st.tuples(
    versions,
    locktimes,
    st.lists(input_specs, min_size=1, max_size=3),
    st.lists(output_specs, min_size=1, max_size=3),
)


def reseal(tx, conds, carrier=0):
    """The same transaction with the carrier input's condition list
    replaced, the carrier index taken modulo the input count so any
    input can carry the seals. Conditions are witness data, so
    neither derived quantity changes."""
    carrier %= len(tx.inputs)
    replaced = replace(tx.inputs[carrier], conditions=tuple(conds))
    inputs = tx.inputs[:carrier] + (replaced,) + tx.inputs[carrier + 1 :]
    return replace(tx, inputs=inputs)


def outcome(tx):
    try:
        validate_transaction(tx)
        return None
    except BitLispError as exc:
        return exc.code


def flip(data, position):
    return data[:position] + bytes([data[position] ^ 1]) + data[position + 1 :]


@given(transactions)
@EXAMPLES
def test_derivations_match_core_oracle(spec):
    """The model's txid and outputs hash equal the Core framework's,
    byte for byte, over every generated shape including legacy
    scriptSigs and top-bit versions."""
    tx = build_tx(*spec, conds=())
    assert tx.txid == oracle_txid(tx)
    assert tx.outputs_hash == oracle_outputs_hash(tx)


@given(transactions, carrier_indexes)
@EXAMPLES
def test_lone_seal_iff_operand_matches(spec, carrier):
    """A lone SEAL on any carrying input is satisfied exactly when
    its operand is the transaction's txid, and a flip at the first,
    a middle, or the last operand byte rejects with the family's
    error."""
    tx = build_tx(*spec, conds=())
    operand = oracle_txid(tx)
    assert outcome(reseal(tx, (Seal(operand),), carrier)) is None
    for position in FLIP_POSITIONS:
        flipped = reseal(tx, (Seal(flip(operand, position)),), carrier)
        assert outcome(flipped) == "unsatisfied_seal_assert"


@given(transactions, carrier_indexes)
@EXAMPLES
def test_lone_outputs_seal_iff_operand_matches(spec, carrier):
    tx = build_tx(*spec, conds=())
    operand = oracle_outputs_hash(tx)
    assert outcome(reseal(tx, (SealOutputs(operand),), carrier)) is None
    for position in FLIP_POSITIONS:
        flipped = reseal(tx, (SealOutputs(flip(operand, position)),), carrier)
        assert outcome(flipped) == "unsatisfied_seal_assert"


@given(transactions, transactions)
@EXAMPLES
def test_sealed_merge_always_rejects(spec_a, spec_b):
    """Concatenating a sealed transaction with any other transaction
    is rejected whichever variant sealed it: the merge appends inputs
    and outputs, so both derived quantities change."""
    tx_a = build_tx(*spec_a, conds=(), txid_prefix=b"\x01")
    tx_b = build_tx(*spec_b, conds=(), txid_prefix=b"\x02")
    for cond in (Seal(oracle_txid(tx_a)), SealOutputs(oracle_outputs_hash(tx_a))):
        sealed_a = reseal(tx_a, (cond,))
        assert outcome(sealed_a) is None
        merged = Transaction(
            version=max(tx_a.version, tx_b.version),
            locktime=max(tx_a.locktime, tx_b.locktime),
            inputs=sealed_a.inputs + tx_b.inputs,
            outputs=sealed_a.outputs + tx_b.outputs,
        )
        assert outcome(merged) == "unsatisfied_seal_assert"


@given(transactions)
@EXAMPLES
def test_seal_implies_outputs_seal(spec):
    """Whenever a SEAL is satisfied, the SEAL_OUTPUTS carrying the
    transaction's outputs hash is satisfied beside it: the txid
    commits to the outputs."""
    tx = build_tx(*spec, conds=())
    sealed = reseal(tx, (Seal(oracle_txid(tx)),))
    assert outcome(sealed) is None
    both = reseal(tx, (Seal(oracle_txid(tx)), SealOutputs(oracle_outputs_hash(tx))))
    assert outcome(both) is None


@given(transactions, input_specs, versions, locktimes)
@EXAMPLES
def test_outputs_seal_reads_outputs_alone_and_seal_reads_everything(
    spec, extra_input, new_version, new_locktime
):
    """Every input-side mutation leaves a satisfied SEAL_OUTPUTS
    satisfied and breaks a satisfied SEAL: a fresh version, a fresh
    locktime, and an appended non-BitLisp input all change the txid
    and none of them touch an output slot."""
    tx = build_tx(*spec, conds=())
    txid_operand = oracle_txid(tx)
    outputs_operand = oracle_outputs_hash(tx)
    extra_txid, extra_sig, extra_sequence = extra_input
    mutations = [
        Transaction(
            version=new_version,
            locktime=tx.locktime,
            inputs=tx.inputs,
            outputs=tx.outputs,
        ),
        Transaction(
            version=tx.version,
            locktime=new_locktime,
            inputs=tx.inputs,
            outputs=tx.outputs,
        ),
        Transaction(
            version=tx.version,
            locktime=tx.locktime,
            inputs=tx.inputs
            + (
                TxInput(
                    txid=b"\x03" + extra_txid[1:],
                    index=0xFFFF,
                    script_pubkey=b"\x51",
                    amount=0,
                    sequence=extra_sequence,
                    conditions=None,
                    script_sig=extra_sig,
                ),
            ),
            outputs=tx.outputs,
        ),
    ]
    for mutated in mutations:
        assume(mutated.txid != txid_operand)
        assert outcome(reseal(mutated, (SealOutputs(outputs_operand),))) is None
        assert (
            outcome(reseal(mutated, (Seal(txid_operand),))) == "unsatisfied_seal_assert"
        )


@given(transactions, st.booleans(), carrier_indexes)
@EXAMPLES
def test_duplication_and_list_order_change_nothing(spec, satisfied, carrier):
    """Duplicating a seal within its input and reordering the
    condition list never change the outcome, satisfied or not,
    whichever input carries the seals."""
    tx = build_tx(*spec, conds=())
    operand = oracle_txid(tx)
    if not satisfied:
        operand = flip(operand, 31)
    conds = (Seal(operand), SealOutputs(oracle_outputs_hash(tx)))
    base = outcome(reseal(tx, conds, carrier))
    assert base == (None if satisfied else "unsatisfied_seal_assert")
    assert outcome(reseal(tx, conds + conds, carrier)) == base
    assert outcome(reseal(tx, conds[::-1], carrier)) == base


@given(transactions)
@EXAMPLES
def test_output_reorder_breaks_outputs_seal(spec):
    """Swapping two output slots of differing content breaks a
    satisfied SEAL_OUTPUTS: the hash commits to slot order."""
    tx = build_tx(*spec, conds=())
    assume(len(tx.outputs) >= 2)
    assume(tx.outputs[0].content != tx.outputs[-1].content)
    sealed = reseal(tx, (SealOutputs(oracle_outputs_hash(tx)),))
    assert outcome(sealed) is None
    swapped = Transaction(
        version=tx.version,
        locktime=tx.locktime,
        inputs=sealed.inputs,
        outputs=(tx.outputs[-1],) + tx.outputs[1:-1] + (tx.outputs[0],),
    )
    assert outcome(swapped) == "unsatisfied_seal_assert"
