# The REPL and the converter commands

The interactive front end over the reference VM, the spend runner,
the compiler, and the debug machine, all in `python/bitlisp_tools/`.
This is tooling, not consensus. The REPL is the `bitlisp` command,
and five one-shot commands ship beside it: `bitlisp-asm` assembles
text to serialized bytecode hex, `bitlisp-disasm` renders hex back
as text, `bitlisp-compile` compiles a source program to serialized
bytecode hex, and `bitlisp-curry` and `bitlisp-uncurry` fix values
into a program and split them back out. The text syntax is defined
in `syntax.md`, the authoring language in `language.md`, and the
currying and tree-hash surfaces in `curry.md`.

## Starting the REPL

```
bitlisp [tx.json] [--input N] [--max-cost N] [-I PATH]...
```

The optional positional loads a transaction context at startup, the
same JSON shape `bitlisp-run` takes, and the flags mirror that
command's vocabulary. A context that fails to load exits 2 before
the first prompt, and `--input` without the context positional is
rejected the same way, because loading a context later would reset
the selection. With piped stdin the prompt and banner disappear, so
a scripted session reads clean, and the same scripts run inside a
session through `source`. Piped input must be UTF-8: an
undecodable byte ends the run with an error line and exit 2.

`-I` adds a directory to the include search path, repeatable and
searched in flag order, the same flag `bitlisp-compile` takes, so
a program using `include` compiles identically in both.

Line editing history persists at `~/.bitlisp_history`, overridable
through the `BITLISP_HISTORY` environment variable, capped at 2000
lines.

## Commands

| command | behavior |
| --- | --- |
| `eval <program> [<solution>]` | run on the reference VM, print the result and the cost |
| `(<program>)` | a line starting with `(` runs as `eval` |
| `spend <program> [<solution>]` | the full pipeline against the loaded context: evaluation, condition parsing, validation, printing each condition and the verdict |
| `asm <sexpr>` | serialized bytecode hex for the text |
| `disasm <hex>` | text for the serialized bytecode hex |
| `tx [<path>]` | load a JSON transaction context, or show the loaded one |
| `input <n>` | select the transaction input being spent |
| `maxcost [<n>]` | show or set the cost budget for eval, spend, and debug |
| `(defun <name> <params> <body>)` | define a named function |
| `(defun-inline <name> <params> <body>)` | define an inline function |
| `(defconstant <name> <value>)` | define a constant, its value evaluated at declaration |
| `(include "<file>")` | splice a declaration file from the include search path |
| `def <name> <sexpr>` | bind a name to a parsed node |
| `undef <name>` | remove a definition or binding |
| `defs` | list definitions and bindings |
| `compile <expr>` | show an expression's compiled tree as canonical text |
| `sym <path>` | load a symbol file written by bitlisp-compile |
| `curry <program> <value> ...` | fix the values into the program, printing the curried program |
| `uncurry <program>` | split a curried program back into program and fixed values |
| `treehash <program>` | the program's tree hash |
| `debug <program> [<solution>]` | open a stepping session |
| `step` | execute one task, show the stacks |
| `next` | step over: the pending task and its whole subtree |
| `cont` | continue: run to the result |
| `trace` | run to the result, showing every step |
| `abort` | discard the session |
| `source <path>` | run commands from a file, one per line, an exit in the file ends the session |
| `help [<command>]` | the command list, or one command's line |
| `exit`, `quit`, EOF | leave |

Lines starting with `;` are comments, an empty line does nothing,
and a command error prints and returns to the prompt. The error
taxonomy matches the one-shot commands: a consensus verdict prints
as `invalid:` with its pinned error code, unusable input prints as
`error:`.

## Definitions

`def` binds a name to one parsed expression, constants only. A
binding is consulted only where a bare symbol would otherwise be
rejected as unknown, after operator names, decimals, hex, and
strings all decline, so a binding can never change the meaning of
text that already parses, and `q` or `12` can never be redefined.
The bound node splices in wherever the name sits, head position and
dotted tails included.

A definition body assembles under the bindings current at `def`
time, so definitions snapshot: redefining a dependency later does
not rewrite what an earlier definition captured.

A line whose head is `defun`, `defun-inline`, `defconstant`, or
`include` is a language declaration, `language.md` syntax exactly,
and adds to the session's compiler definitions. Declarations and `def` bindings
share one namespace with the reserved words and the condition
constants, so one spelling can never mean two things, and `undef`
removes a name from whichever space holds it.

The shared namespace narrows `def` from its original surface, a
deliberate change with the compiler landing: a reserved word or a
condition constant name can no longer be bound. Before the
compiler, `def CREATE_OUTPUT` was an ordinary binding. Now that
spelling belongs to the language, and allowing the binding would
make the same text mean different things raw and compiled. The
rejection is loud, an error line at the `def`.

## Running language source

