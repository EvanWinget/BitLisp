# A Script Layer for Nine Billion
## Rationale, Method, and Recommendation for Bitcoin's Contract-Layer Successor

*Working outline — July 26, 2026. Internal draft ahead of a hostile-review essay. All numbers marked (est.) are envelope estimates pending measured artifacts.*

---

## 1. Executive Summary

**Recommendation:** Bitcoin's script successor should be a **Lisp VM with a condition-emission interface** — the *curated conditions architecture* — deployed as a single new tapleaf version, carrying four binding design obligations (§7). This is the answer to the ten-year question ("what substrate can carry global-scale self-custody?"). The answer to the three-year question ("what is the correct next soft fork?") is published alongside it without hedging: **CTV+CSFS, or BIP 448's spelling of the same capability, is the right next step, and our proposal is its destination, not its rival.**

**Confidence: 70%** that this is the best terminal architecture among currently known designs, decomposed in §8. The load-bearing judgment (conditions over introspection, ~72%) awaits hostile review — this document exists to enable that review.

---

## 2. Why Investigate at All: The Problem

### 2.1 The mission constraint

Bitcoin's purpose is self-custodial money. Self-custody at global scale is therefore not a feature request; it is the success condition. The question is whether Bitcoin's current script layer can support it.

### 2.2 The arithmetic (the theorem the argument hangs on)

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

**Finding:** at 9B users the per-exit budget (58 vb) is smaller than any transaction. Per-user on-chain exit cannot exist at terminal scale, for any candidate. The gate therefore takes its true form:

- **At 1B (transitional):** single unilateral exit must fit **526 vb**.
- **At 9B (terminal):** what is measured is *structure* — (a) k exits amortize sub-linearly in one transaction; (b) batching is **non-interactive** (an exiting user must not depend on coordinating with strangers); (c) pools **nest** (a sub-pool exits as one unit), since even fully-batched flat-pool exits floor at ~85–95 vb/user (est.). Recursion is not optional at 9B; it is the only path through.

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

The rows that stay broken forever without a language upgrade — pools, factories, offers — are exactly the rows the scaling arithmetic runs through.

### 2.5 The null hypothesis already prices the alternative

BitVM demonstrates arbitrary computation *without* a fork — via challenge games, operator capital lockup, existential-honesty trust models, and mandatory liveness. The market is already paying enormous complexity costs to emulate what a fork provides directly. "Do nothing" is not free; it is BitVM.

---

## 3. Method: How We Score Value

### 3.1 Two questions, two instruments

A single weighted rubric produced ranking flips under defensible re-weightings. Diagnosis: it was being asked to answer two different questions at once.

- **Q1 — best next soft fork (3–5 yr):** scored by the ratified rubric below.
- **Q2 — best terminal architecture (10 yr):** adds the arithmetic-derived sufficiency gate (§2.3) and re-anchors reviewability to *auditability at maturity* (given spec, tooling, signet-years) rather than familiarity today.

Both results are published, including the one we initially disliked.

### 3.2 Hard gates (pass/fail, all candidates)

1. **Deterministic tx-scoped validity** — validity depends only on the tx + its spent outputs (protects mempool, compact blocks, reorg handling).
2. **Bounded, priced execution** — worst-case cost model mapping to fees.
3. **Tapleaf-version soft-fork deployable** — no hard fork.

### 3.3 Ratified rubric (Q1)

| Criterion | Weight | Measures |
|---|---|---|
| Reviewability & consensus risk | 25% | Size/novelty/centralization of new consensus surface; testability; blast radius |
| L2 & UTXO-sharing enablement | 20% | Benchmark suite performance; interactivity assumptions |
| Resource footprint | 15% | Witness + UTXO-set growth + worst-case cost/weight |
| Externalities & incentive safety | 10% | MEV surface, token/spam enablement, pinning vectors |
| Similarity to Script (intrinsic) | 10% | Knowledge transfer; activation odds handled *outside* the sum |
| Self-custody power | 10% | Vaults/clawback/limits as shippable audited templates |
| Analyzability & tooling | 5% | Static effect extraction vs per-tx symbolic execution |
| Validation scalability | 5% | Batch verification, parallelism, aggregation-readiness |

Protocols: weights locked before scoring; every score cites a benchmark; sensitivity re-weightings reported; single-scorer noise (±1/cell) acknowledged — only conclusions stable across all weightings are treated as findings.

### 3.4 Benchmark suite

Vault · LN-Symmetry · payment pool · Ark round · CTV congestion batch · asynchronous offer · oracle/DLC · channel factory · fungible asset token — each with a today-baseline column.

---

## 4. Options Evaluated (8)

