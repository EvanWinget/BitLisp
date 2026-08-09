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
| C4 | unknown condition opcodes | ignored and unenforced, one-byte opcodes free before the hard fork 2 pricing flag and a flat 200 under it, a computed low-byte cost table for larger opcodes (verified in chia_rs `compute_unknown_condition_cost` 2026-07-29, pricing regimes re-verified at 0.46.0 during the rule 4 pass, 2026-08-08) | three tiers: assigned, invalid, reserved 0x80 to 0xff with declared cost and a floor | Invalid-by-default matches the consensus mindset (reject the ambiguous case). The reserved tier is the deliberate forward-compatibility hatch, priced so old and new validators agree forever. Ratified 2026-07-29, four sub-decisions in section 3. | `conditions/encoding.json` tier cases |
| C5 | timelock enforcement | condition operands compared directly against chain state, previous transaction block height and timestamp, relative locks anchored at coin creation | conditions constrain the transaction's own locktime, sequence, and version fields, base consensus enforces them against the chain (BIP 65, 68, 112, 113 semantics inherited, relative locks anchored at prevout confirmation) | The validator holds no clock and stage 3 stays empty in v0. Reversibility decided it: a chain read stays addable through the reserved tier, the reverse migration cannot happen. Ratified 2026-08-07, decision 15. | `validation/time-asserts.json` |
| C6 | timelock operand range | arbitrary-size integer operands | typed domains inherited from the fields: heights below 500,000,000, times 500,000,000 to 2^32 - 1, relative values 16 bits with 512-second time units | The envelope is what base consensus enforces. Exceeding it would require chain reads, the declined shape. Out-of-domain operands are malformed at stage 1, so a mistyped operand fails loudly at parse. Ratified 2026-08-07, decision 15. | `conditions/time-asserts.json` domain cases |
| C7 | before-style timelocks | `ASSERT_BEFORE_*` family, expiring spend authorization | declined, structurally inexpressible in the field shape | Base consensus has no valid-only-before rule to delegate to. Expiring validity is the reorg hazard Bitcoin has deliberately avoided. Final decision 2026-08-07, decision 15, closing the decision 9 flag. | none, the opcodes stay invalid per `conditions/encoding.json` tier cases |
| C8 | message scope | messages balance across the validation unit, a whole block or spend bundle | messages balance within the single transaction | A Bitcoin transaction must be independently valid for relay and mempool admission, and the bundle model's recombination instability is the recorded public objection the layer avoids importing (evaluation doc section 11.4). Ratified 2026-08-07, decision 16. | `validation/messages.json` |
| C9 | message addressing fields | parent coin id, puzzle hash, amount, coin id, all content-derived | creating txid, spent scriptPubKey as raw bytes, amount, outpoint, with script and amount content-derived, txid and outpoint location-derived. Amount domains follow the fields: u64 there, 0 to MAX_MONEY here | The validator holds prevout data only. The creating txid is the creator handle it possesses, the txid half of the outpoint. Raw script bytes follow C1's rationale. The outpoint is Bitcoin's coin identity. Chia's coin-parent reading ("output of whichever transaction spent coin P") is unverifiable from prevout data and is a recorded decline. Ratified 2026-08-07, decision 16. | `validation/messages.json` mode cases |
| C10 | condition argument arity | consensus accepts trailing extra arguments, strict arity only under the mempool flag (STRICT_ARGS_COUNT) | strict arity everywhere | One validator, one behavior, reject the ambiguous case. Verified in chia_rs conditions.rs: check_nil runs only under the mempool flag. Already the landed behavior of every prior family, recorded as a divergence here because the message probes surfaced it. Ratified 2026-08-07, decision 16. | `conditions/messages.json` arity cases |
| C11 | broadcast conditions | four announcement codes, announcer bound by coin id or puzzle hash, namespacing by payload prefix convention | two conditions, announcer precision chosen by the assert through the shared specifier grammar, namespace a first-class operand | Decision 10's safety rationale upheld against the match-by-default policy: the prefix convention produced inadvertently insecure spends, CHIP-0025's own stated motivation. Chia's two flavors survive as commitment values 7 and 2. Ratified 2026-08-07, decision 16. | `validation/announcements.json` |
| C12 | per-spend coordination cap | 1,024 message, announcement, and concurrent-assert conditions per spend, enforced by today's deployed binary, removed under the hard fork 2 pricing flag | no cap in v0 | Deployed Chia's cap is the pre-pricing spam bound and CHIP-0049 replaces it with per-condition pricing. Rule 5 is the pre-registered home for the same cap-or-price decision here, so v0 records the gap rather than adopting a bound upstream is removing. Recorded 2026-08-07 with decision 16, final decision owed by rule 5. | none until rule 5 lands |
| C13 | birth asserts | ASSERT_MY_BIRTH_HEIGHT and ASSERT_MY_BIRTH_SECONDS, two-phase: differing occurrences must-equal at parse, then exact equality against the coin record's confirmation height and timestamp at the node layer | declined | Checking them reads when the prevout confirmed, the chain read the decision 15 shape excludes, and no base-consensus field enforces exact birth (BIP 68 enforces minimum age, the monotone form the sequence asserts already carry). Usage research 2026-08-08: added by CHIP-0014 with no standalone stated motivation, and a GitHub-wide search found only definitional hits, no deployed first-party puzzle emits them. Their one systemic role in Chia, anchoring the relative-before windows, is played at base consensus by BIP 68 here. A chain-read assert stays addable through the reserved tier, the reverse migration cannot happen. Ratified 2026-08-08, decision 20. | `conditions/self-asserts.json` gap cases pin 0x34 and 0x35 invalid |
| C14 | ephemeral assert | ASSERT_EPHEMERAL, the coin was created in the same block it is spent in, plus a companion rule forbidding relative timelocks and birth asserts on ephemeral spends | declined, structurally inexpressible | A Bitcoin transaction cannot spend its own outputs (an input would need the txid of a transaction whose txid depends on that input), and validation scope is one transaction, so the asserted fact is always false. The companion interlock is also moot: BIP 68 anchors relative locks at prevout confirmation at base consensus. Reintroduction trigger recorded: package-level validation, if it ever exists, makes the fact expressible again through the reserved tier. Ratified 2026-08-08, decision 20. | `conditions/self-asserts.json` gap cases pin 0x36 invalid |
| C15 | RESERVE_FEE operand domain | any canonical uint below 2^64, an operand exceeding the achievable fee is well-formed and fails the fee comparison | 0 to MAX_MONEY, larger operands rejected at parse | The landed amount-operand convention (CREATE_OUTPUT, ASSERT_MY_AMOUNT). An operand above MAX_MONEY exceeds every possible fee, so the only observable difference is the error surface: `bad_condition_arg` at stage 1 instead of `insufficient_fee` at stage 4. Chia's checked-sum overflow error is likewise subsumed: with exact arithmetic the oversized sum simply fails the comparison. The hardened implementation must reproduce this with a wide or checked accumulator: a wrapping 64-bit sum would turn an unreachable demand satisfiable, the accept-invalid direction. Ratified 2026-08-09, decision 21. | `conditions/reserve-fee.json` domain cases |
| C16 | signature carrier | eight AGG_SIG conditions carry (pubkey, message), one aggregated BLS12-381 signature at the spend-bundle level satisfies every pair through a single aggregate verification | each condition carries its own 64-byte BIP340 signature as a third operand and verifies as a self-contained triple | secp256k1 has no deployed aggregation, so per-pair signatures are forced and only their location was open. The taproot annex was considered and declined: a contested namespace BitLisp does not own, annex-bearing transactions are non-standard under today's relay policy, and our leaf version already owns its witness (reintroduction trigger: a ratified upstream annex format plus relay). An external per-input signature list was declined for its positional pairing convention, a silent-failure surface the triple avoids. Ratified 2026-08-09, decision 23. | `validation/signature-asserts.json` |
| C17 | signature digest construction | final message = program message ++ binding data ++ 32-byte suffix, ME's suffix the genesis challenge verbatim, the six variant suffixes derived sha256(genesis challenge ++ opcode byte), UNSAFE suffixless, variable-length concatenation | digest = BIP340 tagged hash, one ASCII tag per variant, fixed-length binding fields before the message | Byte compatibility is already impossible under the curve substitution, so only semantic parity binds, and what each variant commits to is preserved. Chia's concatenation is non-injective, probe-found during the research pass: an AGG_SIG_AMOUNT signature for amount 128 also verifies for a zero-amount coin with the amount encoding absorbed into the message, because amount 0 encodes as zero bytes. Fixed-length fields under per-variant tags make the ambiguity class inexpressible, in the deployed Bitcoin idiom. Ratified 2026-08-09, decision 23. | `validation/signature-asserts.json` binding cases |
| C18 | raw-mode replay firewall | AGG_SIG_UNSAFE messages of 32 or more bytes may not end with any of the seven domain suffixes, a consensus rule in every regime | no firewall | The firewall patches the seam of suffix-at-the-end domain separation: a raw message could otherwise imitate a suffixed one. Under per-variant tagged hashes the raw digest and every bound digest live in disjoint domains by construction, so the rule has nothing to guard. A consensus rule deleted rather than ported. Ratified 2026-08-09, decision 23. | `validation/signature-asserts.json` raw cases |
| C19 | duplicate signature conditions | counted: every occurrence is charged and pushed, and the aggregate signature must include a duplicated (pk, msg) pair exactly as many times as it occurs (probe P9: aggregated once fails, aggregated twice passes) | idempotent facts under rule 4's assert classification: identical triples in one input hold or fail together | Chia's counted semantics is BLS aggregate arithmetic, not design intent: the pairing equation happens to demand each pushed pair. A self-contained triple verifies or it does not, and occurrence count carries no meaning, which is rule 4's assert commitment. Cost stays per occurrence under rule 5's accounting, matching Chia's parse-time charging. Ratified 2026-08-09, decision 23. | `validation/duplicates.json` signature cases |

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
  validation rule 5. The per-condition base cost of 500 in
  CHIP-0049's review draft supplied the provisional value of
  RESERVED_COST_FLOOR in rule 6, to be revisited when rule 5
  lands (the deployed code differs, per the second correction
  below). Two decisions are pre-registered as deliberate rather
  than inherited: whether a per-spend free tier is acceptable,
  and which precedent prices tx-scoped SEND_MESSAGE and
  RECEIVE_MESSAGE. The precedent was re-verified
  2026-08-07 against chia_rs source during the rule 3 research
  pass: under the hard fork 2 COST_CONDITIONS flag both message
  conditions and all four announcement conditions charge a flat
  700 (MESSAGE_CONDITION_COST), and the 1,024-per-spend
  announcement cap is skipped in favor of that pricing. The
  earlier reading that CHIP-0049 leaves Chia's message conditions
  on the free tier was wrong and is corrected in the execution
  plan. A second correction landed 2026-08-08 from the rule 4
  research pass: the deployed 0.46.0 wheel has no per-spend free
  tier and no 500 base cost. Under COST_CONDITIONS it charges a
  flat 200 (GENERIC_CONDITION_COST) per condition from the first
  one, including one-byte unknown opcodes, plus 450,000
  (SPEND_COST) per spend and 1,350,000 (NEW_CREATE_COIN_COST) per
  CREATE_COIN, verified by probe (150 generic asserts cost
  exactly 150 x 200 post-fork and 0 pre-fork). The tiers do not
  stack: the coordination family's 700 and the AGG_SIG and
  CREATE_COIN costs replace the generic 200 for those opcodes. The first-100
  carve-out and the 500 base in the earlier note describe a
  CHIP-0049 review draft, not deployed code. RESERVED_COST_FLOOR
  keeps its provisional 500 and its rule 5 revisit, which now
  weighs this corrected baseline. The pre-fork 1,024 countdown
  turned out to cover the concurrent asserts and the message
  conditions as well as the announcements, and is skipped
  entirely under the fork flag.
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
- **Duplicate-condition semantics (verified 2026-08-08).** Pinned
  against the deployed binary for validation rule 4 by 18 probes
  of chia_rs `get_conditions_from_spendbundle`, all confirming a
  source read of `conditions.rs` at the pinned wheel's own 0.46.0
  tag. Cost is charged per occurrence at parse time before any
  collapse, in every regime. Duplicate CREATE_COIN errors
  (DuplicateOutput) with the hint excluded from coin identity.
  RESERVE_FEE occurrences accumulate by checked sum. After-style
  time asserts collapse to the max and before-style to the min,
  with a cross-family contradiction erroring, so the collapse is
  observationally equivalent to checking each occurrence. The
  my-asserts check immediately against spend data, duplicates
  idempotent. Birth asserts are must-equal between occurrences:
  two differing values error at parse with no chain fact
  consulted, the single-valued-fact pattern decision 19 records.
  Announcements, their asserts, the concurrent asserts, and
  ASSERT_EPHEMERAL are set-semantics idempotent facts. AGG_SIG
  duplicates are counted: each occurrence charges 1,200,000 and
  emits its (pk, message) pair, and aggregate verification over a
  duplicated pair fails with the signature aggregated once and
  passes aggregated twice. Multi-byte unknown opcodes parse as
  softfork conditions and self-price through a 256-entry table
  indexed by the opcode's low byte, 100 times 17/16 to the index.
  That is a distinct mechanism from the clvm_rs operator-level
  multiplier-and-two-bit shape in the reserved-opcode precedent
  entry below: the condition table has no multiplier, no argument
  sensitivity, and no shape selector, so rule 5 weighs the two as
  separate precedents.
