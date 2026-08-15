# Text s-expression syntax

The textual form of BitLisp program trees, read by the assembler and
written by the disassembler in `python/bitlisp_tools/`. This is
tooling, not consensus. The one wire format remains the canonical
serialization defined in `spec/VM.md` section 2, and every text
program is one `serialize` call away from those bytes. This page is
the reference for anyone writing programs by hand, in the REPL, or in
vector review.

The syntax reads as Chialisp assembly does, with BitLisp's operator
names. Two deliberate deviations from `clvm_tools` are called out
below: unknown bare symbols are rejected, and the printer's decimal
display is sign-split, covering non-negative minimal encodings up
to eight bytes where `clvm_tools` stops at two, so amounts print as
numbers instead of hex.

## Grammar

```
program   := ws expr ws EOF                (exactly one expression)
expr      := atom | "(" ws body
body      := ")"
           | expr ws body                  (proper list element)
           | expr ws "." ws expr ws ")"    (dotted tail, needs 1+ preceding exprs)
atom      := opname | hex | decimal | string
opname    := q a i c f r l x = >s sha256 substr strlen concat secp_verify
             + - * / divmod > ash lsh logand logior logxor lognot
             not any all sha256tree
hex       := "0x" [0-9a-fA-F]*   case-insensitive, odd digit count gets a
                                 leading 0 nibble, bare "0x" is the empty atom
decimal   := "-"? [0-9]+         minimal signed encoding
string    := '"' [^"]* '"' | "'" [^']* "'"   UTF-8 bytes, no escapes
comment   := ";" to end of line, treated as whitespace
ws        := (whitespace | comment)*         may be empty
```

Whitespace separates tokens and otherwise carries no meaning, and
it is exactly the four ASCII characters space, tab, carriage
return, and newline. Unicode whitespace is not a separator: it
falls into a bare token and is rejected there, so a lookalike space
can never silently split an expression. A comment runs from `;` to
the end of the line and counts as whitespace. `ws` may be empty, so
tokens need no separator where one already ends at a delimiter:
`("a""b")` is a list of two string atoms. The input must contain
exactly one expression: empty input and trailing tokens are both
errors.

## Atoms

A bare token ends at whitespace, `(`, `)`, `"`, `'`, or `;`. It is
resolved in this order:

1. A `0x` prefix makes it a hex atom. Digits are case-insensitive,
   an odd digit count gets a leading zero nibble (`0xf` is the byte
   `0x0f`), and bare `0x` is the empty atom.
2. An exact match in the operator name table below makes it that
   operator's opcode atom. Names resolve anywhere they appear, not
   only in operator position: the reader is context-free, so
   `(q . q)` is the pair of two `0x01` atoms.
3. An optionally negative run of digits is a decimal integer,
   encoded minimally as signed big-endian two's complement. `0` is
   the empty atom. A leading `+` is not accepted.
4. Anything else is an error. This diverges from `clvm_tools`, which
   silently turns an unknown symbol into the UTF-8 bytes of its
   name, so a typo like `sha256tre` assembles cleanly and fails only
   at runtime. Here it fails at assembly. To write literal name
   bytes, use a string (`"foo"`) or hex (`0x666f6f`).

A string literal is delimited by double or single quotes and becomes
the UTF-8 bytes of its contents. There are no escape sequences, so a
string cannot contain its own delimiter. A `;` inside a string is
literal, and so is a raw newline, a string may span lines. Contents
that UTF-8 cannot represent, such as a lone surrogate, are
rejected.

The empty atom, which is also nil, false, zero, and the empty list,
can be written `()`, `0`, or `0x`.

## Operator names

The names are exactly those of `spec/VM.md` section 4.

| Name | Opcode | | Name | Opcode |
| --- | --- | --- | --- | --- |
| `q` | `0x01` | | `+` | `0x10` |
| `a` | `0x02` | | `-` | `0x11` |
| `i` | `0x03` | | `*` | `0x12` |
| `c` | `0x04` | | `/` | `0x13` |
| `f` | `0x05` | | `divmod` | `0x14` |
| `r` | `0x06` | | `>` | `0x15` |
| `l` | `0x07` | | `ash` | `0x16` |
| `x` | `0x08` | | `lsh` | `0x17` |
| `=` | `0x09` | | `logand` | `0x18` |
| `>s` | `0x0a` | | `logior` | `0x19` |
| `sha256` | `0x0b` | | `logxor` | `0x1a` |
| `substr` | `0x0c` | | `lognot` | `0x1b` |
| `strlen` | `0x0d` | | `not` | `0x20` |
| `concat` | `0x0e` | | `any` | `0x21` |
| `secp_verify` | `0x0f` | | `all` | `0x22` |
| | | | `sha256tree` | `0x3f` |

