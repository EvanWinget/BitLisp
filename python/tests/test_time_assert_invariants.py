"""Property-based invariants for the time assert family.

The family reads only the transaction's own locktime, sequence, and
version fields, so every property here is a pure function of
generated transactions. Fields and operands are drawn from small
pools straddling every boundary the family checks (the locktime type
threshold, the sequence disable and type flags, the version 2 gate,
operand equality with the field), so satisfied and unsatisfied
asserts are both dense.
"""

from dataclasses import replace

from bitlisp import (
    AssertLocktimeHeight,
    AssertLocktimeTime,
    AssertSequenceHeight,
    AssertSequenceTime,
    BitLispError,
    Transaction,
    TxInput,
    TxOutput,
    validate_transaction,
)
from bitlisp.conditions import (
    LOCKTIME_MAX,
    LOCKTIME_THRESHOLD,
    SEQUENCE_VALUE_MAX,
)
from hypothesis import given
from hypothesis import strategies as st

_FINAL = 0xFFFFFFFF
_DISABLE = 1 << 31
_TYPE = 1 << 22

versions = st.sampled_from((0, 1, 2, 3, 0xFFFFFFFF))
locktimes = st.sampled_from((0, 100, 499_999_999, 500_000_000, 1_700_000_000))
sequences = st.sampled_from(
    (
        _FINAL,
        0xFFFFFFFE,
        0,
        100,
        _TYPE | 100,
        _DISABLE | 100,
        _DISABLE | _TYPE | 100,
    )
)

time_asserts = st.one_of(
    st.sampled_from((0, 100, 101, 499_999_999)).map(AssertLocktimeHeight),
    st.sampled_from((500_000_000, 1_600_000_000, 1_700_000_001)).map(
        AssertLocktimeTime
    ),
    st.sampled_from((0, 100, 101)).map(AssertSequenceHeight),
    st.sampled_from((0, 100, 101)).map(AssertSequenceTime),
)
input_specs = st.lists(
    st.tuples(sequences, st.lists(time_asserts, max_size=3)),
    min_size=1,
    max_size=3,
)


def build_tx(version, locktime, spec):
    """A transaction whose first input funds the single output."""
    inputs = tuple(
        TxInput(
            txid=bytes([n + 1]) * 32,
            index=0,
            script_pubkey=b"\x51",
            amount=40_000 if n == 0 else 0,
            sequence=sequence,
            conditions=tuple(asserts),
            tapleaf=b"\x0a" * 32,
            merkle_root=b"\x0b" * 32,
            internal_key=b"\x0c" * 32,
        )
        for n, (sequence, asserts) in enumerate(spec)
    )
    return Transaction(version, locktime, inputs, (TxOutput(b"\x51", 40_000),))


def is_valid(tx):
    try:
        validate_transaction(tx)
        return True
    except BitLispError as exc:
        assert exc.code in (
            "unsatisfied_locktime_assert",
            "unsatisfied_sequence_assert",
        )
        return False


def _spec_says_valid(tx):
    """The family's semantics bullets, restated directly. Like rule
    1's containment restatement, this pins the implementation against
    drift rather than judging the algorithm: the behavioral
    properties below are the independent judges."""
    for tx_input in tx.inputs:
        for cond in tx_input.conditions or ():
            if isinstance(cond, AssertLocktimeHeight):
                ok = (
                    tx_input.sequence != _FINAL
                    and tx.locktime < LOCKTIME_THRESHOLD
                    and tx.locktime >= cond.height
                )
            elif isinstance(cond, AssertLocktimeTime):
                ok = (
                    tx_input.sequence != _FINAL
                    and tx.locktime >= LOCKTIME_THRESHOLD
                    and tx.locktime >= cond.time
                )
            elif isinstance(cond, AssertSequenceHeight):
                ok = (
                    tx.version >= 2
                    and not tx_input.sequence & _DISABLE
                    and not tx_input.sequence & _TYPE
                    and tx_input.sequence & SEQUENCE_VALUE_MAX >= cond.blocks
                )
            elif isinstance(cond, AssertSequenceTime):
                ok = (
                    tx.version >= 2
                    and not tx_input.sequence & _DISABLE
                    and tx_input.sequence & _TYPE
                    and tx_input.sequence & SEQUENCE_VALUE_MAX >= cond.units
                )
            else:
                continue
            if not ok:
                return False
    return True


