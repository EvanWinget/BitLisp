# Mutation triage

The vector corpus is the source of truth between sessions (ground
rule 2), which makes its strength a question worth measuring. The
diff harness measures the reference against the oracles. The
mutation harness, `tools/mutate.py`, measures the corpus against the
reference: it breaks the reference in one small way at a time and
asks whether the corpus notices. This record keeps the results of
each pass, the survivor classes accepted with their rationale, and
the vectors each pass added. It is the corpus-side counterpart of
the divergence review in the two record docs.

## Method

The harness generates every mutant of every module in
`python/bitlisp/` from a fixed set of edits: each comparison operator
flipped to its neighbor or negation, each arithmetic and bitwise
operator swapped, each `and` and `or` exchanged, each integer
constant moved by one and each boolean flipped, each `if` test
negated, each `not` removed, each `raise` deleted, and `break` and
`continue` exchanged. Each mutant runs the whole corpus in a private
mirror of the tree. A mutant the corpus fails is killed. One the
corpus passes survived and is triaged by hand into a class below.
One that makes the reference raise outside its error taxonomy on
some case, while no case in any file reaches a verdict, crashed:
detected by Python rather than by the corpus, and counted apart so
the corpus's coverage is not overstated by kills it did not earn.
Every case runs regardless, so a verdict anywhere outranks a crash.
With `--tests`, every corpus survivor also runs the pytest suite
(hypothesis invariants, oracle differentials, unit tests), which
separates survivors nothing catches from survivors the tests catch
but the corpus does not.

    .venv/bin/python tools/mutate.py --tests --report mutants.json

The run refuses to start unless the unmutated tree passes every
oracle the mutants face. A timeout is the same kind of detection: a
mutant that hangs is a mutant the budget eventually rejects, at a
cost in wall clock the harness will not pay, so it too is counted
apart from the kills.

## Survivor classes

Each survivor is triaged into one class. The first five are
accepted without a vector, each for a stated reason. The sixth is
the finding the harness exists for.

| class | meaning | accepted because |
| --- | --- | --- |
| equivalent | the mutant computes the same function on every input | nothing to pin: the constant is a private tag, the index is `[0]` against `[-1]` on a one-element list, the shifted low bits are already set, the annotation is never evaluated, the frozen flag guards a hash nobody takes |
| unreachable guard | the deleted or flipped check cannot fire on any input the caller can supply | the guard defends an invariant of the implementation (a mistyped error code, a width the caller already checked, the apply backstop that the charge-before-completion invariant makes dead), not a rule of the spec |
| same code | the mutant changes which check reports a defect, never whether it is a defect | the corpus pins error codes, and two checks that share a code are indistinguishable by design: which of them fires is a diagnostic, and fail-fast is the contract (decision 22) |
| model precondition | the mutant weakens the transaction model's constructor in `tx.py` | a malformed model is a harness bug and raises `ValueError`, never a spend failure. The model is the reference's stand-in for base consensus, and every vector is a well-formed transaction by construction |
| beyond reach | the input that would distinguish the mutant cannot be built, or cannot be carried in a vector | the boundary sits above the 4 MB witness ceiling, needs a signature with a scalar in a range no signer can reach without infeasible work, or needs an atom too large for the corpus and is pinned by a unit test instead |
| gap | a behavior the spec states and no vector pins | fixed the same day: a vector with its spec citation |

Not a class, but recorded: test-facing helpers exported from the
package whose only callers are the invariant suites (`condition_cost`,
which the cost invariants use to check that the meter's total equals
the per-condition sum) survive the corpus by construction and are
pinned by `--tests`.

## Passes of 2026-08-23 and 2026-09-05

The first pass ran against `main` at PR 60 (`7eee46f`) and found the
seventeen gaps below. The second ran on 2026-09-05 against `main` at
PR 66 (`95ae47d`) merged with this branch, the corpus at 1,126 cases,
after the review reshaped the harness: crashes and timeouts told
apart from kills, a case's verdict outranking an earlier case's
escape, the doubled negations deduplicated, and the
augmented-assignment, expression-test, and while sites added. The
table is the second pass.

