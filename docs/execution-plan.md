# BitLisp Execution Plan
## From evaluation to executable spec, measured artifacts, and hostile review

*July 26, 2026. Working plan for Evan + Claude Code (Fable 5). Companion to `bitcoin-script-successor-evaluation.md`.*

---

## Ground rules (apply to every phase)

1. **Spec before code.** No consensus-relevant behavior lands in the Python reference without a section in `/spec` it can cite. Every PR touching semantics references its spec section.
2. **Vectors are the source of truth between sessions.** Claude Code sessions are stateless; the vector corpus is not. Any behavior worth keeping becomes a vector the same day.
3. **Divergence is documented, never silent.** Anywhere BitLisp differs from CLVM, the divergence table says so and why.
4. **The novel layer gets adversarial treatment first.** The matching rules (injective output matching, mixed-tx rule, message scoping) are the only part with no external reference — they get property-based invariants and theft-bug regression vectors before feature work.
5. **Nothing in Phases 0–2 depends on the hardened-implementation language.** The language is decided ahead of the gate: C++ (decision by Evan, 2026-07-29, recorded at the Phase 3 gate below). The independence rule stands unchanged: no Phase 0-2 artifact may assume the language.
6. **Skeleton fixed, flesh just-in-time.** Binding from day 0: the ground rules, the phase ordering and dependencies, the done-criteria, and the decision gates with their pre-registered evidence. Everything else — task lists inside phases, session specs, far-phase detail — is indicative only, and is re-planned at the recurring checkpoint when the preceding done-criterion clears. Task specs for Claude Code are written the day they're executed, against the current state of the repo. Changing the skeleton requires an explicit, recorded decision; changing the flesh requires nothing.

---

## Phase 0 — Repo bootstrap

**Goal:** a repo Claude Code can be productive in within one session.

- [x] Create `bitlisp` monorepo (monorepo so spec, reference impl, and vectors version together):
  ```
  bitlisp/
    CLAUDE.md              # working rules for Claude Code (below)
    LICENSE                # Apache-2.0 (matches chia_rs/clvm_rs; simplifies vector reuse)
    spec/
      SPEC.md              # architecture: leaf version, commitment, witness structure
      VM.md                # evaluator semantics + divergence-from-CLVM table
      CONDITIONS.md        # condition vocabulary v0
      MATCHING.md          # the novel layer: matching rules against a Bitcoin tx
      COSTS.md             # cost model: inherited table + weight mapping
    python/bitlisp/           # reference implementation (executable spec)
    vectors/
      vm/                  # (puzzle, solution) -> (result, cost | error)
      conditions/          # condition-list parsing/validation vectors
      matching/            # tx-context matching vectors incl. adversarial
    tools/                 # vector runners, corpus generators, size measurement
    docs/                  # evaluation doc, essay drafts
  ```
- [x] `bll-consensus`: add README pointer ("paused; superseded by BitLisp — rationale in linked evaluation doc"), archive.
- [x] Cherry-pick from bll-consensus: CI config, vector-runner scaffolding, any generic utilities. No history fork.
- [x] CI from day 1: pytest + vector runner + `hypothesis` property suite (empty is fine; the gate exists before the tests do).
- [x] **Reference-material policy (no submodules, deliberately):**
  - Oracles = released artifacts: `clvm` + `chia_rs` wheels pinned in the lockfile (dev deps only); upstream commit hashes recorded in `VM.md` provenance. Hardened phase: intersection diffing stays at the vector and corpus level through the Python harness and the pinned wheels, `clvm_rs` consulted as source only.
  - Chia's official test vectors vendored as **data** into `vectors/upstream/` with provenance headers (repo, commit, license). CI never fetches from the network.
  - `tools/fetch-references.sh` clones clvm/clvm_rs/chia_rs into git-ignored `references/`.
  - **Upstream sync is a governance event, never a float:** on each upstream clvm/chia_rs release, triage the changelog — *adopt* (semantics we want: spec amendment + vectors + pin bump in one reviewed commit), *take* (oracle-only bug fix: pin bump), or *decline* (Chia-specific: rationale recorded in the divergence table). Every pin bump is a commit with reasons; oracle drift is never ambient.
  - CLAUDE.md rule (as amended by Evan, 2026-07-26, superseding the original triage-only rule): reading upstream source is allowed at any time, including during implementation, under three guardrails recorded in CLAUDE.md. Code is never copied from it, spec statements are established by evidence against the consensus binary rather than by "matches upstream source", and upstream influence on an implementation choice is disclosed in the commit message. Tree cleanliness (all code ours, one license) remains part of the reviewability story.

