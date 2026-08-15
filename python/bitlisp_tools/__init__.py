"""Front-end tooling over the bitlisp consensus package.

The authoring side of BitLisp: text s-expressions to program trees
and back, the spend runner, the pausable debug machine, and the
REPL. The compiler grows here in the next Phase 3 unit. Nothing in
this package is consensus code, and nothing in the consensus
package depends on it.
"""

from .keywords import ATOM_TO_NAME, NAME_TO_ATOM
from .printer import disassemble
from .reader import ParseError, assemble, assemble_many, definable
from .stepper import DebugMachine

__all__ = [
    "ATOM_TO_NAME",
    "NAME_TO_ATOM",
    "DebugMachine",
    "ParseError",
    "assemble",
    "assemble_many",
    "definable",
    "disassemble",
]
