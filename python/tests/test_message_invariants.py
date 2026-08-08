"""Property-based invariants for validation rule 3.

The message ledger and the announcement facts read nothing outside
the transaction, so every property is a pure function of generated
transactions. Inputs come from a fixed pool of three identities, and
conditions are built against those identities: matched pairs,
deliberately stray halves addressed to a phantom input, announcements,
and asserts that sometimes name the wrong announcer. Balanced and
unbalanced ledgers are both dense.
"""

from collections import Counter
from dataclasses import replace

from bitlisp import (
    Announce,
    AssertAnnouncement,
    BitLispError,
    ReceiveMessage,
    SendMessage,
    Transaction,
    TxInput,
    TxOutput,
    validate_transaction,
)
from bitlisp.validation import self_specifier
from hypothesis import given
from hypothesis import strategies as st

_MODES = tuple(range(8))
_PAYLOADS = (b"x", b"y")
_NAMESPACES = (b"n1", b"n2")
_PHANTOM = -1


def _input_identity(salt, n):
    """The pool: input n of a group has a group-unique txid, a
    nonzero position (so the outpoint's little-endian index bytes
    discriminate), its own script, and an amount that varies by
    position so amount-mode specifiers discriminate."""
    return TxInput(
        txid=bytes([salt + n]) * 32,
        index=n + 1,
        script_pubkey=bytes([0x51, n]),
        amount=40_000 if n == 0 else n,
        sequence=0xFFFFFFFE,
        conditions=None,
    )


def _specifier(salt, idx, commitment):
    """The self specifier of pool input idx, or of the phantom input
    no transaction contains."""
    n = 0x70 if idx == _PHANTOM else idx
    return self_specifier(_input_identity(salt, n), commitment)


def _realize(salt, item):
    """One abstract condition into a dataclass instance."""
    kind = item[0]
    if kind == "send":
        _, target, s_half, r_half, payload = item
        return SendMessage(s_half, _specifier(salt, target, r_half), payload)
    if kind == "recv":
        _, source, s_half, r_half, payload = item
        return ReceiveMessage(_specifier(salt, source, s_half), r_half, payload)
    if kind == "ann":
        _, namespace, payload = item
        return Announce(namespace, payload)
    _, announcer, commitment, namespace, payload = item
    return AssertAnnouncement(
        _specifier(salt, announcer, commitment), namespace, payload
    )


def _condition_pool():
    items = []
    for target in (0, 1, 2, _PHANTOM):
        for s_half in _MODES:
            for r_half in _MODES:
                for payload in _PAYLOADS:
                    items.append(("send", target, s_half, r_half, payload))
                    items.append(("recv", target, s_half, r_half, payload))
    for namespace in _NAMESPACES:
        for payload in _PAYLOADS:
            items.append(("ann", namespace, payload))
            for announcer in (0, 1, 2, _PHANTOM):
                for commitment in _MODES:
                    items.append(("assert", announcer, commitment, namespace, payload))
    return items


condition_items = st.sampled_from(_condition_pool())
input_specs = st.lists(st.lists(condition_items, max_size=3), min_size=1, max_size=3)


def build_tx(spec, salt=1):
    inputs = tuple(
        replace(
            _input_identity(salt, n),
            conditions=tuple(_realize(salt, item) for item in items),
        )
        for n, items in enumerate(spec)
    )
    return Transaction(2, 0, inputs, (TxOutput(b"\x51", 40_000),))


def is_valid(tx):
    try:
        validate_transaction(tx)
        return True
    except BitLispError as exc:
        assert exc.code in (
            "unbalanced_message",
            "unsatisfied_announcement_assert",
        )
        return False


def _spec_says_valid(tx):
    """Rule 3 restated directly: every ledger record nets zero and
    every announcement assert finds a matching announcement. Like the
    other families' restatements, this pins against drift, and the
    behavioral properties below are the independent judges."""
    ledger = Counter()
    for tx_input in tx.inputs:
        for cond in tx_input.conditions or ():
            if isinstance(cond, SendMessage):
                sender = self_specifier(tx_input, cond.sender_commitment)
                ledger[(sender, cond.receiver, cond.message)] += 1
            elif isinstance(cond, ReceiveMessage):
                receiver = self_specifier(tx_input, cond.receiver_commitment)
                ledger[(cond.sender, receiver, cond.message)] -= 1
    if any(weight != 0 for weight in ledger.values()):
        return False
    for tx_input in tx.inputs:
        for cond in tx_input.conditions or ():
            if isinstance(cond, AssertAnnouncement) and not any(
                isinstance(announced, Announce)
                and announced.namespace == cond.namespace
                and announced.payload == cond.payload
                and self_specifier(announcer, cond.announcer.commitment)
                == cond.announcer
                for announcer in tx.inputs
                for announced in announcer.conditions or ()
            ):
                return False
    return True


@given(input_specs)
def test_validation_matches_the_rule_restatement(spec):
    tx = build_tx(spec)
    assert is_valid(tx) == _spec_says_valid(tx)


