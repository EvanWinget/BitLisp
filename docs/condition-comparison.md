# Condition and validation inventory: Chia, BitLisp

Informative, not normative. This document places Chia's deployed
condition vocabulary side by side with BitLisp's v0 vocabulary and
compares the two validation layers. It is the condition-layer companion
to [opcode-comparison.md](opcode-comparison.md). The BitLisp columns
restate [spec/CONDITIONS.md](../spec/CONDITIONS.md) and
[spec/VALIDATION.md](../spec/VALIDATION.md), which are the normative
sources. Divergence ids (C1 to C22) and decision ids (D-CC2) refer to
[condition-record.md](condition-record.md).

There is no bllsh column. bllsh has no condition layer at all: its
programs read the transaction directly through the `tx` and
`bip342_txmsg` operators, so its counterpart to this entire document
is the transaction-introspection section of
[opcode-comparison.md](opcode-comparison.md).

Sources, as read on 2026-07-31:

- **Chia**: the condition vocabulary dispatched by the pinned
  consensus oracle `chia-rs` 0.46.0 (provenance in
  [condition-record.md](condition-record.md) section 2), read from
  `opcodes.rs`, `conditions.rs`, and `messages.rs` in the
  `references/` clone. Those files are identical at the `0.46.0` tag
  and the clone's head. CHIP-0049 (the Chia 3.0 hard fork, in
  review) revises costs but not the vocabulary, and is noted where
  it matters.
- **BitLisp**: spec/CONDITIONS.md and spec/VALIDATION.md, Phase 2 in
  progress, plus the Phase 2 plan in
  [execution-plan.md](execution-plan.md).

Opcode numbers are not comparable across columns. BitLisp lays its
code space out fresh (divergence C4) rather than inheriting Chia's
assignments. Chia opcodes are written in decimal, upstream's
convention, and BitLisp opcodes in hex, the CONDITIONS.md convention.

The BitLisp column uses three statuses. **Normative** entries are in
CONDITIONS.md today, and the vocabulary v0 table is complete: no
entry remains planned. **Open** items await a named design decision.
**Not in the v0 plan** means no entry and no recorded decision,
which is not the same as declined: the consensus outcome is that
the opcode is invalid, and the reserved tier is the future path.

## Output creation

| Capability | Chia | BitLisp |
| --- | --- | --- |
| create an output | `CREATE_COIN` 51, target is a 32-byte puzzle hash, optional memo list | `CREATE_OUTPUT` 0x01, normative, target is full scriptPubKey bytes (C1), no memos (C2) |
| duplicate creation in one spend | rejected, identical children would collide under content-derived coin ids | valid, k identical claims require k distinct output slots (C3) |
| create a taproot output from components | absent | `CREATE_OUTPUT_TAPROOT` 0x02, normative, the validator computes the BIP341 tweak from `internal_key` and `merkle_root` (D-CC2) |

`CREATE_OUTPUT_TAPROOT` has no Chia analogue because Chia outputs
are puzzle hashes, not scriptPubKeys, so no tweak derivation exists
to encapsulate. The nearest relative anywhere is bllsh's
`secp256k1_muladd` operator, whose decline is recorded in D-CC2.

## Signatures

| Capability | Chia | BitLisp |
| --- | --- | --- |
| signature asserts | `AGG_SIG_ME` 50, `AGG_SIG_UNSAFE` 49, and six spend-binding variants 43 to 48 (parent, puzzle, amount combinations), BLS12-381 aggregated, message suffixed with the committed spend fields and a domain separator | landed, the signature assert family at `0x10` to `0x17` in Chia's opcode order: `ASSERT_SIG_MY_*` over the same binding menu re-addressed to prevout fields plus `ASSERT_SIG_RAW`, per-condition BIP340 triples with tagged-hash digests (decision 23, divergences C16 to C19) |

The signature scheme divergence is inherited from the VM layer:
BitLisp declined the BLS family and verifies BIP340 Schnorr over
secp256k1 (divergences D1 and D2 in `docs/vm-record.md`). Chia
composes each variant's message by appending fixed spend fields
and a suffix. BitLisp landed the program-composed message under a
per-variant tagged-hash digest with fixed-length binding fields
(decision 23 and divergence C17 in `docs/condition-record.md`).