- **Self-assert semantics (verified 2026-08-08).** Pinned against
  the deployed binary for the ASSERT_MY_* design by 25 probes of
  chia_rs `run_block_generator2` under the COST_CONDITIONS flag,
  all confirming a source read of `conditions.rs`,
  `condition_sanitizers.rs`, and `check_time_locks.rs` at the
  pinned wheel's 0.46.0 tag. The four spend-data asserts check
  immediately at parse by exact equality against the spend's own
  data, hash operands are exactly 32 bytes, amount and birth
  operands are canonical unsigned ints that error on negatives
  and overflow rather than collapsing to unsatisfiable. Birth
  asserts are two-phase, must-equal at parse and exact equality
  against the coin record at the node layer, and they share the
  not-ephemeral interlock with the relative timelocks.
  ASSERT_EPHEMERAL takes no arguments and requires a same-block
  creator spend matching by puzzle hash and amount with the hint
  ignored. The whole family prices at the generic 200 under the
  fork flag and 0 before it, isolated by probe from generator
  byte cost. The declined conditions' usage research (CHIP-0014
  text, GitHub-wide code search) is recorded at C13 and C14.
- **Fee-reserve semantics (verified 2026-08-09).** Pinned against
  the deployed binary for the fee family design by 16 probes of
  chia_rs `get_conditions_from_spendbundle` under the
  COST_CONDITIONS flag, all confirming a source read of
  `conditions.rs` at the pinned wheel's 0.46.0 tag. RESERVE_FEE
  accumulates by checked sum within a spend and across spends,
  the fee (removals minus additions) must be at least the total
  with boundary equality passing, and the comparison runs inside
  the consensus layer's own `validate_conditions`, not in the
  caller. The operand is a canonical uint below 2^64, zero
  legal, with negative, non-canonical, and above-64-bit operands
  all mapped to the one family error (a 9-byte encoding with a
  protective leading zero is canonical there, per sanitize_uint's
  size allowance), and checked-sum overflow mapped to the same
  code. Cost is the generic 200 under the fork flag and 0 before
  it, a rule 5 input. Trailing extra arguments are rejected at
  this always-mempool-strict entry point, with consensus
  leniency established by the source read alone, the C10
  divergence area.
