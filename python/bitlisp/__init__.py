"""BitLisp reference implementation.

This package is the executable specification. Every consensus-relevant
behavior implemented here cites a section of spec/ (ground rule 1 in
CLAUDE.md).
"""

from .errors import CODES, BitLispError
from .machine import run, run_serialized
from .serialize import deserialize, serialize
from .sexp import NIL, TRUE, atom_to_int, int_to_atom, is_atom, is_pair

__version__ = "0.0.1"

__all__ = [
    "BitLispError",
    "CODES",
    "NIL",
    "TRUE",
    "atom_to_int",
    "deserialize",
    "int_to_atom",
    "is_atom",
    "is_pair",
    "run",
    "run_serialized",
    "serialize",
]
