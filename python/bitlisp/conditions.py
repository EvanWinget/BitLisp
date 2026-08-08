"""Condition-list parsing and validation.

A successful program evaluation yields a condition list: a proper list
of conditions, each a proper list opening with a one-byte opcode atom.
Opcode values fall in three tiers. Assigned values carry the
vocabulary's semantics under strict arity and minimal integer
encodings. Values 0x80 and above are reserved: accepted with a
declared cost and no enforced semantics, the forward-compatibility
hatch a later soft fork can tighten into real conditions. Everything
else is invalid, so a typo near a real opcode fails loudly instead of
becoming an accidental no-op.
"""

from dataclasses import dataclass

from . import secp256k1
from .errors import BitLispError
from .sexp import NIL, atom_to_int, int_to_atom, is_atom, is_pair

MAX_MONEY = 2_100_000_000_000_000
MAX_SCRIPT_PUBKEY_SIZE = 10_000
RESERVED_COST_FLOOR = 500

CREATE_OUTPUT = 0x01
CREATE_OUTPUT_TAPROOT = 0x02
ASSERT_LOCKTIME_HEIGHT = 0x20
ASSERT_LOCKTIME_TIME = 0x21
ASSERT_SEQUENCE_HEIGHT = 0x22
ASSERT_SEQUENCE_TIME = 0x23
ANNOUNCE = 0x40
ASSERT_ANNOUNCEMENT = 0x41
SEND_MESSAGE = 0x42
RECEIVE_MESSAGE = 0x43
_RESERVED_START = 0x80

MAX_MESSAGE_SIZE = 1024
OUTPOINT_SIZE = 36

# A participant specifier names an input's prevout data at one of
# eight precisions. The commitment value's bits select the fields:
# 0b100 the creating txid, 0b010 the spent scriptPubKey, 0b001 the
# amount, except that 0b111 commits to the whole outpoint as a
# single 36-byte value rather than the three fields separately.
SPECIFIER_OPERANDS = {
    0b000: (),
    0b001: ("amount",),
    0b010: ("script_pubkey",),
    0b011: ("script_pubkey", "amount"),
    0b100: ("txid",),
    0b101: ("txid", "amount"),
    0b110: ("txid", "script_pubkey"),
    0b111: ("outpoint",),
}

# A locktime below the threshold counts blocks, at or above it counts
# Unix seconds. Operand domains exclude the wrong-typed range, so a
# mistyped operand is malformed here at parse rather than
# unsatisfiable later against the field.
LOCKTIME_THRESHOLD = 500_000_000
LOCKTIME_MAX = 0xFFFFFFFF
SEQUENCE_VALUE_MAX = 0xFFFF


@dataclass(frozen=True)
class CreateOutput:
    """Claims one output slot with exactly this content."""

    script_pubkey: bytes
    amount: int

    opcode = CREATE_OUTPUT


@dataclass(frozen=True)
class CreateOutputTaproot:
    """Claims one output slot with derived taproot content.

    script_pubkey is computed from internal_key and merkle_root at
    parse time. The claimed slot content is (script_pubkey, amount),
    exactly as for CreateOutput.
    """

    internal_key: bytes
    merkle_root: bytes
    amount: int
    script_pubkey: bytes

    opcode = CREATE_OUTPUT_TAPROOT


@dataclass(frozen=True)
class AssertLocktimeHeight:
    """Asserts a non-final own sequence and a height-typed locktime
    at or above height."""

    height: int

    opcode = ASSERT_LOCKTIME_HEIGHT


@dataclass(frozen=True)
class AssertLocktimeTime:
    """Asserts a non-final own sequence and a time-typed locktime at
    or above time."""

    time: int

    opcode = ASSERT_LOCKTIME_TIME


@dataclass(frozen=True)
class AssertSequenceHeight:
    """Asserts version 2, an enabled height-typed own sequence whose
    value is at least blocks."""

    blocks: int

    opcode = ASSERT_SEQUENCE_HEIGHT


@dataclass(frozen=True)
class AssertSequenceTime:
    """Asserts version 2, an enabled time-typed own sequence whose
    value, in 512-second units, is at least units."""

    units: int

    opcode = ASSERT_SEQUENCE_TIME


