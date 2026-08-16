# Macros

The v0 language's macro system: `defmacro` declares a small program
that runs at compile time and writes source, and `qq` with
`unquote` is how such a body writes a code template around the
pieces it was handed. The semantics follow classic Chialisp, with
the deliberate differences recorded in `language.md` and the two
limits stated at the end of this page.

## defmacro

```
(defmacro <name> <params> <body>)
```

A macro call looks exactly like a function call and is gone before
anything runs: the compiler replaces the call with whatever the
macro's body computes, and only that replacement compiles into the
program.

The difference from a function is when the body runs and what it
receives. A function body runs at run time, on the values its
arguments evaluated to. A macro body runs at compile time, on the
argument source itself, unevaluated: a name arrives as its
spelling, an atom as itself, a form as the tree the reader built.
`(add 50 60)` under `(defmacro add (n1 n2) (+ n1 n2))` therefore
compiles to the constant `(q . 110)`. The addition happened inside
the compiler, and nothing of it remains at run time.

Parameters bind positionally, exactly as function parameters do,
shapes and arity checks included. A bare-name tail binds the whole
remaining argument list, which is what a variadic macro walks.

## What a macro body can see

A macro body compiles at its declaration, as its own self-contained
program. It sees its parameters, the macros declared before it, the
operators, the condition constants, and the expression forms `if`,
`list`, and `qq`. It does not see the program's functions or
constants: those exist at run time, and a macro runs before run
time exists. A macro used inside another macro's body must
therefore be declared earlier. A call in a function body or the
main body may name a macro declared anywhere in the program,
because those bodies expand only when the whole program compiles.

## qq and unquote

```
(qq <template>)
(unquote <expression>)      inside a template only
```

`qq` evaluates to the template as data, except that each
`(unquote E)` hole evaluates E and splices the value in place. A
name in a template becomes its spelling, so a template can mention
functions and operators that will only mean something where the
expansion lands. Templates nest by level: a `qq` inside a template
deepens it one level, an `unquote` steps one level back, and only
an `unquote` at the outermost level escapes. Both forms are
ordinary expressions, usable outside macro bodies too, where a
template simply builds data.

There is no splicing unquote. Splicing is spelled by hand, by
consing a macro's name onto a shortened argument list, the idiom
below.

## How an expansion is read back

The value a macro returns is read as source and compiled, and it
may contain further macro calls, which expand the same way, so a
macro can build on other macros or splice its own name back in.

Reading bytes back as source means deciding which atoms are
names. Two questions are asked of every atom that spells a name
the reader would accept. Does the name resolve where the call
sits: a parameter of the surrounding body, a function, a
constant, a macro, a condition constant, or an expression form?
And is there evidence it was written rather than computed? The
answers decide everything:

```
                       resolves here          resolves nowhere
                    +---------------------+---------------------+
   written          |  a name             |  error:             |
                    |                     |  unknown name       |
                    +---------------------+---------------------+
   computed         |  error: spells a    |  data               |
                    |  name never written |                     |
                    +---------------------+---------------------+
```

Written means the spelling is in the macro's evidence, which has
exactly two sources. First, everything the macro's own expanded
body spells: template names, string literals, and whatever
earlier macros contributed at its declaration, but not its
parameters, which substitute at expansion time and never reach
the output as spellings. Second, every name the caller wrote in
this call's arguments, quoted argument content excluded, which is
what lets a spliced argument come back as the name the caller
meant.

A written, resolving spelling is a name, which is every ordinary
template and every spliced argument. A written spelling that
resolves nowhere is the same unknown-name error the direct
spelling gets, so a typo in a call or a stale name in a template
is caught, not compiled as data. A computed atom whose bytes
happen to spell something in scope is rejected outright, the
capture guard below. Everything else is data. A pair whose head
is the quote opcode passes through whole, its content data, so a
macro that must emit name-shaped bytes as data wraps them in
`(q . ...)`.

One refinement keeps macro composition working. Inside another
macro's body, at declaration time, an expansion is not judged by
this table: a spelling that resolves in the macro world lifts,
and everything else stays data and rides the compiled body
outward, because its real judgment happens where a program
finally uses it.

## The capture guard