`eval`, `spend`, and `debug` read their text as raw VM syntax
first, and its meaning never changes. If and only if the reader
rejects the text on an unknown name, the expression compiles as
language source against the session's declarations, so `(fact 5)`
works the moment `fact` is defined, and a full `(program ...)` form
runs anywhere a program is accepted. Raw text stays raw whatever
is declared, because a declaration can never occupy text that
already parses. A `def` binding participates in raw parsing, so
which reading applies follows from the text and the session's
bindings, never from a mode. A solution is always data and never
compiles: a name inside one is an error.

Every in-REPL compile registers the compiled functions in the
session symbol map, and `sym` loads the JSON table
`bitlisp-compile --symbols` writes, so foreign bytecode debugs with
names too. The debugger display consults the map: a pair matching a
compiled function body prints as its source name, and an eval task
whose environment has the call shape shows the live arguments by
parameter name, `eval fact [N=3]`. Every other surface, `disasm`
and `compile` output included, prints canonical text untouched, so
what round-trips stays round-trippable.

## The debugger

`debug` opens a session on the pausable debug machine, a separate
evaluator pinned to the consensus machine by differential tests,
and the session uses the current `maxcost` budget. One session is
open at a time. The display after each command shows the accrued
cost and the task stack, the pending task first:

```
cost: 1 of 11000000000
  0: eval (* (q . 3) (q . 4)) env=()
  1: eval (q . 2) env=()
  2: apply + over 2 value(s)
```

An `eval` line is an expression awaiting evaluation in its
environment. An `apply` line is an operator waiting for its
arguments to finish, and arguments evaluate right to left, the
consensus order. The `values:` line, when present, is the value
stack newest first. `step` executes exactly one task. `next` runs
the pending task's whole subtree, stopping when the stack returns
to one shorter than it was. `cont` and `trace` run to the end,
`trace` printing the display after every task. A finished session
prints its result and cost, or the pinned error with the frozen
stacks as a post-mortem, and closes. Interrupting a stepping
command with Ctrl-C discards its session, because an interrupt can
land mid-task and a half-stepped machine cannot be trusted to
finish truthfully. The in-REPL `asm` and `disasm` report rejected
input with the `error:` prefix, like their one-shot counterparts,
since a converter issues no spend verdict.

## A worked session

```
$ bitlisp
bitlisp> debug (+ (q . 2) (* (q . 3) (q . 4)))
cost: 0 of 11000000000
  0: eval (+ (q . 2) (* (q . 3) (q . 4))) env=()
bitlisp> step
cost: 1 of 11000000000
  0: eval (* (q . 3) (q . 4)) env=()
  1: eval (q . 2) env=()
  2: apply + over 2 value(s)
bitlisp> next
cost: 1041 of 11000000000
  0: eval (q . 2) env=()
  1: apply + over 2 value(s)
  values: 12
bitlisp> cont
result: 14
cost: 1816 of 11000000000
bitlisp> asm (+ (q . 2) (q . 3))
ff10ffff0102ffff010380
bitlisp> exit
```

## The converter commands

```
bitlisp-asm [-T] [<file-or-literal>]      text to serialized hex
bitlisp-disasm [-T] [<file-or-literal>]   serialized hex to text
bitlisp-compile [--symbols <path>] [-I <path>]... [-T] [<file-or-literal>]
                                          language source to serialized hex
bitlisp-curry [-a <sexpr>]... [-T] [<file-or-literal>]
                                          fix values into a program
bitlisp-uncurry [<file-or-literal>]       split a curried program back
```

All five take one argument, a file when one exists at that path
and the literal otherwise, the `bitlisp-run` convention, or read
stdin when the argument is omitted, so they compose in pipelines:

```
$ echo '(+ (q . 2) (q . 3))' | bitlisp-asm | bitlisp-disasm
(+ (q . 2) (q . 3))
```

`bitlisp-compile` takes one self-contained `(program ...)` form,
`language.md` syntax, and prints the serialized bytecode hex that
`bitlisp-run --hex` and `bitlisp-disasm` accept. Its symbol table
is written only under `--symbols`, never as a side effect, and the
`sym` command loads the file. `-I` adds a directory to the include
search path, repeatable, searched in flag order, and a program
with `include` declarations compiles identically anywhere the
search path is the same, the REPL's `-I` included.

`bitlisp-curry` fixes each `-a` value, text s-expression syntax,
into a hex program, and `bitlisp-uncurry` prints the inner
program's hex and then one fixed value per line as text. The
curried shape and its contract are defined in `curry.md`.

`bitlisp-asm`, `bitlisp-disasm`, `bitlisp-compile`, and
`bitlisp-curry` take `-T`, printing the program's tree hash
instead of their usual output. The digest names the tree, not the
encoding, so every command prints the same hash for the same
program, the in-REPL `treehash` command included.

`bitlisp-disasm` deserializes strictly, accepting only the unique
canonical encoding. Exit status is 0 on success and 2 on every
failure. In this command suite exit 1 means a consensus verdict
about a spend, which the converters never issue, but the error line
keeps the pinned code when strict deserialization rejects the
bytes:

```
$ bitlisp-disasm c00161
error: bad_encoding: non-minimal length encoding
```
