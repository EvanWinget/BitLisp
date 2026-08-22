"""The one-shot command surface: bitlisp-run, bitlisp-asm,
bitlisp-disasm, bitlisp-compile, bitlisp-curry, bitlisp-uncurry.

Each command is a thin main over the tools library. bitlisp-run runs
one spend and reports the verdict. bitlisp-asm assembles a text
s-expression to serialized bytecode hex. bitlisp-disasm renders
serialized hex back as text. bitlisp-compile compiles a source
program to serialized bytecode hex. bitlisp-curry fixes argument
values into a program and bitlisp-uncurry splits them back out. The
converters and bitlisp-curry take -T to print the program's tree
hash instead of their usual output.
"""

import argparse
import contextlib
import json
import os
import sys

from bitlisp import BitLispError, deserialize, serialize

from .compiler import CompileError, compile_program, symbols_to_json, tree_hash
from .curry import curry, uncurry
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
                 "conditions": "<hex node, optional>",
                 "tapleaf": "<hex, optional>",
                 "merkle_root": "<hex, optional>",
                 "internal_key": "<hex, optional>"}],
     "outputs": [{"script_pubkey": "<hex>", "amount": 600}]}

--input selects which input the program spends, the first by
default. That input must not carry a conditions field, because the
runner computes its conditions, and must carry tapleaf,
merkle_root, and internal_key, the executing input's identity. Any
other input carrying a conditions field is a BitLisp input whose
evaluation result is taken as given, and the model requires the
same identity triple on it.

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

With -T the output is the program's tree hash instead, the
sha256tree digest naming the tree, so the same program hashes
identically through every command that takes the flag.

Exit status 0 on success, 2 when the text does not parse or the
file does not open.

Usage:
    bitlisp-asm "(+ (q . 2) (q . 3))"
    bitlisp-asm puzzle.bl
    echo "(q . 1)" | bitlisp-asm
    bitlisp-asm -T "(+ 2 5)"
"""

_DISASM_DOC = """Render serialized bytecode hex as a text s-expression.

The argument names a file when one exists at that path and reads as
literal hex otherwise. With no argument the hex is read from stdin.
Deserialization is strict, accepting only the unique canonical
encoding, and the error line carries the consensus error code when
it rejects the bytes.

With -T the output is the program's tree hash instead of its text.
The hash names the decoded tree, not the encoding, so bitlisp-asm
-T and bitlisp-disasm -T print the same digest for the same
program.

Exit status 0 on success, 2 when the hex does not decode or the
file does not open.

Usage:
    bitlisp-disasm ff10ffff0102ffff010380
    echo ff10ffff0102ffff010380 | bitlisp-disasm
    bitlisp-disasm -T ff10ff02ff0580
"""


_COMPILE_DOC = """Compile a source program to serialized bytecode hex.

The input is one self-contained (program ...) form in the v0
authoring language. The argument names a file when one exists at
that path and reads as literal text otherwise. With no argument the
text is read from stdin. Prints one line of lowercase hex.

-I adds a directory to the include search path, repeatable and
searched in flag order, first match winning. A program's (include
"file") declarations resolve only through this path, never an
implicit current directory, so what a program compiles to never
depends on where the command runs.

--symbols writes the program's symbol table, a JSON object mapping
the tree hash of each compiled function body to its name and
parameter names. The REPL's sym command loads it, so bytecode
compiled here debugs with source names.

With -T the output is the whole compiled program's tree hash
instead of its hex, a different digest from the per-function-body
hashes keying the symbol table. --symbols still writes either way.

Exit status 0 on success, 2 when the source does not compile, the
file does not open, or the symbol file does not write.

Usage:
    bitlisp-compile "(program (X) (defun double (N) (* 2 N)) (double X))"
    bitlisp-compile puzzle.bl --symbols puzzle.sym
    bitlisp-compile puzzle.bl -I lib | bitlisp-disasm
    bitlisp-compile -T puzzle.bl
"""


_CURRY_DOC = """Fix argument values into a program, making a new program.

The program is serialized bytecode hex, naming a file when one
exists at that path and reading as literal hex otherwise. With no
program argument the hex is read from stdin, so the command
composes with bitlisp-asm and bitlisp-compile in a pipeline. Each
--arg is a text s-expression value, fixed in the order given.
Prints the curried program as one line of lowercase hex.

The curried program applies the original with the fixed values
placed ahead of the environment, so a program taking (A B C)
curried with one value becomes a program taking (B C). With no
--arg the wrapper is still built, a curry of zero values.

With -T the output is the curried program's tree hash instead of
its hex, the identity an output would commit to.

Exit status 0 on success, 2 when the hex does not decode, a value
does not parse, or the file does not open.

Usage:
    bitlisp-curry ff10ff02ff0580 --arg 10
    bitlisp-curry puzzle.hex --arg 0x0014ab --arg 600
    bitlisp-compile puzzle.bl | bitlisp-curry -a 600 -T
"""


_UNCURRY_DOC = """Split a curried program back into program and values.

