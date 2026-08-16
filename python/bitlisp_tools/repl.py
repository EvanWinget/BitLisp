"""The interactive REPL with the stepping debugger.

Evaluation:
    eval <program> [<solution>]    run on the reference VM
    (<program>)                    a bare s-expression runs as eval
    spend <program> [<solution>]   the full spend pipeline against
                                   the loaded transaction context
    asm <sexpr>                    serialized bytecode hex for text
    disasm <hex>                   text for serialized bytecode hex

Transaction context:
    tx [<path>]                    load a JSON context, or show it
    input <n>                      select the input being spent
    maxcost [<n>]                  show or set the cost budget

Definitions:
    (defun <name> <params> <body>)   define a named function
    (defconstant <name> <value>)     define a constant
    def <name> <sexpr>             bind a name to a parsed node
    undef <name>                   remove a definition or binding
    defs                           list definitions and bindings
    compile <expr>                 show an expression's compiled tree
    sym <path>                     load a bitlisp-compile symbol file

Currying and identity:
    curry <program> <value> ...    fix the values into the program,
                                   printing the curried program
    uncurry <program>              split a curried program back into
                                   program and fixed values
    treehash <program>             the program's tree hash

Debugger:
    debug <program> [<solution>]   open a stepping session
    step                           execute one task, show the stacks
    next                           step over: the pending task's
                                   whole subtree
    cont                           continue: run to the result
    trace                          run to the result showing every
                                   step
    abort                          discard the session

Session:
    source <path>                  run commands from a file
    help [<command>]               this table, or one command
    exit, quit, EOF                leave

Lines starting with ; are comments. Definitions substitute only
where a bare symbol would otherwise be unknown, so a binding can
never change the meaning of text that already parses.

The same rule shapes the compiler surface: eval, spend, and debug
read their text as raw VM syntax first, and only text the reader
rejects on an unknown name retries as language source against the
session's defun and defconstant definitions, the condition
constants included. A program's solution is always data and never
compiles.
"""

import argparse
import cmd
import functools
import json
import os
import re
import sys

from bitlisp import BitLispError, deserialize, run, serialize
from bitlisp.sexp import NIL, is_pair

from .compiler import (
    CONDITION_CONSTANTS,
    DECLARATION_KEYWORDS,
    RESERVED_WORDS,
    CompileError,
    Definitions,
    bind_values,
    compile_expression,
    declaration_keyword,
    first_symbol,
    load_symbols,
    parse_source,
    parse_source_many,
    source_text,
    tree_hash,
)
from .curry import curry, uncurry
from .keywords import ATOM_TO_NAME
from .printer import disassemble
from .reader import (
    ParseError,
    UnknownSymbol,
    assemble,
    assemble_many,
    definable,
    tokenize,
)
from .runner import (
    DEFAULT_MAX_COST,
    ContextError,
    load_context,
    render_condition,
    run_spend,
)
from .stepper import APPLY_OP, EVAL, DebugMachine

_HISTORY_LENGTH = 2000

_NAME_SPLIT = re.compile(r"[ \t\r\n]+")


# A ( line is a declaration exactly when its head token is a
# definition keyword, decided on the reader's own tokens so no
# whitespace or comment spelling can split the dispatch from what
# the parse will see.
def _declaration_line(stripped):
    try:
        tokens = tokenize(stripped)
    except ParseError:
        return False
    return (
        len(tokens) >= 2
        and tokens[0][0] == "("
        and tokens[1][0] in DECLARATION_KEYWORDS
    )


def _survives(method):
    """Command errors print and return to the prompt, never exit.

    The taxonomy matches the one-shot commands: a consensus verdict
    prints as invalid with its pinned code, unusable input prints
    as error.
    """

    @functools.wraps(method)
    def wrapper(self, arg):
        try:
            return method(self, arg)
        except BitLispError as exc:
            print(f"invalid: {exc.code}: {exc}")
        except (
            CompileError,
            ContextError,
            ParseError,
            OSError,
            RecursionError,
            ValueError,
        ) as exc:
            print(f"error: {exc}")
        except KeyboardInterrupt:
            # An interrupt cancels the command. A stepping command
            # interrupted mid-task leaves its machine poisoned,
            # finished with neither result nor error, so that
            # session is unusable and goes.
            print("interrupted")
            if self.session is not None and self.session.finished:
                self.session = None
                print("debug session discarded")

    return wrapper


