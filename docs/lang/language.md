# The v0 authoring language

The language named functions, constants, and condition programs are
written in, compiled to VM bytecode by `bitlisp-compile` and by the
REPL. This is tooling, not consensus: a compiled program is an
ordinary program tree under `spec/VM.md`, and nothing about the
language changes what the VM accepts or how it behaves.

The language is the text syntax of `syntax.md` plus bare names. A
name is exactly a token the raw reader rejects as an unknown symbol,
so strings, hex, operator names, and decimals keep their raw
spelling rules, and the language occupies only text that previously
errored. The reserved words are `program`, `defun`, `defconstant`,
`if`, and `list`.

## The program form

```
(program <params> <declaration>* <body>)
```

A source program is one self-contained form: a parameter tree, any
number of declarations in any order, and exactly one body
expression. The declarations are `defun` and `defconstant`, and
nothing else may appear in declaration position. Compiling a
program uses nothing outside the form, so a program that compiles
in a file compiles identically pasted into the REPL.

The parameter tree names the program's arguments, which arrive as
the environment at run time, the solution in a spend. A parameter
tree is made of names and may take any shape:

```
(program (X Y) ...)        two arguments
(program ALL ...)          one name binds the whole argument value
(program (A . B) ...)      A first, B everything after
(program ((A B) C) ...)    the first argument destructures as a pair
```

Duplicate names in one tree are rejected, and a parameter may not
be a reserved word or a condition constant name.

## defun

```
(defun <name> <params> <body>)
```

Defines a named function. Parameters bind exactly as program
parameters do, shapes included. Functions may call themselves and
each other, in any declaration order, and recursion needs no
special machinery. Inside a body, parameter names shadow function
and constant names.

A call must match the parameter tree's arity: a proper list of n
parameters takes exactly n arguments, and a dotted or bare-name
tail takes at least the parameters before it, the tail name binding
the remaining arguments as a list. Arity mismatches are rejected at
compile time. A function name is only meaningful in call position:
using one as a value is an error in v0.

## defconstant

```
(defconstant <name> <value>)
```

Binds a name to a literal value, taken verbatim and never
evaluated, so the value cannot contain names. A constant reference
compiles to its quoted value at the use site. `(defconstant K
(+ 1 2))` therefore binds the three-element tree whose head is the
byte 0x10, not 3, exactly as `(q . (+ 1 2))` would read it.

A name is defined once: functions, constants, condition constants,
and reserved words share one namespace, and redefinition is an
error.

## Condition constants

Every condition name of `CONDITIONS.md` section 2 is a built-in
constant whose value is its one-byte opcode, `CREATE_OUTPUT`
through `SEAL_OUTPUTS`, 26 names. They inline like any constant,
cannot be redefined, and need no declaration:

```
(list (list CREATE_OUTPUT SCRIPT AMT))
```

## if

```
(if <condition> <then> <else>)
```

Evaluates the condition, then exactly one branch. The VM's `i`
operator evaluates all three of its arguments, so `if` is what
recursive functions terminate through, and it compiles to the
apply-a-quoted-branch idiom:

```
(a (i <condition> (q . <then>) (q . <else>)) 1)
```

The raw `i` operator remains available for the eager three-argument
select.

## list

```
(list <expr>*)
```

Builds a proper list of its evaluated arguments, folding into `c`
calls: `(list A B)` compiles as `(c A (c B ()))`, and `(list)` is
nil. Condition output is written with it.

## Expressions and quoting

An expression is an atom, a name, or a form.

- An atom quotes itself: `500` compiles to `(q . 500)`, and a
  decimal is never an environment path in source. Nil is the one
  exception in the output: a nil literal is emitted as the bare nil
  atom, whose path lookup already yields nil, saving a byte.
- A name resolves, in order, to a parameter, a user constant, a
  condition constant, or an error. Function names resolve only in
  call position.
- `(q . X)` quotes X verbatim, and X is data: names inside quoted
  content are rejected.
- Any other form is an operator application. The head must be a
  known operator, quote and apply included, and its arguments
  compile as expressions. Unknown and reserved opcodes are rejected
  at compile time, and a pair in operator position is an error.

