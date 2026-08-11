"""Operator name tables for the text syntax.

NAME_TO_ATOM maps every operator name, quote and apply included, to
its single-byte opcode atom. The table is written out literally so a
reviewer can check it against the consensus operator set by eye, and
a test pins it against bitlisp's OPERATORS, QUOTE, and APPLY so a
drift between the two fails loudly.
"""

NAME_TO_ATOM = {
    "q": b"\x01",
    "a": b"\x02",
    "i": b"\x03",
    "c": b"\x04",
    "f": b"\x05",
    "r": b"\x06",
    "l": b"\x07",
    "x": b"\x08",
    "=": b"\x09",
    ">s": b"\x0a",
    "sha256": b"\x0b",
    "substr": b"\x0c",
    "strlen": b"\x0d",
    "concat": b"\x0e",
    "secp_verify": b"\x0f",
    "+": b"\x10",
    "-": b"\x11",
    "*": b"\x12",
    "/": b"\x13",
    "divmod": b"\x14",
    ">": b"\x15",
    "ash": b"\x16",
    "lsh": b"\x17",
    "logand": b"\x18",
    "logior": b"\x19",
    "logxor": b"\x1a",
    "lognot": b"\x1b",
    "not": b"\x20",
    "any": b"\x21",
    "all": b"\x22",
    "sha256tree": b"\x3f",
}

ATOM_TO_NAME = {atom: name for name, atom in NAME_TO_ATOM.items()}

if len(ATOM_TO_NAME) != len(NAME_TO_ATOM):
    raise AssertionError("NAME_TO_ATOM maps two names to one opcode")