| module | mutants | killed | crashed | survived | timeout |
| --- | --- | --- | --- | --- | --- |
| conditions | 391 | 310 | 41 | 40 | 0 |
| costs | 114 | 114 | 0 | 0 | 0 |
| errors | 2 | 0 | 1 | 1 | 0 |
| machine | 79 | 61 | 13 | 5 | 0 |
| operators | 369 | 307 | 44 | 17 | 1 |
| secp256k1 | 148 | 105 | 26 | 15 | 2 |
| serialize | 166 | 106 | 24 | 34 | 2 |
| sexp | 35 | 27 | 8 | 0 | 0 |
| tx | 168 | 93 | 14 | 61 | 0 |
| validation | 141 | 120 | 14 | 7 | 0 |
| total | 1,613 | 1,243 | 185 | 180 | 5 |

The first pass, on the tree before PR 60 merged, had 195 survivors
out of 1,720 mutants under the old counting, and 180 out of 1,651
after its vectors landed, with 225 crashes under the rule that ended
a file at its first escape. The 185 crashes are dominated by deleted
raises and shifted indices that Python detects before any verdict,
and the corpus takes no kill credit for them. Of the 180 survivors,
the pytest suite kills 53: 29 of the 61 model preconditions in
`tx.py`, ten of the fifteen in `secp256k1.py` (the group order moved
by one, the width guards, the point-at-infinity branch), nine in
`serialize.py` (length-form table constants, the floor at 2^20
among them, the `bytes`-only type check, the truncated-atom check),
the `name` table index, the reserved branch of `condition_cost`, and
the `frozen` flag of the derived-taproot output in `conditions.py`,
and one of `substr`'s negative-index checks. The other 127 survive
both, the five in `machine.py` and all seven in `validation.py`
among them. All 180 fall into the accepted classes below. The five
timeouts are mutants that loop until the budget rejects them: the
`if` operator returning one branch in both cases, the scalar
multiplication shifting its scalar the wrong way or by zero, and the
deserializer stepping backward or not at all.

### Gaps found, vectors added

Seventeen cases, each a behavior the spec states that no vector
exercised. All pass the reference, the two vm path cases were
cross-checked against the consensus oracle, and the seal case
against the vendored Bitcoin Core framework.

| site | mutant that survived | vector | spec |
| --- | --- | --- | --- |
| path cost, leading zero bytes | `break` to `continue` in the leading-zero count: a zero byte after a nonzero byte was counted as leading | `vm/paths.json` `path_trailing_zero_byte`, `path_leading_and_trailing_zero_bytes` | VM.md section 3.1 |
| one-byte atom in the long form | `<= 0x7F` to `< 0x7F` and `0x7F` to `0x7E`: `0x81 0x7F` accepted as canonical | `vm/serialize.json` `nonminimal_one_byte_atom_7f` | VM.md section 2 (D5) |
| invalid prefix byte | `>= 0xFC` to `> 0xFC`: a lone `0xFC` fell through every length form. The vector pins the error code, and the harness reports the mutant crashed rather than killed, since the fall-through indexes an empty list before any verdict | `vm/serialize.json` `lone_prefix_fc` | VM.md section 2 (D5) |
| three-byte length form floor | floor `0x2000` to `0x1FFF`: a length of 8,191 in the three-byte form accepted as minimal | `vm/serialize.json` `nonminimal_length_e0_at_8191` | VM.md section 2 (D5) |
| ASSERT_SEQUENCE_HEIGHT domain | low bound `0` to `1` and to `-1`: zero rejected, minus one accepted | `conditions/time-asserts.json` `seqheight_zero`, `seqheight_negative` | CONDITIONS.md time asserts |
| reserved declared cost | `cost < 0` to `cost < -1`: a declared cost of exactly -1 reported as `reserved_cost_too_low` instead of `bad_condition_arg` | `conditions/encoding.json` `reserved_cost_minus_one` | CONDITIONS.md section 1, VALIDATION.md rule 6 |
| ASSERT_MY_SCRIPTPUBKEY and ASSERT_MY_AMOUNT arity | the arity raise deleted: two operands accepted, the second ignored | `conditions/self-asserts.json` `scriptpubkey_arity_zero`, `scriptpubkey_arity_two`, `amount_arity_zero`, `amount_arity_two` | CONDITIONS.md self asserts |
| specifier field shape | the atom check on a non-amount specifier field deleted: a pair carried into the ledger | `conditions/messages.json` `assure_script_specifier_pair` | CONDITIONS.md message family |
| ASSERT_ANNOUNCEMENT arity | the arity raise deleted: an empty list crashed instead of reporting `bad_condition_arity`. The vector pins the error code, and the harness reports the mutant crashed rather than killed, since Python detects it before any verdict | `conditions/messages.json` `assert_announcement_arity_zero` | CONDITIONS.md message family |
| composed specifier operand order | `continue` to `break` after an amount field: the identity fields after it never parsed | `conditions/messages.json` `assure_amount_tapleaf_specifier_parses` | CONDITIONS.md message family |
| specifier amount domain | `0 <= value` to `0 < value`: a zero-amount prevout unaddressable by amount | `validation/messages.json` `amount_specifier_over_zero_amount_input_balances` | VALIDATION.md rule 3, divergence C9 in the condition record |
| compact-size boundary in the txid and outputs hash | `n < 0xFD` to `n < 0xFC`: a 252-byte script encoded in the three-byte form | `validation/seals.json` `seal_outputs_script_252_bytes_one_byte_length`. The 253 side was already pinned by the existing boundary case and the seal unit suite, and two review-added 253 cases were removed as pinning nothing | VALIDATION.md transaction view (the txid and outputs-hash serializations) |

