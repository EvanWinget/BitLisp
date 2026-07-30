# Condition and matching record

The rationale, reference provenance, and decision record for the
condition layer (`spec/CONDITIONS.md`) and the matching layer
(`spec/MATCHING.md`). The specs state behavior only. This record says
why, and what the evidence was. It is the Phase 2 counterpart of the
VM record (`docs/vm-record.md`), with one structural difference: the
VM record's divergence rows are each diff-tested against a consensus
binary, while the rows here are established against Chia's deployed
condition semantics by translated consensus tests and source reading,
because the transaction models differ and no binary diff is possible.
Section 4 registers the rules that have no external reference at all.

## 1. Divergence from Chia conditions

| id | area | Chia (deployed) | BitLisp | rationale | vectors |
| --- | --- | --- | --- | --- | --- |
| C1 | CREATE_COIN target | 32-byte puzzle hash | full scriptPubKey bytes, 1 to 10,000 | A Bitcoin output carries any script, and exits to non-BitLisp outputs are ordinary. A hash would also block the validator from comparing against the transaction's actual outputs without a reveal. Ratified 2026-07-29. | `matching/create-coin.json` |
| C2 | CREATE_COIN memos | optional third argument, wallet-discovery hints | declined, strict arity two | The discovery job does not exist under output-script scanning. Consensus-carried bytes with no consensus meaning are a deliberate non-affordance (design obligation 4, inscription counterargument recorded there). A memo-bearing variant stays reachable through the reserved tier. Ratified 2026-07-29. | `conditions/encoding.json` arity cases |
| C3 | duplicate CREATE_COIN within one spend | rejected (child coin ids would collide) | valid, two claims requiring two distinct slots | Chia's rejection exists because its content-derived coin ids make identical children the same coin. Bitcoin output identity is positional, so identical slots are meaningful and routine (batch payouts). Counting under rule 1 handles them. Ratified 2026-07-29. | `matching/create-coin.json` duplicate cases |
| C4 | unknown condition opcodes | ignored and unenforced, zero cost for one-byte opcodes, a computed cost table for larger opcodes (verified in chia_rs `compute_unknown_condition_cost`, 2026-07-29) | three tiers: assigned, invalid, reserved 0x80 to 0xff with declared cost and a floor | Invalid-by-default matches the consensus mindset (reject the ambiguous case). The reserved tier is the deliberate forward-compatibility hatch, priced so old and new validators agree forever. Ratified 2026-07-29, four sub-decisions in section 3. | `conditions/encoding.json` tier cases |

## 2. Reference provenance

- **Chia condition semantics.** Established from the deployed
  behavior of the pinned oracle wheels where portable, and from
  translated Chia consensus tests for semantics that overlap
  (the cross-check subset lands with the timelock family). No
  binary diffing: the transaction models differ.
- **CHIP-0025 (message conditions)** and **CHIP-0049 (Chia 3.0
  cost revisions)** are the recorded costing precedents for
  matching rule 5. CHIP-0049's per-condition base cost of 500 is
  the provisional value of RESERVED_COST_FLOOR in rule 6, to be
  revisited when rule 5 lands. Two decisions are pre-registered as
  deliberate rather than inherited: whether a per-spend free tier
  is acceptable, and which precedent prices tx-scoped
  SEND_MESSAGE and RECV_MESSAGE (the CHIP-0049 precedent is split,
  see `docs/execution-plan.md` Phase 2 notes).
