# BitLisp VM

Status: Phase 1 in progress. Sections 1 to 6 are normative for the
evaluator core and the arithmetic operator family. Remaining operator
families land one session at a time, each extending section 4 and the
vector corpus together.

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

The deserializer rejects, with error `bad_encoding`:

1. Truncated input, and input with trailing bytes after the root node.
   Deserialization consumes the input exactly.
2. Non-minimal length encodings. An atom must use the shortest form
   that can express its length, and a one-byte atom with value
   `0x00`-`0x7f` must use the one-byte form.
3. The `0xfc`, `0xfd`, and `0xfe` prefixes.

The serializer emits the canonical form. Serialize and deserialize are
exact inverses on the accepted domain.

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
   - `0x02` (**apply**) checks its arity (exactly 2) here, then
     charges 90, then evaluates the first result as a program with
     the second result as its environment. That evaluation's result
     or error is the apply's.
   - A table operator checks arity, validates arguments, and charges
     per [COSTS.md](COSTS.md), in the per-operator interleaving
     specified there.

### 3.3 Cost budget

Cost accrues as evaluation proceeds and is checked against `max_cost`
at every charge. The budget is inclusive: a program whose total cost
equals `max_cost` exactly succeeds. Exceeding it raises
`cost_exceeded`.

## 4. Operator table

Implemented so far: the core specials and the arithmetic family.
Remaining families (bytes and strings, tree ops, crypto) land in later
sessions.

| Opcode | Name | Arity | Semantics |
| --- | --- | --- | --- |
| `0x01` | `q` quote | none | Returns its unevaluated tail. Section 3.2. |
| `0x02` | `a` apply | 2 | Evaluates result 1 as a program with result 2 as environment. |
| `0x08` | `x` raise | any | Evaluates its arguments, then raises `user_raise`. Never returns. |
| `0x10` | `+` add | 0 or more | Sum of integer arguments. No arguments gives nil (zero). |
| `0x11` | `-` subtract | 0 or more | First argument minus the rest. No arguments gives nil, one argument returns it. |
| `0x12` | `*` multiply | 0 or more | Product. No arguments gives 1 (`0x01`). |
| `0x13` | `/` divide | 2 | Floor division, truncating toward negative infinity. Divisor zero raises `div_by_zero`. See divergence D6. |
| `0x14` | `divmod` | 2 | Returns the pair `(quotient . remainder)` under floor division. Divisor zero raises `div_by_zero`. |
| `0x15` | `>` greater | 2 | Signed integer comparison. TRUE if the first argument is strictly greater. |

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

## 5. Error taxonomy

Errors are consensus-relevant only as "the spend is invalid". The
classes exist so vectors and the diff harness can assert that BitLisp
fails for the same reason as the oracles. Oracle message columns are
informative, not normative.

| Code | Raised when | chia_rs message | clvm message |
| --- | --- | --- | --- |
| `bad_encoding` | Deserialization fails (section 2) | bad encoding | (varies) |
| `path_into_atom` | Path lookup steps into an atom | path into atom | path into atom |
| `operator_not_atom` | Pair in operator position | (accepted, D4) | in ((X)...) syntax X must be lone atom |
| `reserved_operator` | Empty atom in operator position | Reserved operator | reserved operator |
| `unknown_operator` | Operator atom not in the table | (accepted, D3) | (accepted, D3) |
| `bad_arg_list` | Operator arguments are not a proper list | (varies) | (varies) |
| `wrong_arg_count` | Operator arity violated | InvalidOperatorArg | (per-op message) |
| `arg_not_atom` | Integer operator got a pair | InvalidOperatorArg | (per-op message) |
| `arg_too_long` | Operand exceeds a section 4 size limit | InvalidOperatorArg | (absent, the `clvm` package has no operand limits) |
| `div_by_zero` | Division or divmod by zero | Division by zero | div/divmod with 0 |
| `user_raise` | The `x` operator | clvm raise | clvm raise |
| `cost_exceeded` | Cost budget exceeded | cost exceeded or below zero | cost exceeded |

