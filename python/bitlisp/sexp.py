"""Value model: atoms are bytes, pairs are 2-tuples.

Integers are atoms read as signed big-endian two's complement, the
empty atom is zero, and results of integer operators are always
minimally encoded.
"""

from .errors import BitLispError

NIL = b""
TRUE = b"\x01"


def is_atom(node):
    return isinstance(node, bytes)


def is_pair(node):
    return isinstance(node, tuple)


def atom_to_int(atom):
    """Signed big-endian two's complement, empty atom is zero."""
    return int.from_bytes(atom, "big", signed=True)


def int_to_atom(value):
    """Minimal signed encoding, zero is the empty atom."""
    if value == 0:
        return NIL
    length = (value.bit_length() + 8) // 8
    encoded = value.to_bytes(length, "big", signed=True)
    # For values like -128 and -32768 (exactly -(2**(8k-1))) the
    # formula above overshoots by one byte: strip the redundant 0xff.
    if len(encoded) > 1 and encoded[0] == 0xFF and encoded[1] >= 0x80:
        encoded = encoded[1:]
    return encoded


def iter_proper_list(node):
    """Yields the elements of a proper list, else raises bad_arg_list."""
    while node != NIL:
        if not is_pair(node):
            raise BitLispError("bad_arg_list", "operator arguments improper list")
        yield node[0]
        node = node[1]