## Time asserts

| Capability | Chia | BitLisp |
| --- | --- | --- |
| after, absolute height | `ASSERT_HEIGHT_ABSOLUTE` 83 | `ASSERT_LOCKTIME_HEIGHT` 0x20 |
| after, relative height | `ASSERT_HEIGHT_RELATIVE` 82 | `ASSERT_SEQUENCE_HEIGHT` 0x22 |
| after, absolute time | `ASSERT_SECONDS_ABSOLUTE` 81 | `ASSERT_LOCKTIME_TIME` 0x21 |
| after, relative time | `ASSERT_SECONDS_RELATIVE` 80 | `ASSERT_SEQUENCE_TIME` 0x23 |
| before variants | `ASSERT_BEFORE_*` 84 to 87, expiring spends | declined, structurally inexpressible in the field shape (condition-record.md decision 15) |

The four after-style asserts landed 2026-08-07 in the field
enforcement shape: they constrain the transaction's own locktime,
sequence, and version fields, and base consensus enforces those
fields against the chain (condition-record.md decision 15,
divergences C5 and C6). Double reference coverage in the vectors:
Bitcoin's deployed locktime and sequence rules for the field
semantics, and Chia's deployed comparison boundaries where the
shapes overlap. The before variants would make spend authorization
expire, a capability Bitcoin consensus has deliberately avoided
because a reorg can retroactively invalidate a confirmed spend.
The 2026-08-06 decline lean became a structural decline in
decision 15: the field shape has no valid-only-before rule to
delegate to.

## Self asserts

| Capability | Chia | BitLisp |
| --- | --- | --- |
| own identity | `ASSERT_MY_COIN_ID` 70 | `ASSERT_MY_OUTPOINT` `0x30`, normative (decision 20) |
| own parent | `ASSERT_MY_PARENT_ID` 71 | `ASSERT_MY_TXID` `0x31`, normative, the txid half of the outpoint |
| own program | `ASSERT_MY_PUZZLEHASH` 72 | `ASSERT_MY_SCRIPTPUBKEY` `0x32`, normative, raw script bytes |
| own amount | `ASSERT_MY_AMOUNT` 73 | `ASSERT_MY_AMOUNT` `0x33`, normative |
| own taproot components | absent | `ASSERT_MY_TAPROOT` `0x37`, normative, the D-CC2 mirror |
| own taptree | absent | `ASSERT_MY_TAPTREE` `0x38`, normative, reads the control block's internal key and merkle root at the generic cost (decision 28) |
| own birth time or height | `ASSERT_MY_BIRTH_SECONDS` 74, `ASSERT_MY_BIRTH_HEIGHT` 75 | declined, a chain read outside the transaction view (C13) |
| ephemerality | `ASSERT_EPHEMERAL` 76, the coin was created in the same block it is spent | declined, structurally inexpressible within one transaction (C14) |

The family landed 2026-08-08 (decision 20) with the natural
entries re-addressed to Bitcoin's spend identity, an outpoint and
a scriptPubKey rather than a parent, puzzle hash, and amount
triple. The two birth
asserts and `ASSERT_EPHEMERAL` compare against coin records that
exist in Chia's coin-set model and have no counterpart in the
VALIDATION.md transaction view, so porting any of them would first
require widening that view, a structural decision and not a
vocabulary entry. The ephemeral-coin gap specifically is already
recorded among the known honest costs in section 7 of the
evaluation doc: ephemeral-coin patterns do not port because there
is no intra-transaction chaining.

## Announcements, messages, concurrency