- **bllsh** (AJ Towns' introspection Lisp) was cloned into
  git-ignored `references/` on 2026-07-29 and read for the
  CREATE_COIN_TAPROOT evaluation, under the reading guardrails
  (no code copied, spec statements established by our own
  evidence, influence disclosed). Findings recorded in the D-CC2
  entry below. `tools/fetch-references.sh` clones it alongside the
  Chia repos.

## 3. Design decision record

1. **Condition-list encoding (decision zero).** RATIFIED (decisions
   by Evan, 2026-07-29). Five parts:
   - Chia-shaped lists: a proper list of conditions, each a proper
     list with a one-byte opcode atom first. No Chia opcode-value
     compatibility (the code space is laid out fresh, C4).
   - Strict arity and minimal integer encodings for assigned
     conditions, every deviation rejected. Strictness is the
     loosenable direction post-deployment.
   - Reserved tier with declared cost: the first argument is the
     cost, charged as declared by validators before and after any
     future assignment, which is what keeps them in consensus. The
     cost argument itself is strict. Everything after it is
     unconstrained forever, because the future assignment defines
     the shape and old validators must not reject what it needs.
     RESERVED_COST_FLOOR prevents free spam.
   - Code-space layout: 0x00 invalid, family blocks 0x01 to 0x5f
     with intra-block gaps invalid (typos near real opcodes fail
     loudly), 0x60 to 0x7f unallocated invalid, 0x80 to 0xff
     reserved. More than 128 future conditions means a new leaf
     version, accepted deliberately.
   - Policy stance: reserved conditions are consensus-valid and
     policy-discouraged until assigned, the upgradable-NOP
     precedent. The spec marks the policy note as non-consensus.
2. **CREATE_COIN shape.** RATIFIED (decisions by Evan, 2026-07-29).
   Script bytes not hash (C1), memos declined (C2), duplicates
   allowed as distinct claims (C3), empty script rejected as
   burn-or-bug material, amount 0 to MAX_MONEY with zero-amount
   outputs left to policy exactly as Bitcoin base rules leave them.
3. **CREATE_COIN_TAPROOT (D-CC2).** RATIFIED (decision by Evan,
   2026-07-29). Covenant recursion needs successor scriptPubKeys of
   the form taproot(internal key, tree root), and the BIP341 tweak
   is elliptic-curve arithmetic the VM deliberately lacks (the D2
   curation in `docs/vm-record.md`). Resolved as a condition:
   `CREATE_COIN_TAPROOT(internal_key, merkle_root, amount)`, strict
   arity three, the validator computes the tweak natively and the
   condition then matches as an ordinary rule 1 claim. Two
   alternatives declined:
   - `secp256k1_muladd` (bllsh's general linear-combination
     assert). Reading bllsh's examples on 2026-07-29 found three
     usage patterns: re-implementing BIP340 (covered by
     `secp_verify` and the AGG_SIG family), verifying the current
     input's own taproot construction (impossible as a VM operator
     in a pure VM, flagged as ASSERT_MY_TAPROOT for the ASSERT_MY_*
     design), and covenant recursion (test-flexmarks), which is
     exactly the computation the condition form performs. The
     honest residual: muladd also enables adaptor-signature-class
     and Pedersen-class equation verification. That capability is
     named here, not silently dropped, and the reserved tier is its
     priced future path.
   - A narrow `taptweak` VM operator. Strictly weaker than the
     condition form in this architecture: a pure VM has no
     transaction access, so the operator could only check
     solution-supplied claims, while costing a VM operator slot, a
     no-oracle divergence row, an extra witness element (the
     claimed key plus a parity bit that compute-mode never needs),
     and the first exception to "the VM's only curve door is
     signature verification."
   The condition enters the v0 vocabulary in its own PR immediately
   after the opening one. Its commit discloses the bllsh reading.
4. **Rule 1 equality-only matching.** RATIFIED (decision by Evan,
   2026-07-29, as part of the rule 1 draft). Claims match slots by
   exact content equality only, which collapses injective matching
   to multiset containment (counting) and keeps graph algorithms
   out of consensus. The spec makes the restriction normative text
   so relaxing it requires amending visible prose plus a recorded
   decision here.
5. **Invariant direction correction.** The Phase 0 stub stated that
   removing a condition never turns an invalid transaction valid.
   Under rule 1 that is false (removing one of two over-claims
   restores validity) and the true property is the reverse
   monotonicity: constraints only tighten, so removing a condition
   never invalidates a valid transaction. Corrected in the spec
   commit that made the invariants normative, 2026-07-29, flagged
   in that PR for review.

## 4. Novel-layer register

The matching rules have no external reference: no deployed system
checks a condition list against a Bitcoin transaction. What stands in
for an oracle, per ground rule 4:

| rule | status | oracle substitute |
| --- | --- | --- |
| 1. Injective multiset output matching | normative | hypothesis invariant suite (injectivity, reorder invariance, monotonicity, metamorphic mutations) plus the adversarial corpus in `vectors/matching/`, opening with the duplicate-CREATE_COIN theft vector |
| 2. Mixed-transaction rule | pending | same treatment on landing |
| 3. Message scoping | pending | same treatment on landing |
| 4. Dedup and multiplicity | pending | same treatment, plus translated Chia dedup tests where semantics overlap |
| 5. Per-condition costing | pending | CHIP-0049 precedent comparison plus cost-conservation properties |
| 6. Reserved conditions | normative | encoding vectors in `vectors/conditions/`, every error path pinned |