Classic Chialisp reads back any resolving atom as a name, and
that captures. The number 110 and the letter `n` are the same
byte, so under Chialisp

```
(program (n) (defmacro add (n1 n2) (+ n1 n2)) (add 50 60))
```

compiles not to a constant but to a reference to the parameter
`n`, silently. BitLisp rejects it instead, a recorded divergence:
the macro computed 110, never wrote an `n`, and the collision is
reported as `macro output 0x6e spells 'n', a name the macro never
wrote`. The same fold with no `n` in scope stays the constant
`(q . 110)`, so constant folding works until the day it would
misbind, and that day is an error, not a wrong program.

The guard is evidence-based, not value-based, so it has a stated
residue with two faces. A computed atom whose bytes spell a name
the body also legitimately writes is indistinguishable from the
written one and still lifts. And handing a macro a name as an
argument is evidence for that spelling anywhere in the expansion,
so a computed collision with a handed-in name also still lifts:
`(add3 50 60 n)` under a two-argument fold captures the caller's
`n` exactly as Chialisp would, because the caller put `n` on the
table. The guard therefore narrows capture to spellings the
macro was given or writes itself, it does not abolish it. Quote
data that must stay data and neither face arises.

Macros remain positionally unhygienic in Chialisp's sense: an
unquoted argument is spliced as source, so a template that
unquotes the same parameter twice evaluates that argument twice
at run time, cost included, and a template may deliberately name
whatever is in scope at the call site.

At the REPL, `def` bindings fall out of the same rule: they are
not language names, so a caller-written def name through a macro
is evidence that resolves nowhere, rejected as an unknown name
rather than silently read as data while the raw path reads the
binding.

## The splicing idiom

A variadic macro that rebuilds the built-in `list` form, verbatim
from the Chialisp corpus apart from its name:

```
(defmacro list1 args
    (if args
        (qq (c (unquote (f args)) (unquote (c list1 (r args)))))
        ()))
```

With arguments, the template conses the first argument onto a
spliced call of `list1` itself over the rest, one element shorter.
Without, it is nil. Each expansion round consumes one element, so
the recursion terminates, and the result compiles to exactly what
`(list ...)` emits.

## Limits

Three guards bound compile time, all deliberate departures from
Chialisp, which lets a runaway macro run until the interpreter
dies:

- Expansion depth. A chain of expansions more than 100 levels deep
  is rejected with `macro expansion depth exceeded 100 levels`. A
  self-splicing macro spends one level per argument plus one for
  the final empty round, so the cap bounds such calls at 99
  arguments.
- Total expansions. One compile may run at most 10000 macro
  executions across all its bodies, rejected past that with
  `macro expansion exceeded 10000 executions`. Depth alone would
  not do: a template that splices two calls to itself doubles the
  work per level while every chain stays shallow.
- Execution cost. Each macro execution runs under the same
  11000000000 budget a spend gets, and a burst is rejected with
  `macro '<name>' failed: cost_exceeded` naming the macro.

Any other error inside a running macro is reported the same way,
`macro '<name>' failed:` with the VM's error code, at the call
site's offset.

## A worked session

Every line below pastes into the REPL as written, and the same
declarations compile from a file.

```
$ bitlisp
bitlisp> (defmacro add (n1 n2) (+ n1 n2))
bitlisp> compile (add 50 60)
(q . 110)
bitlisp> (defmacro inc (e) (qq (+ (unquote e) 1)))
bitlisp> compile (inc 5)
(+ (q . 5) (q . 1))
bitlisp> (inc 41)
42
cost: 796 of 11000000000
bitlisp> (defmacro list1 args (if args (qq (c (unquote (f args)) (unquote (c list1 (r args))))) ()))
bitlisp> compile (list1 300 40 50)
(c (q . 300) (c (q . 40) (c (q . 50) ())))
bitlisp> compile (list 300 40 50)
(c (q . 300) (c (q . 40) (c (q . 50) ())))
bitlisp> (list1 300 40 50)
(300 40 50)
cost: 257 of 11000000000
bitlisp> exit
```

The `add` call folded to a constant at compile time. The `inc`
call left run-time work in place but spliced its argument into the
template. The `list1` macro expands to the same tree the built-in
`list` form emits, which is the point of the idiom.