## 6. Divergence from CLVM

Every entry names the divergence, the rationale, and the vectors that
pin it. No divergence exists outside this table. "Both oracles" means
`chia-rs` flags 0 (consensus) and the `clvm` Python package.

| # | Area | CLVM behavior | BitLisp behavior | Rationale | Vectors |
| --- | --- | --- | --- | --- | --- |
| D1 | BLS operators | `point_add`, `pubkey_for_exp`, BLS extension ops present | absent, `unknown_operator` | Bitcoin has no BLS. Removing them removes their entire attack and cost surface. | `vm/operators.json` |
| D2 | secp256k1 | `secp256k1_verify` post-hardfork op | `secp_verify`, BIP340 Schnorr (crypto family session) | Native curve, native signature scheme. | TODO Phase 1 crypto session |
| D3 | Unknown operators | Both oracles accept unknown opcodes, cost derived from the opcode bytes, result nil | `unknown_operator` error | The operator set is closed by design. Bitcoin soft-forks at the tapleaf-version level, not through unknown-opcode acceptance. PROVISIONAL, see section 8. | `vm/dispatch.json` |
| D4 | Pair in operator position | `clvm` rejects. `chia-rs` accepts via a legacy apply-style rule (observed: `((A . B) . rest)` dispatches on `A` with arity errors reported for `A`'s operator) | `operator_not_atom` error | The oracles disagree with each other. Strict rejection is the smaller, reviewable surface. PROVISIONAL, see section 8. | `vm/dispatch.json` |
| D5 | Deserialization strictness | Both oracles accept non-minimal length encodings, trailing bytes, and (chia-rs) `0xfe` back-references | `bad_encoding` for all three (section 2) | Witness bytes must have exactly one accepted spelling per program. Malleability of the serialized form is a consensus hazard in the Bitcoin context. | `vm/serialize.json` |
| D6 | `/` with negative operands | Consensus (`chia-rs`): floor division. The `clvm` package injects a policy error ("deprecated") that is not consensus | Floor division, matching consensus | Intersection parity targets the consensus oracle. The Python package's rejection is library policy, the diff harness treats it as an expected divergence. OPEN QUESTION, see section 8. | `vm/arith.json` |

## 7. Oracle provenance

Oracles are released artifacts pinned as dev dependencies in
`pyproject.toml` (extra `oracles`). Pin bumps follow the
adopt/take/decline triage in `docs/execution-plan.md`.

| Oracle | Version | Pinned | Upstream commit | Notes |
| --- | --- | --- | --- | --- |
| `clvm` (PyPI) | 0.9.15 | 2026-07-26 | TODO on first triage | Python oracle. Carries non-consensus library policy (see D6), lacks the consensus operand size limits (section 4), and checks the cost budget only after an operator completes. The diff harness tolerates all three, each tagged in its output. |
| `chia-rs` (PyPI) | 0.46.0 | 2026-07-26 | TODO on first triage | Consensus oracle, run with flags 0 |

Divergent operators are tested against their own oracles. `secp_verify`
will use the official BIP340 vectors plus libsecp256k1 via `coincurve`.

## 8. Open questions for design ratification

Decisions taken provisionally by the implementing session, to be
ratified or overturned in an architecture session. Overturning any of
these is a spec amendment plus vector update in one reviewed commit.

1. **D3 (unknown operators).** Strict rejection implemented. Confirm
   that BitLisp's upgrade path is new tapleaf versions and that
   unknown-opcode acceptance stays out permanently.
2. **D4 (pair operator).** Strict rejection implemented, which matches
   the Python oracle and rejects chia_rs's legacy rule. Confirm.
3. **D6 (negative division).** Consensus floor semantics implemented.
   Chia deprecated negative `/` operands at the policy layer because
   floor division on negatives surprises programmers. Options: keep
   floor semantics, reject negative operands in consensus, or drop
   `/` entirely and keep only `divmod`. Needs a decision before the
   operator set freezes.
