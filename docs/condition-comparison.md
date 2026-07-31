# Condition and matching inventory: Chia, BitLisp

Informative, not normative. This document places Chia's deployed
condition vocabulary side by side with BitLisp's v0 vocabulary and
compares the two matching layers. It is the condition-layer companion
to [opcode-comparison.md](opcode-comparison.md). The BitLisp columns
restate [spec/CONDITIONS.md](../spec/CONDITIONS.md) and
[spec/MATCHING.md](../spec/MATCHING.md), which are the normative
sources. Divergence ids (C1 to C4) and decision ids (D-CC2) refer to
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
- **BitLisp**: spec/CONDITIONS.md and spec/MATCHING.md, Phase 2 in
  progress, plus the planned-entry list in CONDITIONS.md section 2
  and the Phase 2 plan in
  [execution-plan.md](execution-plan.md).

Opcode numbers are not comparable across columns. BitLisp lays its
code space out fresh (divergence C4) rather than inheriting Chia's
assignments. Chia opcodes are written in decimal, upstream's
convention, and BitLisp opcodes in hex, the CONDITIONS.md convention.

The BitLisp column uses four statuses. **Normative** entries are in
CONDITIONS.md today. **Planned** entries are named in the
CONDITIONS.md planned list and land across Phase 2. **Open** items
await a named design decision. **Not in the v0 plan** means no entry
and no recorded decision, which is not the same as declined: the
consensus outcome is that the opcode is invalid, and the reserved
tier is the future path.

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
| signature asserts | `AGG_SIG_ME` 50, `AGG_SIG_UNSAFE` 49, and six spend-binding variants 43 to 48 (parent, puzzle, amount combinations), BLS12-381 aggregated, message suffixed with the committed spend fields and a domain separator | planned, a secp AGG_SIG family with program-composed messages, membership and count open |

The signature scheme divergence is inherited from the VM layer:
BitLisp declined the BLS family and verifies BIP340 Schnorr over
secp256k1 (divergences D1 and D2 in `docs/vm-record.md`). Chia
composes each variant's message by appending fixed spend fields.
The BitLisp family's message-composition design is the open item.

## Time asserts

| Capability | Chia | BitLisp |
| --- | --- | --- |
| after, absolute height | `ASSERT_HEIGHT_ABSOLUTE` 83 | `ASSERT_HEIGHT_ABSOLUTE`, planned |
| after, relative height | `ASSERT_HEIGHT_RELATIVE` 82 | `ASSERT_HEIGHT_RELATIVE`, planned |
| after, absolute time | `ASSERT_SECONDS_ABSOLUTE` 81 | `ASSERT_SECONDS_ABSOLUTE`, planned |
| after, relative time | `ASSERT_SECONDS_RELATIVE` 80 | `ASSERT_SECONDS_RELATIVE`, planned |
| before variants | `ASSERT_BEFORE_*` 84 to 87, expiring spends | not in the v0 plan |

The four after-style asserts have double reference coverage: Chia's
deployed semantics and Bitcoin's own locktime and sequence rules,
which the transaction view in MATCHING.md names as the model. The
translated Chia consensus tests planned for the cross-check subset
(condition-record.md section 2) land with this family. The before
variants would make spend authorization expire, a capability Bitcoin
consensus has historically avoided because a reorg can retroactively
invalidate a confirmed spend. No decision on them is recorded.

## Self asserts

| Capability | Chia | BitLisp |
| --- | --- | --- |
| own identity | `ASSERT_MY_COIN_ID` 70 | open at the `ASSERT_MY_*` design |
| own parent | `ASSERT_MY_PARENT_ID` 71 | open at the `ASSERT_MY_*` design |
| own program | `ASSERT_MY_PUZZLEHASH` 72 | open at the `ASSERT_MY_*` design |
| own amount | `ASSERT_MY_AMOUNT` 73 | open at the `ASSERT_MY_*` design |
| own taproot components | absent | `ASSERT_MY_TAPROOT`, flagged as a candidate in D-CC2, open |
| own birth time or height | `ASSERT_MY_BIRTH_SECONDS` 74, `ASSERT_MY_BIRTH_HEIGHT` 75 | not in the v0 plan, reads chain state outside the transaction view |
| ephemerality | `ASSERT_EPHEMERAL` 76, the coin was created in the same block it is spent | not in the v0 plan, reads chain state outside the transaction view |

The `ASSERT_MY_*` family is named in the planned list but its
membership is an open design item, the natural entries differing
because BitLisp's spend identity is an outpoint and a scriptPubKey
rather than a parent, puzzle hash, and amount triple. The two birth
asserts and `ASSERT_EPHEMERAL` compare against coin records that
exist in Chia's coin-set model and have no counterpart in the
MATCHING.md transaction view, so porting any of them would first
require widening that view, a structural decision and not a
vocabulary entry. The ephemeral-coin gap specifically is already
recorded among the known honest costs in section 7 of the
evaluation doc: ephemeral-coin patterns do not port because there
is no intra-transaction chaining.

## Announcements, messages, concurrency

| Capability | Chia | BitLisp |
| --- | --- | --- |
| announcements | `CREATE_COIN_ANNOUNCEMENT` 60, `ASSERT_COIN_ANNOUNCEMENT` 61, `CREATE_PUZZLE_ANNOUNCEMENT` 62, `ASSERT_PUZZLE_ANNOUNCEMENT` 63 | not ported, the message conditions are their successors, per the CHIP-0025 precedent recorded in the Phase 2 plan |
| messages | `SEND_MESSAGE` 66, `RECEIVE_MESSAGE` 67 (CHIP-0025), mode flags select which sender and receiver fields the pairing commits to, paired within the surrounding block | `SEND_MESSAGE` and `RECV_MESSAGE`, planned, strictly transaction-scoped, binding modes and multiplicity owed by MATCHING.md rule 3 |
| concurrency asserts | `ASSERT_CONCURRENT_SPEND` 64, `ASSERT_CONCURRENT_PUZZLE` 65, another spend with the named coin id or puzzle hash occurs alongside this one | not in the v0 plan |

