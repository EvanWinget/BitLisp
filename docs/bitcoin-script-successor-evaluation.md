# A Script Layer for Nine Billion
## The Contract-Layer Comparison Behind BitLisp

*Working outline, July 26, 2026. Internal draft ahead of a hostile-review essay. All numbers marked (est.) are envelope estimates pending measured artifacts.*

*Revised August 6, 2026 after an email exchange on the architecture (roadmap item 5): aggregation qualification in section 4.4, consolidation benchmark in section 3.4, obligation 2 rewording and track-record precision in section 7, confidence update in section 8, steelmen in section 10.*

*Revised August 7, 2026 after a conversation with the deployed architecture's designer and a production puzzle-corpus study (both 2026-08-06, recorded in section 11): design principles in section 7, aggregation reality check in section 4.4, ossification argument in section 10.2, confidence update in section 8, roadmap item 6.*

*Revised August 9, 2026 at the rule 5 costing decision: obligation 2's superlinear clause amended to flat high pricing with a pre-registered Phase 4 revisit, decision 25 in `docs/condition-record.md`.*

*Revised August 9, 2026 (decision by Evan): reframed as a factual comparison. The recommendation framing, the scoring rubric and its totals, the stable-conclusions list, the confidence table, and every adoption-likelihood judgment are removed, and the surviving sections are renumbered (the earlier revision notes above cite the old numbering, and the full prior text is in git history). What the architecture is worth is for measured artifacts (Phase 4) and hostile review (Phase 5) to establish, not for this document to assert.*

---

## 1. Scope

This document records the comparison behind BitLisp: the scaling arithmetic that motivates a contract-layer question at all, the candidate architectures and their mechanical properties, the design obligations BitLisp carries, and the evidence gathered from the deployed condition architecture and from the public record. It states facts of the comparison and records both sides' strongest arguments. It does not score candidates, rank them, or estimate adoption. BitLisp builds the conditions architecture of section 5 as a specification with measured artifacts so that review can judge it on evidence.

---

## 2. The Problem

### 2.1 The mission constraint

Bitcoin's purpose is self-custodial money. The question this document starts from is whether the current script layer can support self-custody at global scale.

### 2.2 The arithmetic

Bitcoin's block space is essentially fixed: ~1M vbytes/block × ~52,560 blocks/year ≈ **52.56 billion vbytes/year**.

Any self-custody model that assigns each user their own UTXO — including Lightning, where a channel is a per-user UTXO — costs at minimum ~300 vbytes per user-lifetime (open + close, maximally batched, zero subsequent activity). That caps individual-UTXO self-custody at roughly **175M user-lifecycles/year at 100% block occupancy** — realistically tens of millions per year. Per-user-UTXO models cannot reach billions of users in decades of full blocks. This is arithmetic, not architecture opinion.

Shared-UTXO (pooled) models change the equation categorically: 1,000-user pools mean 9M UTXOs for 9B people. The binding constraint becomes **unilateral exit** — the safety valve that makes pooling custody rather than trust.

### 2.3 The exit budget (pre-registered gate parameters)

Parameters fixed before measuring any candidate: 10% of annual block space allowed for unilateral exits; 1%/yr unilateral exit rate (sensitivity at 0.5%/5%); pool size N=1024 baseline.

| Scale | 0.5%/yr | 1%/yr | 5%/yr |
|---|---|---|---|
| 100M users | 10,512 vb | 5,256 vb | 1,051 vb |
| 1B users | 1,051 vb | **526 vb** | 105 vb |
| 9B users | 117 vb | **58 vb** | 12 vb |

Reference: the smallest possible Bitcoin transaction (1 keypath input, 1 output) is **111 vb**.

At 9B users the per-exit budget (58 vb) is smaller than any transaction, so per-user on-chain exit cannot exist at terminal scale for any candidate. The gate therefore takes this form:

- **At 1B (transitional):** single unilateral exit must fit **526 vb**.
- **At 9B (terminal):** what is measured is *structure* — (a) k exits amortize sub-linearly in one transaction; (b) batching is **non-interactive** (an exiting user must not depend on coordinating with strangers); (c) pools **nest** (a sub-pool exits as one unit), since even fully-batched flat-pool exits floor at ~85–95 vb/user (est.).

