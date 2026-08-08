# Condition and validation record

The rationale, reference provenance, and decision record for the
condition layer (`spec/CONDITIONS.md`) and the validation layer
(`spec/VALIDATION.md`). The specs state behavior only. This record says
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
| C1 | CREATE_COIN target | 32-byte puzzle hash | full scriptPubKey bytes, 1 to 10,000 | A Bitcoin output carries any script, and exits to non-BitLisp outputs are ordinary. A hash would also block the validator from comparing against the transaction's actual outputs without a reveal. Ratified 2026-07-29. | `validation/create-output.json` |
| C2 | CREATE_COIN memos | optional third argument, wallet-discovery hints | declined, strict arity two | The discovery job does not exist under output-script scanning. Consensus-carried bytes with no consensus meaning are a deliberate non-affordance (design obligation 4, inscription counterargument recorded there). A memo-bearing variant stays reachable through the reserved tier. Ratified 2026-07-29. | `conditions/encoding.json` arity cases |
| C3 | duplicate CREATE_COIN within one spend | rejected (child coin ids would collide) | valid, two claims requiring two distinct slots | Chia's rejection exists because its content-derived coin ids make identical children the same coin. Bitcoin output identity is positional, so identical slots are meaningful and routine (batch payouts). Counting under rule 1 handles them. Ratified 2026-07-29. | `validation/create-output.json` duplicate cases |
| C4 | unknown condition opcodes | ignored and unenforced, zero cost for one-byte opcodes, a computed cost table for larger opcodes (verified in chia_rs `compute_unknown_condition_cost`, 2026-07-29) | three tiers: assigned, invalid, reserved 0x80 to 0xff with declared cost and a floor | Invalid-by-default matches the consensus mindset (reject the ambiguous case). The reserved tier is the deliberate forward-compatibility hatch, priced so old and new validators agree forever. Ratified 2026-07-29, four sub-decisions in section 3. | `conditions/encoding.json` tier cases |
| C5 | timelock enforcement | condition operands compared directly against chain state, previous transaction block height and timestamp, relative locks anchored at coin creation | conditions constrain the transaction's own locktime, sequence, and version fields, base consensus enforces them against the chain (BIP 65, 68, 112, 113 semantics inherited, relative locks anchored at prevout confirmation) | The validator holds no clock and stage 3 stays empty in v0. Reversibility decided it: a chain read stays addable through the reserved tier, the reverse migration cannot happen. Ratified 2026-08-07, decision 15. | `validation/time-asserts.json` |
| C6 | timelock operand range | arbitrary-size integer operands | typed domains inherited from the fields: heights below 500,000,000, times 500,000,000 to 2^32 - 1, relative values 16 bits with 512-second time units | The envelope is what base consensus enforces. Exceeding it would require chain reads, the declined shape. Out-of-domain operands are malformed at stage 1, so a mistyped operand fails loudly at parse. Ratified 2026-08-07, decision 15. | `conditions/time-asserts.json` domain cases |
| C7 | before-style timelocks | `ASSERT_BEFORE_*` family, expiring spend authorization | declined, structurally inexpressible in the field shape | Base consensus has no valid-only-before rule to delegate to. Expiring validity is the reorg hazard Bitcoin has deliberately avoided. Final decision 2026-08-07, decision 15, closing the decision 9 flag. | none, the opcodes stay invalid per `conditions/encoding.json` tier cases |
| C8 | message scope | messages balance across the validation unit, a whole block or spend bundle | messages balance within the single transaction | A Bitcoin transaction must be independently valid for relay and mempool admission, and the bundle model's recombination instability is the recorded public objection the layer avoids importing (evaluation doc section 11.4). Ratified 2026-08-07, decision 16. | `validation/messages.json` |
| C9 | message addressing fields | parent coin id, puzzle hash, amount, coin id, all content-derived | creating txid, spent scriptPubKey as raw bytes, amount, outpoint, with script and amount content-derived, txid and outpoint location-derived. Amount domains follow the fields: u64 there, 0 to MAX_MONEY here | The validator holds prevout data only. The creating txid is the creator handle it possesses, the txid half of the outpoint. Raw script bytes follow C1's rationale. The outpoint is Bitcoin's coin identity. Chia's coin-parent reading ("output of whichever transaction spent coin P") is unverifiable from prevout data and is a recorded decline. Ratified 2026-08-07, decision 16. | `validation/messages.json` mode cases |
| C10 | condition argument arity | consensus accepts trailing extra arguments, strict arity only under the mempool flag (STRICT_ARGS_COUNT) | strict arity everywhere | One validator, one behavior, reject the ambiguous case. Verified in chia_rs conditions.rs: check_nil runs only under the mempool flag. Already the landed behavior of every prior family, recorded as a divergence here because the message probes surfaced it. Ratified 2026-08-07, decision 16. | `conditions/messages.json` arity cases |
| C11 | broadcast conditions | four announcement codes, announcer bound by coin id or puzzle hash, namespacing by payload prefix convention | two conditions, announcer precision chosen by the assert through the shared specifier grammar, namespace a first-class operand | Decision 10's safety rationale upheld against the match-by-default policy: the prefix convention produced inadvertently insecure spends, CHIP-0025's own stated motivation. Chia's two flavors survive as commitment values 7 and 2. Ratified 2026-08-07, decision 16. | `validation/announcements.json` |
| C12 | per-spend coordination cap | 1,024 message and announcement conditions per spend, enforced by today's deployed binary, removed under the hard fork 2 pricing flag | no cap in v0 | Deployed Chia's cap is the pre-pricing spam bound and CHIP-0049 replaces it with per-condition pricing. Rule 5 is the pre-registered home for the same cap-or-price decision here, so v0 records the gap rather than adopting a bound upstream is removing. Recorded 2026-08-07 with decision 16, final decision owed by rule 5. | none until rule 5 lands |

