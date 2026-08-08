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
_RESERVED_START = 0x80

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