@dataclass(frozen=True)
class Specifier:
    """A participant specifier: a commitment value and the fields it
    commits to, in SPECIFIER_OPERANDS order. Equality is the rule 3
    definition: equal commitment value and equal fields, so a
    36-byte outpoint specifier never equals a txid-and-script one,
    whatever coin each names."""

    commitment: int
    fields: tuple


@dataclass(frozen=True)
class Announce:
    """Creates the announcement (this input, namespace, payload).
    Constrains nothing by itself."""

    namespace: bytes
    payload: bytes

    opcode = ANNOUNCE


@dataclass(frozen=True)
class AssertAnnouncement:
    """Asserts some input announced (namespace, payload) and matches
    the announcer specifier."""

    announcer: Specifier
    namespace: bytes
    payload: bytes

    opcode = ASSERT_ANNOUNCEMENT


@dataclass(frozen=True)
class SendMessage:
    """Weight +1 in the message ledger. The sender half describes the
    emitting input itself, so only its commitment value is stored
    here. The receiver is the argument specifier."""

    sender_commitment: int
    receiver: Specifier
    message: bytes

    opcode = SEND_MESSAGE


@dataclass(frozen=True)
class ReceiveMessage:
    """Weight -1 in the message ledger. The receiver half describes
    the emitting input itself, the sender is the argument
    specifier."""

    sender: Specifier
    receiver_commitment: int
    message: bytes

    opcode = RECEIVE_MESSAGE


@dataclass(frozen=True)
class Reserved:
    """No enforced semantics, only the declared cost. args holds the
    raw argument nodes after the cost, unconstrained by design."""

    opcode: int
    cost: int
    args: tuple


def _iter_conditions(node, what):
    """Yields the elements of a proper list, else bad_condition_list."""
    while node != NIL:
        if not is_pair(node):
            raise BitLispError("bad_condition_list", f"{what} is an improper list")
        yield node[0]
        node = node[1]


def _parse_int(atom, what):
    if not is_atom(atom):
        raise BitLispError("bad_condition_arg", f"{what} must be an atom")
    value = atom_to_int(atom)
    if int_to_atom(value) != atom:
        raise BitLispError("bad_condition_arg", f"{what} not minimally encoded")
    return value


def _parse_create_output(args):
    if len(args) != 2:
        raise BitLispError(
            "bad_condition_arity", f"CREATE_OUTPUT takes 2 arguments, got {len(args)}"
        )
    script_pubkey, amount_atom = args
    if not is_atom(script_pubkey):
        raise BitLispError("bad_condition_arg", "scriptPubKey must be an atom")
    if not 1 <= len(script_pubkey) <= MAX_SCRIPT_PUBKEY_SIZE:
        raise BitLispError(
            "bad_condition_arg",
            f"scriptPubKey must be 1 to {MAX_SCRIPT_PUBKEY_SIZE} bytes, "
            f"got {len(script_pubkey)}",
        )
    amount = _parse_int(amount_atom, "CREATE_OUTPUT amount")
    if not 0 <= amount <= MAX_MONEY:
        raise BitLispError("bad_condition_arg", f"amount out of range: {amount}")
    return CreateOutput(script_pubkey, amount)


def _parse_create_output_taproot(args):
    if len(args) != 3:
        raise BitLispError(
            "bad_condition_arity",
            f"CREATE_OUTPUT_TAPROOT takes 3 arguments, got {len(args)}",
        )
    internal_key, merkle_root, amount_atom = args
    if not is_atom(internal_key):
        raise BitLispError("bad_condition_arg", "internal key must be an atom")
    if len(internal_key) != 32:
        raise BitLispError(
            "bad_condition_arg",
            f"internal key must be 32 bytes, got {len(internal_key)}",
        )
    if not is_atom(merkle_root):
        raise BitLispError("bad_condition_arg", "merkle root must be an atom")
    if len(merkle_root) not in (0, 32):
        raise BitLispError(
            "bad_condition_arg",
            f"merkle root must be 0 or 32 bytes, got {len(merkle_root)}",
        )
    amount = _parse_int(amount_atom, "CREATE_OUTPUT_TAPROOT amount")
    if not 0 <= amount <= MAX_MONEY:
        raise BitLispError("bad_condition_arg", f"amount out of range: {amount}")
    output_key = secp256k1.taproot_output_key(internal_key, merkle_root)
    if output_key is None:
        raise BitLispError(
            "bad_condition_arg", "internal key and merkle root derive no output key"
        )
    script_pubkey = b"\x51\x20" + output_key
    return CreateOutputTaproot(internal_key, merkle_root, amount, script_pubkey)