## 2. Reference provenance

- **Chia condition semantics.** Established from the deployed
  behavior of the pinned oracle wheels where portable, and from
  translated Chia consensus tests for semantics that overlap. No
  binary diffing: the transaction models differ. For the timelock
  family the field enforcement shape (decision 15) superseded
  direct test translation: the overlap that survives the shape
  change is the comparison boundary, where chia_rs
  `check_time_locks.rs` fails only when the chain value is
  strictly below the operand, agreeing with OP_CLTV and OP_CSV
  that equality passes, and the family's boundary vectors pin
  exactly that. Translation stays the plan for the dedup
  semantics of rule 4.
- **CHIP-0025 (message conditions)** and **CHIP-0049 (Chia 3.0
  cost revisions)** are the recorded costing precedents for
  validation rule 5. CHIP-0049's per-condition base cost of 500 is
  the provisional value of RESERVED_COST_FLOOR in rule 6, to be
  revisited when rule 5 lands. Two decisions are pre-registered as
  deliberate rather than inherited: whether a per-spend free tier
  is acceptable, and which precedent prices tx-scoped
  SEND_MESSAGE and RECEIVE_MESSAGE. The precedent was re-verified
  2026-08-07 against chia_rs source during the rule 3 research
  pass: under the hard fork 2 COST_CONDITIONS flag both message
  conditions and all four announcement conditions charge a flat
  700 (MESSAGE_CONDITION_COST), and the 1,024-per-spend
  announcement cap is skipped in favor of that pricing. The
  earlier reading that CHIP-0049 leaves Chia's message conditions
  on the free tier was wrong and is corrected in the execution
  plan.
- **Message-condition semantics (verified 2026-08-07).** Pinned
  against the deployed binary by direct probes of chia_rs
  `get_conditions_from_spendbundle`: counted balance per record
  key, the mode inside the matching key, self-send legal, spend
  order irrelevant, payload 0 to 1024 bytes, empty payload legal,
  arity strict only under the mempool flag. Confirmed by a source
  read of `messages.rs` and `conditions.rs` under the reading
  guardrails: the balance check is a hash map of record key to
  sends minus receives with every bucket required to be zero, and
  each 3-bit mode half re-emits as a tag byte of the key, which is
  why the mode is part of the key. The probe corpus is translated
  into `vectors/validation/messages.json`.
- **BIP341 wallet test vectors** are vendored as data into
  `vectors/upstream/bip341/` with a provenance sibling, and are the
  primary tweak-derivation oracle for CREATE_OUTPUT_TAPROOT. The
  vendored Bitcoin Core test framework carries no named taproot
  constructor, but its generic tagged-hash and x-only tweak
  primitives compose into a second runnable oracle, and the test
  suite runs the derivation differentially against that composition
  alongside the official vector pins.
- **CHIP-0011 (the Chia 2.0 hard fork)** is the recorded precedent
  for signature binding granularity: its six partial-binding
  AGG_SIG variants (parent, puzzle, and amount combinations) were
  retrofitted for state-channel patterns, evidence that the
  AGG_SIG family needs a menu of binding granularities at day one
  rather than a single full binding.
- **Design-history evidence (2026-08-06).** A conversation with
  the deployed architecture's designer and a same-day study of the
  production puzzle corpus (CATs, singletons, offers), summarized
  in section 11 of the evaluation doc. Per project policy the
  correspondence itself stays out of the repo. This evidence base
  informs the decision 9 addendum and decisions 10 to 12 below.
