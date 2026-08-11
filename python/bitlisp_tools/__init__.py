"""Front-end tooling over the bitlisp consensus package.

The authoring side of BitLisp: text s-expressions to program trees
and back. The runner, the REPL, and the compiler grow here in later
Phase 3 units. Nothing in this package is consensus code, and
nothing in the consensus package depends on it.
"""

from .keywords import ATOM_TO_NAME, NAME_TO_ATOM
from .printer import disassemble
from .reader import ParseError, assemble

__all__ = [
    "ATOM_TO_NAME",
    "NAME_TO_ATOM",
    "ParseError",
    "assemble",
    "disassemble",
]