- **Signature-condition semantics (verified 2026-08-09).** Pinned
  against the deployed binary for the signature assert design by
  probes of chia_rs `get_conditions_from_spendbundle` and
  `validate_clvm_and_signature`, the entry point that runs the
  real aggregate verification, all confirming a source read of
  `conditions.rs`, `make_aggsig_final_message.rs`, and
  `spendbundle_validation.rs` at the pinned wheel's 0.46.0 tag.
  The per-variant final message construction was confirmed end to
  end for all eight opcodes: the predicted message was signed and
  the aggregate accepted it, and a wrong-construction signature
  failed. Final message = program message ++ binding data ++
  32-byte suffix, ME's suffix the genesis challenge verbatim and
  each variant's derived sha256(challenge ++ opcode byte),
  verified against all six mainnet constants. Amount binding uses
  the canonical minimal int encoding, empty for zero, verified at
  0, 127, 128, and 2^63, which is the C17 injectivity wart.
  Pubkey operand exactly 48 bytes then point-validated with
  infinity rejected, message capped at 1024 by the announcement
  sanitizer, the UNSAFE tail firewall enforced in every regime
  with exact-tail matching only. Duplicate pairs counted at the
  signature layer (aggregated once fails, twice passes),
  reconfirming the rule 4 pass's P9 probe at the verifying entry
  point. AGG_SIG_COST is 1,200,000 per occurrence charged
  unconditionally in both regimes, the per-condition delta
  isolated by probe pre-fork and post-fork, so CHIP-0049 left
  AGG_SIG pricing untouched, a rule 5 input. Mempool prior art:
  any signature condition kills dedup eligibility, and the ME and
  parent-binding variants kill fast-forward eligibility.
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
      and a fee reserve once those entries land. Corrected
      2026-08-09 during the fee family's adversarial review: the
      fee reserve does not belong on that list. Its floor is a
      transaction-global demand satisfiable from any input's
      value, so an aggregator who adds their own input can
      capture a spend's surplus while meeting the reserve from
      the added value, the surplus_capture_with_attacker_input
      vector. Per-spend value protection is the other two items
      alone: assert your amount and claim all of it, leaving no
      surplus to capture. The reserve buys fee assurance, not
      value protection.
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

