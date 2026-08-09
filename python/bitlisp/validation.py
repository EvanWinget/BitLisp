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

The self asserts check under the same clause and read even less:
each is an equality against the spending input's own prevout data,
which travels with the spend, so no recombination of spends into a
different transaction can change an outcome. The taproot assert's
scriptPubKey is derived at parse, so here it compares like the
plain script assert.

Rule 3, message scoping: the addressed pair contributes signed
weights to a per-transaction ledger keyed by (sender specifier,
receiver specifier, message), and every key must net to zero.
Balance is a sum, so the check is order-free and two balanced
groups of inputs stay balanced when spent together. Announcements
are ordinary asserts over facts other inputs create: existence is
checked, nothing is consumed, and an unread announcement
constrains nothing. Both checks stay counting problems like rule
1: the ledger is one pass, and announcement facts are indexed
once per commitment value in use before the asserts run.
"""

from collections import Counter

from .conditions import (
    LOCKTIME_THRESHOLD,
    SPECIFIER_OPERANDS,
    Announce,
    AssertAnnouncement,
    AssertLocktimeHeight,
    AssertLocktimeTime,
    AssertMyAmount,
    AssertMyOutpoint,
    AssertMyScriptPubKey,
    AssertMyTaproot,
    AssertMyTxid,
    AssertSequenceHeight,
    AssertSequenceTime,
    CreateOutput,
    CreateOutputTaproot,
    ReceiveMessage,
    SendMessage,
    Specifier,
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


def check_self_asserts(tx):
    """The self assert family: each condition is an equality against
    its own input's prevout data, checked as a conjunction."""
    for tx_input in tx.inputs:
        outpoint = tx_input.txid + tx_input.index.to_bytes(4, "little")
        for cond in tx_input.conditions or ():
            if isinstance(cond, AssertMyOutpoint):
                if cond.outpoint != outpoint:
                    raise BitLispError(
                        "unsatisfied_outpoint_assert",
                        f"ASSERT_MY_OUTPOINT demands {cond.outpoint.hex()}, "
                        f"the input consumes {outpoint.hex()}",
                    )
            elif isinstance(cond, AssertMyTxid):
                if cond.txid != tx_input.txid:
                    raise BitLispError(
                        "unsatisfied_outpoint_assert",
                        f"ASSERT_MY_TXID demands {cond.txid.hex()}, "
                        f"the creating txid is {tx_input.txid.hex()}",
                    )
            elif isinstance(cond, (AssertMyScriptPubKey, AssertMyTaproot)):
                if cond.script_pubkey != tx_input.script_pubkey:
                    name = (
                        "ASSERT_MY_TAPROOT"
                        if isinstance(cond, AssertMyTaproot)
                        else "ASSERT_MY_SCRIPTPUBKEY"
                    )
                    raise BitLispError(
                        "unsatisfied_scriptpubkey_assert",
                        f"{name} demands "
                        f"{cond.script_pubkey.hex() or '(empty)'}, the spent "
                        f"scriptPubKey is "
                        f"{tx_input.script_pubkey.hex() or '(empty)'}",
                    )
            elif isinstance(cond, AssertMyAmount):
                if cond.amount != tx_input.amount:
                    raise BitLispError(
                        "unsatisfied_amount_assert",
                        f"ASSERT_MY_AMOUNT demands {cond.amount}, "
                        f"the spent amount is {tx_input.amount}",
                    )


def self_specifier(tx_input, commitment):
    """The input's own prevout data at a commitment value: what a
    SEND or RECEIVE says about its emitting input, and what an
    announcement assert compares its announcer operands against."""
    fields = []
    for kind in SPECIFIER_OPERANDS[commitment]:
        if kind == "txid":
            fields.append(tx_input.txid)
        elif kind == "script_pubkey":
            fields.append(tx_input.script_pubkey)
        elif kind == "amount":
            fields.append(tx_input.amount)
        else:
            fields.append(tx_input.txid + tx_input.index.to_bytes(4, "little"))
    return Specifier(commitment, tuple(fields))


def check_messages(tx):
    """Rule 3, the message ledger. Every distinct (sender specifier,
    receiver specifier, payload) record must net to zero across the
    whole transaction, sends counting +1 and receives -1."""
    ledger = Counter()
    for tx_input in tx.inputs:
        for cond in tx_input.conditions or ():
            if isinstance(cond, SendMessage):
                sender = self_specifier(tx_input, cond.sender_commitment)
                ledger[(sender, cond.receiver, cond.message)] += 1
            elif isinstance(cond, ReceiveMessage):
                receiver = self_specifier(tx_input, cond.receiver_commitment)
                ledger[(cond.sender, receiver, cond.message)] -= 1
    for (_, _, message), weight in ledger.items():
        if weight != 0:
            raise BitLispError(
                "unbalanced_message",
                f"message record nets {weight:+d}, message bytes "
                f"{message.hex() or '(empty)'}",
            )


def check_announcements(tx):
    """Rule 3, announcements. Each assert must find a single input
    that announced its exact namespace and payload and whose self
    specifier at the assert's commitment value equals the announcer
    operands. Nothing is consumed: one announcement satisfies any
    number of asserts. Announced facts are indexed once per
    commitment value appearing in an assert, so the check stays
    linear in the condition count rather than quadratic."""
    commitments = {
        cond.announcer.commitment
        for tx_input in tx.inputs
        for cond in tx_input.conditions or ()
        if isinstance(cond, AssertAnnouncement)
    }
    if not commitments:
        return
    facts = set()
    for tx_input in tx.inputs:
        for cond in tx_input.conditions or ():
            if isinstance(cond, Announce):
                for commitment in commitments:
                    facts.add(
                        (
                            self_specifier(tx_input, commitment),
                            cond.namespace,
                            cond.payload,
                        )
                    )
    for tx_input in tx.inputs:
        for cond in tx_input.conditions or ():
            if (
                isinstance(cond, AssertAnnouncement)
                and (cond.announcer, cond.namespace, cond.payload) not in facts
            ):
                raise BitLispError(
                    "unsatisfied_announcement_assert",
                    f"no announcement matches namespace "
                    f"{cond.namespace.hex() or '(empty)'} payload "
                    f"{cond.payload.hex() or '(empty)'}",
                )


def validate_transaction(tx):
    """Every validation rule that has landed so far, stage 2 work
    before stage 4."""
    check_self_asserts(tx)
    check_output_claims(tx)
    check_time_asserts(tx)
    check_messages(tx)
    check_announcements(tx)