### 4.1 Great Script Restoration + CTV + CSFS ("GSR+")
Restored opcodes (CAT, 64-bit arithmetic, varops budget) plus template and signature-from-stack covenant primitives. **Q1 winner (3.40/5).** Strengths: smallest per-piece review surface, maximal Script continuity, native Ark/LN-Symmetry/DLC wins. Weaknesses: pooled constructions require CAT-covenant gymnastics — KB-scale, write-only, footgun-dense scripts (single pool exit 438–638 vb (est.), marginal at the 1B gate); batch exits grow superlinearly; no purity. **Verdict: correct next fork; asymptotically excluded as destination.**

### 4.2 Simplicity
Combinator language + Bit Machine + jets; deployed on Liquid. Formal verification unmatched; static cost bounds best-in-class. **Eliminated for mainnet:** the largest consensus surface of any candidate against the smallest qualified reviewer set; predicate/introspection model inherits that side's structural limits. (Worth stealing: static pre-execution cost bounds.)

### 4.3 Lisp + transaction introspection ("LISP-I"; BLL/bllsh architecture)
Real language, predicate model, tx-introspection opcodes; Elements-adjacent precedent. **Never first under any weighting tried** — concedes Script-similarity to GSR+ without capturing conditions' structural wins. Loses to LISP-C on five margins: cross-input runtime coordination (the witness wall), single-validator auditability, assertive/batchable signature semantics, flat-effect analyzability, offer-economy completeness. Gains vs LISP-C: native universal tx-properties (vocabulary-patchable on the other side) and lower validator novelty.

### 4.4 Lisp + condition emission ("LISP-C"; CLVM-architecture port)
Pure (program, witness arguments) → condition list; consensus-side validator checks conditions against the transaction; tx ≈ Chia spend bundle, input ≈ coin spend. **Q1 runner-up (3.25/5, statistical tie); Q2 winner.** Passes 1B gate with headroom (336–374 vb single exit (est.)); batches at 153 vb/exit at k=10 (est.), falling with k; nesting native via covenant recursion; **non-interactive exit aggregation** via offers (exit-intents swept by permissionless aggregators). Deficits are design variables, not architecture properties: witness compression unsolved, validator novel with theft-grade sharp edges (injective output matching), externality surface (easy tokens, pinning) requiring curation.

### 4.5 MATT / OP_CHECKCONTRACTVERIFY
State-commitment interface — a genuine third point between introspection and conditions; smallest consensus surface of anything expressive; beats GSR-CAT on pools (~250–400 vb (est.), passes 1B gate). **Loses on terminal margins:** general computation arrives via fraud proofs, re-importing challenge-game interactivity exactly where the gate forbids it; direct-covenant mode collapses computation back to Script's; contract logic remains scattered per-contract Script; no purity, hence no non-interactive aggregation economy. Best answer to "expressiveness per consensus byte" — which is not the terminal figure of merit; asymptotic exit structure is.

### 4.6 TXHASH-family (incl. BIP 446/448 lineage)
Programmable sighash: cleaner field access, no computation upgrade. Pool-root succession still needs merkle/arithmetic Script lacks. **Folded into Q1 as a refinement of the transition; eliminated as destination.**

### 4.7 ZK-verifier opcode
Asymptotically the gate's favorite (validity-rollup exits amortized across thousands, no challenge games). **Decisive finding:** rollup exit credibility is *data-availability-dependent* (on-chain DA fails 9B activity arithmetic; off-chain DA reintroduces trust), while covenant-pool exit credibility is *self-contained* — each member holds their own merkle branch and needs nothing from anyone. Worst blast-radius profile on the board (a silent soundness bug is unbounded theft). **Verdict: not the substrate — a future vocabulary word.** The conditions architecture's unknown-condition upgrade path admits a ZK_VERIFY condition later without redesign.

### 4.8 BitVM (null hypothesis, no fork)
Fails the gate on every axis that matters: operator-fronted exits, challenge-game disputes, capital bonds, liveness/watchers, 1-of-n honesty. **Eliminated as recommendation; retained as Exhibit A for §2.5.**

---

## 5. Q1 Result (published without hedging)

| | GSR+ | SIMP | LISP-I | LISP-C |
|---|---|---|---|---|
| Weighted total | **3.40** | 2.75 | 3.15 | 3.25 |

GSR+ and LISP-C are a statistical tie at the top (±1/cell scorer noise → ±0.10–0.25 swings on contested cells). GSR+ is the correct next fork. The community is converging on this independently (CTV+CSFS frontrunner status; BIP 448) even as it fragments over the exact spelling.

## 6. Stable Conclusions (invariant across all instrument revisions)