19. **Validation rule 4: sort-bound multiplicity, no collapse.**
    RATIFIED (decisions by Evan, 2026-08-08). The validator never
    merges, deduplicates, or collapses conditions, and what a
    duplicate means binds to the condition sorts: claims and
    message records are counted by their own rules, asserts are
    idempotent within their carrying input, and a condition
    producing none of the three constrains nothing. Cost
    accounting is per occurrence and identity-independent,
    matching deployed chia_rs exactly, which charges as parsed
    before any collapse in every regime. Six sub-decisions:
    - Idempotence is scoped to the carrying input, a five-agent
      review catch folded in before the PR opened. An assert's
      fact may read the carrying input's own fields (every time
      assert reads its input's sequence), so byte-identical
      asserts on different inputs can diverge, and an ANNOUNCE
      copied to a different input creates a new fact under rule
      3's fact identity. The first draft claimed transaction-wide
      idempotence, which would have licensed a transaction-wide
      dedup optimization that splits consensus. The spec now
      states the within-input scope, the invariant is scoped to
      in-place duplication, and the divergence vectors pin both
      cross-input counterexamples.
    - The sort binding replaced a universal asserts-are-idempotent
      sentence after checking it against the full planned
      vocabulary per the lesson recorded with decision 14 (check
      every normative sentence against the full planned
      vocabulary, not just landed entries): AGG_SIG duplicates are
      counted in the deployed precedent (each occurrence demands
      the signature in the aggregate, probe-verified), and
      RESERVE_FEE occurrences sum. Both therefore land in counted
      sorts when their units design them, with the sort assignment
      made there. The spec reader keeps the invariant that an
      assert's duplicates never carry meaning.
    - No divergence row: Chia's strictest-wins collapse of its
      time asserts is observationally equivalent to checking each
      occurrence, because after-style asserts compose by max, and
      Chia charges per occurrence pre-collapse. Nothing observable
      differs for the landed vocabulary. Claims already diverge
      per C3.
    - The single-valued-fact pattern stays out of the spec. Chia
      rejects two differing birth asserts at parse because birth
      facts are unavailable there, so must-equal is a
      satisfiability shortcut. Every fact a v0 assert reads is in
      the validator's hands, stage 3 is empty, so contradictory
      equality asserts need no pairwise rule: each is checked and
      one is false. Revisit trigger: any future assert reading a
      fact the validator cannot see.
    - The cost sentence says identity-independence and nothing
      stronger. A draft "no duplicate prices below a first
      occurrence" was cut because a count-based tier, still open
      for rule 5, could legitimately price a late duplicate
      differently, and a draft whitelist of permitted price
      inputs was cut in review because it accidentally excluded
      per-opcode counts, the natural form of rule 5's announced
      superlinear CREATE_OUTPUT pricing. Identity-independence
      alone is the anti-spam property, and the spec states it as
      the sole pricing constraint.
    - Chia's mempool spend-dedup machinery (ELIGIBLE_FOR_DEDUP,
      and the fast-forward eligibility beside it) is a recorded
      decline. It merges identical spends across competing
      bundles, and Bitcoin's mempool unit is the transaction:
      two transactions spending one outpoint conflict rather than
      merge, so the mechanism has nothing to attach to. The
      fast-forward half's territory, respending under a changed
      parent, is owned by decision 12's stability classes.
    Like rule 2 the rule performs no computation, defines no
    error, and carries no stage assignment. Implementation delta
    nil: the implementation already checks every occurrence, and
    the vectors and the new invariant prove it.
