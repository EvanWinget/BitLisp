# The REPL and the converter commands

The interactive front end over the reference VM, the spend runner,
and the debug machine, all in `python/bitlisp_tools/`. This is
tooling, not consensus. The REPL is the `bitlisp` command, and two
one-shot converters ship beside it: `bitlisp-asm` assembles text to
serialized bytecode hex, `bitlisp-disasm` renders hex back as text.
The text syntax is defined in `syntax.md`.

## Starting the REPL

```
bitlisp [tx.json] [--input N] [--max-cost N]
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
| `def <name> <sexpr>` | bind a name to a parsed node |
| `undef <name>` | remove a binding |
| `defs` | list the bindings |
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
not rewrite what an earlier definition captured. Named functions
with parameters are not definitions, they arrive with the compiler
unit that owns call semantics.

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
bitlisp-asm  [<file-or-literal>]     text to serialized hex
bitlisp-disasm [<file-or-literal>]   serialized hex to text
```

Both take one argument, a file when one exists at that path and the
literal otherwise, the `bitlisp-run` convention, or read stdin when
the argument is omitted, so the two compose in a pipeline:

```
$ echo '(+ (q . 2) (q . 3))' | bitlisp-asm | bitlisp-disasm
(+ (q . 2) (q . 3))
```

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