1. Per-user-UTXO self-custody caps near 10⁸ users; terminal scale requires recursive shared UTXOs with amortized, **non-interactive** exit. *(Arithmetic.)*
2. That requirement implies real spend-time computation (merkle work, state succession, arithmetic) — eliminating opcode-bundle approaches as destinations.
3. The interface asymmetries favoring conditions — purity → non-interactive composition; one hardened validator vs thousands of hand-rolled checkers; the witness wall on cross-input runtime data; assertive (batchable, aggregation-ready) signature semantics — survived error-correction and every re-weighting. Introspection's advantages (universal tx-properties) are vocabulary-patchable; purity is not retrofittable onto introspection.
4. Simplicity's review surface disqualifies it for mainnet regardless of weighting; the introspection Lisp never leads under any weighting.
5. GSR-vs-conditions is purely a time-horizon question; two-track deployment is therefore the dominant strategy, not a hedge.

---

## 7. The Recommendation: Curated Conditions Architecture

A Lisp VM under one new tapleaf version. Witness carries (serialized program, witness arguments). Evaluation is pure; output is a condition list; a single consensus-side validator checks conditions against the transaction. Signatures are BIP340 with program-composed messages (subsuming sighash flags and APO-class rebinding); verification is assertive, preserving batch verification and future half-aggregation.

**Four binding design obligations** (each converts a scored deficit into a requirement):

1. **Validator specification to BIP standard before advocacy** — injective (multiset) output matching so k identical CREATE_OUTPUTs consume k distinct outputs; mixed-transaction rule ("every condition finds a distinct output," never "outputs = union of conditions"); message matching scoped strictly within the transaction; explicit dedup and multiplicity rules; differential testing against Chia's five-years-hardened validator for every semantic that ports, and adversarial vectors for every rule that doesn't (the matching rules are precisely the part with no Chia prior art).
2. **Per-condition costing tuned against UTXO-set growth** — CREATE_OUTPUT priced superlinearly against set expansion; CLVM's battle-tested cost table inherited and mapped to weight.
3. **Witness-compression story measured against the gate** — canonical standard-layer shorthands, currying discipline, taproot-tree vs program-tree division of labor; validated against 526 vb (1B single exit) and amortized/nested thresholds (9B). This is the recommendation's binding technical constraint.
4. **Curated vocabulary** — Chia's core conditions plus deliberately chosen universal asserts (output count, fee bound); token-affordance decisions made explicitly and documented (recording the counterargument: inscriptions produced token manias on bare Script — expressiveness may not be the binding constraint on spam); ZK_VERIFY reserved as an upgrade word via unknown-conditions-with-declared-cost.

**Deployment:** two-track. Endorse and support CTV/CSFS (or BIP 448) now; build the conditions architecture as specification + Inquisition/signet deployment, valuable in every activation scenario including slow ones.

**Known honest costs carried forward:** validator novelty (no Bitcoin-family deployment precedent); witness verbosity pending obligation 3; ephemeral-coin patterns do not port (no intra-tx chaining); externality surface pending obligation 4; cultural headwind ("porting Chia to Bitcoin").

---

## 8. Confidence: 70%, Decomposed

| Claim | Confidence | Basis / limiter |
|---|---|---|
| Scaling arithmetic → recursive pools + amortized non-interactive exit required | 95% | Arithmetic; attackable only via pre-registered parameters |
| Terminal substrate is a real-VM covenant language (some interface) | 85% | Residual: a DA breakthrough making ZK-custody self-contained |
| **Conditions over introspection (the load-bearing judgment)** | **72%** | Survived every stress test — all authored by one analyst; needs hostile review |
| Two-track deployment strategy | 90% | Derived independently by rubric and by politics |
| Mainnet activation within 10 years | 25–35% | Outside the recommendation; 0% CTV signaling + proposal fragmentation as of mid-2026 |

**What would change the recommendation:** measured witness sizes blowing the gate thresholds after compression work; a hostile reviewer breaking the purity/witness-wall asymmetry (§6.3); a self-contained-DA construction for ZK exits; a validator-spec failure mode not repairable by rule design.

**Why 70% is the ceiling here:** single-analyst process, envelope estimates, and two-party agreement with rising enthusiasm — a known warning sign. Remaining confidence lives in exactly two places: hostile review, and measured artifacts.

---

## 9. Roadmap

1. **Essay for hostile review** (Delving Bitcoin) — spine: §2 arithmetic → §5 Q1 endorsement → §2.3 gate → §4 landscape → §7 recommendation. Leads by endorsing the other side's proposal.
2. **Measured artifacts** — write and serialize the real pool program (CLVM) and benchmark 3/6 equivalents per candidate; replace every (est.) in this document.
3. **Validator specification** (obligation 1) — the injective-matching rules first; they are the novel consensus surface.
4. **Witness-compression design** (obligation 3) — the binding constraint on the scaling narrative.
5. **Direct review with AJ Towns** — framing: "here is where the introspection architecture is right, and here are the five margins where we believe conditions beat it."