def _parse_time_assert(args, name, cls, low, high):
    """One plain-quantity operand whose domain is [low, high]."""
    if len(args) != 1:
        raise BitLispError(
            "bad_condition_arity", f"{name} takes 1 argument, got {len(args)}"
        )
    value = _parse_int(args[0], f"{name} operand")
    if not low <= value <= high:
        raise BitLispError(
            "bad_condition_arg",
            f"{name} operand must be {low} to {high}, got {value}",
        )
    return cls(value)


def _parse_payload_atom(atom, what):
    """A message, namespace, or payload: an atom of 0 to 1024 bytes."""
    if not is_atom(atom):
        raise BitLispError("bad_condition_arg", f"{what} must be an atom")
    if len(atom) > MAX_MESSAGE_SIZE:
        raise BitLispError(
            "bad_condition_arg",
            f"{what} must be at most {MAX_MESSAGE_SIZE} bytes, got {len(atom)}",
        )
    return atom


def _parse_specifier(commitment, args, name):
    """Parses the specifier operands for a commitment value. The
    caller has already checked the argument count."""
    fields = []
    for kind, atom in zip(SPECIFIER_OPERANDS[commitment], args, strict=True):
        if kind == "amount":
            value = _parse_int(atom, f"{name} specifier amount")
            if not 0 <= value <= MAX_MONEY:
                raise BitLispError(
                    "bad_condition_arg", f"specifier amount out of range: {value}"
                )
            fields.append(value)
            continue
        if not is_atom(atom):
            raise BitLispError("bad_condition_arg", f"{name} {kind} must be an atom")
        if kind == "txid" and len(atom) != 32:
            raise BitLispError(
                "bad_condition_arg",
                f"{name} txid must be 32 bytes, got {len(atom)}",
            )
        if kind == "script_pubkey" and len(atom) > MAX_SCRIPT_PUBKEY_SIZE:
            raise BitLispError(
                "bad_condition_arg",
                f"{name} scriptPubKey must be at most "
                f"{MAX_SCRIPT_PUBKEY_SIZE} bytes, got {len(atom)}",
            )
        if kind == "outpoint" and len(atom) != OUTPOINT_SIZE:
            raise BitLispError(
                "bad_condition_arg",
                f"{name} outpoint must be {OUTPOINT_SIZE} bytes, got {len(atom)}",
            )
        fields.append(atom)
    return Specifier(commitment, tuple(fields))


def _parse_mode(atom, name, high):
    value = _parse_int(atom, f"{name} mode")
    if not 0 <= value <= high:
        raise BitLispError(
            "bad_condition_arg", f"{name} mode must be 0 to {high}, got {value}"
        )
    return value


def _parse_message_pair(args, name, self_half_high):
    """Shared parse for the addressed pair: mode, message, then the
    specifier operands for the argument half. self_half_high says
    whether the emitting input's own half is the mode's high bits
    (SEND_MESSAGE) or its low bits (RECEIVE_MESSAGE)."""
    if len(args) < 2:
        raise BitLispError(
            "bad_condition_arity",
            f"{name} takes at least 2 arguments, got {len(args)}",
        )
    mode = _parse_mode(args[0], name, 63)
    self_half = (mode >> 3) & 0b111 if self_half_high else mode & 0b111
    arg_half = mode & 0b111 if self_half_high else (mode >> 3) & 0b111
    expected = 2 + len(SPECIFIER_OPERANDS[arg_half])
    if len(args) != expected:
        raise BitLispError(
            "bad_condition_arity",
            f"{name} with mode {mode} takes {expected} arguments, got {len(args)}",
        )
    message = _parse_payload_atom(args[1], f"{name} message")
    specifier = _parse_specifier(arg_half, args[2:], name)
    return mode, self_half, specifier, message


def _parse_send_message(args):
    _, self_half, receiver, message = _parse_message_pair(
        args, "SEND_MESSAGE", self_half_high=True
    )
    return SendMessage(self_half, receiver, message)


def _parse_receive_message(args):
    _, self_half, sender, message = _parse_message_pair(
        args, "RECEIVE_MESSAGE", self_half_high=False
    )
    return ReceiveMessage(sender, self_half, message)


