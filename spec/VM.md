# BitLisp VM

Status: Phase 1 in progress. Sections 1 to 6 are normative for the
evaluator core, the tree ops family, the arithmetic operator family,
and the bytes and strings family. Remaining operator families land one
session at a time, each extending section 4 and the vector corpus
together.

The evaluator is CLVM-derived. The shared core must be bit-for-bit
equivalent to the pinned consensus oracle (`chia-rs`, flags 0) on the
operator intersection. Everything else appears in the divergence table
(section 6). Every behavior in this document is pinned by vectors in
`vectors/vm/`.

## 1. Values

A value (node) is either an **atom** (a byte string, possibly empty) or
a **pair** of two values. There are no other types.

- **nil** is the empty atom. It serves as the empty list, boolean
  false, and the integer zero.
- **TRUE** as produced by predicate operators is the one-byte atom
  `0x01`. Any value other than nil is truthy.
- **Integers** are atoms read as signed big-endian two's complement.
  The empty atom is zero. Operators accept redundantly encoded integer
  arguments (leading `0x00` on non-negatives, leading `0xff` on
  negatives) and cost them at their actual byte length. Operator
  *results* are always minimally encoded: no redundant leading byte,
  zero is the empty atom.
- **Proper list**: nil, or a pair whose rest is a proper list.

## 2. Serialization

BitLisp uses the CLVM serialization format with strict canonicality
rules on input (divergence D5). One node serializes as follows.

| First byte | Meaning |
| --- | --- |
| `0x00`-`0x7f` | One-byte atom containing that byte |
| `0x80`-`0xbf` | Atom, length in the low 6 bits, bytes follow |
| `0xc0`-`0xdf` | Atom, 13-bit length: low 5 bits then 1 more length byte |
| `0xe0`-`0xef` | Atom, 20-bit length: low 4 bits then 2 more length bytes |
| `0xf0`-`0xf7` | Atom, 27-bit length: low 3 bits then 3 more length bytes |
| `0xf8`-`0xfb` | Atom, 34-bit length: low 2 bits then 4 more length bytes |
| `0xfc`, `0xfd` | Invalid |
| `0xfe` | Invalid (CLVM back-reference marker, not in BitLisp v0) |
| `0xff` | Pair: the two serialized children follow |

nil is `0x80` (the zero-length case of the second row).

Deserialization operates on an immutable byte string. The reference
implementation rejects any other input type with `bad_encoding`
before reading a byte, so type coercion can never produce a
differently shaped tree.

The deserializer rejects, with error `bad_encoding`:

1. Truncated input, and input with trailing bytes after the root node.
   Deserialization consumes the input exactly.
2. Non-minimal length encodings. An atom must use the shortest form
   that can express its length, and a one-byte atom with value
   `0x00`-`0x7f` must use the one-byte form.
3. The `0xfc`, `0xfd`, and `0xfe` prefixes.

The serializer emits the canonical form. Serialize and deserialize are
exact inverses on the accepted domain.

The length forms cap an atom at 2^34 - 1 bytes, so a longer atom has
no wire encoding. The serializer reports `bad_encoding` for such an
atom, the one case where that error arises outside deserialization.
Input atoms are never oversized, deserialization bounds them by
construction. Evaluation can only build an oversized atom as a
freshly allocated operator result, and every freshly built result
atom charges `MALLOC_COST_PER_BYTE = 10` per byte, so reaching this
rejection requires a budget of at least 10 * 2^34, about 1.7 * 10^11
cost units. The Phase 3 weight mapping is expected to grant budgets
far below that threshold, making the rejection unreachable in
consensus (section 8, question 4).

## 3. Evaluation

`run(program, env, max_cost)` returns `(cost, value)` or an error from
the taxonomy in section 5. Errors carry no consensus data beyond their
class. Cost accounting rules are in [COSTS.md](COSTS.md), the constants
below are cited from its table.

### 3.1 Atom program: path lookup

An atom program is a **path** into `env`, read as an unsigned
big-endian integer (leading zero bytes are allowed and costed).

- Path 0 (any encoding, including nil) returns nil.
- Otherwise, ignore the highest set bit and walk the remaining bits
  from least significant to most significant: bit 0 steps to the first
  (left) child, bit 1 steps to the rest (right) child. The value
  arrived at is the result. Path 1 is the whole environment.
