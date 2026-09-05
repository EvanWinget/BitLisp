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
errored. The reserved words are `program`, `defun`, `defun-inline`,
`defconstant`, `include`, `if`, `let`, `list`, `list*`, `assert`,
`and`, and `or`.

## The program form

```
(program <params> <declaration>* <body>)
```

A source program is one self-contained form: a parameter tree, any
number of declarations in any order, and exactly one body
expression. The declarations are `defun`, `defun-inline`,
`defconstant`, and `include`, and nothing else may appear in
declaration position. Compiling a program uses nothing outside the
form and the include files it names, resolved through the same
search path everywhere, so a program that compiles in a file
compiles identically pasted into a REPL running with the same
include path.

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

## defun-inline

```
(defun-inline <name> <params> <body>)
```

Defines an inline function. A call compiles by splicing: each
argument expression compiles once, and the body compiles at the
call site with every parameter reference replaced by its
argument's compiled expression. Nothing enters the function tree,
so an inline call pays no apply and no path lookup, and the
compiled program is smaller wherever the body is short.

Substitution is by name, not by value. An argument evaluates once
per parameter reference in the body: a parameter used twice
evaluates its argument twice, and a parameter the body never
references leaves its argument unevaluated. That laziness is
Chialisp's inline contract and programs may rely on it, but an
expensive argument belongs in a `defun`, whose arguments evaluate
exactly once.

Parameters bind exactly as `defun` parameters do, shapes included.
A destructured name reaches its component through first and rest
steps applied to the argument expression, and a dotted or bare
tail name binds the remaining arguments as a list, each occurrence
paying its own evaluations. Arity is checked at compile time, the
same rule as `defun`. Inline bodies may call functions of both
kinds, and inline calls nested in inline bodies expand to a depth
of 100 before the compiler rejects the program, so an inline
function cannot call itself: recursion needs the function tree,
which is what `defun` is for. Expansion is also capped at one
million emitted nodes, because a chain of doubling inlines can
square its tree per declaration while nesting only a little, and
the cap turns that into a compile error instead of an artifact too
large to serialize.

## defconstant

```
(defconstant <name> <value>)
```

Binds a name to the value its expression computes at compile time.
The value compiles against the declarations above it, earlier
constants and functions included, and runs on the reference VM
under the default cost budget of 11000000000, so a constant can
hold a computed tree hash or a table a helper builds. The result
is data: a constant reference compiles to its quoted value at the
use site, and an evaluation that raises or exhausts the budget is
a compile error naming the constant.

An atom is its own value, so `(defconstant FEE 400)` binds 400.
Structured data needs quoting: `(defconstant K (q 1 2 3))` binds
the list, where `(defconstant K (+ 1 2))` binds 3. Declaration
order matters for constants alone. A constant's value sees only
what is declared above it, and so does everything the value
reaches: a function it calls compiles at that moment, against the
declarations made so far. Function bodies a constant never reaches
may reference names in any order.

A name is defined once: functions, constants, condition
constants, and reserved words share one namespace, and
redefinition is an error.

## include

```
(include "<file>")
```

Splices a declaration file into the program. An include file holds
exactly one parenthesized list of declarations, any mix of
`defun`, `defun-inline`, `defconstant`, and nested `include`, and
nothing else, no parameter tree and no body:

```
(
  (defconstant FEE 400)
  (defun pay (SCRIPT AMT) (list CREATE_OUTPUT SCRIPT (- AMT FEE)))
)
```

The file name is a string, and since the compiler sees an atom,
any atom spelling a printable name reads as one. It resolves
through the include search path, the repeatable `-I` flag of
`bitlisp-compile` and of the REPL, first match in flag order
winning, never an implicit current directory. A name may reach a
subdirectory of an include directory, and a name that is absolute
or climbs out of its directory is rejected, so the search path is
the whole resolution story. Spliced declarations join the one
namespace exactly as if written in place, so a name collision
across files is the ordinary redefinition error. A file already
loaded in the same compile is skipped rather than reloaded, the
file's identity not its spelling, so two libraries may include a
common third, and a cycle of includes is a compile error naming
the chain. In the REPL the session is the load-once scope, and a
failed include line applies nothing. By convention library files
end in `.blib`, though nothing enforces an extension.

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

## list*

```
(list* <expr>* <tail>)
```

Builds a list of its evaluated arguments consed onto the last one,
which becomes the tail: `(list* A B T)` compiles as
`(c A (c B T))`. Where `list` always ends in nil, `list*` is how a
condition list extends a tail the program inherited. With a single
operand there is nothing to cons and the tail compiles bare.
`(list*)` is rejected at compile time: "list* takes items and a
final tail".

## assert

```
(assert <condition>* <value>)
```

Evaluates each condition in order and yields the final operand once
every condition holds. A falsy condition raises, failing the spend,
and nothing after it evaluates. Each level compiles to the same
apply-a-quoted-branch idiom as `if`, with the raise operator as the
untaken branch, so `(assert C V)` compiles as

```
(a (i C (q . V) (q 8)) 1)
```

With a single operand there is nothing to check and the value
compiles bare. `(assert)` is rejected at compile time: "assert
takes conditions and a final value".

## and

