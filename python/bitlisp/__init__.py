"""BitLisp reference implementation.

This package is the executable specification: small, boring, and
readable whole. Behavior is pinned by the vector corpus, by
differential testing against the consensus oracle where one exists,
and by property-based invariants where none does.
"""

from .commitment import BITLISP_LEAF_VERSION, tree_hash
from .conditions import (
    MAX_MONEY,
    Announce,
    AssertAnnouncement,
    AssertLocktimeHeight,
    AssertLocktimeTime,
    AssertSequenceHeight,
    AssertSequenceTime,
    Assure,
    CreateOutput,
    CreateOutputTaproot,
    Require,
    Reserved,
    Specifier,
    condition_cost,
    parse_conditions,
)
from .errors import CODES, BaseConsensusError, BitLispError
from .machine import run, run_serialized
from .serialize import deserialize, serialize
from .sexp import NIL, TRUE, atom_to_int, int_to_atom, is_atom, is_pair
from .spend import MAX_WITNESS_ELEMENT_SIZE, evaluate_spend
from .tx import Transaction, TxInput, TxOutput
from .validation import validate_transaction

__version__ = "0.0.1"

__all__ = [
    "Announce",
    "AssertAnnouncement",
    "AssertLocktimeHeight",
    "AssertLocktimeTime",
    "AssertSequenceHeight",
    "AssertSequenceTime",
    "BITLISP_LEAF_VERSION",
    "BaseConsensusError",
    "BitLispError",
    "CODES",
    "CreateOutput",
    "CreateOutputTaproot",
    "Specifier",
    "MAX_MONEY",
    "MAX_WITNESS_ELEMENT_SIZE",
    "NIL",
    "Require",
    "Reserved",
    "Assure",
    "TRUE",
    "Transaction",
    "TxInput",
    "TxOutput",
    "atom_to_int",
    "condition_cost",
    "deserialize",
    "evaluate_spend",
    "int_to_atom",
    "is_atom",
    "is_pair",
    "parse_conditions",
    "run",
    "run_serialized",
    "serialize",
    "tree_hash",
    "validate_transaction",
]