- **Reserved-opcode pricing precedent (recorded 2026-08-07).** The
  conversation that produced decision 13's cold-reader evidence
  also flagged CLVM's reserved-opcode pricing as prior art worth a
  deliberate comparison. Verified by reading clvm_rs's unknown-op
  handler under the reading guardrails: an unknown CLVM opcode
  prices itself from its own bytes, a cost multiplier of up to four
  bytes and a two-bit cost function selecting the charging shape
  (constant, add-like, mul-like, or concat-like, each scaled by the
  multiplier plus one). The reserved space therefore carries many
  opcodes with distinct, argument-sensitive costs that a future
  fork can assign without a price change. Rule 6 prices the
  reserved condition tier differently: a per-instance declared
  constant cost with a floor. The owed triage folds into the rule 5
  costing design next to the RESERVED_COST_FLOOR revisit: decide
  whether rule 6 adopts anything from the CLVM shape, in particular
  whether constant-only declarations underprice future conditions
  whose validation work scales with argument size.
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

   Addendum (2026-07-31, decisions by Evan, landed with the
   CREATE_OUTPUT_TAPROOT PR). Key-path-only handling uses the
   empty-root sentinel: one opcode, `merkle_root` exactly 0 or 32
   bytes, the empty atom committing to no script tree. A separate
   key-only opcode and declining key-path-only entirely were both
   considered and declined. The sentinel is unambiguous because a
   real root is always exactly 32 bytes, and it keeps one BIP341
   concept in one vocabulary entry. Two of the entry's rejection
   branches, a tweak scalar at or above the group order and a
   tweaked point at infinity, are unreachable by any constructible
   vector because both require hash-preimage control, roughly a
   2^-128 event. They are pinned by contrived-scalar unit tests
   through the implementation's application-step seam. This is a
   recorded exception to "every error path is a vector," accepted so
   the corpus gap is deliberate rather than an oversight. The tweak
   oracle provenance is recorded in section 2.
4. **Rule 1 equality-only matching.** RATIFIED (decision by Evan,
   2026-07-29, as part of the rule 1 draft). Claims match slots by
   exact content equality only, which collapses injective matching
   to multiset containment (counting) and keeps graph algorithms
   out of consensus. The spec makes the restriction normative text
   so relaxing it requires amending visible prose plus a recorded
   decision here.
5. **Curation notes stay in the spec.** RATIFIED (decision by Evan,
   2026-07-29). The Phase 0 stub planned a curation note on every
   vocabulary entry, and the later spec-purity rule (spec states
   behavior only, rationale in docs) arguably forbade it. Resolved
   in favor of the notes: obligation 4 wants the curation visible
   where the vocabulary is, so entries keep a brief note and this
   record keeps the full rationale. CLAUDE.md ground rule 1 records
   the exception. Reversed 2026-08-08, decision 17.
6. **RESERVED_COST_FLOOR stays at 500.** RATIFIED (decision by Evan,
   2026-07-29). The CHIP-0049 per-condition base cost stands as the
   provisional floor, revisited when rule 5's costing design lands.
7. **CREATE_COIN renamed to CREATE_OUTPUT.** RATIFIED (decision by
   Evan, 2026-07-31). The condition claims a transaction output
   slot and names no coin type. With a second output-creation
   condition arriving, the old name read as a type pair and invited
   two false readings: that the conditions create different kinds
   of coin, and that a taproot output requires the taproot
   condition. Renamed together with a standing terminology policy:
   BitLisp is aimed at Bitcoin developers and always favors
   Bitcoin-native vocabulary, with cross-blockchain mappings in
   `docs/glossary.md`. Chia-name continuity is explicitly
   subordinate to that policy. Name-only change: opcode, arguments,
   semantics, and every vector payload are unchanged. Earlier
   entries in this record keep the name that was current when they
   were ratified. The policy's term decisions (Evan, 2026-07-31):
   coin stays, because Bitcoin Core's own class Coin names a UTXO
   entry, puzzle becomes program, and solution becomes witness
   arguments. CREATE_OUTPUT stands alongside coin deliberately: in
   Core's own vocabulary inputs spend coins while transactions
   create outputs, and the OUTPUT name encodes the positional
   output identity behind divergences C1 and C3.
8. **Invariant direction correction.** The Phase 0 stub stated that
   removing a condition never turns an invalid transaction valid.
   Under rule 1 that is false (removing one of two over-claims
   restores validity) and the true property is the reverse
   monotonicity: constraints only tighten, so removing a condition
   never invalidates a valid transaction. Corrected in the spec
   commit that made the invariants normative, 2026-07-29, flagged
   in that PR for review.
