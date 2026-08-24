"""Property-based invariants for the fee reserve.

The fee reserve is the counted sort: occurrences sum into one
transaction-wide demand against the fee, inputs minus outputs. The
properties pin the sum semantics from every side an implementation
could get wrong: monotonicity in the operand, invariance under
splitting a reserve into parts or moving it between inputs (the
demand belongs to the transaction, not the carrier), the exact
boundary, and the fee-theft direction where a grafted output shrinks
the fee below a covered demand. Reserve pools and fee margins are
small and colliding so covered and uncovered demands are both dense.
"""

from bitlisp import (
    BitLispError,
    Transaction,
    TxInput,
    TxOutput,
    validate_transaction,
)
from bitlisp.conditions import ReserveFee
from conftest import filler_identity
from hypothesis import assume, given
from hypothesis import strategies as st

TXID_A = b"\xaa" * 32
TXID_B = b"\xbb" * 32
TXID_C = b"\xcc" * 32
SPK_IN = b"\x51\x20" + b"\xaa" * 32
SPK_OUT = b"\x00\x14" + b"\xbb" * 20

INPUT_AMOUNT = 20_000_000_000

reserve_values = st.sampled_from((0, 1, 200, 300, 600, 601, 2**32, 2**32 + 100))
reserve_lists = st.lists(reserve_values, max_size=3)
fees = st.sampled_from((0, 1, 199, 200, 599, 600, 601, 1200, 1801, 2**32, 2**32 + 100))


def build_tx(reserve_lists_per_input, fee, extra_input=False):
    """BitLisp inputs carrying only reserves, one output absorbing
    everything but the fee. INPUT_AMOUNT per input keeps every fee
    in the pool reachable."""
    inputs = tuple(
        TxInput(
            txid,
            0,
            SPK_IN,
            INPUT_AMOUNT,
            0xFFFFFFFF,
            tuple(ReserveFee(r) for r in reserves),
            **filler_identity(),
        )
        for txid, reserves in zip(
            (TXID_A, TXID_B), reserve_lists_per_input, strict=True
        )
    )
    if extra_input:
        inputs += (TxInput(TXID_C, 0, SPK_IN, INPUT_AMOUNT, 0xFFFFFFFF),)
    total_in = sum(i.amount for i in inputs)
    outputs = (TxOutput(SPK_OUT, total_in - fee),)
    return Transaction(2, 0, inputs, outputs)


def outcome(tx):
    try:
        validate_transaction(tx)
        return "valid"
    except BitLispError as exc:
        return exc.code


@given(reserve_lists, reserve_lists, fees, st.data())
def test_operand_monotonicity(reserves_a, reserves_b, fee, data):
    """Decreasing an operand never invalidates, increasing one never
    validates."""
    assume(reserves_a)
    tx = build_tx([reserves_a, reserves_b], fee)
    before = outcome(tx)
    index = data.draw(st.integers(0, len(reserves_a) - 1))
    if before == "valid":
        lowered = list(reserves_a)
        lowered[index] = data.draw(st.integers(0, lowered[index]))
        assert outcome(build_tx([lowered, reserves_b], fee)) == "valid"
    else:
        assert before == "insufficient_fee"
        raised = list(reserves_a)
        raised[index] += data.draw(st.integers(0, 500))
        assert outcome(build_tx([raised, reserves_b], fee)) == "insufficient_fee"


@given(reserve_lists, reserve_lists, fees, st.data())
def test_split_within_input_preserves_outcome(reserves_a, reserves_b, fee, data):
    """One reserve of x and two reserves summing to x are the same
    demand."""
    assume(reserves_a)
    index = data.draw(st.integers(0, len(reserves_a) - 1))
    part = data.draw(st.integers(0, reserves_a[index]))
    split = list(reserves_a)
    split[index : index + 1] = [part, reserves_a[index] - part]
    whole_tx = build_tx([reserves_a, reserves_b], fee)
    split_tx = build_tx([split, reserves_b], fee)
    assert outcome(whole_tx) == outcome(split_tx)