| Capability | Chia | BitLisp |
| --- | --- | --- |
| announcements | `CREATE_COIN_ANNOUNCEMENT` 60, `ASSERT_COIN_ANNOUNCEMENT` 61, `CREATE_PUZZLE_ANNOUNCEMENT` 62, `ASSERT_PUZZLE_ANNOUNCEMENT` 63 | `ANNOUNCE` 0x40 and `ASSERT_ANNOUNCEMENT` 0x41, normative, transaction-scoped, namespacing first-class in the arguments rather than payload prefix bytes, announcer precision chosen by the assert through the specifier grammar (decisions 10 and 16, divergence C11) |
| messages | `SEND_MESSAGE` 66, `RECEIVE_MESSAGE` 67 (CHIP-0025), mode flags select which sender and receiver fields the pairing commits to, paired within the surrounding block | `ASSURE` and `REQUIRE` at the same numeric opcodes (renamed 2026-08-20, decision 27), normative, strictly transaction-scoped counted balance with fields re-addressed to prevout data plus the execution-identity pair, tapleaf hash and merkle root, at bits 3 and 4 of each five-bit half (decisions 16 and 26, divergences C8 to C10 and C23) |
| concurrency asserts | `ASSERT_CONCURRENT_SPEND` 64, `ASSERT_CONCURRENT_PUZZLE` 65, another spend with the named coin id or puzzle hash occurs alongside this one | not in the v0 plan |

The scoping difference is the architectural one: Chia validates a
block's spends together, so its messages and concurrency asserts
reach any spend in the block. BitLisp validation is a pure function of
one transaction, so message pairing shrinks to the transaction
boundary and block-scoped concurrency has no place to attach.

The announcement row changed on 2026-08-06 (decision 10 in
condition-record.md). The message conditions are not the
announcements' successors in practice: announcements are the
unaddressed broadcast primitive, load-bearing for offers because
the asserting side cannot know counterparty coin ids at signing
time, while messages are addressed exact pairing. The v0 plan
therefore carries an addressed pair and a broadcast pair side by
side, both transaction-scoped.

## Fees and transaction-wide quantities

| Capability | Chia | BitLisp |
| --- | --- | --- |
| fee floor | `RESERVE_FEE` 52 | `RESERVE_FEE` `0x50`, normative (rule 7, decision 21) |
| fee ceiling | absent | declined (decision 21) |
| output count | absent | declined, exact and floor forms (decision 21) |
| input count | absent | declined, mirroring output count (decision 21) |
| weight, fee rate | absent | declined, self-referential (decision 21) |

The fee floor is the ported entry, matching Chia's deployed
checked-sum semantics exactly. The once-planned universal asserts
(`ASSERT_FEE_LE`, `ASSERT_OUTPUT_COUNT`) are recorded declines:
the transaction-wide forms are forbidden by the composition
guarantee (whose sole recorded exception is the seal family
below), the per-input fee bound decomposes into landed
vocabulary, and the composition-safe count floors had no
identified user. Decision 21 in the condition record carries the
full rationale and the reserved-tier reintroduction path.

## Seals

| Capability | Chia | BitLisp |
| --- | --- | --- |
| pin the spending transaction | absent, coin identity is content-derived so a spend's authorization is indifferent to which aggregate bundle carries it | `SEAL` `0x60`, normative, asserts the spending transaction's own txid (C20, decision 24) |
| pin the outputs alone | absent, same reason | `SEAL_OUTPUTS` `0x61`, normative, asserts the BIP 341 outputs hash, the fee-bumping posture (C20, decision 24) |

The seal family is the one pure addition in the vocabulary, born
from Bitcoin's positional output identity: an intercepted covenant
spend can otherwise be rebuilt around a grafted output with every
condition still holding. Chia never faces the problem, which is
why no Chia column entry exists to port. Sealed transactions are
excluded from the composition guarantee by its own hypothesis,
the family's recorded scoping.

## No-op and forward compatibility

| Capability | Chia | BitLisp |
| --- | --- | --- |
| assigned no-op | `REMARK` 1, always true, arguments ignored | no entry. Consensus-carried bytes with no consensus meaning are a recorded non-affordance (the C2 rationale). No REMARK-specific decision is recorded. |
| priced future opcode | `SOFTFORK` 90, first argument declares the cost, scaled by 10,000, no other semantics until a softfork assigns them | reserved tier 0x80 to 0xff, first argument declares the cost, floor of 500, no other semantics until assigned (VALIDATION.md rule 6) |
| unknown one-byte opcode | ignored, unenforced, zero cost | invalid (C4) |
| unknown multi-byte opcode | ignored, unenforced, cost computed from the opcode value | invalid, a condition opcode is exactly one byte (C4) |

