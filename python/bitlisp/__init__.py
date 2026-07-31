"""BitLisp reference implementation.

This package is the executable specification: small, boring, and
readable whole. Behavior is pinned by the vector corpus, by
differential testing against the consensus oracle where one exists,
and by property-based invariants where none does.
"""

from .conditions import MAX_MONEY, CreateOutput, Reserved, parse_conditions
from .errors import CODES, BitLispError
from .machine import run, run_serialized
from .matching import validate_transaction
from .serialize import deserialize, serialize
from .sexp import NIL, TRUE, atom_to_int, int_to_atom, is_atom, is_pair
from .tx import Transaction, TxInput, TxOutput

__version__ = "0.0.1"

__all__ = [
    "BitLispError",
    "CODES",
    "CreateOutput",
    "MAX_MONEY",
    "NIL",
    "Reserved",
    "TRUE",
    "Transaction",
    "TxInput",
    "TxOutput",
    "atom_to_int",
    "deserialize",
    "int_to_atom",
    "is_atom",
    "is_pair",
    "parse_conditions",
    "run",
    "run_serialized",
    "serialize",
    "validate_transaction",
]
