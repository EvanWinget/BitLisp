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

Definitions, constants only until the compiler unit:
    def <name> <sexpr>             bind a name to a parsed node
    undef <name>                   remove a binding
    defs                           list the bindings

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
"""

import argparse
import cmd
import functools
import json
import os
import re
import sys

from bitlisp import BitLispError, deserialize, run, serialize
from bitlisp.sexp import NIL

from .keywords import ATOM_TO_NAME
from .printer import disassemble
from .reader import ParseError, assemble, assemble_many, definable
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
        except (ContextError, ParseError, OSError, RecursionError, ValueError) as exc:
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
            return self.do_eval(stripped)
        word = stripped.split()[0]
        print(f"error: unknown command {word!r}, type help for the list")
        return None

    def _programs(self, arg, what):
        """The program and optional solution one argument line holds."""
        nodes = assemble_many(arg, self.names)
        if len(nodes) not in (1, 2):
            raise ValueError(f"{what} takes a program and an optional solution")
        return nodes[0], nodes[1] if len(nodes) == 2 else NIL

    def _node_text(self, node):
        # The one rendering seam: every node the shell displays
        # passes through here, so a compiler symbol table can later
        # rename nodes in one place.
        return disassemble(node)

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
        nodes = assemble_many(body, self.names)
        if len(nodes) != 1:
            print("error: def takes a name and one expression")
            return
        self.names[name] = nodes[0]

    @_survives
    def do_undef(self, arg):
        """undef <name>: remove a binding."""
        name = arg.strip()
        if name not in self.names:
            print(f"error: {name!r} is not defined")
            return
        del self.names[name]

    @_survives
    def do_defs(self, arg):
        """defs: list the bindings."""
        for name in sorted(self.names):
            print(f"{name} = {self._node_text(self.names[name])}")

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
                line = f"eval {self._node_text(node)} env={self._node_text(env)}"
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
                self._node_text(value) for value in reversed(machine.values)
            )
            print(f"  values: {rendered}")

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