@given(reserve_lists, reserve_lists, fees, st.data())
def test_moving_a_reserve_between_inputs_preserves_outcome(
    reserves_a, reserves_b, fee, data
):
    """The demand belongs to the transaction, not the carrying
    input."""
    assume(reserves_a)
    index = data.draw(st.integers(0, len(reserves_a) - 1))
    moved_a = list(reserves_a)
    moved = moved_a.pop(index)
    before = outcome(build_tx([reserves_a, reserves_b], fee))
    after = outcome(build_tx([moved_a, reserves_b + [moved]], fee))
    assert before == after


@given(reserve_lists, reserve_lists, st.data())
def test_boundary_raise_by_one_rejects(reserves_a, reserves_b, data):
    """At fee exactly the summed demand, one more satoshi of demand
    rejects."""
    assume(reserves_a)
    fee = sum(reserves_a) + sum(reserves_b)
    assert outcome(build_tx([reserves_a, reserves_b], fee)) == "valid"
    index = data.draw(st.integers(0, len(reserves_a) - 1))
    raised = list(reserves_a)
    raised[index] += 1
    assert outcome(build_tx([raised, reserves_b], fee)) == "insufficient_fee"


@given(reserve_lists, reserve_lists, st.data())
def test_fee_theft_grafted_output_rejects(reserves_a, reserves_b, data):
    """At fee exactly the summed demand, any grafted output steals
    reserved fee and rejects."""
    total = sum(reserves_a) + sum(reserves_b)
    assume(total >= 1)
    tx = build_tx([reserves_a, reserves_b], total)
    assert outcome(tx) == "valid"
    stolen = data.draw(st.integers(1, total))
    grafted = Transaction(
        tx.version,
        tx.locktime,
        tx.inputs,
        tx.outputs + (TxOutput(SPK_OUT, stolen),),
    )
    assert outcome(grafted) == "insufficient_fee"


@given(fees, st.integers(0, 400))
def test_added_slot_without_reserves_never_invalidates(fee, slot_amount):
    """The re-scoped slot half: with no reserve carried, an added
    slot cannot invalidate."""
    assume(slot_amount <= fee)
    tx = build_tx([[], []], fee)
    assert outcome(tx) == "valid"
    extended = Transaction(
        tx.version,
        tx.locktime,
        tx.inputs,
        tx.outputs + (TxOutput(SPK_OUT, slot_amount),),
    )
    assert outcome(extended) == "valid"


@given(reserve_lists, reserve_lists, fees)
def test_added_non_bitlisp_input_never_invalidates(reserves_a, reserves_b, fee):
    """The unconditional input half: added input value only raises
    the fee."""
    tx = build_tx([reserves_a, reserves_b], fee)
    before = outcome(tx)
    extended = outcome(build_tx([reserves_a, reserves_b], fee, extra_input=True))
    if before == "valid":
        assert extended == "valid"


@given(reserve_lists, reserve_lists, fees, fees)
def test_merge_of_covered_reserves_is_covered(reserves_a, reserves_b, fee_1, fee_2):
    """The composition guarantee's arithmetic: fees sum, reserves
    sum."""
    tx_1 = build_tx([reserves_a, []], fee_1)
    tx_2 = Transaction(
        2,
        0,
        (
            TxInput(
                TXID_B,
                1,
                SPK_IN,
                INPUT_AMOUNT,
                0xFFFFFFFF,
                tuple(ReserveFee(r) for r in reserves_b),
                **filler_identity(),
            ),
        ),
        (TxOutput(SPK_OUT, INPUT_AMOUNT - fee_2),),
    )
    assume(outcome(tx_1) == "valid" and outcome(tx_2) == "valid")
    merged = Transaction(2, 0, tx_1.inputs + tx_2.inputs, tx_1.outputs + tx_2.outputs)
    assert outcome(merged) == "valid"


def test_sum_not_max():
    """Two reserves of 300 demand 600 together: a max-semantics
    mutant passes fee 599 and dies here."""
    assert outcome(build_tx([[300, 300], []], 599)) == "insufficient_fee"
    assert outcome(build_tx([[300, 300], []], 600)) == "valid"


def test_counted_not_collapsed():
    """Three identical reserves demand three times the operand: a
    set-collapse mutant passes fee 200 and dies here."""
    assert outcome(build_tx([[200, 200, 200], []], 200)) == "insufficient_fee"
    assert outcome(build_tx([[200, 200, 200], []], 599)) == "insufficient_fee"
    assert outcome(build_tx([[200, 200, 200], []], 600)) == "valid"