class BitLispShell(cmd.Cmd):
    prompt = "bitlisp> "

    def __init__(self):
        super().__init__()
        self.names = {}
        self.defs = Definitions()
        self.symbols = {}
        self.context = None
        self.context_path = None
        self.input_index = 0
        self.max_cost = DEFAULT_MAX_COST
        self.session = None

    # Line handling.

    def emptyline(self):
        # cmd.Cmd repeats the last command on an empty line, which
        # would re-step the debugger by surprise. An empty line does
        # nothing.
        return None

    def default(self, line):
        stripped = line.strip()
        if stripped.startswith(";"):
            return None
        if stripped.startswith("("):
            if _declaration_line(stripped):
                return self._declare(stripped)
            return self.do_eval(stripped)
        word = stripped.split()[0]
        print(f"error: unknown command {word!r}, type help for the list")
        return None

    def _forms(self, arg, what, wants, least, most, data_noun):
        """The program and trailing data forms one argument line
        holds, the one parse seam behind every command that takes a
        program.

        Raw VM text first, its meaning unchanged forever. Only text
        the reader rejects on an unknown name retries as language
        source, so no line that ran before the compiler existed can
        change meaning. The reader's verdict decides which reading
        applies, under the session's def bindings, and never a mode:
        a declaration cannot flip a line to the compiler because it
        can never occupy text that already parses. On the language
        reading only the first form compiles: every trailing form
        is data and cannot hold names.
        """
        try:
            nodes = assemble_many(arg, self.names)
            compiled = False
        except UnknownSymbol:
            nodes = parse_source_many(arg)
            compiled = True
        if len(nodes) < least or (most is not None and len(nodes) > most):
            raise ValueError(f"{what} takes {wants}")
        if compiled:
            for tree in nodes[1:]:
                symbol = first_symbol(tree)
                if symbol is not None:
                    raise CompileError(
                        f"{symbol.name!r} in {data_noun}, "
                        "which is data and cannot hold names",
                        symbol.offset,
                    )
            program, table = compile_expression(nodes[0], self.defs)
            self._register_symbols(table)
            nodes = [program, *nodes[1:]]
        return nodes

    def _programs(self, arg, what):
        nodes = self._forms(
            arg, what, "a program and an optional solution", 1, 2, "the solution"
        )
        return nodes[0], nodes[1] if len(nodes) == 2 else NIL

    def _one_program(self, arg, what):
        (program,) = self._forms(arg, what, "one program", 1, 1, "the argument")
        return program

    def _register_symbols(self, table):
        for key, entry in table["functions"].items():
            self.symbols[key] = entry

    def _node_text(self, node):
        # The one rendering seam: every node the shell displays
        # passes through here. The debugger branches off through
        # _debug_text, where the symbol table renames compiled
        # function bodies. Everything else prints canonical text, so
        # results, definitions, and disasm output stay assemblable.
        return disassemble(node)

    def _debug_text(self, node):
        if not self.symbols:
            return self._node_text(node)
        return disassemble(node, rename=self._symbol_name)

    def _symbol_name(self, node):
        entry = self.symbols.get(tree_hash(node).hex())
        return entry[0] if entry is not None else None

    # Evaluation.

    @_survives
    def do_eval(self, arg):
        """eval <program> [<solution>]: run on the reference VM."""
        program, solution = self._programs(arg, "eval")
        cost, result = run(program, solution, self.max_cost)
        print(self._node_text(result))
        print(f"cost: {cost} of {self.max_cost}")

    @_survives
    def do_spend(self, arg):
        """spend <program> [<solution>]: the full spend pipeline
        against the loaded transaction context."""
        if self.context is None:
            print("error: no transaction context loaded, use tx <path>")
            return
        program, solution = self._programs(arg, "spend")
        cost, conditions = run_spend(
            program, solution, self.context, self.input_index, self.max_cost
        )
        for condition in conditions:
            print(render_condition(condition))
        print(f"valid: {len(conditions)} condition(s), cost {cost} of {self.max_cost}")

    @_survives
    def do_asm(self, arg):
        """asm <sexpr>: serialized bytecode hex for the text."""
        try:
            line = serialize(assemble(arg, self.names)).hex()
        except BitLispError as exc:
            # A converter issues no spend verdict, so its rejection
            # is unusable input, the same prefix bitlisp-asm prints.
            print(f"error: {exc.code}: {exc}")
            return
        print(line)

    @_survives
    def do_disasm(self, arg):
        """disasm <hex>: text for the serialized bytecode hex."""
        try:
            node = deserialize(bytes.fromhex(arg.strip()))
        except BitLispError as exc:
            print(f"error: {exc.code}: {exc}")
            return
        print(self._node_text(node))

    # Transaction context.

    @_survives
    def do_tx(self, arg):
        """tx [<path>]: load a JSON transaction context, or show
        the loaded one."""
        path = arg.strip()
        if path:
            self._load_context(path)
        if self.context is None:
            print("no context loaded")
            return
        print(
            f"{self.context_path}: "
            f"{len(self.context.inputs)} input(s), "
            f"{len(self.context.outputs)} output(s), "
            f"input {self.input_index} selected"
        )

    def _load_context(self, path):
        with open(path) as handle:
            self.context = load_context(json.load(handle))
        self.context_path = path
        self.input_index = 0

    @_survives
    def do_input(self, arg):
        """input <n>: select the transaction input being spent."""
        if self.context is None:
            print("error: no transaction context loaded, use tx <path>")
            return
        index = int(arg.strip())
        if not 0 <= index < len(self.context.inputs):
            print(f"error: input {index} out of range")
            return
        self.input_index = index

    @_survives
    def do_maxcost(self, arg):
        """maxcost [<n>]: show or set the cost budget for eval,
        spend, and debug."""
        text = arg.strip()
        if text:
            budget = int(text)
            if budget < 0:
                print("error: the budget cannot be negative")
                return
            self.max_cost = budget
        print(f"maxcost: {self.max_cost}")

    # Definitions.

    @_survives
    def _declare(self, line):
        """A (defun ...) or (defconstant ...) line adds to the
        compiler definitions space. Names are claimed once across
        this space and the def bindings, so one spelling can never
        mean two things."""
        tree = parse_source(line)
        taken = set(self.names)
        if declaration_keyword(tree) == "defun":
            self.defs.add_defun(tree, taken)
        else:
            self.defs.add_defconstant(tree, taken)

    @_survives
    def do_def(self, arg):
        """def <name> <sexpr>: bind a name to a parsed node. The
        body assembles under the current bindings, so a definition
        snapshots what its dependencies mean now."""
        # The name splits from the body at the reader's whitespace,
        # the four ASCII characters only. Python's default split
        # would also cut at unicode whitespace, which the tokenizer
        # deliberately treats as part of a bare token.
        parts = _NAME_SPLIT.split(arg.strip(" \t\r\n"), maxsplit=1)
        if len(parts) != 2:
            print("error: def takes a name and one expression")
            return
        name, body = parts
        if not definable(name):
            print(f"error: {name!r} is not definable")
            return
        if name in RESERVED_WORDS or name in CONDITION_CONSTANTS:
            print(f"error: {name!r} is reserved by the language")
            return
        if name in self.defs.functions or name in self.defs.constants:
            print(f"error: {name!r} is already defined")
            return
        nodes = assemble_many(body, self.names)
        if len(nodes) != 1:
            print("error: def takes a name and one expression")
            return
        self.names[name] = nodes[0]

    @_survives
    def do_undef(self, arg):
        """undef <name>: remove a definition or binding."""
        name = arg.strip()
        spaces = (self.names, self.defs.functions, self.defs.constants)
        for space in spaces:
            if name in space:
                del space[name]
                return
        print(f"error: {name!r} is not defined")

    @_survives
    def do_defs(self, arg):
        """defs: list definitions and bindings."""
        for name in sorted(self.names):
            print(f"{name} = {self._node_text(self.names[name])}")
        for name in sorted(self.defs.constants):
            print(f"(defconstant {name} {source_text(self.defs.constants[name])})")
        for name in sorted(self.defs.functions):
            params, body, _ = self.defs.functions[name]
            print(f"(defun {name} {source_text(params)} {source_text(body)})")

    @_survives
    def do_compile(self, arg):
        """compile <expr-or-program>: show the compiled tree as
        canonical text, the artifact itself, never renamed."""
        program, table = compile_expression(parse_source(arg), self.defs)
        self._register_symbols(table)
        print(self._node_text(program))

    @_survives
    def do_sym(self, arg):
        """sym <path>: load a symbol file written by
        bitlisp-compile, so foreign bytecode debugs with names."""
        with open(arg.strip()) as handle:
            data = json.load(handle)
        loaded = load_symbols(data)
        self.symbols.update(loaded)
        print(f"{len(loaded)} function name(s) loaded")

    # Currying and identity.

    @_survives
    def do_curry(self, arg):
        """curry <program> <value> ...: fix the values into the
        program, printing the curried program."""
        nodes = self._forms(
            arg, "curry", "a program and optional values", 1, None, "a fixed value"
        )
        print(self._node_text(curry(nodes[0], nodes[1:])))

    @_survives
    def do_uncurry(self, arg):
        """uncurry <program>: split a curried program back into
        the inner program and its fixed values."""
        program, values = uncurry(self._one_program(arg, "uncurry"))
        if values is None:
            print("error: not a curried program")
            return
        print(f"program: {self._node_text(program)}")
        for value in values:
            print(f"value: {self._node_text(value)}")

    @_survives
    def do_treehash(self, arg):
        """treehash <program>: the program's tree hash, the identity
        an output would commit to."""
        print(tree_hash(self._one_program(arg, "treehash")).hex())

    # The debugger.

    @_survives
    def do_debug(self, arg):
        """debug <program> [<solution>]: open a stepping session."""
        if self.session is not None:
            print("error: a debug session is open, use abort or cont")
            return
        program, solution = self._programs(arg, "debug")
        self.session = DebugMachine(program, solution, self.max_cost)
        self._show_machine(self.session)

    def _no_session(self):
        if self.session is None:
            print("no debug session, use debug <program>")
            return True
        return False

    @_survives
    def do_step(self, arg):
        """step: execute one task, then show the stacks."""
        if self._no_session():
            return
        self.session.step()
        self._after_stepping(show=True)

    @_survives
    def do_next(self, arg):
        """next: step over, executing the pending task and its
        whole subtree."""
        if self._no_session():
            return
        self.session.step_over()
        self._after_stepping(show=True)

    @_survives
    def do_cont(self, arg):
        """cont: continue, running the session to its result."""
        if self._no_session():
            return
        self.session.run()
        self._after_stepping(show=False)

    @_survives
    def do_trace(self, arg):
        """trace: run to the result, showing every step."""
        if self._no_session():
            return
        while not self.session.finished:
            self.session.step()
            if not self.session.finished:
                self._show_machine(self.session)
                print()
        self._after_stepping(show=False)

    @_survives
    def do_abort(self, arg):
        """abort: discard the debug session."""
        if self._no_session():
            return
        self.session = None
        print("debug session discarded")

    def _after_stepping(self, show):
        if self.session.finished:
            machine = self.session
            self.session = None
            if machine.error is not None:
                print(f"invalid: {machine.error.code}: {machine.error}")
                self._show_machine(machine)
            else:
                print(f"result: {self._node_text(machine.result)}")
                print(f"cost: {machine.cost} of {machine.max_cost}")
        elif show:
            self._show_machine(self.session)

    def _show_machine(self, machine):
        print(f"cost: {machine.cost} of {machine.max_cost}")
        for depth, task in enumerate(reversed(machine.tasks)):
            kind = task[0]
            if kind == EVAL:
                _, node, env = task
                line = self._eval_line(node, env)
            elif kind == APPLY_OP:
                _, op, arg_count = task
                name = ATOM_TO_NAME.get(op, "0x" + op.hex())
                line = f"apply {name} over {arg_count} value(s)"
            else:
                _, arg_count = task
                line = f"apply program over {arg_count} value(s)"
            print(f"  {depth}: {line}")
        if machine.values:
            rendered = " ".join(
                self._debug_text(value) for value in reversed(machine.values)
            )
            print(f"  values: {rendered}")

    def _eval_line(self, node, env):
        """One eval task's display. A node matching a compiled
        function body shows its source name, and its live arguments
        by parameter name when the environment has the call shape
        the compiler emits, (function tree . arguments)."""
        if self.symbols and is_pair(node):
            entry = self.symbols.get(tree_hash(node).hex())
            if entry is not None:
                name, params = entry
                bindings = bind_values(params, env)
                if bindings:
                    bound = " ".join(
                        f"{key}={self._debug_text(value)}"
                        for key, value in bindings.items()
                    )
                    return f"eval {name} [{bound}]"
                if bindings == {}:
                    return f"eval {name}"
                return f"eval {name} env={self._debug_text(env)}"
        return f"eval {self._debug_text(node)} env={self._debug_text(env)}"

    # Session.

    @_survives
    def do_source(self, arg):
        """source <path>: run commands from a file, one per line.
        An exit in the file ends the session, as it would piped."""
        with open(arg.strip()) as handle:
            lines = handle.read().splitlines()
        for line in lines:
            if line.strip() and self.onecmd(line):
                return True

    def do_exit(self, arg):
        """exit: leave the REPL."""
        return True

    def do_quit(self, arg):
        """quit: leave the REPL."""
        return True

    def do_EOF(self, arg):
        """EOF: leave the REPL."""
        if sys.stdin.isatty():
            print()
        return True