9. **Assert vocabulary covers the field grid by default.** RATIFIED
   (decision by Evan, 2026-08-06). The ASSERT_* family enumerates
   every applicable field of the transaction context rather than
   curating entries case by case. Coverage is the default and every
   omission is a recorded decline in this record, so the burden of
   proof sits on leaving a field out. Three grounds:
   - In this architecture the assert vocabulary is a program's only
     window onto the transaction. A missing introspection opcode in
     other designs is an inconvenience the contract author routes
     around. A missing assert here is an expressiveness hole that
     only a soft fork through the reserved tier can patch.
   - Chia curated its assert set and the gaps surfaced as a
     retrofit: CHIP-0014 added the ASSERT_BEFORE family, the birth
     asserts, ASSERT_EPHEMERAL, and the concurrent asserts years
     into deployment. Field coverage is cheap up front and
     expensive to recover.
   - Asserts are uniform read-only comparisons against data the
     validator already holds, so systematic coverage is more
     reviewable than a judgment-call subset. The spec states one
     rule for the whole grid instead of a rationale per entry, and
     the vector corpus enumerates the grid mechanically.
   The grid, to be enumerated exhaustively when the assert sections
   of `spec/CONDITIONS.md` land: transaction-level fields (version,
   locktime, input count, output count, fee), the spending input's
   own fields (outpoint, amount, spent scriptPubKey, sequence,
   input index, leaf commitment), sibling inputs' fields by index,
   outputs' fields by index (amount, scriptPubKey), and chain
   context (height and median time past, absolute and relative).
   Three cells are flagged for their own recorded decisions rather
   than defaulted in:
   - The before/expiry direction. An assert that a height or time
     has not yet passed makes validity expire, a valid-to-invalid
     transition Bitcoin has deliberately avoided for reorg safety,
     while Chia ships the ASSERT_BEFORE family and the
     expiring-offer pattern wants it. Include or decline is a real
     decision with a benchmark on one side and a mempool and reorg
     safety norm on the other. The lean, recorded 2026-08-06, is
     decline: Bitcoin has repeatedly rejected expiring spend
     authorization on reorg-safety grounds. The final decision and
     its full decline note land with the timelock family.
   - Witness-dependent quantities (transaction weight, fee rate).
     The witness contains the program making the claim, so these
     are self-referential and need either a stripped-measure
     definition or a decline.
   - The annex. Pre-execution visibility of declared claims
     composes naturally with the assert family, and its shape is an
     open thread from the email exchange recorded in the evaluation
     doc roadmap item 5.
   Obligation 4's curation stance is unchanged for affordances
   (output creation variants, memos, message conditions): coverage
   by default applies to read-only asserts over transaction fields,
   where the risk profile is uniform, not to conditions that create
   abilities.

   Addendum (2026-08-06). The design-history evidence generalized
   this decision into the schema-completeness principle now
   recorded in section 7 of the evaluation doc: the vocabulary is
   complete over Bitcoin's spend schema, never curated by predicted
   applications. Chia's iteration history is the evidence that
   use-case curation fails. Announcements had to be followed by
   the message conditions, the assert set grew by the CHIP-0014
   retrofit above, and userspace repurposed magic amount values as
   signals where the vocabulary had no word. Schema enumeration is
   tractable, application prediction is not.

10. **Coordination vocabulary carries addressed and unaddressed
    primitives.** RATIFIED (decision by Evan, 2026-08-06). Earlier
    Phase 2 notes treated the CHIP-0025 message pair as the
    announcements' successor and left the four announcement
    conditions unported. The design-history evidence overturned
    that premise: announcements are not deprecated in practice.
    They are the unaddressed broadcast primitive, and they are
    load-bearing for offers, where the asserting side cannot know
    the counterparty's coin ids at signing time. Messages are
    addressed exact pairing and cannot express that. The v0
    vocabulary therefore plans both: the addressed message pair
    and an unaddressed broadcast pair, each strictly
    transaction-scoped. Namespacing is first-class in the
    condition arguments. Chia's production puzzles separate their
    announcement kinds by reserving payload prefix bytes, a
    userspace convention consensus never sees, and that convention
    is not ported. Names, arguments, binding modes, and
    multiplicity land with the VALIDATION.md rule 3 design.