- Stepping into an atom raises `path_into_atom`.
- Cost: `40 + 4 * max(1, bit_length(path)) + 4 * leading_zero_bytes`.
- The walk precedes the charge: `path_into_atom` is reported
  regardless of the remaining budget, and a successful lookup's cost
  is charged and checked after the walk completes.

### 3.2 Pair program: operator application

For a program `(op . args)`, in this exact sequence:

1. If `op` is a pair, raise `operator_not_atom`, uncharged
   (divergence D4).
2. If `op` is the atom `0x01` (**quote**), charge 20 and return
   `args`, exactly as given, unevaluated. There is no arity
   constraint: `(q . X)` returns X whether X is an atom, pair, or
   nil.
3. `args` must be a proper list, else `bad_arg_list`, raised before
   any charge for this application.
4. Identify the operator. Opcode matching is exact on the atom bytes:
   a redundantly encoded integer such as `0x0010` is not opcode
   `0x10`. An atom that is neither in the operator table (section 4)
   nor the empty atom raises `unknown_operator`, uncharged
   (divergence D3). Otherwise (a table operator, apply, or the empty
   atom) charge the dispatch cost 1 now, before any argument is
   evaluated.
5. Evaluate each argument in the same environment, **right to left**
   (the CLVM stack-machine order). The order is consensus-visible:
   when more than one argument fails, the error of the rightmost
   failing argument is the one raised, and cost accrues in evaluation
   order against the budget.
6. Apply. All application-time errors come after every argument has
   evaluated, so argument errors always win:
   - The empty atom raises `reserved_operator` here, not at
     identification: its dispatch cost is charged and its arguments
     evaluate first.
   - `0x02` (**apply**) checks its arity (exactly 2) here, uncharged.
     Its cost 90 then accrues without an immediate budget check: the
     check rides on the applied program's first charge, so pre-charge
     failures inside the applied program (a path walk into an atom,
     an improper argument list) are reported even when the accrued
     cost already exceeds the budget. Such a charge always exists,
     because every program charges before it completes (a path
     lookup, a quote, or a dispatch cost), so no program can succeed
     with an accrued cost above the budget. Apply then evaluates the first
     result as a program with the second result as its environment,
     and that evaluation's result or error is the apply's.
   - A table operator checks arity, validates arguments, and charges
     per [COSTS.md](COSTS.md), in the per-operator interleaving
     specified there.

### 3.3 Cost budget

Cost accrues as evaluation proceeds and is checked against `max_cost`
at every charge. The budget is inclusive: a program whose total cost
equals `max_cost` exactly succeeds. Exceeding it raises
`cost_exceeded`.

`max_cost` is a nonnegative integer. In the consensus interface it is
an unsigned 64-bit quantity, derived from transaction weight in the
Phase 3 mapping. The Python reference accepts any nonnegative Python
integer and does not enforce the 64-bit bound, the hardened
implementation will. A budget of zero is a real budget: every program
charges at least once before completing, so no program succeeds under
a zero budget. A program whose uncharged checks fail first (a path
walk into an atom, an improper argument list, an unknown operator)
reports that error, every other program reports `cost_exceeded`. Both
CLVM oracles instead treat a zero `max_cost` as unlimited (divergence
D7).

**The charge-before-completion invariant.** Every program charges at
least once before it completes: a path lookup charges after its walk,
a quote charges 20, and every other application either fails or
charges the dispatch cost 1 before its operator runs. Apply's
deferred budget check (section 3.2) and the zero-budget rule above
both rest on this invariant, and every future operator and special
form must preserve it. As a backstop, `run` checks the accrued cost
against the budget once more when evaluation completes. The backstop
cannot fire while the invariant holds, so no vector can pin it. If a
future change broke the invariant, the backstop would turn an
over-budget success, a soundness failure, into `cost_exceeded`,
failing closed.

## 4. Operator table

Implemented so far: the core specials, the tree ops family, the
arithmetic family, the bytes and strings family, the bitwise family,
and the boolean family. The remaining family (crypto) lands in a
later session.