@given(input_specs, st.data())
def test_matched_pair_addition_and_lone_halves(spec, data):
    """From the spec's invariant list: adding a balanced send and
    receive pair to a valid transaction keeps it valid, and adding
    either half alone invalidates it."""
    if not is_valid(build_tx(spec)):
        return
    sender_idx = data.draw(st.integers(0, len(spec) - 1))
    receiver_idx = data.draw(st.integers(0, len(spec) - 1))
    s_half = data.draw(st.sampled_from(_MODES))
    r_half = data.draw(st.sampled_from(_MODES))
    payload = data.draw(st.sampled_from(_PAYLOADS))
    send = ("send", receiver_idx, s_half, r_half, payload)
    recv = ("recv", sender_idx, s_half, r_half, payload)

    def extended(additions):
        grown = [list(items) for items in spec]
        for idx, item in additions:
            grown[idx] = grown[idx] + [item]
        return build_tx(grown)

    assert is_valid(extended([(sender_idx, send), (receiver_idx, recv)]))
    assert not is_valid(extended([(sender_idx, send)]))
    assert not is_valid(extended([(receiver_idx, recv)]))


@given(input_specs)
def test_reorder_invariance(spec):
    """The ledger is a sum and asserts are a conjunction, so input
    order and condition order never affect the outcome."""
    tx = build_tx(spec)
    reordered = Transaction(
        tx.version,
        tx.locktime,
        tuple(
            replace(tx_input, conditions=tx_input.conditions[::-1])
            for tx_input in tx.inputs[::-1]
        ),
        tx.outputs,
    )
    assert is_valid(tx) == is_valid(reordered)


@given(input_specs, st.sampled_from(_NAMESPACES), st.sampled_from(_PAYLOADS))
def test_announce_addition_is_monotone(spec, namespace, payload):
    """Adding an announcement never invalidates: announcements are
    facts, and rule 3's asserts only ever gain satisfiers."""
    if not is_valid(build_tx(spec)):
        return
    for idx in range(len(spec)):
        grown = [list(items) for items in spec]
        grown[idx] = grown[idx] + [("ann", namespace, payload)]
        assert is_valid(build_tx(grown))


@given(
    st.sampled_from(_MODES),
    st.sampled_from(_NAMESPACES),
    st.sampled_from(_PAYLOADS),
)
def test_removing_the_sole_announcement_invalidates(commitment, namespace, payload):
    """The other half of announcement monotonicity, from the spec's
    invariant list."""
    announced = [
        [("ann", namespace, payload)],
        [("assert", 0, commitment, namespace, payload)],
    ]
    assert is_valid(build_tx(announced))
    assert not is_valid(build_tx([[], announced[1]]))


@given(st.sampled_from(_MODES), st.sampled_from(_PAYLOADS))
def test_namespace_byte_flip_rejects(commitment, payload):
    """Metamorphic, from the spec's invariant list: flipping a byte
    of the namespace an assert reads rejects."""
    namespace = _NAMESPACES[0]
    spec = [
        [("ann", namespace, payload)],
        [("assert", 0, commitment, namespace, payload)],
    ]
    assert is_valid(build_tx(spec))
    flipped = bytes([namespace[0] ^ 0x01]) + namespace[1:]
    spec[1] = [("assert", 0, commitment, flipped, payload)]
    assert not is_valid(build_tx(spec))


@given(st.sampled_from(_PAYLOADS))
def test_specifier_field_flip_rejects(payload):
    """Metamorphic, from the spec's invariant list: flipping a byte
    of a committed specifier field of the only balancing pair
    rejects. The send's receiver script specifier is mutated after
    construction, so only the field byte changes."""
    spec = [[("send", 1, 2, 2, payload)], [("recv", 0, 2, 2, payload)]]
    tx = build_tx(spec)
    assert is_valid(tx)
    send_cond = tx.inputs[0].conditions[0]
    script = send_cond.receiver.fields[0]
    tampered_desc = replace(
        send_cond.receiver, fields=(bytes([script[0] ^ 0x01]) + script[1:],)
    )
    tampered = Transaction(
        2,
        0,
        (
            replace(
                tx.inputs[0],
                conditions=(replace(send_cond, receiver=tampered_desc),),
            ),
            tx.inputs[1],
        ),
        tx.outputs,
    )
    assert not is_valid(tampered)


@given(
    st.sampled_from(_MODES),
    st.sampled_from(_MODES),
    st.sampled_from(_PAYLOADS),
)
def test_payload_byte_flip_rejects(s_half, r_half, payload):
    """Metamorphic, from the spec's invariant list: flipping a byte of
    the only balancing pair's payload rejects."""
    spec = [
        [("send", 1, s_half, r_half, payload)],
        [("recv", 0, s_half, r_half, payload)],
    ]
    assert is_valid(build_tx(spec))
    flipped = bytes([payload[0] ^ 0x01]) + payload[1:]
    spec[1] = [("recv", 0, s_half, r_half, flipped)]
    assert not is_valid(build_tx(spec))


@given(input_specs, input_specs)
def test_merge_preserves_balance(spec_a, spec_b):
    """The composition guarantee over this family: two valid groups
    with disjoint outpoints concatenate into a valid transaction,
    even when their records collide."""
    tx_a = build_tx(spec_a, salt=1)
    tx_b = build_tx(spec_b, salt=0x21)
    if not (is_valid(tx_a) and is_valid(tx_b)):
        return
    merged = Transaction(
        2,
        0,
        tx_a.inputs + tx_b.inputs,
        tx_a.outputs + tx_b.outputs,
    )
    assert is_valid(merged)