20. **The self assert family.** RATIFIED (decisions by Evan,
    2026-08-08). Five conditions asserting equality against the
    spending input's own prevout data, opcodes 0x30 to 0x33 and
    0x37, the first occupants of validation stage 2, enforcing
    through rule 2's assert clause with no VALIDATION.md change.
    Design session held in chat after an oracle research pass
    (probe provenance in section 2). Sub-decisions:
    - Separate opcodes, not a specifier-mode encoding. A
      mode-based draft reusing rule 3's commitment grammar was
      considered and dropped: for asserts every field combination
      decomposes into separate single-field conditions, so
      combination modes would be redundant re-encodings of the
      same fact, where the message family's mode halves are
      irreducible parts of the matching key. Deployed Chia draws
      the same line, separate ASSERT_MY_* opcodes beside
      CHIP-0025's mode-based messages, so the readable choice is
      also the match-Chialisp one. Splitting the message pair
      into per-combination opcodes for uniformity was considered
      and declined, preserving the key semantics would take 128
      opcodes, 64 sender-receiver combinations per direction.
    - Offset numbering, 0x30 plus k for Chia's 70 plus k.
      Identity continuity is impossible: Chia's 70 to 73 are hex
      0x46 to 0x49, inside the message family's block. 0x34 to
      0x36 stay invalid as the visible gap for the three declined
      conditions, in Chia's own order, and ASSERT_MY_TAPROOT
      takes 0x37, Chia's unused 77.
    - Field substitutions inherited from decision 16: coin id to
      outpoint, parent id to creating txid, puzzle hash to spent
      scriptPubKey, amount unchanged. ASSERT_MY_TXID asserts a
      strict subset of ASSERT_MY_OUTPOINT, deliberately: in Chia
      the parent id is not recoverable from the hashed coin id,
      here the txid is a visible prefix of the outpoint, and the
      pair is kept for schema completeness with the redundancy
      recorded rather than discovered. The spec entry states the
      subset relation so no reader mistakes it for a distinct
      fact.
    - Birth asserts declined, the C13 row records the research
      and the BIP 68 substitute. The single-valued-fact pattern
      they carry in Chia stays out per decision 19: every fact a
      v0 assert reads is in the validator's hands.
    - ASSERT_EPHEMERAL declined as structurally inexpressible,
      the C14 row records the reasoning and the package-level
      reintroduction trigger.
    - ASSERT_MY_TAPROOT adopted, closing the Phase 2 flag
      (self-construction verification cannot be a VM op in a pure
      VM). The assert-side mirror of CREATE_OUTPUT_TAPROOT's
      derivation (D-CC2), compared against the spent scriptPubKey
      instead of claiming an output slot. It is the covenant
      primitive for self-propagation: a program pins the internal
      key, takes the merkle root from its witness arguments,
      proves its own construction with the assert, and recreates
      itself with CREATE_OUTPUT_TAPROOT from the same operands.
      Without it the raw scriptPubKey assert hands the program 34
      opaque bytes and a lying witness breaks the covenant chain
      at the first hop.
    - The quantum consideration, raised by Evan in the design
      chat against the public conversations about disabling
      taproot key-path spends. The condition verifies
      construction by a deterministic tweak equation, not
      spendability, and carries no signature, so no quantum
      scenario falsifies it. The explicit internal-key operand
      lets a program prove in-band that its key path is
      classically unspendable by pinning a NUMS point, a property
      a raw scriptPubKey assert cannot express. That protection
      is classical only, a correction from the five-agent review
      to the design chat's stronger framing: the tweaked output
      key is exposed in the scriptPubKey, and a quantum adversary
      computes its discrete log directly without ever needing the
      internal key, which is exactly why the public
      disable-key-path proposals are consensus rules rather than
      program-level commitments. A NUMS-only variant
      with the internal key fixed in the spec was considered and
      declined: the general form subsumes it, forcing it would
      kill cooperative key-path designs, and the safety
      preference belongs in authoring-tool defaults, the decision
      15 precedent for Todd's height-only position. A future
      quantum-resistant output type is covered unstructured by
      CREATE_OUTPUT and ASSERT_MY_SCRIPTPUBKEY from day one.
      Structured entries for it land in the family blocks while
      v0 is still pre-deployment, and only through the reserved
      tier after deployment: in-family gaps are invalid, not
      reserved, so assigning one post-deployment would loosen
      validity, the direction a soft fork cannot take.
    - Errors grouped by the field read, three codes for five
      conditions (outpoint, scriptPubKey, amount), mirroring
      decision 15's two-error precedent for the time asserts and
      chosen over Chia's per-condition codes.
    - The decision 12 stability classification extends to the
      family by reusing rule 3's normative table: amount,
      scriptPubKey, and the taproot assert are content-committed
      and stable, txid and outpoint are location-committed and
      not. The recombination-stability entry decision 12 owes the
      register still waits on the signature design, the other
      half of the identity work.
    Rule 4's sort binding covers the family with no new text:
    self asserts are idempotent within their carrying input.