| Opcode | Name | Arity | Semantics |
| --- | --- | --- | --- |
| `0x01` | `q` quote | none | Returns its unevaluated tail. Section 3.2. |
| `0x02` | `a` apply | 2 | Evaluates result 1 as a program with result 2 as environment. |
| `0x03` | `i` if | 3 | Selects on the first argument: nil selects the third argument, any other value selects the second. All three arguments are evaluated first, there is no lazy branch. |
| `0x04` | `c` cons | 2 | Builds the pair `(first . second)`. |
| `0x05` | `f` first | 1 | The left cell of a pair argument. An atom argument raises `arg_not_pair`. |
| `0x06` | `r` rest | 1 | The right cell of a pair argument. An atom argument raises `arg_not_pair`. |
| `0x07` | `l` listp | 1 | TRUE if the argument is a pair, nil if it is an atom. |
| `0x08` | `x` raise | any | Evaluates its arguments, then raises `user_raise`. Never returns. |
| `0x09` | `=` equal | 2 | Byte equality of two atoms: TRUE if identical, nil otherwise. A pair argument raises `arg_not_atom`. |
| `0x0a` | `>s` greater-bytes | 2 | Unsigned lexicographic comparison of two atoms: TRUE if the first is greater, nil otherwise. |
| `0x0c` | `substr` | 2 or 3 | The slice of an atom from a start index to an end index, which defaults to the atom's length. |
| `0x0d` | `strlen` | 1 | The byte length of an atom, as a minimally encoded integer. |
| `0x0e` | `concat` | 0 or more | The concatenation of its atom arguments. No arguments gives nil. |
| `0x10` | `+` add | 0 or more | Sum of integer arguments. No arguments gives nil (zero). |
| `0x11` | `-` subtract | 0 or more | First argument minus the rest. No arguments gives nil, one argument returns it. |
| `0x12` | `*` multiply | 0 or more | Product. No arguments gives 1 (`0x01`). |
| `0x13` | `/` divide | 2 | Floor division, truncating toward negative infinity. Divisor zero raises `div_by_zero`. See divergence D6. |
| `0x14` | `divmod` | 2 | Returns the pair `(quotient . remainder)` under floor division. Divisor zero raises `div_by_zero`. |
| `0x15` | `>` greater | 2 | Signed integer comparison. TRUE if the first argument is strictly greater. |
| `0x16` | `ash` arithmetic shift | 2 | Shift of the value's integer reading by a signed count: positive shifts left, negative shifts right with sign extension. |
| `0x17` | `lsh` logical shift | 2 | Shift of the value's bytes read as an unsigned integer, re-encoded signed. |
| `0x18` | `logand` | 0 or more | Bitwise AND fold over sign-extended two's complement. No arguments gives -1. |
| `0x19` | `logior` | 0 or more | Bitwise inclusive-OR fold. No arguments gives nil. |
| `0x1a` | `logxor` | 0 or more | Bitwise exclusive-OR fold. No arguments gives nil. |
| `0x1b` | `lognot` | 1 | Bitwise complement, always `-(value + 1)`. |
| `0x20` | `not` | 1 | TRUE if the argument is nil, nil otherwise. |
| `0x21` | `any` | 0 or more | TRUE if at least one argument is not nil. No arguments gives nil. |
| `0x22` | `all` | 0 or more | TRUE if every argument is not nil. No arguments gives TRUE. |

The tree ops select, build, and compare nodes without interpreting
them as integers:

- `=` compares raw atom bytes. Redundantly encoded integers are
  distinct values to `=`: `0x0001` does not equal `0x01`, and `0x00`
  does not equal nil. There is no operand size limit, the cost is
  linear in the bytes compared.
- `i` treats nil as the only false value. Every other value selects
  the second argument, the one-byte atom `0x00` and every pair
  included.
- No tree op charges malloc: every result is an existing node, the
  pair built by `c`, or a shared constant (TRUE, nil).
- Each tree op's checks all precede its single charge, in the order
  given in COSTS.md: arity, then the pair or atom requirements. Every
  check therefore wins over `cost_exceeded` when both would fire.

All arithmetic operators require atom arguments and raise
`arg_not_atom` on a pair argument. Arity violations raise
`wrong_arg_count`. Results are minimally encoded integers (section 1),
except `>` which returns TRUE or nil.

