"""Disassembler: program trees to canonical text.

disassemble maps any node to one text spelling, and assembling that
spelling reproduces the identical node, non-UTF-8 atoms and improper
tails included. Operator names appear only in operator position, the
head of a printed list, because an atom carries no record of how it
was written and naming it anywhere else would suggest one.

Printing is iterative with an explicit task stack: tree depth must
not be limited by the Python recursion limit.
"""

from bitlisp.sexp import atom_to_int, int_to_atom

from .keywords import ATOM_TO_NAME

_STRING_MIN_BYTES = 3

# The decimal window is sign-split. Eight bytes of non-negative
# minimal encoding covers every satoshi amount, cost, height, and
# index an author reads as a number. Negative readings get only two
# bytes, the small-constant range -1 to -32768: half of random
# binary atoms lead with a byte of 0x80 or above, and a wider window
# would print that binary as plausible-looking negative integers.
# Hex is never misleading, a wrong decimal is.
_DECIMAL_MAX_BYTES = 8
_NEGATIVE_DECIMAL_MAX_BYTES = 2

_NODE = 0
_TAIL = 1


def _atom_text(atom, operator_position):
    """One atom as text: name, nil, string, decimal, or hex, in that order."""
    if operator_position:
        name = ATOM_TO_NAME.get(atom)
        if name is not None:
            return name
    if atom == b"":
        return "()"
    # Printable means every byte is ASCII space through tilde. The
    # string form is checked before the decimal form because every
    # printable atom is also some integer's minimal encoding.
    if len(atom) >= _STRING_MIN_BYTES and all(0x20 <= byte <= 0x7E for byte in atom):
        text = atom.decode("ascii")
        if '"' not in text:
            return '"' + text + '"'
        if "'" not in text:
            return "'" + text + "'"
        # No escape sequences exist, so contents holding both quote
        # characters have no string spelling and print as hex.
        return "0x" + atom.hex()
    if len(atom) <= _DECIMAL_MAX_BYTES:
        value = atom_to_int(atom)
        if int_to_atom(value) == atom and (
            value >= 0 or len(atom) <= _NEGATIVE_DECIMAL_MAX_BYTES
        ):
            return str(value)
    return "0x" + atom.hex()


def disassemble(node):
    """The canonical text spelling of a node, ValueError on a non-node."""
    pieces = []
    stack = [(_NODE, node, False)]
    while stack:
        kind, current, operator_position = stack.pop()
        if kind == _NODE:
            if isinstance(current, bytes):
                pieces.append(_atom_text(current, operator_position))
            elif isinstance(current, tuple) and len(current) == 2:
                pieces.append("(")
                stack.append((_TAIL, current[1], False))
                stack.append((_NODE, current[0], True))
            else:
                raise ValueError(f"not a node: {current!r}")
        elif isinstance(current, bytes):
            if current == b"":
                pieces.append(")")
            else:
                pieces.append(" . ")
                pieces.append(_atom_text(current, False))
                pieces.append(")")
        elif isinstance(current, tuple) and len(current) == 2:
            pieces.append(" ")
            stack.append((_TAIL, current[1], False))
            stack.append((_NODE, current[0], False))
        else:
            raise ValueError(f"not a node: {current!r}")
    return "".join(pieces)