11. **The validator spec is organized as validation stages.**
    RATIFIED (decision by Evan, 2026-08-06). VALIDATION.md organizes
    validation into stages of strictly increasing context:
    1. Stateless per-spend work: the VM run and condition
       well-formedness, cacheable forever.
    2. Claims bound to the spent output's own data (outpoint,
       spent scriptPubKey, amount), cacheable per outpoint.
    3. Chain-context asserts: height and median time past, which
       define validity ranges the mempool re-evaluates cheaply.
    4. Cross-spend relational checks: message and broadcast
       pairing and injective output matching, the only stage that
       re-runs when spends are recombined into a different
       transaction.
    5. Batch signature verification over the collected
       (pk, message) pairs.
    Three grounds. It matches the deployed implementation's
    structure: chia_rs parses and checks conditions in stages of
    the same shape. It matches Bitcoin Core's own split between
    context-free and contextual validation. And it makes decision
    12 structural: a condition's stage assignment states exactly
    what context can invalidate it, so recombination-stability
    classification is stage assignment. VALIDATION.md's rule
    numbering is unchanged. The stages are the spec's organizing
    frame, and each rule states its stage.
    Amended 2026-08-07 (decision by Evan): the frame's noun is
    stage, formerly wave. Stage is the word Bitcoin Core and
    chia_rs reviewers already use for staged validation, wave was
    our coinage and read as parallelism jargon. The five-part
    structure is unchanged. Under decision 14's two-sort
    vocabulary, stage 2's entry reads as facts of the spent
    output's own data (prevout-bound checks are asserts, not
    claims), and the spec's stage list is the authoritative text.
12. **Every binding mode gets a recombination-stability class.**
    RATIFIED as a requirement (decision by Evan, 2026-08-06), with
    the classification itself owed by the identity and signature
    designs. Chia's coin id is content-derived from parent,
    program hash, and amount, so it is stable across whichever
    aggregate spend bundle carries the spend. A Bitcoin outpoint
    is (txid, vout), transaction-scoped and unknown before
    assembly. Conditions and signature messages therefore bind to
    prevout data (the outpoint, the spent scriptPubKey, the
    amount), and every binding mode offered is classified as
    recombination-stable, meaning its claims survive aggregation
    of the spend into a different transaction, or
    recombination-fragile, meaning they do not. The classification
    is the structural answer to the aggregation qualification in
    section 4.4 of the evaluation doc: aggregation survives
    exactly for spends whose bindings are stable, the analogue of
    Chia's fast-forward eligibility rules. Chia's converged
    vocabulary is a fixed point of their identity model, so this
    classification has no upstream reference and gets the
    ground-rule-4 novel-layer treatment, invariants and
    adversarial recombination vectors first.
13. **The layer is named condition validation.** RATIFIED (decision
    by Evan, 2026-08-07). The layer this record has called matching
    is renamed condition validation. `spec/MATCHING.md` becomes
    `spec/VALIDATION.md`, `vectors/matching/` becomes
    `vectors/validation/`, and prose across the repo follows. Three
    grounds. First, a conversation with an external protocol
    designer produced the record's first cold-reader evidence on
    naming: the old name misled the reader, because matching also
    names wallet-side program template recognition in the Chia
    ecosystem and order pairing on exchanges, and those senses came
    first. Second, only rule 1 computes a matching in the technical
    sense. Message scoping, dedup, costing, and reserved conditions
    match nothing, so the layer name had overfit its first rule.
    Third, decision 11 already organizes the layer into validation
    stages, and Bitcoin Core's transaction-context consensus checks
    live in validation.cpp, so validation is the Bitcoin-native
    noun the terminology policy favors. The word matching survives
    exactly where it is precise: rule 1 keeps its name, injective
    multiset output matching, the claim-to-slot assignment keeps
    the glossary's injective matching row, and technical uses
    (bipartite matching, opcode matching, matching the consensus
    oracle) are untouched.