**Operand size limits**, matching the consensus oracle and raising
`arg_too_long`:

| Operator | Limit |
| --- | --- |
| `*` | each argument atom at most 256 bytes |
| `/`, `divmod` | numerator at most 256 bytes, divisor at most 1024 bytes |
| `+`, `-`, `>` | no limit |

The limit applies to the argument atom's length as given, redundant
encoding bytes included: a 257-byte atom encoding the value 2 is
rejected. It does not apply to intermediate values: a multiplication
accumulator may exceed 256 bytes and keep multiplying. Ordering,
consensus-visible and pinned by vectors:

- `*` checks each argument's atomness and size together, argument by
  argument, in the conversion order of COSTS.md: an oversized first
  argument is reported before a pair in the second.
- `/` and `divmod` check both arguments' atomness first, then both
  sizes: a pair in either argument is reported before an oversized
  operand.
- Size checks precede the operator's charges and the zero-divisor
  check: dividing an oversized numerator by zero reports
  `arg_too_long`.

Floor division examples, pinned by vectors: `7 / 2 = 3`,
`-7 / 2 = -4`, `divmod(-7, 2) = (-4 . 1)`.

The bytes and strings ops treat atoms as raw byte strings, never as
integers. All four require atom arguments and raise `arg_not_atom` on
a pair, except that a pair in a `substr` index position raises
`bad_index` (below). None has an operand size limit.

- `>s` compares raw atom bytes as unsigned values, lexicographically:
  the first differing byte position decides, the greater byte winning,
  and when one atom is a proper prefix of the other the longer one is
  greater. Equal atoms give nil. Redundantly encoded integers are
  distinct values to `>s`, and `0x0001` is less than `0x01` because
  its first byte is smaller. No malloc: the result is TRUE or nil.
- `strlen` returns its argument's byte length as given, redundant
  encoding bytes included, as a minimally encoded integer.
- `concat` returns the concatenation of its arguments in argument
  order, a freshly built atom. Concatenation is the one implemented
  operator whose result can exceed every input atom, but its
  per-input-byte charge is above the plain malloc rate, so the
  section 2 threshold for building an atom the wire format cannot
  encode applies unchanged.
- `substr` returns the slice of its first argument from index `start`
  up to but not including index `end`. The two-argument form
  `(substr data start)` slices to the end of the atom. The result is
  a portion of an existing atom, charged no malloc, and never longer
  than the data argument, so `substr` alone can never build an
  oversized atom.

`substr` index arguments follow consensus exactly, pinned by vectors:

- An index must be an atom of at most four bytes. A longer atom or a
  pair raises `bad_index`.
- The index value is the signed big-endian two's-complement reading
  of the atom, the same reading integers get everywhere else (section
  1). The empty atom is index 0, and leading zero bytes are legal
  within the four-byte cap: `0x0000ffff` is 65535, while a five-byte
  encoding of the same value raises `bad_index`.
- The indices must satisfy `0 <= start <= end <= strlen(data)`, else
  `index_out_of_range`. A negative index is out of range, not a
  from-the-end reference. `start = end` gives nil, and both indices
  equal to the length are legal, so `(substr data (strlen data))` is
  nil for any atom.

The bitwise ops read atoms as signed two's-complement integers, like
the arithmetic family, and return minimally encoded integer results.
All six require an atom in every value position and raise
`arg_not_atom` on a pair there, except that a pair in a shift count
position raises `bad_index` (below). None has an operand size limit.

- `logand`, `logior`, `logxor` fold their arguments under bitwise
  AND, inclusive OR, and exclusive OR of sign-extended two's
  complement. With no arguments they return their fold identities:
  -1 (the one-byte atom `0xff`) for `logand`, nil for the other two.
  With one argument they return its value, minimally re-encoded.
- `lognot` takes exactly one argument and returns its bitwise
  complement, always `-(value + 1)`. `(lognot nil)` is -1.
- `ash` shifts the value's integer reading: a positive count shifts
  left, a negative count shifts right with sign extension, so a right
  shift floors like `/`: `(ash -7 -1)` is -4, and a negative value
  shifted right far enough settles at -1, never 0.