def _operand(cond):
    (value,) = (
        getattr(cond, field)
        for field in ("height", "time", "blocks", "units")
        if hasattr(cond, field)
    )
    return value


def _with_operand(cond, value):
    (field,) = (
        field for field in ("height", "time", "blocks", "units") if hasattr(cond, field)
    )
    return replace(cond, **{field: value})


def _operand_domain(cond):
    if isinstance(cond, AssertLocktimeHeight):
        return 0, LOCKTIME_THRESHOLD - 1
    if isinstance(cond, AssertLocktimeTime):
        return LOCKTIME_THRESHOLD, LOCKTIME_MAX
    return 0, SEQUENCE_VALUE_MAX


@given(versions, locktimes, input_specs)
def test_validation_matches_the_spec_restatement(version, locktime, spec):
    tx = build_tx(version, locktime, spec)
    assert is_valid(tx) == _spec_says_valid(tx)


@given(versions, locktimes, input_specs)
def test_removing_a_time_assert_never_invalidates(version, locktime, spec):
    """Constraints only tighten: dropping any one assert from a valid
    transaction leaves it valid."""
    if not is_valid(build_tx(version, locktime, spec)):
        return
    for i, (sequence, asserts) in enumerate(spec):
        for j in range(len(asserts)):
            reduced = list(spec)
            reduced[i] = (sequence, asserts[:j] + asserts[j + 1 :])
            assert is_valid(build_tx(version, locktime, reduced))


@given(versions, locktimes, input_specs)
def test_operand_monotonicity(version, locktime, spec):
    """Increasing any operand never turns an invalid transaction
    valid, and decreasing any operand never turns a valid one
    invalid."""
    valid = is_valid(build_tx(version, locktime, spec))
    for i, (sequence, asserts) in enumerate(spec):
        for j, cond in enumerate(asserts):
            low, high = _operand_domain(cond)
            value = _operand(cond)
            step = -1 if valid else 1
            moved = value + step
            if not low <= moved <= high:
                continue
            mutated = list(spec)
            mutated[i] = (
                sequence,
                asserts[:j] + [_with_operand(cond, moved)] + asserts[j + 1 :],
            )
            assert is_valid(build_tx(version, locktime, mutated)) == valid


@given(versions, locktimes, input_specs)
def test_boundary_flips_reject(version, locktime, spec):
    """Metamorphic, from the spec's invariant list: on a valid
    transaction, moving a read field across its boundary rejects.
    Locktime crosses the type threshold against any locktime assert,
    the disable flag rises against any sequence assert, and version
    drops below 2 against any sequence assert."""
    if not is_valid(build_tx(version, locktime, spec)):
        return
    reads_locktime = any(
        isinstance(c, (AssertLocktimeHeight, AssertLocktimeTime))
        for _, asserts in spec
        for c in asserts
    )
    if reads_locktime:
        flipped = 1_700_000_000 if locktime < LOCKTIME_THRESHOLD else 100
        assert not is_valid(build_tx(version, flipped, spec))
    for i, (sequence, asserts) in enumerate(spec):
        if not any(
            isinstance(c, (AssertSequenceHeight, AssertSequenceTime)) for c in asserts
        ):
            continue
        disabled = list(spec)
        disabled[i] = (sequence | _DISABLE, asserts)
        assert not is_valid(build_tx(version, locktime, disabled))
        assert not is_valid(build_tx(1, locktime, spec))


@given(versions, locktimes, input_specs, versions, locktimes, input_specs)
def test_merge_under_the_guarantee_discipline(
    version_a, locktime_a, spec_a, version_b, locktime_b, spec_b
):
    """The amended composition guarantee: two valid transactions with
    same-typed locktime fields concatenate into a valid transaction
    under the greater version and greater locktime."""
    if (locktime_a < LOCKTIME_THRESHOLD) != (locktime_b < LOCKTIME_THRESHOLD):
        return
    tx_a = build_tx(version_a, locktime_a, spec_a)
    tx_b = build_tx(version_b, locktime_b, spec_b)
    if not (is_valid(tx_a) and is_valid(tx_b)):
        return
    renumbered = tuple(
        replace(tx_input, txid=bytes([0x40 + n]) * 32)
        for n, tx_input in enumerate(tx_b.inputs)
    )
    merged = Transaction(
        max(version_a, version_b),
        max(locktime_a, locktime_b),
        tx_a.inputs + renumbered,
        tx_a.outputs + tx_b.outputs,
    )
    assert is_valid(merged)