14. **The layer principle: claims and asserts, with a composition
    guarantee.** RATIFIED (decisions by Evan, 2026-08-07, designed
    in the rule 2 chat session). Four parts:
    - Two sorts. A condition constrains the transaction only
      through claims, which consume a resource assigned
      injectively (the assigned resource is the claim's
      satisfier), and asserts, which are predicates over the
      transaction view and validation context, freely shared and
      checked as a conjunction. An earlier single-sort framing
      (satisfiers with exclusive and shared modes) was rejected
      by Evan because nothing is assigned when an assert is
      checked, and duplicate fact reads are the normal exhaust of
      composing programs that cannot see each other: batched vault
      withdrawals each asserting their own height, layered
      programs each defensively asserting their own amount.
    - Non-obligation. The implication runs one way, nothing
      unclaimed and unread is constrained. Rule 2 is this
      statement made normative. It defines no error, so five of
      its six vectors are acceptance vectors and the sixth pins
      the rule 1 boundary (plain inputs rescue nothing), including
      the surplus-capture shape: a spend whose claims total less than
      its amount leaves the difference to whoever assembles the
      transaction, accepted deliberately, with per-spend value
      protection expressible through own-amount asserts, claims,
      and a fee reserve once those entries land.
    - Composition guarantee. Two transactions valid under the
      layer, consuming disjoint outpoints, concatenate into a
      valid transaction whenever the concatenation satisfies the
      view's preconditions. Ratified in this form after a stronger
      candidate (no condition may be invalidated by any single
      addition to the transaction) failed against RESERVE_FEE: a
      fee floor is broken by grafting a bare output onto the
      transaction, which is fee theft, and defending against it is
      the condition's job. Fees are non-negative and sum under
      concatenation, so fee floors survive merges, and the
      deployed Chia vocabulary is merge-closed on inspection. The
      designer's public statement of the property is the merge
      form ("the only way two transactions can conflict with each
      other is if they both try to spend the same coin",
      bitcoin-dev, March 2022, evaluation doc section 11.4).
      Pre-registered consequence: the planned ASSERT_FEE_LE and
      exact-form ASSERT_OUTPUT_COUNT are merge-poison, an
      aggregate upper bound vetoes strangers' decisions about
      strangers' value, and both go to the CONDITIONS.md session
      as recorded declines unless a use case survives that
      analysis. Neither exists in Chia (the comparison table in
      `docs/condition-comparison.md` marks the Chia side absent
      for both). Whole-transaction exactness
      stays available outside the layer on the taproot key path
      with SIGHASH_ALL.
    - Enforcement is twofold: the spec sentence binding future
      vocabulary (relaxation is a recorded decision, the rule 1
      equality-only precedent), and a hypothesis merge invariant
      over the landed vocabulary. Every new condition family owes
      merge vectors when it lands.