- `lsh` shifts the value's byte string read as an unsigned integer,
  redundant encoding bytes included, then encodes the result signed
  as usual. A shift can therefore change sign and value: `(lsh -1 0)`
  is 255 (`0x00ff`), and `(lsh 0x00ff 0)` is also 255 because the
  unsigned reading of both spellings is 255.

Shift count arguments follow the substr index rules, pinned by
vectors: an atom of at most four bytes read as a signed integer,
leading zero bytes legal within the cap, a pair or a longer atom
raising `bad_index`. The count's magnitude is additionally capped at
65535, raising `shift_too_large` beyond it in either direction. The
checks run in consensus order, all before any charge: the value's
atom check first (a pair value is reported before any count defect),
then the count's shape, then the count's range.

A left shift can grow an atom by at most 8191 bytes over its input,
and the result charges plain malloc per byte, so the section 2
threshold for building an atom the wire format cannot encode applies
unchanged.

The boolean ops test nil-ness and return the shared TRUE and nil
constants. They are the one non-tree family that accepts pair
arguments: any node is legal in any position, and nil is the only
false value (the one-byte atom `0x00` and every pair are true), the
same rule `i` applies to its selector.

- `not` takes exactly one argument: TRUE if it is nil, nil otherwise.
- `any` returns TRUE if at least one argument is not nil, and nil
  with no arguments.
- `all` returns nil if at least one argument is nil, and TRUE with no
  arguments.
- No boolean op charges malloc, and no boolean cost carries a
  per-byte term: a large atom argument costs the same as a one-byte
  one.

## 5. Error taxonomy

Errors are consensus-relevant only as "the spend is invalid". The
classes exist so vectors and the diff harness can assert that BitLisp
fails for the same reason as the oracles. Oracle message columns are
informative, not normative.