def _parse_announce(args):
    if len(args) != 2:
        raise BitLispError(
            "bad_condition_arity", f"ANNOUNCE takes 2 arguments, got {len(args)}"
        )
    namespace = _parse_payload_atom(args[0], "ANNOUNCE namespace")
    payload = _parse_payload_atom(args[1], "ANNOUNCE payload")
    return Announce(namespace, payload)


def _parse_assert_announcement(args):
    if len(args) < 3:
        raise BitLispError(
            "bad_condition_arity",
            f"ASSERT_ANNOUNCEMENT takes at least 3 arguments, got {len(args)}",
        )
    mode = _parse_mode(args[0], "ASSERT_ANNOUNCEMENT", 7)
    expected = 3 + len(SPECIFIER_OPERANDS[mode])
    if len(args) != expected:
        raise BitLispError(
            "bad_condition_arity",
            f"ASSERT_ANNOUNCEMENT with mode {mode} takes {expected} "
            f"arguments, got {len(args)}",
        )
    namespace = _parse_payload_atom(args[1], "ASSERT_ANNOUNCEMENT namespace")
    payload = _parse_payload_atom(args[2], "ASSERT_ANNOUNCEMENT payload")
    announcer = _parse_specifier(mode, args[3:], "ASSERT_ANNOUNCEMENT")
    return AssertAnnouncement(announcer, namespace, payload)


def _parse_reserved(opcode, args):
    if not args:
        raise BitLispError(
            "bad_condition_arity", "reserved condition missing its declared cost"
        )
    cost = _parse_int(args[0], "declared cost")
    if cost < 0:
        raise BitLispError("bad_condition_arg", f"declared cost negative: {cost}")
    if cost < RESERVED_COST_FLOOR:
        raise BitLispError(
            "reserved_cost_too_low",
            f"declared cost {cost} below floor {RESERVED_COST_FLOOR}",
        )
    return Reserved(opcode, cost, tuple(args[1:]))


def _parse_condition(node):
    if not is_pair(node):
        raise BitLispError("bad_condition_list", "condition is not a list")
    items = list(_iter_conditions(node, "condition"))
    opcode_atom = items[0]
    if not is_atom(opcode_atom) or len(opcode_atom) != 1:
        raise BitLispError(
            "bad_condition_opcode", "opcode must be an atom of exactly one byte"
        )
    opcode = opcode_atom[0]
    args = items[1:]
    if opcode >= _RESERVED_START:
        return _parse_reserved(opcode, args)
    if opcode == CREATE_OUTPUT:
        return _parse_create_output(args)
    if opcode == CREATE_OUTPUT_TAPROOT:
        return _parse_create_output_taproot(args)
    if opcode == ASSERT_LOCKTIME_HEIGHT:
        return _parse_time_assert(
            args,
            "ASSERT_LOCKTIME_HEIGHT",
            AssertLocktimeHeight,
            0,
            LOCKTIME_THRESHOLD - 1,
        )
    if opcode == ASSERT_LOCKTIME_TIME:
        return _parse_time_assert(
            args,
            "ASSERT_LOCKTIME_TIME",
            AssertLocktimeTime,
            LOCKTIME_THRESHOLD,
            LOCKTIME_MAX,
        )
    if opcode == ASSERT_SEQUENCE_HEIGHT:
        return _parse_time_assert(
            args,
            "ASSERT_SEQUENCE_HEIGHT",
            AssertSequenceHeight,
            0,
            SEQUENCE_VALUE_MAX,
        )
    if opcode == ASSERT_SEQUENCE_TIME:
        return _parse_time_assert(
            args,
            "ASSERT_SEQUENCE_TIME",
            AssertSequenceTime,
            0,
            SEQUENCE_VALUE_MAX,
        )
    if opcode == ANNOUNCE:
        return _parse_announce(args)
    if opcode == ASSERT_ANNOUNCEMENT:
        return _parse_assert_announcement(args)
    if opcode == SEND_MESSAGE:
        return _parse_send_message(args)
    if opcode == RECEIVE_MESSAGE:
        return _parse_receive_message(args)
    raise BitLispError("bad_condition_opcode", f"invalid opcode {opcode:#04x}")


def parse_conditions(node):
    """Parses an evaluation result into a tuple of conditions.

    Raises BitLispError on any encoding violation. Order is the
    emitted order.
    """
    return tuple(
        _parse_condition(element)
        for element in _iter_conditions(node, "condition list")
    )