Quote is ordinary syntax, not a reader special form. `(q . X)` is a
dotted pair whose head is the atom `0x01`, and the VM, not the
reader, gives it quoting behavior. Names the upstream CLVM assembler
knows but BitLisp does not (`point_add`, `pubkey_for_exp`,
`softfork`) are unknown symbols here and are rejected.

## Printer normal form

The disassembler maps any program tree to one canonical text, and
assembling that text reproduces the identical tree. This round-trip
guarantee holds for every node, including atoms that are not valid
UTF-8 and lists with improper tails.

Pairs print as lists. A proper tail collapses into list syntax,
`(a b c)`, and an improper tail prints dotted, `(a b . c)`. Quoted
forms fall out naturally: `(q . 2)` when the tail is an atom,
`(q 1 2)` when the tail is a proper list.

An atom prints as its operator name exactly when it sits in operator
position and its bytes match a table opcode. Operator position means
the head of a printed list: the first child of a pair that is not
itself the rest of another pair. Later list elements and dotted
tails are data, so `(q 1 2)` prints with a plain `1` even though
`0x01` is quote's opcode, and `(q . q)` prints as `(q . 1)`.

The cons structure of `(q 1 2)` makes the rule concrete. The tree
is three pairs ending in nil, and only the head of the first pair
sits in operator position:

```
        pair
       /    \
    0x01     pair          operator position, prints as q
            /    \
         0x01     pair     data, prints as 1
                 /    \
              0x02     ()  data, prints as 2, and nil closes the list
```

The second and third pairs are each the rest of the pair above
them, so their heads are list elements, data under the definition
above. The two `0x01` atoms in one tree print differently, `q` at
the head and `1` in the body, and both spellings assemble back to
the same byte.

In data position an atom prints in this order:

1. Nil prints `()`.
2. An atom of three or more bytes that are all printable ASCII
   (`0x20` to `0x7e`) prints as a string. The delimiter is `"`, or
   `'` when the contents contain `"`. Contents containing both quote
   characters fall back to hex, since there are no escapes.
3. An atom that is the minimal encoding of its signed integer
   reading prints as that decimal integer, up to eight bytes when
   the value is non-negative and up to two bytes when it is
   negative. Eight bytes covers every satoshi amount, cost, height,
   and index an author reads, and two negative bytes cover the real
   constants `-1` through `-32768`. `clvm_tools` uses two bytes for
   both signs.
4. Anything else prints as lowercase hex with an even digit count,
   so `0x0001` and `0x01` remain distinct atoms in text exactly as
   they are distinct in bytes.

The string check runs before the decimal check because every
printable atom is also some integer's minimal encoding. `"test"`
prints as a string, never as `1952805748`. The decimal window is
sign-split because bytes read as signed two's complement: half of
all binary atoms lead with a byte of `0x80` or above, and a
symmetric window would print that binary as plausible negative
integers, `0xdeadbeef` as `-559038737`. Under the split, decimals
appear only where a genuine number is the likely reading, and a
value that is really binary shows its bytes. Hex is never
misleading, a wrong decimal is. The printer can never distinguish
the two readings of the same bytes, an atom carries no record of
how it was written, so the window is chosen to make the common
reading the printed one.

Operator opcodes in data position print as data. The atom `0x10`
prints as `16` unless it sits in operator position, where it prints
as `+`. Both spellings assemble to the same byte, so the display
choice never changes the tree.

## Examples

```
(+ (q . 2) (q . 3))          ; serializes to ff10ffff0102ffff010380
(52 . 100000000)             ; amounts up to 8 bytes print decimal
(x "err")                    ; string atoms print readably
(sha256 0xdeadbeef)          ; negative-reading binary stays hex
(> 3 -1)                     ; small negative constants stay decimal
(a (q . (f 1)) (q . (99)))   ; reader input, prints back as (a (q 5 1) (q 99))
```