21. **The fee family: RESERVE_FEE adopted, the transaction-wide
    quantity asserts declined.** RATIFIED (decisions by Evan,
    2026-08-09, designed in the fee-family chat session after a
    steelman pass over each question). Seven parts:
    - Sequencing. The unit was chosen over rule 5 after Evan asked
      whether the condition set should complete before costing:
      rule 5's framework should be designed with its dominant cost
      driver in the set (Chia prices an AGG_SIG pair at 1,200,000
      against the 200 generic), the pre-registered free-tier
      decision may read differently with signatures present, and
      both precedents (Chia's original costs, CHIP-0049) priced a
      complete deployed vocabulary in one pass. Queue: the AGG_SIG
      family next, rule 5 last as the Phase 2 closer. Decision
      19's counted-sort deferral anticipated this unit's sort
      question only, so the sequencing is decided fresh here.
    - RESERVE_FEE adopted at `0x50`, matching deployed Chia
      exactly under the match-by-default policy: every occurrence
      accumulates by checked sum within and across inputs, the
      fee (inputs minus outputs) must be at least the total, and
      boundary equality passes. Probe-verified against the
      chia_rs wheel (16 probes, provenance in section 2). Numeric
      continuity with Chia's opcode 52 is impossible: 52 is
      `0x34`, inside the self-assert block's recorded decline
      gap, so the entry opens the `0x50` fees block.
    - The fee reserve is the fourth condition sort, beside
      claims, asserts, and message records. It is not an assert
      (duplication changes the demand, asserts commit to
      idempotence under rule 4) and not a claim (rule 1's
      equality-only sentence guards the claim matcher's
      algorithmic class, and a divisible scalar resource would
      relax it for no benefit). The message-record precedent of
      decision 16 established the new-sort path. Rule 4 gains
      the counted-reserve bullet, and validation rule 7 states
      the one aggregation rule.
    - ASSERT_FEE_LE declined. The transaction-wide form is the
      merge-poison decision 14 pre-registered: an aggregate upper
      bound vetoes strangers' decisions about strangers' value.
      The composition-safe per-input re-shape (a bound on this
      input's own fee contribution) is a redundant conjunction by
      the decomposition proof: an input's contribution is its
      amount minus the sum of its claims, so ASSERT_MY_AMOUNT
      plus the program's own claims already pins it, the decision
      20 precedent for declining re-encodings. Whole-transaction
      exactness stays where it belongs, in signatures: the
      taproot key path with SIGHASH_ALL today, the AGG_SIG
      binding menu when that family lands.
    - ASSERT_OUTPUT_COUNT declined in both forms, the closest
      call of the session (steelmanned at 65 percent confidence
      before ratification). The exact form is merge-poison per
      decision 14. The floor form survives the composition
      guarantee (counts are non-negative and sum) and is a
      genuine expressiveness gap (claims force slots only by
      naming content), but no identified program wants slots of
      unspecified content, and consensus surface without a user
      loses to the quality mandate. The reserved tier is the
      recorded reintroduction path if a use case materializes.
      ASSERT_INPUT_COUNT declined mirroring it: an asymmetric
      resolution of the grid row would need a rationale that does
      not exist, and the thin use case (a co-spender exists) is
      served more strongly by the message family.
    - The witness-dependent cells of decision 9's grid (weight,
      fee rate) declined as self-referential: the witness
      contains the program making the claim. A stripped-measure
      definition stays possible through the reserved tier and
      would want Phase 4's measurement evidence first.
    - Error and encoding mechanics. One field-grouped error,
      `insufficient_fee`, covering the unmet comparison, per the
      decision 15 and 20 grouping precedent (Chia likewise maps
      every family failure to one code). The operand takes the
      landed amount-operand convention, divergence C15. Stage 4,
      and the stage assignment doubles as the recombination
      class per decision 11: a fee floor survives the guarantee's
      valid-merge arithmetic yet an aggregator rebuilding the
      transaction can still break it, which is exactly the
      stage 4 re-check.

22. **Error codes are diagnostic, fail-fast is the contract.**
    RATIFIED (decision by Evan, 2026-08-09, raised by the fee
    family review's surviving check-reorder mutant and the
    cross-rule precedence flag from the self assert PR, settled
    in chat after a steelman of complete error enumeration). A
    transaction violating more than one condition-layer rule is
    invalid under each, and an implementation conforms by
    rejecting it with any violated rule's code. The corpus pins
    codes only for transactions violating a single rule, so
    check order never affects conformance, and the spec states
    the freedom explicitly in the VALIDATION.md preamble.
    Complete enumeration was considered and declined on three
    grounds:
    - Fail-fast bounds the work an invalid transaction can
      extract, the denial-of-service property every deployed
      consensus validator shares. Complete enumeration makes
      every invalid transaction cost full validation, and rule
      5's coming budgets want the opposite.
    - The set of all errors is not well-defined, because
      failures gate evaluability in the stage frame's dependency
      order: a spend whose conditions fail stage 1 parsing has
      no rule 7 question to answer. Defining which rules stay
      evaluable after which failures would be diagnostic
      machinery living in consensus text.
    - Identical-set reporting would widen the
      cross-implementation conformance surface for zero
      consensus benefit, against the minimal-surface mindset.
    Full-enumeration diagnostics are recorded as tooling: the
    Phase 3 compiler and the Phase 5 playground can wrap the
    reference validator and collect each rule's verdict
    independently, outside the consensus contract. This closes
    the precedence flag as unpinned by design.

23. **The signature assert family.** RATIFIED (decisions by Evan,
    2026-08-09, designed in one chat session after the oracle
    research pass, each item steelmanned with a stated confidence
    before ratification). Seven parts:
    - Scheme and carrier. BIP340 Schnorr over secp256k1, 32-byte
      x-only keys, 64-byte signatures, the VM's one scheme (D2 in
      `docs/vm-record.md` demands one curve and one scheme in the
      consensus core, and its rationale pre-registered condition
      layer batchability). BLS-style aggregation does not exist
      deployed on secp256k1, so each declared pair needs its own
      signature, a question Chia's bundle-level aggregate never
      faced. The signature rides as the condition's third
      operand: self-contained triples, no positional pairing
      convention, no witness-format change. The taproot annex
      and an external per-input signature section were considered
      and declined, C16 records both rationales. MuSig2 key
      aggregation survives the choice untouched: n signers can
      appear as one key and one signature above this layer.
    - Digest shape. Program-composed messages, matching deployed
      Chia and the program-composed shape the execution plan's
      vocabulary item recorded from the start, with the
      consensus-appended binding data per variant. The
      alternative, a consensus-composed digest hashing the
      input's own emitted conditions into every signature in the
      sighash style, was steelmanned and declined: program
      composition strictly contains it (a program can compose its
      message as a conditions commitment, the delegated-program
      idiom, and Phase 3 tooling makes that the default), the
      forced form cannot be composed away by protocols that need
      partial commitments (the CHIP-0011 retrofit is the recorded
      evidence such protocols exist), and the reversibility
      asymmetry that decided the timelock shape and the birth
      asserts applies verbatim: a conditions-hash variant stays
      addable through the reserved tier, pre-registered here as
      the reintroduction path. The cost is real and recorded: the
      fixed-message rewrite footgun (a signature over bytes that
      commit to nothing lets an interceptor rewrite the spend's
      effects) moves from inexpressible to tooling-prevented.
      Evan ratified this item on my recommendation with the
      compensating control ratified alongside: the footgun gets
      dedicated adversarial regression vectors and the PR review
      guide leads with that attack.
    - Domain separation. BIP340 tagged hashes, one ASCII tag per
      variant, fixed-length binding fields ahead of the
      variable-length message. C17 records the injectivity wart
      in Chia's suffix construction that the probes surfaced, and
      C18 records the firewall this construction deletes.
    - The menu and its names. All eight variants adopted, the
      full CHIP-0011 geometry: launching trimmed and hard-forking
      the rest in is the recorded evidence a menu declined is a
      menu retrofitted. Field substitutions follow decision 16's
      specifier table: parent id to creating txid, puzzle hash to
      spent scriptPubKey, coin id to outpoint, amount to amount.
      Stability classes carry over from the rule 3 table:
      scriptPubKey and amount bindings knowable at authoring
      time, txid and outpoint bindings existing only once the
      creating transaction is final, closing decision 12's
      register obligation for the signature design. Names: my
      CHECKSIG_* draft was revised mid-chat by the decision 18
      precedent, OP_CHECKSIG imports the sighash expectation that
      a signature commits to the transaction's effects, exactly
      the guarantee this design deliberately does not provide,
      and familiarity that misleads loses to precision. Evan then
      caught the remaining ambiguity in spec review: bare
      ASSERT_SIG_TXID does not say whose txid, and the spending
      transaction's own txid is both the sighash reader's
      assumption and the coming seal operand. The bound variants
      therefore adopt the self-assert MY convention,
      ASSERT_SIG_MY_*, with ASSERT_SIG_RAW keeping no MY because
      it binds nothing about its input, an asymmetry that is
      itself informative. Opcodes 0x10 to 0x17 in the landed
      signatures block, offset continuity 0x10+k with Chia 43+k
      in Chia's own order, after my 0x60 chat proposal collided
      with the landed block table, the numbering-correction
      pattern of decision 20 repeating.
    - ASSERT_SIG_RAW adopted. The in-VM `secp_verify` covers raw
      verification functionally, so the condition is not needed
      for expressiveness, and Chia ships both layers anyway
      because they complement: the VM op is eager, serial, and
      branchable (its result steers program logic), the
      condition is deferred, batched at stage 5, and
      all-or-nothing. Batch verification of n Schnorr signatures
      approaches half the cost of n serial checks, which is what
      consensus validity wants and a branching program cannot
      use. Rule 8's guidance paragraph states the replay
      property bluntly: RAW imports attestations, it does not
      authorize spends.
    - Composition and the merge analysis. Every variant binds
      prevout facts or program-chosen bytes, all fixed before any
      transaction exists, so every signature survives
      concatenation and the composition guarantee needs no
      relaxation, the direct payoff of decision 12's
      bind-to-prevout-data discipline. A whole-transaction
      binding variant is declined as merge-poison, the
      ASSERT_FEE_LE precedent in signature shape. The MEV
      analysis from the design chat is recorded here as
      rationale: transaction merging hands miners no value
      beyond the fee already theirs (redirecting overpaid fee
      into a grafted output is pocket-to-pocket relabeling, with
      two footnotes, coinbase maturity and fee-statistics
      legibility), third-party fee skimming is self-defeating in
      open relay (the skim lowers the fee on more bytes, so the
      original outbids it, leaving eclipse-class attacks as the
      residual), and the genuine costs are wallet fee discipline
      (reserve exactly what you pay, decision 21's surplus
      fact) and in-flight txid malleability, recorded in the
      evaluation doc's aggregation qualification and answered at
      consensus by the seal family below.
    - Sequencing and the seal. Ratified in the same chat, raised
      by Evan's challenge that senders need mempool immutability
      once they sign: a seal family, SEAL pinning the spending
      transaction's own txid and SEAL_OUTPUTS pinning the BIP341
      outputs hash, lands as its own unit after this one and
      before rule 5, so costing prices the complete vocabulary.
      Its full design record, including the option steelmen
      (exact counts fail on output order, the BIP341 pair alone
      fails on the version, locktime, and sequence fields, a
      sealed signature variant fails keyless coins), the
      composition guarantee's second scoping, and the decision
      21 amendment its adoption entails, lands with that unit.
      Two PRs, not one: neither unit is trivially small, and the
      seal amends the guarantee paragraph that requires its own
      recorded decision.

