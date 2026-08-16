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
names. An atom that spells a name the reader would accept becomes
a name in two cases. It resolves where the call sits: a parameter
of the surrounding body, a function, a constant, a macro, a
condition constant, or an expression form. That is the classic
Chialisp rule, and it is what makes every ordinary template work.
Or it is a name that was demonstrably written: the macro's own
body spells it, or the caller spelled it in this call's
arguments, the macro's parameters excepted since those substitute
at expansion time. A written name that resolves nowhere then
fails as the unknown name it is, exactly as the direct spelling
would. This second case is the recorded divergence from Chialisp,
which reads such an atom back as data and silently compiles the
typo: here a misspelled argument, a stale template name, or a
removed definition is an error at the call site, never a wrong
program.

Every other atom stays data, and a pair whose head is the quote
opcode passes through whole, its content data, so a macro that
must emit name-shaped bytes as data wraps them in `(q . ...)`.

One refinement keeps macro composition working. Inside another
macro's body, at declaration time, nothing errs: a spelling that
resolves in the macro world lifts, and everything else stays data
and rides the compiled body outward, because its real judgment
happens where a program finally uses it.

## Capture, the Chialisp sharp edge

The resolution rule is positional and textual, exactly as in
Chialisp, and it can capture. The number 110 and the letter `n`
are the same byte, so

```
(program (n) (defmacro add (n1 n2) (+ n1 n2)) (add 50 60))
```

compiles not to `(q . 110)` but to a reference to the parameter
`n`. The macro computed 110, the read-back found an `n` in scope,
and the program now returns whatever its argument is. Nothing
warns, and nothing can: once the reader is done, a computed
number, a string, and a spelled name are the same bytes, so no
compile-time rule can tell them apart, only quoting can. Keep
macro output away from name-shaped bytes unless naming things is
the intent, and quote data that must stay data: a `(q . ...)`
wrapper survives read-back untouched.

Macros are also positionally unhygienic in Chialisp's sense: an
unquoted argument is spliced as source, so a template that
unquotes the same parameter twice evaluates that argument twice
at run time, cost included, and a template may deliberately name
whatever is in scope at the call site.

At the REPL, `def` bindings fall out of the written-name rule:
they are not language names, so a def-bound name written into a
macro call is rejected as an unknown name, never read as the
binding, and a computed atom that merely coincides with a def
spelling is data like any other computed bytes.

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