## The compiled shape

A compiled program's environment is one pair:

```
            env (path 1)
           /            \
   function tree     arguments
     (path 2)         (path 3)
```

The function tree holds every reachable function body, balanced, in
declaration order. A call site rebuilds the layout for its callee,
passing the tree it received at path 2 and the evaluated arguments
as a proper list:

```
(a <function path> (c 2 (c <arg> ... ())))
```

Every function therefore sees the same environment shape, its own
parameters rooted at path 3, which is why recursion and mutual
recursion fall out of the layout. The whole program is emitted as

```
(a (q . <main>) (c (q . <function tree>) 1))
```

with the incoming arguments consed behind the tree. A program whose
body reaches no function skips all of this: its body is emitted
bare and its parameters root at path 1. Functions and constants the
body never mentions are pruned, so scratch definitions cost
nothing.

The compiler emits code directly and runs no rewriting passes. What
the rules above produce is what serializes.

The worked example, `bitlisp-compile` output disassembled:

```
$ echo '(program (X) (defun double (N) (* 2 N)) (double X))' \
    | bitlisp-compile | bitlisp-disasm
(a (q 2 2 (c 2 (c 5 ()))) (c (q 18 (q . 2) 5) 1))
```

One function makes a one-item tree, so `double`'s body `(* (q . 2)
5)` sits whole at path 2, spelled `(q 18 (q . 2) 5)` in data
position. The main expression calls it with X, path 5, and `N`
inside the body is path 5 of the callee's environment.

## The symbol table

Compilation also produces a symbol table, written by
`bitlisp-compile --symbols` and loaded by the REPL's `sym` command:

```json
{
  "schema": "bitlisp-sym-v0",
  "functions": {
    "<sha256 tree hash of the compiled body>": {
      "name": "double",
      "params": "(N)"
    }
  },
  "main_params": "(X)"
}
```

The key is the tree hash the `sha256tree` operator would compute
over the compiled function body, so the debugger recognizes a body
wherever it appears, in a freshly deserialized program included,
and shows the source name and the live arguments by parameter name
instead of raw bytecode. A function whose compiled body is a single
atom stays out of the table, because an atom's hash cannot be told
apart from ordinary data. `main_params` records the program's own
parameter names for the reader.

## Deviations from Chialisp

The language reads as Chialisp does and keeps its semantics where
nothing forces a change. The deliberate differences:

- The module form is `program`, not `mod`, after this repo's own
  vocabulary for the artifact it compiles to.
- Constants inline as quoted literals instead of living in the
  environment tree, so no optimizer is needed to collapse them and
  the symbol table holds only function bodies.
- The function tree is ordered by declaration, not alphabetically.
- Call arity is checked at compile time.
- `defconstant` is literal-only. There is no compile-time-evaluated
  constant form.
- Unknown bare operator atoms in call position are rejected at
  compile time rather than at run time.
- `if` and `list` are compiler forms, not macros, and there is no
  macro system, no include mechanism, no inline functions, and no
  currying helper in v0.

## A worked session

Every line below pastes into the REPL as written, and the same text
compiles from a file.

```
$ bitlisp
bitlisp> (defconstant FEE 400)
bitlisp> (defun pay (SCRIPT AMT) (list CREATE_OUTPUT SCRIPT (- AMT FEE)))
bitlisp> (pay 0x00149999999999999999999999999999999999999999 1000)
(q 0x00149999999999999999999999999999999999999999 600)
cost: 1767 of 11000000000
bitlisp> compile (pay 0x0014 600)
(a (q 2 2 (c 2 (c (q . 0x0014) (c (q . 600) ())))) (c (q 4 (q . 1) (c 5 (c (- 11 (q . 400)) ()))) 1))
bitlisp> debug (pay 0x0014 600)
cost: 0 of 11000000000
  0: eval (a (q 2 2 (c 2 (c (q . 0x0014) (c (q . 600) ())))) (c (q . pay) 1)) env=()
bitlisp> exit
```

The condition list's leading opcode byte 0x01 prints as `q` because
the canonical printer names operator bytes in list-head position,
as `syntax.md` defines. The bytes are the condition opcode either
way.