15. **The time assert family: field enforcement, full coverage,
    plain operands.** RATIFIED (decisions by Evan, 2026-08-07,
    designed in the timelock chat session). Five parts:
    - Enforcement shape. Two candidates were steelmanned: direct
      chain reads (Chia's deployed shape, argued from directness,
      freedom from the locktime machinery's historical warts, no
      range ceiling, and uniformity with the assert grid) and
      constraining the transaction's own locktime, sequence, and
      version fields with base consensus enforcing them (the
      OP_CHECKLOCKTIMEVERIFY and OP_CHECKSEQUENCEVERIFY shape,
      argued from zero new chain-reading surface, inherited reorg
      and mempool semantics, and interoperability with every
      deployed wallet's locktime discipline). Ratified: the field
      shape. The deciding asymmetries: reversibility (a chain-read
      assert stays addable later through the reserved tier with
      evidence in hand, while a shipped chain read can never be
      removed) and burden of proof before hostile review (the
      validator holds no clock at all, so a timestamp objection
      indicts deployed Bitcoin, not this layer). Validation stage 3
      is deliberately empty in v0, and the VALIDATION.md
      transaction view now states unconditional purity.
    - ASSERT_BEFORE, final decision: declined, closing the cell
      flagged in decision 9. Under the field shape the decline is
      structural, not curated: base consensus has no valid-only-
      before rule to delegate to, so the shape cannot express
      expiring validity. The known cost is recorded honestly, the
      async offer benchmark loses Chia-style offer expiry and uses
      the standard alternative (the maker spends an input of the
      offer to revoke it). If evidence from Phase 4 or hostile
      review demands expiry, the pre-registered path is a reserved-
      tier condition designed against the reorg-safety objection,
      not a retrofit of this family.
    - The time-typed pair is kept. The height-only position
      (advocated publicly by Peter Todd: height is the chain's
      native clock, timestamps are miner-influenced within bounds)
      was weighed and declined for the vocabulary. Grounds: the
      schema-completeness principle binds (time-typed locktime and
      time-typed sequence locks are deployed spend-schema fields
      that scripts constrain today), declining removes no attack
      surface under the field shape since the validator reads no
      clock either way, and a calendar-deadline covenant has no
      workaround in a pure conditions VM while height estimates
      drift by months over decade horizons. The height-first
      stance is honored where it has teeth: tooling defaults and
      the language reference, recorded in the curation notes.
    - Plain-quantity operands. The condition code carries the
      type (four names, not two), the operand is a bare height,
      timestamp, block count, or 512-second unit count, and each
      operand domain excludes the wrong-typed range so a mistyped
      operand is malformed at stage 1 rather than unsatisfiable at
      stage 4. OP_CSV's encoded-operand precedent (the operand
      mirrors the field's bit layout) was declined: the bit
      layouts stay in the spec's shared definitions and the field
      decoder, never in arguments, vectors, or program text.
    - Stage home and the guarantee's first relaxation. The family
      is stage 4, corrected from a drafted stage 2 home for the
      sequence pair when drafting surfaced that BIP 68 enforces
      nothing below transaction version 2, so every assert in the
      family reads a transaction-level field (locktime or
      version). The composition guarantee was relaxed under its
      own amendment clause: concatenation carries the greater
      version and greater locktime, and the hypothesis requires
      same-typed locktime fields. The excluded pairs are exactly
      the ones Bitcoin's single nLockTime field already forbids
      every wallet from batching, so the relaxation imports a
      deployed constraint rather than inventing one.
      Pre-registered consequence: the version cell of decision 9's
      grid needs a composition-safe comparison form when it lands,
      an exact-version assert is merge-poison under the
      greater-version rule.
    - Correction from the pre-PR five-agent review (2026-08-07):
      the first spec draft gated the sequence asserts on a signed
      version reading. Deployed consensus compares the version
      unsigned. Core casts nVersion to uint32 in both the BIP 68
      sequence-lock calculation and the OP_CHECKSEQUENCEVERIFY
      gate, with a source comment warning that a signed comparison
      would exclude half the range, and current Core declares the
      field uint32 outright. The signed draft would have
      gratuitously rejected the top-bit wire versions consensus
      enforces. The transaction view, the model, and the entries
      now carry the field unsigned, and the corpus pins the top of
      the range. The draft's error direction was reject-valid, so
      no theft path ever existed.

16. **Rule 3, the message family, and the match-by-default
    policy.** RATIFIED (decisions by Evan, 2026-08-07, designed in
    the rule 3 chat session). Seven parts:
    - The match-by-default policy, stated here on its first
      application: BitLisp matches deployed Chialisp semantics
      unless divergence is strictly necessary, every divergence
      needs a necessity and a table row, and the default yields to
      two things only, a Bitcoin structural difference or a prior
      ratified decision. Names remain governed by the
      Bitcoin-native terminology decision: the policy is about
      semantics, not vocabulary. Precedence was exercised
      immediately in both directions: it overturned a drafted
      5-mode simplification of the addressing grammar (a
      divergence of taste, not necessity), and it yielded to
      decision 10's first-class namespacing (a ratified safety
      decision, part seven below).
    - The addressed pair is adopted whole: Chia's opcodes 66 and
      67 numerically intact at `0x42` and `0x43`, the full
      two-halves mode geometry with all 64 values valid, the
      single 6-bit mode operand, the counted-balance matching
      rule, self-send legality, order independence, and the
      1024-byte payload cap. Provenance in section 2: binary
      probes first, source read second, both agreeing.
    - Field re-addressing, the one strictly necessary divergence
      (C9). The parent gap is recorded honestly: Chia's parent is
      a coin, Bitcoin's creator is a transaction that may consume
      many coins, and the coin-parent reading is unverifiable from
      the prevout data the validator holds, so the creating txid
      is the substitution. The identity case maps Chia's
      content-derived coin id to the location-derived outpoint.
      The geometry survives because both relations are
      one-to-many: a parent coin has many children, a transaction
      has many outputs.
    - The message record is the layer's third condition sort,
      beside claims and asserts. Under counted balance both
      directions demand, so the message pair is the first
      vocabulary whose removal from a valid transaction can
      invalidate it. The constraints-only-tighten invariant is
      re-scoped to claim and assert conditions with the family as
      the recorded exemption: a lone message half invalidates, and
      announcements break the other direction, since removing a
      read announcement invalidates and adding one can validate.
      The composition guarantee is preserved arithmetically rather
      than by monotonicity: balanced ledgers sum to balanced
      ledgers, and announcement facts only accumulate under
      concatenation. This deliberate break of monotonicity matches
      deployed Chia, where an unreceived send likewise
      invalidates.
    - The binding-stability classification (decision 12's first
      landing) is normative in rule 3. Content fields, amount and
      scriptPubKey, are knowable before a coin confirms and
      survive reassembly of an unconfirmed creator. Location
      fields, txid and outpoint, are neither. The recorded public
      recombination objection (bitcoin-dev, March 2022, evaluation
      doc section 11.4) is thereby answered in the spec: the mode
      menu exists so a program written in advance can bind to
      content, and the classification tells authors which modes
      are safe to bake into long-lived programs.
    - The motivating frame in all artifacts is program-authorized
      coordination, the controller-and-vault split: value coins
      delegating spend policy to a shared stateful policy coin,
      approved per spend by an addressed message within one
      transaction. The bundle-aggregation frame (atomic swaps
      between strangers' spends) was rejected as a motivation
      because Bitcoin signatures cover whole transactions and
      permissionless aggregation does not exist here.
    - The broadcast pair keeps decision 10's first-class
      namespacing against the match-by-default policy (C11), and
      both pairs stay in the vocabulary on verified deployed
      evidence: Chia's offer settlement emits puzzle
      announcements, the singleton launcher emits a coin
      announcement, the post-CHIP-25 custody puzzles ship
      announcement and message wrappers side by side, and
      CHIP-0049 prices announcements rather than retiring them.
      The design argument is the audience-count asymmetry: a
      message is a handshake whose sender must know its reader
      count exactly, an announcement is posted once and read by
      any number of asserts, including zero. The two are disjoint
      jobs, and CHIP-0025's "no longer recommended" applies to
      using the loose tool for the tight job, not to the loose
      job itself.

17. **Spec purity: the curation notes leave the spec.** RATIFIED
    (decision by Evan, 2026-08-08, reversing decision 5). Raised
    while reviewing the message family PR: the spec is aimed at
    implementers and states behavior only, with no exception, so
    rationale and Chia references live in docs alone. Every
    curation note is removed from `spec/CONDITIONS.md` and
    CLAUDE.md ground rule 1 drops the recorded exception.
    Obligation 4's visibility want, the curation inspectable where
    the vocabulary is, is carried by `docs/condition-comparison.md`,
    whose tables map every Chia condition to its BitLisp
    disposition, and by this record. The notes' content was
    verified present in those two documents before removal, with
    two clarifications moved here rather than lost:
    - A program wanting no relative lock omits the sequence
      asserts. The operand domain deliberately cannot express
      OP_CSV's disabled no-op form, part of decision 15's
      plain-operand ratification.
    - Seconds-to-units conversion for ASSERT_SEQUENCE_TIME is
      tooling's job, the validator compares the field's own
      512-second units directly. This joins decision 15's
      tooling-defaults stance, and decision 15's phrase "recorded
      in the curation notes" now resolves to this record.

18. **Participant descriptor renamed participant specifier.**
    RATIFIED (decision by Evan, 2026-08-08). To a Bitcoin
    developer, descriptor unqualified means an output script
    descriptor, the BIP 380 family, and rule 3's concept is
    unrelated to it. The terminology policy exists for exactly
    that reader, so the collision fails it in the worst direction,
    a loaded Bitcoin term reused for a non-Bitcoin meaning.
    Binding was considered and declined as overloaded in the other
    direction: the project already uses it for binding modes and
    stability classes. Name-only change: commitment values,
    operands, the pinned JSON forms, and every vector payload are
    unchanged. Vector names and prose across the repo follow, and
    the glossary row moves with the name. Earlier entries in this
    record keep the term that was current when they were ratified,
    except the living divergence table (C11), which reads in
    current vocabulary.

## 4. Novel-layer register

The validation rules have no external reference: no deployed system
checks a condition list against a Bitcoin transaction. What stands in
for an oracle, per ground rule 4:

| rule | status | oracle substitute |
| --- | --- | --- |
| 1. Injective multiset output matching | normative | hypothesis invariant suite (injectivity, reorder invariance, monotonicity, metamorphic mutations) plus the adversarial corpus in `vectors/validation/`, opening with the duplicate-CREATE_COIN theft vector |
| 2. Mixed-transaction rule | normative | `vectors/validation/mixed-transaction.json`: five acceptance vectors (mixed, plain-only, unclaimed slots, merge, surplus capture) and one rule 1 boundary rejection, plus the addition-monotonicity, merge, and plain-only invariants. The time assert family checks under this rule's assert clause: `vectors/validation/time-asserts.json` with BIP 65 and BIP 68 field semantics as the double reference, plus the operand-monotonicity and boundary-flip invariants |
| 3. Message scoping | normative | `vectors/validation/messages.json` and `vectors/validation/announcements.json`: the probe corpus translated from the chia_rs oracle (balance, multiplicity, mode-key, self-send, order cases) plus adversarial wrong-address and forgery cases, and the balanced-pair, announcement-monotonicity, and byte-flip invariants |
| 4. Dedup and multiplicity | pending | same treatment, plus translated Chia dedup tests where semantics overlap |
| 5. Per-condition costing | pending | CHIP-0049 precedent comparison plus cost-conservation properties |
| 6. Reserved conditions | normative | encoding vectors in `vectors/conditions/`, every error path pinned |

Decision 12 adds a seventh entry to this register when the identity
and signature designs land: the recombination-stability
classification, whose adversarial surface is recombination of valid
spends into transactions their authors never assembled. No deployed
system exercises that surface at scale (the aggregation reality
check in section 11.2 of the evaluation doc), so it gets invariants
and adversarial recombination vectors rather than translated tests.