### 2.4 What today's Bitcoin cannot do (baseline)

| Construction | Status today |
|---|---|
| Vaults | Presigned-tx + key-deletion kludges |
| LN-Symmetry | Impossible (needs APO-class capability) |
| Payment pools w/ unilateral exit | Statechains (trusted operator) |
| Channel factories | Interactive n-of-n only; undeployed |
| Non-interactive offers | SIGHASH_SINGLE\|ACP: index-bound, no partial fill |
| Congestion-batched commitments | Impossible without CTV |
| Non-interactive DLCs | Adaptor sigs: interactive, O(n) presigned CETs |

The rows that stay broken without a language upgrade (pools, factories, offers) are the rows the scaling arithmetic runs through.

### 2.5 The no-fork baseline

BitVM demonstrates arbitrary computation without a fork, via challenge games, operator capital lockup, existential-honesty trust models, and mandatory liveness. Whatever a fork's costs, the no-fork path has measurable costs of its own, recorded in section 4.8.

---

## 3. Gates and Benchmarks

### 3.1 Hard gates (pass/fail, all candidates)

1. **Deterministic tx-scoped validity** — validity depends only on the tx + its spent outputs (protects mempool, compact blocks, reorg handling).
2. **Bounded, priced execution** — worst-case cost model mapping to fees.
3. **Tapleaf-version soft-fork deployable** — no hard fork.

### 3.2 Benchmark suite

Vault · LN-Symmetry · payment pool · Ark round · CTV congestion batch · asynchronous offer · oracle/DLC · channel factory · fungible asset token · vault consolidation — each with a today-baseline column.

Vault consolidation was added 2026-08-06 from the email exchange in §6 item 5: an input is authorized only if some output pays the input's own scriptPubKey at least the summed value of every input sharing that scriptPubKey. It is the suite's one case where the architectures differ in complexity class rather than in style. One curated condition makes it O(N) for the validator, per-input introspection makes it O(N^2), and BIP 345 shows the special-cased-opcode middle path. Its adversarial variant (a hostile extra input emitting claims that distort the sums) is exactly the obligation 1 validation-rule surface and gets theft-bug vectors like the rest of that layer.

---

## 4. The Architectures (8)

Each entry states the candidate's mechanics, what it demonstrably provides, and what is open or costly.