```
(and <expr>*)
```

Yields 1 when every operand is truthy and nil at the first falsy
operand, whose successors never evaluate. The result is boolean, 1
or nil, never an operand's value, exactly as Chialisp's `and` macro
behaves. `(and)` is 1. Each level compiles through the same idiom
as `assert`, the remaining chain as the taken branch and nil as
the fallback, so `(and A B)` compiles as

```
(a (i A (q 2 (i B (q 1 . 1) (q)) 1) (q)) 1)
```

## or

```
(or <expr>*)
```

Yields 1 at the first truthy operand, whose successors never
evaluate, and nil when every operand is falsy. `(or)` is nil.
`(and X)` and `(or X)` compile to the same tree, both meaning X as
a boolean.

## let

```
(let ((<name> <expr>)*) <body>)
```

Binds names to evaluated expressions for one body expression.
Bindings are parallel: every expression evaluates in the enclosing
scope, and the bound names are visible only in the body, so a
binding referencing a sibling is an unknown name. Sequential
naming is nested `let`, each layer seeing the ones above. A
binding names one value, with no destructuring shape. Bound names
follow the parameter rules: duplicates in one binding list are
rejected, a name may not be a reserved word or a condition
constant, and inside the body a bound name shadows parameters,
functions, and constants, exactly as a parameter does. Every name
the `let` does not bind stays visible in the body.

`let` compiles as the naming helpers it replaces are written by
hand, a function taking the bound names as parameters and called
once, except that the body is applied in place instead of entering
the function tree:

```
(a (q . <body>) (c 2 (c <expr> ... 3)))
```

The body's environment is the enclosing one with the bound values
consed in front of the arguments, so the function tree stays at
path 2, calls and recursion inside the body work unchanged, and
the cost is one apply plus one cons per binding, the price of the
hand-written helper call. In a program with no function tree the
rebuild drops the tree cons. `(let () <body>)` binds nothing and
its body compiles bare.

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
recursion fall out of the layout. A `let` rebuilds the layout the
same way, its bound values consed in front of the arguments, so a
body under `let` still sees the tree at path 2. The whole program is emitted as

```
(a (q . <main>) (c (q . <function tree>) 1))
```

with the incoming arguments consed behind the tree. A program whose
body reaches no function skips all of this: its body is emitted
bare and its parameters root at path 1. Functions, inline
functions, and constants the body never mentions are pruned, so
scratch definitions cost nothing. Only reachable definitions compile at all, so an error
inside an unreached body surfaces the first time a program reaches
it, not at the declaration. A body error names its function,
because in the REPL the offset indexes the declaring line's text,
not the line that triggered the compile.

The compiler performs no source rewrites. Emission is direct: what
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
apart from ordinary data. Inline functions stay out too: spliced
code has no one compiled body to hash. A `let` body stays out as
well: it is part of the expression that contains it, not a
function of its own. `main_params` records the
program's own parameter names for the reader.

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
- `defconstant` evaluates its value at compile time on the
  reference VM, cost-budgeted, where classic Chialisp quotes the
  value verbatim. This is the modern dialect's `defconst` behavior
  under the classic keyword, and there is no second constant form.
- Unknown bare operator atoms in call position are rejected at
  compile time rather than at run time.
- `if`, `list`, `assert`, `and`, and `or` are compiler forms, not
  macros, with the semantics Chialisp's stage-2 and utility_macros
  macros give the same spellings, and `let` is a compiler form
  with the modern dialect's parallel binding semantics. Nothing
  can shadow any of them: where Chialisp's newest macro silently
  wins, the one-namespace rule makes redefinition an error.
- `list*` is an addition with no Chialisp counterpart: no dialect
  has a form that builds a list onto a tail, so condition lists
  extending an inherited tail are consed by hand there. The
  expansion is one `c` per item, purely syntactic.
- There is no macro system. Chialisp's `defmacro`, `qq`, and
  `unquote` are omitted, a removal decided on production evidence:
  across Chia's deployed puzzle corpus and its largest application
  codebases, the only macros in production use are short-circuit
  `assert`, `and`, and `or`, which ship here as fixed forms. The
  cut removes the expansion machinery's audit surface, and it
  means user code cannot rewrite source: what is written is what
  compiles.
- There is no `function` or `com` reflection form, and lazy
  evaluation exists only through the built-in lazy forms, `if`,
  `assert`, `and`, and `or`.
- `include` names its file with a string, not a bare symbol, and
  takes exactly one declaration list per file, rejecting trailing
  content where classic reads only the first form and ignores the
  rest. A file already loaded is skipped where classic errors on
  the collision a double include causes, and an include cycle is
  an error where classic recurses without bound.
- `defun-inline` keeps Chialisp's call-by-name substitution but
  closes its sharp edges: arity is checked where classic silently
  drops extra arguments, quoted content is never rewritten where
  classic substitutes parameter names inside `(q . X)` data, a
  parameter in operator position stays an error where classic
  substitutes there too, an inline can never shadow an operator or
  any other name, and expansion is depth-capped and size-capped
  where a classic self-recursive inline hangs the compiler.
- Currying is not a language form: it operates on compiled
  programs, through the surfaces defined in `curry.md`.

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