The reserved tier is the C4 divergence's replacement for all three
Chia rows below the first: one priced hatch instead of a free
ignored tier plus a priced one, invalid by default everywhere else.

## Validation layers

Chia has no document corresponding to VALIDATION.md because its
validation problem is thinner: `CREATE_COIN` constructs the child coin
authoritatively rather than claiming a pre-existing transaction
output, so nothing like rule 1's assignment problem arises. The
comparison below is therefore between architectures, not between two
specs of the same shape.

| Property | Chia | BitLisp |
| --- | --- | --- |
| validation scope | a block's spends plus chain state (coin records, prior block height and timestamp) | a single transaction view and nothing else, the time asserts constrain the transaction's own locktime fields and base consensus enforces the fields (decision 15) |
| output identity | content-derived coin id (parent, puzzle hash, amount) | positional slot (scriptPubKey, amount) |
| output creation | authoritative construction, collision rejected | injective claim on existing slots, equality-only, multiset counting (rule 1, normative) |
| coexistence | every coin is a puzzle, no foreign outputs exist | mixed transactions with plain-taproot inputs and unmatched outputs (rule 2, normative) |
| cross-spend interaction | block-scoped messages and concurrency asserts | transaction-scoped messages (rule 3, normative) |
| dedup and multiplicity | deployed semantics, the cross-check source for the translated rule 4 tests | rule 4, normative, sort-bound multiplicity with no collapse |
| costing | deployed per-condition costs under the hard fork 2 flag (`CREATE_COIN` 1,350,000, `AGG_SIG` 1,200,000, message 700, generic 200, spend 450,000) | rule 5, normative, flat per-opcode constants on the shared per-input budget: generic 200, message 700, signature 1,300,000 tied to `secp_verify` (C22), output claim 1,350,000, no per-spend constant (C21), every constant PROVISIONAL pending Phase 4 (decision 25) |
| unknown conditions | ignored tiers | invalid plus the priced reserved tier (rule 6, normative) |

## Observations

- **Where Phase 2 stands.** Twenty-six vocabulary entries are
  normative and the v0 table is complete: `CREATE_OUTPUT`,
  `CREATE_OUTPUT_TAPROOT`, the eight signature asserts (decision
  23), the four time asserts, the five self asserts (decision
  20), the message family (`ASSURE`, `REQUIRE`,
  `ANNOUNCE`, `ASSERT_ANNOUNCEMENT`), `RESERVE_FEE` (decision
  21), and the seal pair (decision 24). All eight validation
  rules are normative, rule 5 landing last by design so costing
  priced the complete vocabulary in one pass (decision 25).
- **Reference coverage is uneven by design.** The ported entries
  (timelocks, messages, `RESERVE_FEE`, the AGG_SIG and `ASSERT_MY_*`
  shapes) have deployed Chia semantics to translate tests from. The
  novel surface, the taproot derivation and
  every validation rule, has no external reference and gets the
  ground-rule-4 treatment instead: invariants first, adversarial
  vectors, and the novel-layer register in condition-record.md.
- **The transaction-view boundary does the curation.** Every Chia
  condition absent from the v0 plan reads state beyond one
  transaction: birth records, ephemerality, block-scoped
  concurrency, block-scoped message pairing. BitLisp's validation
  layer is a pure function of the transaction view, so these did not
  have to be individually declined, the architecture excludes them.
  Widening the view is the structural decision any future port of
  them would have to make first.
- **Chia's vocabulary is larger, 35 assigned opcodes against
  BitLisp's 26.** The remaining gap is the four before-style
  asserts, the chain-state family above, and the announcement
  flavors BitLisp folds into two conditions (decision 16). The
  curation direction matches the VM layer: keep the deployed
  semantics where the model fits, shrink where Bitcoin's transaction
  model already provides the guarantee, and route everything
  uncertain through the priced reserved tier rather than a free
  ignored one.