**Done when:** CI green on an empty vector run; CLAUDE.md committed; first Claude Code session can execute Phase 1 tasks without re-explaining the project.

### CLAUDE.md starter content

- Project one-liner + link to evaluation doc §7 (the four design obligations).
- The five ground rules above.
- "Consensus mindset: prefer rejecting valid-looking input over accepting invalid input; every error path is a vector."
- Commit discipline: spec change and implementation change in separate commits; vectors updated in the same PR as the behavior they pin.
- Never modify `vectors/` to make a failing test pass without a spec citation explaining why the vector was wrong.
- Commands: how to run the vector suite, the diff harness, the invariant suite.

---

## Phase 1 — VM core via CLVM intersection

**Goal:** a minimal Python evaluator whose shared core is bit-for-bit CLVM-equivalent, with divergences enumerated.

- [x] Implement the evaluator in `python/bitlisp/` — own code, not a wrapper (it is the spec artifact), small and boring: cons cells, serialization, operator dispatch, cost accounting.
- [x] Define operator set in `VM.md`: CLVM core **minus** BLS operators, **plus** `secp_verify` (BIP340, assertive semantics deferred to condition layer). Divergence table with rationale per row.
- [x] Inherit the CLVM cost table (`COSTS.md`); weight-mapping section stubbed for Phase 3 data.
- [x] **Differential harness v1** (`tools/diff_clvm.py`): run every intersection program through bitlisp-python AND `clvm`/`chia_rs`; assert identical (result, cost) or identical error class.
- [x] Import Chia's official CLVM test vectors for the intersection; generate randomized program corpus (Claude Code task: corpus generator with size/depth knobs).
- [x] Divergent operators tested against their own oracles (`secp_verify` → BIP340 official vectors + Bitcoin Core's test-framework implementation, vendored). The original `coincurve` plan was dropped for lack of a usable wheel, decision recorded in VM.md section 7.

**Done when:** 100% pass on intersection vectors + 10k randomized corpus programs with zero unexplained divergence; divergence table complete.

**Done 2026-07-29.** All divergence decisions ratified or explicitly assigned to Phase 3 (VM.md section 8). Verified fresh: 76 unit tests, 460 vector cases, the 832-case vendored upstream corpus, `diff_clvm.py --count 10000 --seed 20260729`, and `diff_secp.py --seed 20260729` with three verifiers, all zero failures. Cost-table audit clean in both directions after adding the raise-operator charge-order statement.

**Claude Code fit:** excellent — mechanical, oracle-checked, test-first. Ideal sessions: one operator family per session (arith, bytes/strings, tree ops, crypto), each ending with vectors committed.

---

## Phase 2 — Condition layer + the matching spec — *the crown*

**Goal:** the executable spec for the only consensus component that exists nowhere else.

- [ ] `CONDITIONS.md` v0 vocabulary: ported set (CREATE_COIN, secp AGG_SIG family with program-composed messages, ASSERT_HEIGHT/SECONDS abs/rel, ASSERT_MY_* family, SEND/RECV_MESSAGE tx-scoped, RESERVE_FEE) + universal asserts (ASSERT_OUTPUT_COUNT, ASSERT_FEE_LE) + explicit curation notes per obligation 4.
- [ ] Minimal Bitcoin tx model in Python (inputs w/ outpoint+amount+leaf, outputs w/ scriptPubKey+amount, locktime/sequence) — enough to validate against, no networking.
- [ ] `MATCHING.md` + implementation, in this order (novelty-first):
  1. **Injective multiset output matching** — k identical CREATE_COINs consume k distinct output slots.
  2. **Mixed-transaction rule** — every condition finds a distinct satisfier; unmatched outputs permitted (plain-taproot coexistence).
  3. **Message scoping** — strictly within-tx; sender/receiver binding modes; multiplicity rules for duplicate SENDs/RECVs.
  4. **Dedup and multiplicity** — within-input and cross-input, with cost interaction documented.
  5. **Per-condition costing** — including superlinear CREATE_COIN pricing stub (obligation 2; tuning is Phase 3 data-driven).
- [ ] **Invariant suite** (`hypothesis`), the correlated-blind-spot mitigation:
  - Value conservation on every accepted tx.
  - No output satisfies two conditions (matching injectivity).
  - Validation invariant under input reordering and condition-list reordering.
  - Removing any condition from a spend never turns an invalid tx valid; removing any output never leaves a matched condition matched.
  - Metamorphic: mutate any matched output (amount ±1, script byte flip) → rejection.
- [ ] **Adversarial regression corpus** in `vectors/matching/`: the duplicate-CREATE_COIN theft case as vector #1; batching-wallet scenarios; message forgery/replay shapes; mixed-tx edge cases.
- [ ] Cross-check subset: for semantics that overlap Chia (timelock comparisons, dedup behavior), translate Chia consensus tests into bitlisp vectors.

**Reference material for this phase (recorded 2026-07-29, per Evan):**

- **Condition costing has five years of deployed CLVM learnings: read them before designing ours.** Chia's deployed per-condition costs are the baseline, and CHIP-0049 (the Chia 3.0 hard fork, in review) revises them: a base cost of 500 per condition beyond the first 100, announcement conditions always priced, and the hard 1,024-announcement cap removed in favor of pricing. That is the pricing-over-caps philosophy obligation 2 commits us to, applied by the team with production data. Two decisions to make deliberately rather than inherit: whether a free tier (their first-100 carve-out) is acceptable or a cliff we reject, and how their announcement pricing maps onto our tx-scoped SEND/RECV_MESSAGE conditions, their closest descendant.
- **Taproot output construction belongs to the condition layer, not the VM (design question, decide in CONDITIONS.md).** bllsh ships `secp256k1_muladd`, a general EC linear-combination operator, largely so programs can verify taproot tweaks in-language. BitLisp will meet the same need when covenant recursion constructs a successor coin whose scriptPubKey is taproot(internal key, tree). The conditions-architecture answer is a condition form that commits to the taproot components and lets the one hardened validator compute the tweak natively, keeping EC arithmetic out of the consensus VM. Decide the form when CONDITIONS.md v0 is drafted, and record the muladd decline rationale next to it (VM.md section 8, D2 entry, already records the v0 decline).

**Done when:** invariant suite green over large generated corpora; adversarial corpus ≥ 50 hand-designed vectors each citing a MATCHING.md rule; a reviewer can read MATCHING.md alone and predict every vector's outcome.

**Claude Code fit:** strong for implementation + invariant/corpus generation; **design decisions stay in Fable 5 sessions** (this chat) and land in spec prose before Claude Code touches them. Session pattern: Fable 5 designs a matching rule → spec commit → Claude Code implements + generates vectors → Fable 5 reviews divergence reports.

---

## Phase 3 — Measured artifacts + language gate

**Goal:** replace every (est.) in the evaluation doc; make the gate empirical; decide the hardened-impl language.

- [ ] Write real puzzles in BitLisp: payment pool (benchmark 3), async offer (benchmark 6), vault, singleton wrapper. Serialize; measure bytes.
- [ ] Compute actual vbyte totals vs the pre-registered thresholds (526 vb single exit @1B; amortization curve for k = 1..64; nested-pool exit).
- [ ] Witness-compression experiments: canonical standard-layer shorthands (spec'd as a commitment-scheme option, not ad hoc), currying discipline, taproot-tree vs puzzle-tree split. Re-measure after.
- [ ] Update evaluation doc + essay numbers; if any threshold fails post-compression, that finding goes in the essay verbatim (ground rule: publish the miss).
- [ ] **Decision gate — hardened implementation integration.** The language question is settled: C++, in tree with the deployment target (decision by Evan, 2026-07-29, a recorded skeleton change under ground rule 6). Rationale: Bitcoin Core and Bitcoin Inquisition are C++ and take consensus code without an FFI boundary, so the previous default (Rust `bitlisp-core` + `bitlisp-ffi` C-ABI + thin C++ patch) put a novel FFI seam inside consensus validation, which was itself review surface, and Inquisition integration friction was already this gate's pre-registered overturn condition. The known cost is accepted and mitigated rather than avoided: C++ parses attacker-supplied witness bytes, so the deserializer and evaluator get libFuzzer differential fuzzing against the Python reference (full corpus) and against the oracle wheels (intersection), on Core's own fuzzing model. The gate now decides the remaining structure with Phase 3 evidence: in-tree module vs standalone library consumed by the Inquisition patch, test harness (Boost.Test per Core convention), and fuzz-throughput measurement. The language ADR is still written, recording this decision, its rationale, and the gate evidence.

**Done when:** zero (est.) markers remain in the evaluation doc; gate verdicts are measured; language ADR written.

---

## Phase 4 — Essay + hostile review (overlaps Phase 3)

**Goal:** the confidence experiment.

- [ ] Essay from the evaluation doc spine: arithmetic → Q1 endorsement (CTV/CSFS/BIP 448) → sufficiency gate → landscape → curated conditions recommendation → measured numbers → open problems (validator novelty, ephemeral-coin gap, externalities) stated plainly.
- [ ] Publish `spec/` publicly with the essay — early spec publication is the second-implementation-independence play and the reviewability story in action.
- [ ] Delving Bitcoin post; separately, direct note to AJ framed as: where the introspection architecture is right; the five margins where conditions win; the measured artifacts; invitation to break MATCHING.md.
- [ ] Track objections against the confidence table (§8 of evaluation doc); pre-commit to updating the doc, including downward.

**Done when:** essay live; ≥ 3 substantive external technical responses engaged; confidence table revised against actual objections.

---

## Phase 5 — Hardened implementation + Inquisition (post-review, contingent on Phase 4 not breaking the design)

- [ ] `cpp/bitlisp` per the language ADR, targeting the Bitcoin Core toolchain; differential CI: C++ ↔ Python reference on full corpus; C++ ↔ oracle wheels on intersection; libFuzzer on matching layer with invariant oracles.
- [ ] Minimal Inquisition patch (new tapleaf version, validation hook, weight/cost mapping), no FFI layer.
- [ ] BIP-style draft for the tapleaf commitment + validator, extracted from `/spec`.
- [ ] Signet demo: the measured pool + offer puzzles live, exit-aggregation flow demonstrated end-to-end.

---

## Working rhythm with Claude Code + Fable 5

- **Division of labor:** Fable 5 (this chat) = architecture, spec prose, matching-rule design, review of divergence reports, essay drafting. Claude Code = implementation, corpus/vector generation, harness plumbing, refactors, measurement tooling. The boundary is the spec: nothing crosses from design to code except through `/spec`.
- **Session hygiene:** one spec section or operator family per Claude Code session; every session ends with vectors committed and CI green; start each session by pointing Claude Code at CLAUDE.md + the relevant spec section, not the chat history.
- **Recurring checkpoint (with Fable 5):** divergence-report review, invariant-failure triage, upstream release triage (adopt/take/decline), spec drift audit (does the code do anything MATCHING.md doesn't say?), plan re-sequencing if a phase's done-criteria slipped.
- **Risk watch-list, standing:** correlated blind spots (same author both sides of the diff harness — mitigate via invariants now, external implementers post-Phase 4); witness numbers failing the gate (Phase 3 finding, publish regardless); scope creep into vocabulary before matching rules are hardened (ground rule 4).

## Immediate next actions

1. Create the repo + CLAUDE.md + CI skeleton (Phase 0) — one Claude Code session.
2. Evaluator core + first operator family with clvm diff harness — second session.
3. In parallel here (Fable 5): draft `MATCHING.md` rule 1 (injective matching) so it's ready the moment Phase 1 closes.