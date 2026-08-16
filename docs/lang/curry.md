# Currying and program identity

Fixing values into a program to make a new program, reading them
back out, and naming any program by its tree hash. These are
tooling surfaces in `python/bitlisp_tools/`, not consensus: a
curried program is an ordinary program tree the VM evaluates by
its ordinary rules. The text syntax is defined in `syntax.md`, and
the REPL and one-shot commands hosting these surfaces in
`repl.md`.

## Why fix values into a program

An output commits to one program, and the spender later supplies
the witness arguments. Most programs are reusable templates: the
same payment logic with a different public key, the same vault
with a different timeout. Currying is the specialization step
between template and commitment. It takes a program and some fixed
values and builds a new program behaving like the original with
those values already in place, so the committed artifact carries
its parameters and only the genuinely spend-time arguments stay
with the spender.

## The curried shape

Currying a program `F` with values `v1` to `vn` builds

```
(a (q . F) (c (q . v1) (c (q . v2) ... 1)))
```

Evaluated against an environment `E`, the wrapper quotes `F`,
builds the environment `(v1 v2 ... vn . E)` by consing the quoted
values onto the whole received environment, path 1, and applies
`F` to it. The fixed values sit first, in currying order, and `E`
becomes the tail, so a program taking `(A B C)` curried with one
value becomes a program taking `(B C)`.

Each value is quoted, which makes it committed data: the spender
chooses `E` and nothing else. Changing a fixed value changes the
program tree, and with it the tree hash an output would commit to.

The shape is byte for byte the one Chialisp tooling builds, so a
curried BitLisp program keeps one recognizable identity across
both ecosystems.

## The uncurry contract

Uncurrying inverts the shape. Given exactly the curried form it
returns the inner program and the fixed values in currying order.
Given anything else it reports not curried: the library returns
the program with no value list, and the commands print an error.

A curry of zero values, `(a (q . F) 1)`, is valid and uncurries to
`F` with an empty value list, a different answer from not curried.

The shape check is strict. The tree must be a three-item proper
list headed by the apply operator with its program operand quoted,
and the environment chain must be three-item proper lists headed
by the cons operator, each value quoted, ending in the atom `1`.
An atom, a different head, an extra operand, an unquoted operand,
an improper tail, or a chain ending anywhere but `1` is not a
curried program, never a partial answer.

## Tree hash as identity

The tree hash is the `sha256tree` digest of a program tree: an
atom hashes as SHA-256 over the byte 0x01 then the atom's bytes, a
pair as SHA-256 over the byte 0x02 then its two child digests. The
VM computes the same digest natively through the `sha256tree`
operator, and the symbol table already keys compiled function
bodies by it.

The digest names the tree, not its encoding, so the same program
hashes identically whether it arrives as text, hex, or language
source, through any command. The hash of a curried program commits
to the inner program and every fixed value at once, which is what
makes currying the specialization step: template plus parameters
becomes one committed identity.

What a scriptPubKey commits to on chain is decided by the
commitment scheme and measured in Phase 4. The tree hash is the
program-level identity those commitments build on.

## The command surfaces

The library functions are `curry` and `uncurry` in
`bitlisp_tools`, taking and returning program trees. Around them:

```
bitlisp-curry [-a <sexpr>]... [-H] [<program>]
bitlisp-uncurry [<program>]
```

`bitlisp-curry` takes the program as serialized bytecode hex, a
file or a literal or stdin, and each `-a` value as text
s-expression syntax, fixed in the order given. It prints the
curried program's hex, or with `-H` its tree hash. With no `-a`
the wrapper is still built, a curry of zero values.
`bitlisp-uncurry` takes hex the same way and prints the inner
program's hex, then one value per line as text. Input without the
curried shape is an error. Exit status follows the converter
convention, 0 on success and 2 on every failure, never a consensus
verdict.

The converters take the same flag: `bitlisp-asm -H`,
`bitlisp-disasm -H`, and `bitlisp-compile -H` print the parsed or
compiled program's tree hash instead of their usual output. For
`bitlisp-compile` that digest covers the whole program, a
different thing from the per-function-body hashes keying its
`--symbols` table.

In the REPL, `curry`, `uncurry`, and `hash` do the same over the
session's programs, language source included, and the debugger's
symbol names survive currying because the wrapped function bodies
are untouched. The command rows live in `repl.md`.

## A worked example

A multiply template specialized to one factor, from the command
line:

```
$ bitlisp-compile '(program (X Y) (* X Y))'
ff12ff02ff0580
$ bitlisp-compile '(program (X Y) (* X Y))' | bitlisp-curry -a 6
ff02ffff01ff12ff02ff0580ffff04ffff0106ff018080
$ bitlisp-compile '(program (X Y) (* X Y))' | bitlisp-curry -a 6 -H
d8dc6cb1396e4bccd408878df8f7a450c79ff646ee256665bff412077b5a1925
```

The same artifact in the REPL, run with the remaining argument and
split back apart:

```
$ bitlisp
bitlisp> curry (program (X Y) (* X Y)) 6
(a (q 18 2 5) (c (q . 6) 1))
bitlisp> eval (a (q 18 2 5) (c (q . 6) 1)) (7)
42
cost: 1326 of 11000000000
bitlisp> uncurry (a (q 18 2 5) (c (q . 6) 1))
program: (* 2 5)
value: 6
bitlisp> hash (a (q 18 2 5) (c (q . 6) 1))
d8dc6cb1396e4bccd408878df8f7a450c79ff646ee256665bff412077b5a1925
bitlisp> exit
```

The program compiles bare because it declares no functions, so the
inner program reads back as `(* 2 5)`, multiply over the first two
environment paths. The REPL hash and the `-H` digest agree, one
identity through every entry point.