## 4. Novel-layer register

The validation rules have no external reference: no deployed system
checks a condition list against a Bitcoin transaction. What stands in
for an oracle, per ground rule 4:

| rule | status | oracle substitute |
| --- | --- | --- |
| 1. Injective multiset output matching | normative | hypothesis invariant suite (injectivity, reorder invariance, monotonicity, metamorphic mutations) plus the adversarial corpus in `vectors/validation/`, opening with the duplicate-CREATE_COIN theft vector |
| 2. Mixed-transaction rule | normative | `vectors/validation/mixed-transaction.json`: five acceptance vectors (mixed, plain-only, unclaimed slots, merge, surplus capture) and one rule 1 boundary rejection, plus the addition-monotonicity, merge, and plain-only invariants. The time assert family checks under this rule's assert clause: `vectors/validation/time-asserts.json` with BIP 65 and BIP 68 field semantics as the double reference, plus the operand-monotonicity and boundary-flip invariants. The self assert family checks under the same clause: `vectors/validation/self-asserts.json` with the probe corpus translated to prevout equality cases, the BIP341 tweak derivation shared with CREATE_OUTPUT_TAPROOT as the taproot assert's oracle, plus the outpoint-implies-txid and recombination-invariance invariants |
| 3. Message scoping | normative | `vectors/validation/messages.json` and `vectors/validation/announcements.json`: the probe corpus translated from the chia_rs oracle (balance, multiplicity, mode-key, self-send, order cases) plus adversarial wrong-address and forgery cases, and the balanced-pair, announcement-monotonicity, and byte-flip invariants |
| 4. Duplicates and multiplicity | normative | `vectors/validation/duplicates.json`: the strictest-wins oracle tests translated to identical and differing time asserts within one input, identical asserts across two and three inputs including the diverging final-sequence counterexample, ANNOUNCE duplication within an input and copies across inputs including the new-fact flip, duplicated announcement asserts at loose and script commitments, and duplicated reserved conditions on both sides of the cost floor, plus the identical-signature-triple and copied-triple-across-inputs cases from the signature assert unit, plus the in-place duplication-invariance invariant. The counted-sort boundaries stay pinned where they landed: duplicate claims in `vectors/validation/create-output.json`, duplicate message halves in `vectors/validation/messages.json`. Chia's remaining dedup tests are mempool spend-dedup machinery, declined in decision 19 |
| 5. Per-condition costing | pending | CHIP-0049 precedent comparison plus cost-conservation properties |
| 6. Reserved conditions | normative | encoding vectors in `vectors/conditions/`, every error path pinned |
| 7. The fee reserve | normative | `vectors/validation/reserve-fee.json`: the probe corpus translated from the chia_rs oracle (within-spend and cross-input accumulation, boundary equality, one-short rejection, zero reserve, a reserve stack no fee can reach) plus the fee-theft grafted-output regression vector, the surplus-capture acceptance vector pinning what the reserve does not protect, the above-2^32 and off-boundary separating cases from the review's mutation pass, and the operand-monotonicity, split, and boundary invariants |
| 8. Signature asserts | normative | `vectors/validation/signature-asserts.json`: satisfied and failing triples for every variant with signatures produced by the vendored Bitcoin Core framework signer (the recorded `secp_verify` signing oracle), the fixed-message rewrite regression pair pinning the decision 23 footgun, variant-separation cases pinning txid against outpoint, raw against bound in both directions, and each single-field variant against the two-field variant extending it (exhaustive pair separation lives in the hypothesis invariant), raw-mode replay acceptance pinning what RAW does not protect, plus the own-data-only, operand byte-flip, and variant-separation invariants. The BIP340 official vectors bind the verification relation itself through the shared `secp_verify` implementation |

Decision 12's register obligation is closed as of decision 23: the
recombination-stability classification now covers every landed
binding surface, the rule 3 specifier table for messages and
announcements, the self assert family preamble, and the signature
assert family preamble, each stating the same two classes over the
same prevout fields. Its adversarial surface, recombination of
valid spends into transactions their authors never assembled, is
exercised by the merge invariants and the recombination vectors of
those families, rather than translated tests, because no deployed
system exercises that surface at scale (the aggregation reality
check in section 11.2 of the evaluation doc).
