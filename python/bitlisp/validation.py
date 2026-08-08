"""Condition validation, rule by rule.

Rule 1, injective multiset output matching: every output claim maps
to a distinct output slot with byte-exact content. Because a claim
matches a slot only by exact equality, the injective-assignment
question collapses to multiset containment and the check is counting.
That equality-only restriction is what keeps this a counting problem
rather than bipartite matching. Relaxing it is a recorded design
decision, never an implementation choice.

The time asserts check under rule 2's assert clause. They read only
the transaction's own locktime, sequence, and version fields, the
fields base consensus enforces against the chain, so validation
never reads the chain and a validated transaction never needs
re-validation as the chain grows.
"""

from collections import Counter

from .conditions import (
    LOCKTIME_THRESHOLD,
    AssertLocktimeHeight,
    AssertLocktimeTime,
    AssertSequenceHeight,
    AssertSequenceTime,
    CreateOutput,
    CreateOutputTaproot,
)
from .errors import BitLispError

_SEQUENCE_FINAL = 0xFFFFFFFF
_SEQUENCE_DISABLE_FLAG = 1 << 31
_SEQUENCE_TYPE_FLAG = 1 << 22
_SEQUENCE_VALUE_MASK = 0xFFFF


def output_claims(conditions):
    """The (scriptPubKey, amount) claims a condition list produces."""
    return [
        (c.script_pubkey, c.amount)
        for c in conditions
        if isinstance(c, (CreateOutput, CreateOutputTaproot))
    ]


def check_output_claims(tx):
    """Rule 1. Raises unsatisfied_output_claim unless every claim in
    the transaction can consume its own distinct output slot."""
    claims = Counter()
    for tx_input in tx.inputs:
        if tx_input.conditions is not None:
            claims.update(output_claims(tx_input.conditions))
    slots = Counter(output.content for output in tx.outputs)
    for content, count in claims.items():
        script_pubkey, amount = content
        if count > slots[content]:
            raise BitLispError(
                "unsatisfied_output_claim",
                f"{count} claim(s) on ({script_pubkey.hex()}, {amount}) but "
                f"{slots[content]} matching output slot(s)",
            )


def _check_locktime_assert(tx, tx_input, operand, height_typed, name):
    """Locktime asserts mirror OP_CHECKLOCKTIMEVERIFY: the spending
    input's own non-final sequence guarantees base consensus enforces
    locktime, the field's type must match the condition's, and the
    field must reach the operand."""
    if tx_input.sequence == _SEQUENCE_FINAL:
        raise BitLispError(
            "unsatisfied_locktime_assert",
            f"{name} with a final sequence, locktime is unenforced",
        )
    if (tx.locktime < LOCKTIME_THRESHOLD) != height_typed:
        raise BitLispError(
            "unsatisfied_locktime_assert",
            f"{name} against a locktime of the other type: {tx.locktime}",
        )
    if tx.locktime < operand:
        raise BitLispError(
            "unsatisfied_locktime_assert",
            f"{name} demands {operand}, locktime is {tx.locktime}",
        )


def _check_sequence_assert(tx, tx_input, operand, time_typed, name):
    """Sequence asserts mirror OP_CHECKSEQUENCEVERIFY: base consensus
    enforces a relative lock only for version 2 and up with the
    disable flag clear, the type flag must match the condition's, and
    the 16-bit value must reach the operand."""
    if tx.version < 2:
        raise BitLispError(
            "unsatisfied_sequence_assert",
            f"{name} in a version {tx.version} transaction, "
            "relative locks are unenforced",
        )
    if tx_input.sequence & _SEQUENCE_DISABLE_FLAG:
        raise BitLispError(
            "unsatisfied_sequence_assert",
            f"{name} with the disable flag set, the sequence encodes no relative lock",
        )
    if bool(tx_input.sequence & _SEQUENCE_TYPE_FLAG) != time_typed:
        raise BitLispError(
            "unsatisfied_sequence_assert",
            f"{name} against a sequence of the other type: {tx_input.sequence:#010x}",
        )
    value = tx_input.sequence & _SEQUENCE_VALUE_MASK
    if value < operand:
        raise BitLispError(
            "unsatisfied_sequence_assert",
            f"{name} demands {operand}, the sequence value is {value}",
        )


def check_time_asserts(tx):
    """The time assert family, checked as a conjunction over every
    condition of every BitLisp input."""
    for tx_input in tx.inputs:
        for cond in tx_input.conditions or ():
            if isinstance(cond, AssertLocktimeHeight):
                _check_locktime_assert(
                    tx, tx_input, cond.height, True, "ASSERT_LOCKTIME_HEIGHT"
                )
            elif isinstance(cond, AssertLocktimeTime):
                _check_locktime_assert(
                    tx, tx_input, cond.time, False, "ASSERT_LOCKTIME_TIME"
                )
            elif isinstance(cond, AssertSequenceHeight):
                _check_sequence_assert(
                    tx, tx_input, cond.blocks, False, "ASSERT_SEQUENCE_HEIGHT"
                )
            elif isinstance(cond, AssertSequenceTime):
                _check_sequence_assert(
                    tx, tx_input, cond.units, True, "ASSERT_SEQUENCE_TIME"
                )


def validate_transaction(tx):
    """Every validation rule that has landed so far."""
    check_output_claims(tx)
    check_time_asserts(tx)