### Survivors accepted

The accepted survivors by class, with the sites that represent
them. Line numbers are omitted on purpose: the mutant inventory is
regenerated from the tree, and the classes are what a later pass
compares against.

**Equivalent.** The stepper tags in `machine.py` and the parser
tasks in `serialize.py` are private constants whose only property is
distinctness. Every `args[0]` after an arity check of one reads the
same element as `args[-1]`, as does `values[0]` on the final
one-element stack and `opcode_atom[0]` on a one-byte atom. The
serializer's length-form bound already has every low bit set, so
widening the mask term changes nothing, and a shift by zero is a
shift by zero in either direction. The dataclass `frozen` flags
guard a hash that no rule takes (matching is by index and by
equality). The `bytes | None` annotations in `tx.py` are deferred
under Python 3.14 and never evaluated. In `secp256k1.py`,
`(P + 2) // 4` equals `(P + 1) // 4` because `P + 1` is divisible by
4, and `lift_x(P)` returns `None` under either comparison because 7
is not a quadratic residue modulo `P`.

**Unreachable guard.** The `ValueError` on a mistyped error code in
`errors.py`, the apply backstop in `machine.py` that the
charge-before-completion invariant makes dead, the width checks in
`secp256k1.py` whose callers guarantee widths, the `AssertionError`
branches on an unknown specifier or binding kind in `validation.py`,
and the `bytes`-only type check at the deserializer's door.

**Same code.** Every `bad_encoding` sub-case in the deserializer
(a deleted truncation check falls into the next one), the `is_atom`
checks shadowed by width checks in the condition parsers (a pair has
length two), the first arity check of the two variadic message
parsers (the mode-derived count check reports the same code), the
`(empty)` fallbacks in error messages, and the `name` property's
table index and the taproot-versus-scriptpubkey choice in the
unsatisfied-scriptpubkey message, each of which only names a
condition in a message.

**Model precondition.** Every constructor check in `tx.py`: field
ranges, byte types, the non-empty input and output tuples, distinct
outpoints, and value conservation.

**Beyond reach.** The length-form boundaries at 2^20 and 2^27 bytes
(the first is pinned by `test_serialize.py`, the second lies above
the 4 MB witness ceiling), the prefix byte `0xFB` (a 12 GB atom),
and the compact-size two-byte and four-byte forms in the txid (a
65,536-byte script or 65,536 outputs, and the eight-byte form beyond
that). In `secp256k1.py`, a 64-byte signature with `s` at or above
the group order `N` reduces to a scalar below 2^256 minus `N`, which
no signer reaches without about 2^128 work, `r` at or above `P`
likewise, and a tweak scalar of exactly `N` is a hash preimage. The
group order itself moved by one changes only those checks.

## Re-running

A pass belongs with any change to `python/bitlisp/` that adds a
branch, and at each recurring checkpoint. Compare the survivor list
against the classes above: a survivor that fits none is a gap, and a
survivor in the gap table above is a regression in the corpus.