### 4.1 Great Script Restoration + CTV + CSFS ("GSR+")
Restored opcodes (CAT, 64-bit arithmetic, varops budget) plus template and signature-from-stack covenant primitives. Provides: the smallest per-piece review surface, maximal Script continuity, native Ark, LN-Symmetry, and DLC constructions. Costs: pooled constructions require CAT-covenant techniques producing KB-scale, write-only scripts (single pool exit 438–638 vb (est.) against the 1B gate's 526 vb), batch exits grow superlinearly, and evaluation is not pure. It is the community's converging next step (CTV+CSFS, BIP 448), and BitLisp's deployment posture treats it as compatible groundwork, not a rival (section 5).

### 4.2 Simplicity
Combinator language + Bit Machine + jets; deployed on Liquid. Provides: formal verification and static pre-execution cost bounds unmatched by any other candidate. Costs: the largest new consensus surface of any candidate against the smallest set of reviewers qualified to check it, and the predicate/introspection execution model shares that side's structural properties. The static cost-bound technique is worth adopting regardless of the rest.

### 4.3 Lisp + transaction introspection ("LISP-I"; BLL/bllsh architecture)
Real language, predicate model, tx-introspection opcodes; Elements-adjacent precedent. The two Lisp candidates differ on five interface margins: cross-input runtime coordination (an introspection program sees only its own transaction context, so cross-input data must be replicated into witnesses), single-validator versus per-contract checking, assertive versus imperative signature semantics, flat condition lists versus program execution as the analysis surface, and offer-economy composition. In the other direction, introspection natively reads universal transaction properties (the conditions side covers the same ground only by vocabulary coverage, section 5 principle 1) and carries lower validator novelty. The strongest case for this side is written out in §7.1.

### 4.4 Lisp + condition emission ("LISP-C"; CLVM-architecture port)
Pure (program, witness arguments) → condition list; consensus-side validator checks conditions against the transaction; tx ≈ Chia spend bundle, input ≈ coin spend. Envelope estimates: 336–374 vb single exit (est.) against the 1B gate, batching at 153 vb/exit at k=10 (est.) and falling with k, nesting via covenant recursion, non-interactive exit aggregation via offers (exit-intents swept by permissionless aggregators). Open problems, each carried as a design obligation in section 5: witness compression unsolved (obligation 3), the validator is novel with theft-grade sharp edges such as injective output matching (obligation 1), and the externality surface (easy tokens, pinning) requires curation (obligation 4). The strongest case for this side is written out in §7.2.

**Aggregation qualification (recorded 2026-08-06, from the email exchange in §6 item 5).** Bitcoin output identity is positional. An outpoint is (txid, vout) and the txid commits to the whole transaction, so an untrusted aggregator recombining spends changes every downstream outpoint, and any presigned transaction bound to a txid breaks. Chia never faces this: its coin identity is content-derived from parent, program hash, and amount, independent of which aggregate spend bundle carries the spend. The non-interactive aggregation claim above therefore holds only for constructions whose downstream authorization travels in script (covenant recursion carries the successor in the created output's scriptPubKey) or in rebindable signature messages (the APO-class rebinding of section 5, which brings its own replay sharp edges, and rebinding by scriptPubKey and amount re-enters the duplicate-output ambiguity that obligation 1 exists to resolve). Exit to a plain key, the §2.3 gate's case, is unaffected. Recombined txids also present as malleability to any txid-tracking wallet or L2 stack, an integration cost recorded here so it is priced, not discovered.

**Aggregation reality check (recorded 2026-08-07, from the §8 evidence).** Node-level aggregation of identical spends shipped only in Chia release 2.5.5. Singleton fast-forward is the only program-aware aggregation code in the node, and it caused a block-production incident in February 2025. Fast-forward eligibility versus ASSERT_MY_COIN_ID replay defense is a live tension between rebasability and replay protection, the same tension the recombination-stability classification (decision 12 in `docs/condition-record.md`) must resolve on our side. The offer economy's daily non-interactive composition stands as evidence. The node-level aggregation story is younger and thinner than the architecture allows, and is cited as such.

### 4.5 MATT / OP_CHECKCONTRACTVERIFY
State-commitment interface, a genuine third point between introspection and conditions, with the smallest consensus surface of anything expressive. Provides: pool constructions at ~250–400 vb (est.), inside the 1B gate. Open on the terminal margins: general computation arrives via fraud proofs, which re-import challenge-game interactivity where the gate requires non-interaction, direct-covenant mode limits computation to Script's, contract logic remains scattered per-contract Script, and evaluation is not pure, so no flat-effect analysis surface exists.

### 4.6 TXHASH-family (incl. BIP 446/448 lineage)
Programmable sighash: cleaner field access, no computation upgrade. Pool-root succession still needs merkle and arithmetic work Script lacks, so this family refines the transition rather than adding a computation substrate.

### 4.7 ZK-verifier opcode
Amortizes validity-rollup exits across thousands of users with no challenge games, the strongest asymptotic exit profile of any candidate. Two recorded facts bound it: rollup exit credibility is data-availability-dependent (on-chain DA fails the 9B activity arithmetic, off-chain DA reintroduces trust), while covenant-pool exit credibility is self-contained (each member holds their own merkle branch), and a silent soundness bug in a verifier opcode is unbounded theft, the widest blast radius on the board. The conditions architecture's reserved condition tier admits a ZK_VERIFY condition later without redesign, which is where BitLisp places this capability (obligation 4).

### 4.8 BitVM (no-fork baseline)
Operator-fronted exits, challenge-game disputes, capital bonds, liveness and watcher requirements, 1-of-n honesty assumptions. Recorded as the cost of the no-fork path (section 2.5).

---

## 5. The Curated Conditions Architecture

BitLisp builds this candidate. A Lisp VM under one new tapleaf version. Witness carries (serialized program, witness arguments). Evaluation is pure; output is a condition list; a single consensus-side validator checks conditions against the transaction. Signatures are BIP340 with program-composed messages (subsuming sighash flags and APO-class rebinding); verification is assertive, preserving batch verification and future half-aggregation.

**Four binding design obligations** (each converts a known deficit into a requirement):

1. **Validator specification to BIP standard before advocacy** — injective (multiset) output matching so k identical CREATE_OUTPUTs consume k distinct outputs; mixed-transaction rule ("every condition finds a distinct output," never "outputs = union of conditions"); message matching scoped strictly within the transaction; explicit dedup and multiplicity rules; differential testing against Chia's five-years-hardened validator for every semantic that ports, and adversarial vectors for every rule that doesn't (the validation rules are precisely the part with no Chia prior art).
2. **Per-condition costing tuned against UTXO-set growth** — CREATE_OUTPUT carrying a high flat per-output price at the deployed Chia magnitude, the originally obligated superlinear schedule designed in full and declined 2026-08-09 as foreign to base consensus's linear-price-plus-cap idiom, with the Phase 4 set-growth model pre-registered as the test that can reintroduce a schedule before publication (decision 25 in `docs/condition-record.md`). CLVM's deployed cost table inherited as a starting point, re-validated per operator against measured CPU cost, and mapped to weight. The cost table is the weakest part of the inheritance: Chia's February 2026 security release repriced modpow after finding it priced far below real CPU cost and capped division operand sizes in mempool policy. Both incidents live in operators outside BitLisp's closed set, but they set the re-validation bar.
3. **Witness-compression story measured against the gate** — canonical standard-layer shorthands, currying discipline, taproot-tree vs program-tree division of labor; validated against 526 vb (1B single exit) and amortized/nested thresholds (9B). This is the architecture's binding technical constraint.
4. **Curated vocabulary** — Chia's core conditions plus deliberately chosen universal asserts (output count, fee bound, both declined 2026-08-09 when the composition guarantee forbade their transaction-wide shapes, decision 21 in `docs/condition-record.md`); token-affordance decisions made explicitly and documented (recording the counterargument: inscriptions produced token manias on bare Script — expressiveness may not be the binding constraint on spam); ZK_VERIFY reserved as an upgrade word via unknown-conditions-with-declared-cost.

One further discipline, recorded 2026-08-06 after the email exchange in §6 item 5 and binding on the benchmark programs and standard-layer templates rather than on consensus: a construction claiming non-interactive aggregation must carry every downstream authorization in script or in rebindable signature messages, never in a presigned transaction bound to a txid. The §4.4 qualification is the reason. A template that violates this silently loses the aggregation property the moment an aggregator touches its parent transaction.

**Design principles (added 2026-08-07, from the §8 evidence).** Five principles recorded as normative for the spec work, each earned by the deployed architecture's history rather than invented here:

1. **Schema-completeness over use-case curation.** The condition vocabulary is complete over Bitcoin's spend schema: every field a spend can care about gets an assert or a claim, and every omission is a recorded decline. Use-case curation is the documented failure mode (announcements were followed by messages, the self-assert family grew by the CHIP-0014 retrofit, and userspace repurposed magic amount values, -113 and -24, as signals where the vocabulary had no word). Schema enumeration is tractable, application prediction is not. This generalizes the assert-coverage decision (decision 9 in `docs/condition-record.md`) and is the vocabulary-side counterpart of obligation 4, whose curation stance continues to govern affordances.
2. **The condition list is the complete interface.** Every effect a program has on validity flows through its emitted conditions. No side channel (cost, evaluation order, or any other validator-honored signal) may carry meaning that is not a legible condition. This is the property the obligation 1 validation spec must guarantee. Legibility, speculative pre-signing evaluation, and per-input independent semantics (PSBT-style workflows) all depend on it.
3. **Ossification asymmetry.** Conditions ossify an append-only claim vocabulary. Introspection ossifies the transaction serialization as a script-visible API. Freezing a vocabulary that can only grow is cheaper than freezing a format that was never designed to be an API. Stated as §7.2 item 7 with the counterarguments beside it.
4. **The ZK proof boundary is structural.** The pure (program, witness arguments) to condition-list function is exactly the statement a future proof system would prove, with the validator untouched by such an upgrade. Proofs are producible per input before transaction assembly, where introspection proofs are transaction-entangled and post-assembly. The ZK_VERIFY reservation in obligation 4 is structural, not bolted on.
5. **Stage-structured validator.** The validator spec is organized as validation stages of strictly increasing context: stateless per-spend, prevout-bound, chain-context, cross-spend relational, batch signature verification. Recombination-stability classification is stage assignment. Recorded as decisions 11 and 12 in `docs/condition-record.md`.

**Deployment posture:** two-track. CTV/CSFS (or BIP 448) is compatible groundwork on its own timeline, and this architecture is built as specification plus Inquisition/signet deployment, useful as evidence in every activation scenario including slow ones.

**Known honest costs carried forward:** validator novelty (no Bitcoin-family deployment precedent); witness verbosity pending obligation 3; ephemeral-coin patterns do not port (no intra-tx chaining); externality surface pending obligation 4; cultural headwind ("porting Chia to Bitcoin").

Two more recorded 2026-08-06 after the email exchange in §6 item 5. First, txid instability under aggregation for presigned chains (the §4.4 qualification). Second, the upstream track record stated precisely rather than as "no major bugs," a phrasing retired from this project's correspondence. Chia's condition semantics have no known theft-grade failure in five years of adversarial deployment, but the VM around them has not been incident-free. Negative division was disabled after an admitted implementation bug (2021, soft fork). CHIP-0011 revised the softfork opcode's semantics (2023). The 2.6.0 security release repriced modpow and capped division operands in mempool policy (February 2026). The incidents cluster in the VM cost table and the generator layer, the parts BitLisp respectively re-validates (obligation 2) and declined to port.

---

## 6. Roadmap

1. **Essay for hostile review** (Delving Bitcoin) — spine: §2 arithmetic → §2.3 gate → §4 landscape → §5 architecture, with the CTV/CSFS compatibility stated up front.
2. **Measured artifacts** — write and serialize the real pool program (CLVM) and benchmark 3/6 equivalents per candidate; replace every (est.) in this document.
3. **Validator specification** (obligation 1) — the injective-matching rules first; they are the novel consensus surface.
4. **Witness-compression design** (obligation 3) — the binding constraint on the scaling narrative.
5. **Direct review with AJ Towns** — framing: "here is where the introspection architecture is right, and here are the five margins where we believe conditions beat it." A first email exchange is complete (August 2026). Outcomes: the §4.4 aggregation qualification, the §3.2 consolidation benchmark, the obligation 2 rewording, the section 5 track-record correction, and two concessions from the introspection side (accumulating checks belong in condition lists, and softfork conditions are not a meaningful limitation since returned conditions can merge into the overall requirements). Open threads: composing an annex-declared claim with a program that asserts its presence, the softfork-guard challenge recorded under D3 in `docs/vm-record.md`, and the consolidation benchmark's exploit-resistance treatment under obligation 1.
6. **Design-history review with the deployed architecture's designer** — complete (2026-08-06, a conversation plus a same-day production-corpus study, evidence recorded in §8). Outcomes: the section 5 design principles, the coordination-vocabulary reversal and the stage and recombination decisions (decisions 10 to 12 in `docs/condition-record.md`), and the §4.4 aggregation reality check. The open risks it concentrated: witness-byte cost of computed-over-context claims against the pre-registered gates (a Phase 4 measurement: compute, don't argue), and the identity and recombination classification, the one part of the condition layer that is off the upstream map and ours to prove. The vault-merging objection from the introspection side lives there, so item 5's continuation is the binding test.

---

## 7. Steelmen (added 2026-08-06)

Written after the August 2026 email exchange, one steelman per side, each drafted as if its author had to win. This section exists so the strongest version of each argument is on the record before hostile review, not reconstructed during it.

### 7.1 The best case for LISP-I (introspection)

1. **The novel validator is the whole risk budget.** LISP-C requires a new cross-input consensus object: a matching engine with multiset semantics, dedup rules, and a mixed-transaction rule. Bitcoin's worst consensus failures have lived in exactly this kind of cross-object accounting (CVE-2018-17144 was a duplicate-input accounting bug). Introspection adds vocabulary to a shape Bitcoin already validates: each input's program returns true or false, no new transaction-level object exists, and the blast radius of a bad opcode is that opcode. The margins conditions wins on are capability margins. This one is a correctness margin, and in consensus engineering correctness margins dominate capability margins.
2. **The margins are narrower than they look.** External-state claims can move to the annex, a fixed pre-execution location, with no condition list involved. Accumulating checks can be a small set of special-cased opcodes or annex records (BIP 345's shape), covering the realistic patterns in O(N) without a general matching engine. Purity's caching benefit exists under introspection too, since a predicate over the transaction and an input index is deterministic and cacheable per transaction.
3. **Bitcoin's identity model blunts the flagship win.** The non-interactive aggregation economy that makes conditions shine on Chia rests on content-derived, transaction-independent coin identity. Bitcoin's positional outpoint identity breaks presigned chains under aggregation (§4.4). Once the aggregation claim is qualified down to script-carried constructions, introspection with rebindable signatures reaches much of the same ground.
4. **Continuity compounds.** Introspection reads like Script, composes with the GSR+ transition, has years of deployed precedent on Elements, and inherits a reviewer base that already exists. No Bitcoin-family chain has ever deployed condition matching.
5. **The Chia evidence is contaminated.** Five years of Chia operation validates conditions plus Chia's coin model as a package. Porting the conditions half alone may keep the package's novel-validator cost while shedding the identity model that made the package work.
6. **The public record leans this way (added 2026-08-07).** In the March 2022 bitcoin-dev thread that seeded bll, both the introspection architecture's author and the condition model's designer publicly favored introspection for a Bitcoin retrofit (§8.4). Authority is not argument, and §8.4 records why the underlying objection targets Chia's bundle model rather than within-transaction conditions, but hostile review will cite the lean and this steelman claims it first.

### 7.2 The best case for LISP-C (conditions)

1. **The witness wall is physics, not vocabulary.** An introspection program sees only the transaction it sits in. Any protocol needing another input's runtime data must replicate that data into witnesses or scan every input, O(N^2) in the worst case. Conditions make every input's claims first-class objects that one validator sees at once. Accumulation is native and O(N), and each new accumulating pattern is a vocabulary word rather than a new opcode with its own consensus deployment. The consolidation benchmark (§3.2) is the concrete case: one curated condition on this side, a special-cased opcode (BIP 345) or an O(N^2) scan on the other.
2. **One hardened validator beats ten thousand hand-rolled inspectors.** Script's exploit history is dominated by contract authors miswriting their own checks. Conditions concentrate the sharp edges into one component that can be specified to BIP standard, differentially tested, and adversarially vectored once. The novel surface is real but bounded and enumerable. Introspection's equivalent surface is unbounded, spread across every contract ever deployed, and unfixable by soft fork once coins commit to it.
3. **Assertive signature semantics are an asymptotic fee win.** Program-composed messages keep verification assertive, preserving batch verification and future half-aggregation exactly where the gate needs bytes back, in pooled exits.
4. **Flat effects are the analyzability prize.** A condition list is data. Wallets, watchtowers, and auditors read what a spend can do without symbolically executing an arbitrary introspection program per contract.
5. **The track record, stated precisely.** The condition semantics have had no theft-grade failure in five years of adversarial deployment, on a chain whose offer economy demonstrates non-interactive composition daily. The recorded incidents (negative division, softfork opcode revision, modpow pricing) all live in the VM and its cost table, exactly the parts BitLisp inherits under a closed operator set and re-validates under obligation 2, not in the condition layer whose novelty is the actual objection.
6. **Purity is not retrofittable.** A vocabulary gap on the conditions side is patched by adding a word. Introspection cannot later acquire purity, flat effects, or a single validator without becoming the conditions architecture.
7. **Ossification asymmetry (added 2026-08-07).** Both architectures freeze something forever. Conditions freeze a claim vocabulary that is append-only by construction (the reserved tier is the growth path). Introspection freezes the transaction serialization as a script-visible API, so every future change to the format becomes a script-compatibility question for coins already committed.

### 7.3 What the exercise recorded

The introspection steelman's two best points are new since this document's first draft. The correctness-versus-capability framing of validator novelty is the sharpest available statement of the real objection. The evidence-contamination point is fair: §4.4's qualification shows the aggregation benefit was partly a property of Chia's coin model rather than of conditions alone, and it was this document that had to be corrected. Both are risk arguments rather than capability arguments, and both are answered only by work, not argument: obligation 1's spec-and-adversarial-vectors discipline for the novel validator, and the section 5 template discipline for aggregation stability. The first exchange also yielded concessions from the introspection side on accumulating checks and softfork extensibility, and left the arithmetic and the gate uncontested. The question review should be pointed at is whether the novel validator's correctness risk outweighs the capability margins.

---

## 8. Evidence from the Deployed Architecture (added 2026-08-07)

Recorded from a 2026-08-06 conversation with the deployed architecture's designer and a same-day study of the production puzzle corpus. Per project policy the correspondence itself stays out of the repo. Everything here is either the friendliest possible witness's view or our own reading of public code, and is weighed accordingly.

### 8.1 The designer's view

1. **CLVM ports to Bitcoin largely as-is. The condition layer is the Bitcoin-specific rewrite**, with new conditions needed (taproot was the given example). This matches the same author's 2024 Delving Bitcoin position (conditions are the transaction-format layer): the VM is commodity, the condition vocabulary and validator are the work.
2. **No language regrets.** The remaining limitations are minor CLVM items scheduled for Chia 3.0, a proof-of-space-format fork. The condition vocabulary converged after roughly three revision rounds (CHIP-0011, CHIP-0014, CHIP-0025), and BitLisp inherits the endpoint instead of re-running the iteration.
3. **CHIP-0025 SEND/RECEIVE is stable and working**, with no improvements queued.
4. **Announcements are not deprecated in practice.** They are the unaddressed broadcast primitive, load-bearing for offers because the asserting side cannot know counterparty coin ids at signing time, while messages are addressed exact pairing. A coordination vocabulary needs both. This overturned the earlier successor framing (decision 10 in `docs/condition-record.md`), with namespacing made first-class in the condition rather than repeating the payload prefix-byte convention.

### 8.2 The production corpus

1. **The CAT ring is the flagship contortion exhibit.** Enforcing "token inputs equal token outputs" takes roughly eighty lines of induction-proof ring accounting. It is also the honest price of purity: the guess-and-assert pattern (Chia's "truths") re-derives transaction facts in-program and asserts them. The essay presents both readings.
2. **Condition morphing is the userspace covenant engine.** The singleton and NFT layers rewrite their inner program's output-creation conditions, and the curry-and-treehash discipline is the covenant tax. On our side that tax becomes tapleaf plus taproot-tweak re-derivation, which CREATE_OUTPUT_TAPROOT already prices into one condition.
3. **Offers are the conditions-model exhibit.** A trustless swap in roughly fifty lines via broadcast announcements, running daily in production. This is the offer-economy evidence behind §4.4, to be cited at file level in the essay.
4. **The aggregation record is thin.** Identical-spend dedup shipped only in release 2.5.5, singleton fast-forward is the only program-aware node aggregation and caused the February 2025 block-production incident, and fast-forward versus ASSERT_MY_COIN_ID is a live rebasability and replay-protection tension. Folded into §4.4 as the aggregation reality check.

### 8.3 What the evidence addresses and what it cannot

The evidence bears on three objections: that the rewrite scope is unknown (the designer's own effort-allocation reading matches this project's), that the vocabulary would iterate for years under soft-fork cadence (it converged upstream in three rounds, and BitLisp inherits the endpoint), and that the coordination primitive is speculative (it is deployed and stable). What it cannot settle: all of it is from the friendliest possible witness, and the two concentrated risks it leaves are exactly the ones off the upstream map. Witness-byte cost of computed-over-context claims against the pre-registered gates (526 vb single exit at 1B, amortized and nested structure at 9B) is a Phase 4 measurement: compute, don't argue. And the identity and recombination seam (decision 12 in `docs/condition-record.md`) is where Chia's converged vocabulary stops being a reference, because their fixed point assumes content-derived identity. The vault-merging objection from the introspection side lives there. The hostile review of that seam (§6 item 5) remains the binding test.

### 8.4 The public record (added 2026-08-07)

Unlike §8.1, everything in this subsection is public, on the bitcoin-dev mailing list and Delving Bitcoin, and is cited by name as ordinary public record. The March 2022 bitcoin-dev thread ["bitcoin scripting and lisp"](https://lists.linuxfoundation.org/pipermail/bitcoin-dev/2022-March/020036.html) is the closest the public record comes to a direct debate on this document's central comparison, between the authors of the two architectures §4.3 and §4.4 describe. Quotes below are verbatim from the thread (messages 020036, 020075, 020080, and 020088 in the archive).

1. **The introspection side's origin is on the record.** Anthony Towns opened the thread: "After looking into it, I actually think chia lisp gets pretty much all the major design decisions pretty much right." His two listed changes for Bitcoin are secp256k1 signatures and, verbatim, "adding tx introspection instead of having bundle-oriented CREATE_COIN, and CREATE/ASSERT results". The stated reason declines Chia's bundle and mempool model, not the condition semantics: the bundling "doesn't magically solve the issues with maintaining the mempool and using that to speed up block acceptance", citing Chia's mempool-flooding incidents and, later in the thread, third parties linking their spends to yours. bll and bllsh are that position carried forward.
2. **Both designers publicly leaned introspection for a retrofit.** Bram Cohen, replying in the same thread: "If you're doing everything from scratch it's cleaner to go with the coin set model, but retrofitting onto existing Bitcoin it may be best to leave the UTXO model intact and compensate by adding a bunch more opcodes which are special to parsing Bitcoin transactions." He repeated the lean on Delving Bitcoin in March 2024 ([BTC Lisp as an alternative to Script](https://delvingbitcoin.org/t/btc-lisp-as-an-alternative-to-script/682), suggesting Bitcoin's tradition of direct assertions about the transaction may be the right fit), while separately noting in [Chia Lisp For Bitcoiners](https://delvingbitcoin.org/t/chia-lisp-for-bitcoiners/636) that the conditions language and coin format are what enable capabilities as well as covenants, and that matching this in Bitcoin might take aggressive OP_CAT use. §7.1 point 6 hands this to the steelman.
3. **A condition-list-in-the-transaction shape was on the table in 2022.** Towns, in the same thread: "One way to match the way bitcoin do things, you could have the 'list of extra conditions' encoded explicitly in the transaction via the annex, and then check the extra conditions when the script is executed." An annex-declared list is a near neighbor of the LISP-C shape (evaluation-produced conditions), sketched by the introspection side's author as the way to fit conditions into Bitcoin's transaction model.
4. **Monotonicity is designed in, on the designer's public testimony.** Cohen, answering the mempool worry directly: "Conditions map fairly closely with what's in Bitcoin transactions and are designed so to be monotonic and so the costs and fees are known up front. The only way two transactions can conflict with each other is if they both try to spend the same coin." The composability property the validation layer's rule 2 design makes normative (merge-closure: independently valid transactions concatenate valid, ratified as the composition guarantee, condition-record decision 14) is an intentional design property of the deployed conditions language, not an accident of its vocabulary.
5. **A gap we have queued was named in 2022.** Cohen: "The conditions are already basically what's in transactions. I think the only thing missing is the assertion about one's own id." That is the ASSERT_MY_* design session's problem statement, four years early.

The authority weight in this record belongs to the introspection side: both designers publicly leaned introspection for a Bitcoin retrofit, and §7.1 point 6 carries that. The recorded objection's substance targets Chia's bundle and mempool model, spend bundles merging in the mempool and third-party spend linking, none of which this architecture imports: BitLisp's transaction view is a pure function of the containing transaction, its coordination conditions are strictly within-transaction, and Bitcoin's mempool keeps the transaction as its atomic unit. The stage structure (decision 11 in `docs/condition-record.md`) is the machinery that keeps mempool re-evaluation cheap. Hostile review (§6 item 5) remains the binding test.