The argument is serialized bytecode hex, naming a file when one
exists at that path and reading as literal hex otherwise, or stdin
when omitted. Prints the inner program's hex on the first line,
then one fixed value per line as text, in currying order. A curry
of zero values prints only the program line.

The shape check is strict: input that decodes but is not exactly
the curried shape is an error, never a partial answer. The check
proves shape, not history: a compiled program that declares
functions has the same shape, so it splits into its main body and
its function tree, and a zero exit status is never evidence that
currying happened.

Exit status 0 on success, 2 when the hex does not decode, the tree
is not a curried program, or the file does not open.

Usage:
    bitlisp-uncurry ff02ffff01ff10ff02ff0580ffff04ffff010aff018080
    bitlisp-compile puzzle.bl | bitlisp-curry -a 600 | bitlisp-uncurry
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


def _input_text(arg):
    """The named file or the literal, or stdin when the argument
    is omitted, one reading shared by every one-shot main."""
    if arg is None:
        return sys.stdin.read()
    return _path_or_code(arg)


def _node(source, as_hex):
    return deserialize(bytes.fromhex(source.strip())) if as_hex else assemble(source)


def _tree_hash_flag(parser, usual):
    parser.add_argument(
        "-T",
        "--tree-hash",
        action="store_true",
        help=f"print the program's tree hash instead of {usual}",
    )


@contextlib.contextmanager
def _pipe_shield():
    """On a broken pipe, points stdout at devnull so the interpreter's
    exit flush cannot raise a second time. A downstream reader that
    stops listening does not change the exit status.

    The flush inside the shield forces any buffered tail onto the
    pipe here, where the except arm can catch the failure. Without
    it, output small enough to sit in the stream buffer past the
    last print would first touch a dead pipe during interpreter
    shutdown, whose failed flush exits 120 outside any handler."""
    try:
        yield
        sys.stdout.flush()
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
    _tree_hash_flag(parser, "the hex")
    args = parser.parse_args(argv)
    try:
        node = assemble(_input_text(args.program))
        line = tree_hash(node).hex() if args.tree_hash else serialize(node).hex()
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
    _tree_hash_flag(parser, "the text")
    args = parser.parse_args(argv)
    try:
        node = _node(_input_text(args.bytecode), True)
        line = tree_hash(node).hex() if args.tree_hash else disassemble(node)
    except BitLispError as exc:
        print(f"error: {exc.code}: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with _pipe_shield():
        print(line)
    return 0


def compile_main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bitlisp-compile",
        description=_COMPILE_DOC,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="file path, or the literal source text (default stdin)",
    )
    parser.add_argument(
        "--symbols",
        metavar="PATH",
        help="write the symbol table as JSON to this path",
    )
    parser.add_argument(
        "-I",
        "--include",
        action="append",
        default=[],
        metavar="PATH",
        help="add a directory to the include search path, repeatable, "
        "searched in order",
    )
    _tree_hash_flag(parser, "the hex")
    args = parser.parse_args(argv)
    try:
        program, table = compile_program(_input_text(args.source), tuple(args.include))
        line = tree_hash(program).hex() if args.tree_hash else serialize(program).hex()
        if args.symbols is not None:
            with open(args.symbols, "w") as handle:
                json.dump(symbols_to_json(table), handle)
                handle.write("\n")
    except BitLispError as exc:
        # A converter issues no spend verdict, so even a pinned code
        # reports as unusable input.
        print(f"error: {exc.code}: {exc}", file=sys.stderr)
        return 2
    except (CompileError, ParseError, OSError, RecursionError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with _pipe_shield():
        print(line)
    return 0


def curry_main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bitlisp-curry",
        description=_CURRY_DOC,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "program",
        nargs="?",
        help="file path, or the literal hex (default stdin)",
    )
    parser.add_argument(
        "-a",
        "--arg",
        action="append",
        default=[],
        metavar="SEXPR",
        help="a text s-expression value to fix, repeatable, in order",
    )
    _tree_hash_flag(parser, "the hex")
    args = parser.parse_args(argv)
    try:
        program = _node(_input_text(args.program), True)
        curried = curry(program, [assemble(value) for value in args.arg])
        line = tree_hash(curried).hex() if args.tree_hash else serialize(curried).hex()
    except BitLispError as exc:
        print(f"error: {exc.code}: {exc}", file=sys.stderr)
        return 2
    except (ParseError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with _pipe_shield():
        print(line)
    return 0


def uncurry_main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bitlisp-uncurry",
        description=_UNCURRY_DOC,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "bytecode",
        nargs="?",
        help="file path, or the literal hex (default stdin)",
    )
    args = parser.parse_args(argv)
    try:
        program, values = uncurry(_node(_input_text(args.bytecode), True))
        if values is None:
            print("error: not a curried program", file=sys.stderr)
            return 2
        lines = [serialize(program).hex()]
        lines.extend(disassemble(value) for value in values)
    except BitLispError as exc:
        print(f"error: {exc.code}: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with _pipe_shield():
        for line in lines:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