| Code | Raised when | chia_rs message | clvm message |
| --- | --- | --- | --- |
| `bad_encoding` | Deserialization fails, or a result atom has no wire encoding (section 2) | bad encoding | (varies) |
| `path_into_atom` | Path lookup steps into an atom | path into atom | path into atom |
| `operator_not_atom` | Pair in operator position | (accepted, D4) | in ((X)...) syntax X must be lone atom |
| `reserved_operator` | Empty atom in operator position | Reserved operator | reserved operator |
| `unknown_operator` | Operator atom not in the table | (accepted, D3) | (accepted, D3) |
| `bad_arg_list` | Operator arguments are not a proper list | (varies) | (varies) |
| `wrong_arg_count` | Operator arity violated | InvalidOperatorArg | (per-op message) |
| `arg_not_atom` | An atom-only operator (`=`, the integer family, the bytes family outside `substr`'s index positions, or the bitwise family outside shift count positions) got a pair | InvalidOperatorArg | (per-op message) |
| `arg_not_pair` | `f` or `r` applied to an atom | InvalidOperatorArg: first/rest of non-cons | first/rest of non-cons |
| `arg_too_long` | Operand exceeds a section 4 size limit | InvalidOperatorArg | (absent, the `clvm` package has no operand limits) |
| `bad_index` | A `substr` index or a shift count argument is a pair or an atom longer than four bytes | (per-op) requires int32 args (with no leading zeros) | (per-op) requires int32 args |
| `index_out_of_range` | A `substr` index value is negative, past the end of the data, or an end before a start | Invalid Indices for Substring | invalid indices for substr |
| `shift_too_large` | An `ash` or `lsh` count's magnitude exceeds 65535 | Shift too large | shift too large |
| `div_by_zero` | Division or divmod by zero | Division by zero | div/divmod with 0 |
| `user_raise` | The `x` operator | clvm raise | clvm raise |
| `cost_exceeded` | Cost budget exceeded | cost exceeded or below zero | cost exceeded |

One message column is actively misleading: both oracles' `bad_index`
message claims to reject leading zeros, but both binaries accept
leading zero bytes on a `substr` index and on a shift count within
the four-byte cap, verified by probes and pinned by vectors. The
message text describes neither oracle's behavior and must not be
read back into the rule. The Python oracle additionally reports a
pair in a shift count position with its generic "requires int args"
message, indistinguishable from a pair in the value position, where
the consensus oracle distinguishes the two. The diff harness carries
a tolerance for that conflation.

## 6. Divergence from CLVM

Every entry names the divergence, the rationale, and the vectors that
pin it. No divergence exists outside this table. "Both oracles" means
`chia-rs` flags 0 (consensus) and the `clvm` Python package.

| # | Area | CLVM behavior | BitLisp behavior | Rationale | Vectors |
| --- | --- | --- | --- | --- | --- |
| D1 | BLS operators | `point_add`, `pubkey_for_exp`, BLS extension ops present | absent, `unknown_operator` | Bitcoin has no BLS. Removing them removes their entire attack and cost surface. | `vm/dispatch.json` |
| D2 | secp256k1 | `secp256k1_verify` post-hardfork op | `secp_verify`, BIP340 Schnorr (crypto family session) | Native curve, native signature scheme. | TODO Phase 1 crypto session |
| D3 | Unknown operators | Both oracles accept unknown opcodes, cost derived from the opcode bytes, result nil | `unknown_operator` error | The operator set is closed by design. Bitcoin soft-forks at the tapleaf-version level, not through unknown-opcode acceptance. PROVISIONAL, see section 8. | `vm/dispatch.json` |
| D4 | Pair in operator position | Both oracles accept `((X) . args)` when `X` is a lone atom, a legacy apply-style rule: `X` dispatches on the arguments unevaluated, charging apply's 90. They disagree on a non-nil tail in the operator pair: `chia-rs` ignores the tail and dispatches on the head, `clvm` rejects it | `operator_not_atom` error for every pair in operator position | The legacy rule is a remnant the oracles themselves disagree on at the edges. Strict rejection of the whole family is the smaller, reviewable surface. PROVISIONAL, see section 8. | `vm/dispatch.json` |
| D5 | Deserialization strictness | Both oracles accept non-minimal length encodings, trailing bytes, and (chia-rs) `0xfe` back-references | `bad_encoding` for all three (section 2) | Witness bytes must have exactly one accepted spelling per program. Malleability of the serialized form is a consensus hazard in the Bitcoin context. | `vm/serialize.json` |
| D6 | `/` with negative operands | Consensus (`chia-rs`): floor division. The `clvm` package injects a policy error ("deprecated") that is not consensus | Floor division, matching consensus | Intersection parity targets the consensus oracle. The Python package's rejection is library policy, the diff harness treats it as an expected divergence. Ratified, see section 8. | `vm/arith.json` |
| D7 | Zero cost budget | Both oracles treat `max_cost = 0` as unlimited | A zero budget is a real budget, no program succeeds under it (section 3.3) | A zero sentinel meaning unlimited is a library convenience, not consensus behavior. In the Bitcoin context the budget derives from transaction weight and is never legitimately zero, and an accidental zero must fail closed rather than open. Ratified, see section 8. | `vm/dispatch.json` |

## 7. Oracle provenance

Oracles are released artifacts pinned as dev dependencies in
`pyproject.toml` (extra `oracles`). Pin bumps follow the
adopt/take/decline triage in `docs/execution-plan.md`.

| Oracle | Version | Pinned | Upstream commit | Notes |
| --- | --- | --- | --- | --- |
| `clvm` (PyPI) | 0.9.15 | 2026-07-26 | TODO on first triage | Python oracle. Carries non-consensus library policy (see D6), lacks the consensus operand size limits (section 4), checks the cost budget only after an operator completes, and checks apply's cost immediately where consensus defers the check to the applied program's first charge (section 3.2). The diff harness tolerates all four, each tagged in its output. |
| `chia-rs` (PyPI) | 0.46.0 | 2026-07-26 | TODO on first triage | Consensus oracle, run with flags 0 |

Divergent operators are tested against their own oracles. `secp_verify`
will use the official BIP340 vectors plus libsecp256k1 via `coincurve`.

## 8. Open questions for design ratification

Decisions taken provisionally by the implementing session, to be
ratified or overturned in an architecture session. Overturning any of
these is a spec amendment plus vector update in one reviewed commit.

1. **D3 (unknown operators).** Strict rejection implemented. Confirm
   that BitLisp's upgrade path is new tapleaf versions and that
   unknown-opcode acceptance stays out permanently. The alternative,
   an in-language extension mechanism in the style of CLVM's
   `softfork` operator, was analyzed (discussion with Evan,
   2026-07-26) and is recorded here so ratification weighs it
   explicitly.

   - CLVM's unknown-opcode acceptance is not an upgrade path for
     value-returning operators. An unknown operator evaluates its
     arguments, charges a cost decoded from the opcode bytes, and
     returns nil into the continuing program. Assigning it real
     semantics later would change what deployed programs compute,
     not merely what is valid, which is not a soft fork. Chia's
     documentation states this directly, and Chia shipped its new
     operators first inside the `softfork` guard, then promoted
     them to first-class value-returning operators with a hard
     fork.
   - CLVM's `softfork` guard is sound and is assert-only by
     construction: the declared cost must equal the guarded
     program's actual cost, and the guarded result is always nil,
     so no value crosses the boundary. New operators arrive as
     verifiers, never as producers. Value-producing behavior can be
     simulated by commit-and-verify: the spender supplies the
     claimed result as witness data, the guard recomputes it and
     raises on mismatch, and the outer program uses the supplied
     value. Old nodes use it unverified, new nodes enforce it,
     which is the stricter-only direction a soft fork requires.
     This covers most verify-shaped features at a cost in witness
     bytes and program shape.
   - The guard is declined for v0 on four grounds. It is largely
     redundant with the tapleaf-version boundary, the total
     surrender point Bitcoin already provides in the style of
     OP_SUCCESS, where old nodes validate nothing and new semantics
     may therefore be arbitrary, value-producing included, by soft
     fork. Its machinery (an extension registry, a guard stack,
     exact cost equality, state rollback so no value escapes) is
     permanent consensus surface that must be perfect from v0,
     against a consensus core designed to stay small enough to
     review whole. It only benefits scripts that anticipated it,
     since deployed programs that predate it are equally frozen
     under either scheme. And the choice is reversible in exactly
     one direction: a guard can be added in a later leaf version
     once the cost model has matured, while a guard shipped in v0
     can never be removed.
   - Extensibility for deployed coins is planned at the condition
     layer instead (Phase 2): conditions are inert data in a
     program's output, so a fork can change what an unknown
     condition means to validators without changing what any
     program computes. The reserved-condition rule is the
     condition-layer analog of this question and gets its own
     decision in MATCHING.md.
2. **D4 (pair operator).** Strict rejection implemented. Probing both
   wheels (2026-07-26) corrected the record: the legacy apply-style
   rule for `((X) . args)` is in both oracles, not only chia_rs, so
   strict rejection diverges from both, and the oracles disagree
   only on a non-nil tail in the operator pair. Confirm that BitLisp
   rejects the whole family even though the lone-atom shape is
   common to both oracles.
3. **D6 (negative division).** Floor semantics RATIFIED (decision by
   Evan, 2026-07-26): `/` keeps consensus floor division on negative
   operands, and the alternatives (rejecting negative operands in
   consensus, or dropping `/` for `divmod` alone) are declined. The
   upstream deprecation traces to an admitted implementation bug,
   not a design position: the original Python operator carried a
   branch its own comment called "a buggy behavior from the initial
   implementation" (a quotient of exactly -1 with a nonzero
   remainder was rounded toward zero), consensus settled on clean
   floor division, and the Python library then deprecated negative
   operands in February 2023 rather than model the settled outcome.
   BitLisp matches the consensus binary, which the diff harness
   verifies on every run.
4. **D7 (zero budget).** Fail-closed RATIFIED (decision by Evan,
   2026-07-26): a zero `max_cost` rejects every program where the
   oracles treat it as unlimited. A budget bug must reject every
   spend, a recoverable liveness failure, rather than hand out
   unlimited execution, a soundness failure. Still open: whether the
   reference should also enforce the unsigned 64-bit budget bound the
   hardened implementation will have (section 3.3 currently records
   the bound without enforcing it). The bound interacts with
   serialization: a budget below 10 * 2^34 makes a result atom too
   long for the wire format unbuildable (section 2), and the u64
   bound alone does not. The Phase 3 weight mapping should record its
   maximum grantable budget against that threshold so the
   serializer's rejection of unrepresentable results is provably
   dead in consensus.
