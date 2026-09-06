"""Front-end tooling over the bitlisp consensus package.

The authoring side of BitLisp: text s-expressions to program trees
and back, the v0 language compiler, the spend runner, the pausable
debug machine, and the REPL. Nothing in this package is consensus
code, and nothing in the consensus package depends on it.
"""

from bitlisp.commitment import tree_hash

from .compiler import (
    CONDITION_CONSTANTS,
    RESERVED_WORDS,
    CompileError,
    Definitions,
    compile_expression,
    compile_program,
    load_symbols,
    parse_source,
    parse_source_many,
    symbols_to_json,
)
from .curry import curry, uncurry
from .keywords import ATOM_TO_NAME, NAME_TO_ATOM
from .printer import disassemble
from .reader import ParseError, UnknownSymbol, assemble, assemble_many, definable
from .stepper import DebugMachine

__all__ = [
    "ATOM_TO_NAME",
    "CONDITION_CONSTANTS",
    "NAME_TO_ATOM",
    "RESERVED_WORDS",
    "CompileError",
    "DebugMachine",
    "Definitions",
    "ParseError",
    "UnknownSymbol",
    "assemble",
    "assemble_many",
    "compile_expression",
    "compile_program",
    "curry",
    "definable",
    "disassemble",
    "load_symbols",
    "parse_source",
    "parse_source_many",
    "symbols_to_json",
    "tree_hash",
    "uncurry",
]