The scoping difference is the architectural one: Chia validates a
block's spends together, so its messages and concurrency asserts
reach any spend in the block. BitLisp matching is a pure function of
one transaction, so message pairing shrinks to the transaction
boundary and block-scoped concurrency has no place to attach.

## Fees and universal asserts

| Capability | Chia | BitLisp |
| --- | --- | --- |
| fee floor | `RESERVE_FEE` 52 | `RESERVE_FEE`, planned |
| output count | absent | `ASSERT_OUTPUT_COUNT`, planned, novel |
| fee ceiling | absent | `ASSERT_FEE_LE`, planned, novel |

The two universal asserts are BitLisp additions with no deployed
reference anywhere. They are named by design obligation 4 in the
evaluation doc (curated vocabulary, deliberately chosen universal
asserts over the whole transaction), and their full rationale lands
with their vocabulary entries. Like the matching rules, they get the
novel-layer treatment, invariants and adversarial vectors rather
than translated tests.

## No-op and forward compatibility

| Capability | Chia | BitLisp |
| --- | --- | --- |
| assigned no-op | `REMARK` 1, always true, arguments ignored | no entry. Consensus-carried bytes with no consensus meaning are a recorded non-affordance (the C2 rationale). No REMARK-specific decision is recorded. |
| priced future opcode | `SOFTFORK` 90, first argument declares the cost, scaled by 10,000, no other semantics until a softfork assigns them | reserved tier 0x80 to 0xff, first argument declares the cost, floor of 500, no other semantics until assigned (MATCHING.md rule 6) |
| unknown one-byte opcode | ignored, unenforced, zero cost | invalid (C4) |
| unknown multi-byte opcode | ignored, unenforced, cost computed from the opcode value | invalid, a condition opcode is exactly one byte (C4) |

The reserved tier is the C4 divergence's replacement for all three
Chia rows below the first: one priced hatch instead of a free
ignored tier plus a priced one, invalid by default everywhere else.

## Matching layers

Chia has no document corresponding to MATCHING.md because its
matching problem is thinner: `CREATE_COIN` constructs the child coin
authoritatively rather than claiming a pre-existing transaction
output, so nothing like rule 1's assignment problem arises. The
comparison below is therefore between architectures, not between two
specs of the same shape.

| Property | Chia | BitLisp |
| --- | --- | --- |
| validation scope | a block's spends plus chain state (coin records, prior block height and timestamp) | a single transaction view, contextual asserts compare against validation context in the manner of Bitcoin's locktime rules |
| output identity | content-derived coin id (parent, puzzle hash, amount) | positional slot (scriptPubKey, amount) |
| output creation | authoritative construction, collision rejected | injective claim on existing slots, equality-only, multiset counting (rule 1, normative) |
| coexistence | every coin is a puzzle, no foreign outputs exist | mixed transactions with plain-taproot inputs and unmatched outputs (rule 2, pending) |
| cross-spend interaction | block-scoped messages and concurrency asserts | transaction-scoped messages (rule 3, pending) |
| dedup and multiplicity | deployed semantics, the planned cross-check source for translated tests | rule 4, pending |
| costing | deployed per-condition costs (`CREATE_COIN` 1,800,000, `AGG_SIG` 1,200,000, message 700, generic 200), CHIP-0049 revisions in review | rule 5, pending, CHIP-0049 is the recorded precedent with two pre-registered deliberate decisions |
| unknown conditions | ignored tiers | invalid plus the priced reserved tier (rule 6, normative) |

## Observations

- **Where Phase 2 stands.** Two vocabulary entries are normative,
  `CREATE_OUTPUT` and `CREATE_OUTPUT_TAPROOT`. Nine planned entries
  are named: the four after-style time asserts, `SEND_MESSAGE`,
  `RECV_MESSAGE`, `RESERVE_FEE`, `ASSERT_OUTPUT_COUNT`, and
  `ASSERT_FEE_LE`. Two families are planned with membership open,
  the secp AGG_SIG family and `ASSERT_MY_*`. Of the six matching
  rules, 1 and 6 are normative and 2 to 5 are pending.
- **Reference coverage is uneven by design.** The ported entries
  (timelocks, messages, `RESERVE_FEE`, the AGG_SIG and `ASSERT_MY_*`
  shapes) have deployed Chia semantics to translate tests from. The
  novel surface, both universal asserts, the taproot derivation, and
  every matching rule, has no external reference and gets the
  ground-rule-4 treatment instead: invariants first, adversarial
  vectors, and the novel-layer register in condition-record.md.
- **The transaction-view boundary does the curation.** Every Chia
  condition absent from the v0 plan reads state beyond one
  transaction: birth records, ephemerality, block-scoped
  concurrency, block-scoped message pairing. BitLisp's matching
  layer is a pure function of the transaction view, so these did not
  have to be individually declined, the architecture excludes them.
  Widening the view is the structural decision any future port of
  them would have to make first.
- **Chia's vocabulary is larger, 35 assigned opcodes against a v0
  plan in the teens.** The gap is mostly the six spend-binding
  AGG_SIG variants, the four superseded announcements, the four
  before-style asserts, and the chain-state family above. The
  curation direction matches the VM layer: keep the deployed
  semantics where the model fits, shrink where Bitcoin's transaction
  model already provides the guarantee, and route everything
  uncertain through the priced reserved tier rather than a free
  ignored one.
