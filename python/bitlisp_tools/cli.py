"""The one-shot command surface: bitlisp-run, bitlisp-asm, bitlisp-disasm.

Each command is a thin main over the tools library. bitlisp-run runs
one spend and reports the verdict. bitlisp-asm assembles a text
s-expression to serialized bytecode hex. bitlisp-disasm renders
serialized hex back as text.
"""

import argparse
import contextlib
import json
import os
import sys

from bitlisp import BitLispError, deserialize, serialize

from .printer import disassemble
from .reader import ParseError, assemble
from .runner import (
    DEFAULT_MAX_COST,
    ContextError,
    load_context,
    render_condition,
    run_spend,
)

_RUN_DOC = """Run one BitLisp spend and report the verdict.

Takes a program, an optional solution, and a transaction context,
runs evaluation, condition parsing, and full validation as one
chain, and prints each emitted condition, the verdict, and the
cost, or the error that stopped the chain.

The program and solution arguments name a file when one exists at
that path and read as literal text otherwise. A file that exists
but does not open is an error, never a literal. Text is the
s-expression syntax. With --hex both read as serialized hex
bytecode instead. An omitted solution is nil.

The context argument is always a path to a JSON file holding one
transaction object:

    {"version": 2, "locktime": 0,
     "inputs": [{"txid": "<hex>", "index": 0,
                 "script_pubkey": "<hex>", "amount": 1000,
                 "sequence": <int, optional>,
                 "script_sig": "<hex, optional>",
                 "conditions": "<hex node, optional>"}],
     "outputs": [{"script_pubkey": "<hex>", "amount": 600}]}

--input selects which input the program spends, the first by
default. That input must not carry a conditions field, because the
runner computes its conditions. Any other input carrying one is a
BitLisp input whose evaluation result is taken as given.

Exit status 0 when the spend is valid, 1 when it is invalid with
the error line pinning the consensus code, 2 for unusable input: a
program that does not parse, hex that does not decode, or a context
file that does not match the shape above.

Usage:
    bitlisp-run "(q (1 0x0014<hex> 600))" tx.json
    bitlisp-run puzzle.bl solution.bl tx.json --input 1
    bitlisp-run --hex ff01<hex> 80 tx.json
"""

_ASM_DOC = """Assemble a text s-expression to serialized bytecode hex.

The argument names a file when one exists at that path and reads as
literal text otherwise. With no argument the text is read from
stdin. Prints one line of lowercase hex.

Exit status 0 on success, 2 when the text does not parse or the
file does not open.

Usage:
    bitlisp-asm "(+ (q . 2) (q . 3))"
    bitlisp-asm puzzle.bl
    echo "(q . 1)" | bitlisp-asm
"""

_DISASM_DOC = """Render serialized bytecode hex as a text s-expression.

The argument names a file when one exists at that path and reads as
literal hex otherwise. With no argument the hex is read from stdin.
Deserialization is strict, accepting only the unique canonical
encoding, and the error line carries the consensus error code when
it rejects the bytes.

Exit status 0 on success, 2 when the hex does not decode or the
file does not open.

Usage:
    bitlisp-disasm ff10ffff0102ffff010380
    echo ff10ffff0102ffff010380 | bitlisp-disasm
"""


def _path_or_code(arg):
    """The argument is the file's content when one exists at that
    path, and the literal otherwise. Existence alone selects file
    treatment, and exists() is false for any string no file could
    have as its name. An existing file that then fails to open is an
    error, never a literal that happens to run, so a permission bit
    cannot flip the verdict."""
    if os.path.exists(arg):
        with open(arg) as handle:
            return handle.read()
    return arg


def _node(source, as_hex):
    return deserialize(bytes.fromhex(source)) if as_hex else assemble(source)


@contextlib.contextmanager
def _pipe_shield():
    """On a broken pipe, points stdout at devnull so the interpreter's
    exit flush cannot raise a second time. A downstream reader that
    stops listening does not change the exit status."""
    try:
        yield
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bitlisp-run",
        description=_RUN_DOC,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("program", help="file path, or the literal program")
    parser.add_argument(
        "solution",
        nargs="?",
        help="file path, or the literal solution (default nil)",
    )
    parser.add_argument("context", help="JSON file holding the transaction object")
    parser.add_argument(
        "--hex",
        action="store_true",
        help="read program and solution as serialized hex bytecode",
    )
    parser.add_argument(
        "--input",
        type=int,
        default=0,
        metavar="N",
        help="index of the transaction input being spent",
    )
    parser.add_argument(
        "--max-cost",
        type=int,
        default=DEFAULT_MAX_COST,
        metavar="N",
        help="inclusive cost budget for evaluation and condition parsing",
    )
    args = parser.parse_args(argv)

    # An omitted or empty solution takes the nil default directly,
    # never the file-or-literal treatment, so a stray file named 80
    # or () cannot shadow it.
    if args.solution:
        solution_source = _path_or_code(args.solution)
    else:
        solution_source = "80" if args.hex else "()"

    try:
        program = _node(_path_or_code(args.program), args.hex)
        solution = _node(solution_source, args.hex)
        with open(args.context) as handle:
            tx = load_context(json.load(handle))
        cost, conditions = run_spend(program, solution, tx, args.input, args.max_cost)
    except BitLispError as exc:
        print(f"invalid: {exc.code}: {exc}", file=sys.stderr)
        return 1
    except (ContextError, ParseError, OSError, RecursionError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with _pipe_shield():
        for condition in conditions:
            print(render_condition(condition))
        print(f"valid: {len(conditions)} condition(s), cost {cost} of {args.max_cost}")
    return 0


def asm_main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bitlisp-asm",
        description=_ASM_DOC,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "program",
        nargs="?",
        help="file path, or the literal text (default stdin)",
    )
    args = parser.parse_args(argv)
    try:
        if args.program is None:
            text = sys.stdin.read()
        else:
            text = _path_or_code(args.program)
        line = serialize(assemble(text)).hex()
    except BitLispError as exc:
        print(f"error: {exc.code}: {exc}", file=sys.stderr)
        return 2
    except (ParseError, OSError, ValueError) as exc:
        # ValueError covers a UnicodeDecodeError from reading a
        # non-UTF-8 file or stream.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with _pipe_shield():
        print(line)
    return 0


def disasm_main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bitlisp-disasm",
        description=_DISASM_DOC,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "bytecode",
        nargs="?",
        help="file path, or the literal hex (default stdin)",
    )
    args = parser.parse_args(argv)
    try:
        if args.bytecode is None:
            text = sys.stdin.read()
        else:
            text = _path_or_code(args.bytecode)
        line = disassemble(deserialize(bytes.fromhex(text.strip())))
    except BitLispError as exc:
        print(f"error: {exc.code}: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with _pipe_shield():
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