def _wire_history():
    """Loads readline history, returning the path to save on exit,
    or None when readline is unavailable."""
    try:
        import readline
    except ImportError:
        return None
    path = os.environ.get(
        "BITLISP_HISTORY", os.path.join(os.path.expanduser("~"), ".bitlisp_history")
    )
    try:
        readline.read_history_file(path)
    except OSError:
        pass
    readline.set_history_length(_HISTORY_LENGTH)
    return path


def _save_history(path):
    if path is None:
        return
    import readline

    try:
        readline.write_history_file(path)
    except OSError:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bitlisp",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "context",
        nargs="?",
        help="JSON file holding the transaction object",
    )
    parser.add_argument(
        "--input",
        type=int,
        default=None,
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

    shell = BitLispShell()
    shell.max_cost = args.max_cost
    if args.context is not None:
        try:
            shell._load_context(args.context)
        except BitLispError as exc:
            print(f"invalid: {exc.code}: {exc}", file=sys.stderr)
            return 2
        except (ContextError, OSError, RecursionError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        index = args.input if args.input is not None else 0
        if not 0 <= index < len(shell.context.inputs):
            print(f"error: input {index} out of range", file=sys.stderr)
            return 2
        shell.input_index = index
    elif args.input is not None:
        # Loading a context later resets the selection to 0, so a
        # flag accepted here would be silently discarded.
        print("error: --input needs a transaction context", file=sys.stderr)
        return 2

    interactive = sys.stdin.isatty()
    if not interactive:
        # Piped input reads as a script: no prompt, no banner.
        shell.prompt = ""
    history_path = _wire_history() if interactive else None
    intro = "BitLisp REPL. Type help for commands." if interactive else None
    try:
        while True:
            try:
                shell.cmdloop(intro=intro)
                break
            except KeyboardInterrupt:
                # Cancel the line, keep the session.
                print("^C")
                intro = None
            except UnicodeDecodeError as exc:
                # One undecodable byte in piped input would
                # otherwise kill the run with a traceback.
                print(f"error: input is not valid UTF-8: {exc}", file=sys.stderr)
                return 2
    finally:
        _save_history(history_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
