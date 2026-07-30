"""Condition-list parsing and validation.

A successful puzzle evaluation yields a condition list: a proper list
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

from .errors import BitLispError
from .sexp import NIL, atom_to_int, int_to_atom, is_atom, is_pair

MAX_MONEY = 2_100_000_000_000_000
MAX_SCRIPT_PUBKEY_SIZE = 10_000
RESERVED_COST_FLOOR = 500

CREATE_COIN = 0x01
_RESERVED_START = 0x80


@dataclass(frozen=True)
class CreateCoin:
    """Claims one output slot with exactly this content."""

    script_pubkey: bytes
    amount: int

    opcode = CREATE_COIN


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


def _parse_create_coin(args):
    if len(args) != 2:
        raise BitLispError(
            "bad_condition_arity", f"CREATE_COIN takes 2 arguments, got {len(args)}"
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
    amount = _parse_int(amount_atom, "CREATE_COIN amount")
    if not 0 <= amount <= MAX_MONEY:
        raise BitLispError("bad_condition_arg", f"amount out of range: {amount}")
    return CreateCoin(script_pubkey, amount)


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
    if opcode == CREATE_COIN:
        return _parse_create_coin(args)
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
