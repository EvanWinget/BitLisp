# BitLisp Execution Plan
## From evaluation to executable spec, measured artifacts, and hostile review

*July 26, 2026. Working plan for Evan + Claude Code (Fable 5).
Companion to `bitcoin-script-successor-evaluation.md`. This file is
the skeleton: phases, units, status, done-criteria, and dated
one-line decisions. Rationale lives in the record docs, PR
descriptions, and commit messages*

---

## Ground rules (apply to every phase)

1. **Spec before code.** No consensus-relevant behavior lands in the Python reference without a section in `/spec` it can cite. Every PR touching semantics references its spec section.
2. **Vectors are the source of truth between sessions.** Claude Code sessions are stateless; the vector corpus is not. Any behavior worth keeping becomes a vector the same day.
3. **Divergence is documented, never silent.** Anywhere BitLisp differs from CLVM, the divergence table says so and why.
4. **The novel layer gets adversarial treatment first.** The validation rules are the only part with no external reference. They get property-based invariants and theft-bug regression vectors before feature work.
5. **Nothing in Phases 0 to 3 depends on the hardened-implementation language.** The language is decided ahead of the gate: C++. No Phase 0 to 3 artifact may assume the language.
6. **Skeleton fixed, flesh just-in-time.** Binding from day 0: the ground rules, the phase ordering and dependencies, the done-criteria, and the decision gates with their pre-registered evidence. Everything else is indicative and re-planned when the preceding done-criterion clears. Changing the skeleton requires an explicit, recorded decision.

---

## Phase 0 — Repo bootstrap

**Goal:** a repo Claude Code can be productive in within one session.

- [x] `bitlisp` monorepo: `spec/`, `python/bitlisp/`, `vectors/` (vm, conditions, validation, upstream), `tools/`, `docs/`, CLAUDE.md, MIT license. CI from day 1: pytest, vector runner, hypothesis suite.
- [x] `bll-consensus` archived with a pointer; CI and scaffolding cherry-picked, no history fork.
- [x] Reference-material policy: oracle wheels pinned as dev-only deps, upstream vectors vendored as data with provenance headers, CI never fetches, `tools/fetch-references.sh` clones source into git-ignored `references/`. Every pin bump is a governance event: adopt, take, or decline, one reviewed commit with reasons. Reading upstream source is allowed under the three CLAUDE.md guardrails (amended 2026-07-26, decision by Evan).

**Done 2026-07-26:** CI green on an empty vector run, CLAUDE.md committed.

---

## Phase 1 — VM core via CLVM intersection

**Goal:** a minimal Python evaluator whose shared core is bit-for-bit CLVM-equivalent, with divergences enumerated.

- [x] Evaluator in `python/bitlisp/`, own code, the executable spec artifact.
- [x] Operator set in `VM.md`: CLVM core minus BLS, plus `secp_verify`, plus `sha256tree` (divergence D9, 2026-07-29, decision by Evan). Divergence table with rationale per row.
- [x] CLVM cost table inherited (`COSTS.md`), weight mapping stubbed for Phase 4.
- [x] Differential harness `tools/diff_clvm.py` against both oracle wheels; `secp_verify` against BIP340 vectors and the vendored Core test framework (`diff_secp.py`).
- [x] Chia's official intersection vectors imported; randomized corpus generator.

**Done 2026-07-29:** zero unexplained divergence over the intersection vectors and 10k-program corpora, divergence table complete, decisions in `docs/vm-record.md`.

**Claude Code fit:** excellent. One operator family per session, each ending with vectors committed.

---

## Phase 2 — Condition layer + the validation spec — *the crown*

**Goal:** the executable spec for the only consensus component that exists nowhere else.

- [x] `CONDITIONS.md` v0 vocabulary, closed 2026-08-09: 26 normative entries. CREATE_OUTPUT and CREATE_OUTPUT_TAPROOT, the signature asserts at `0x10` to `0x17`, the time asserts, the self asserts, the message family, RESERVE_FEE, and the seals. Every add, decline, and reversal along the way is a numbered decision in `docs/condition-record.md` (decisions 10 to 25, divergences C13 to C22).
- [x] Minimal Bitcoin tx model in Python, enough to validate against.
- [x] `VALIDATION.md` + implementation, novelty first, one decision pointer each: rule 1 injective multiset matching (decision 4), rule 2 mixed-transaction with the composition guarantee (decision 14), rule 3 within-tx message scoping, where the match-Chialisp-by-default policy was also stated (decision 16), rule 4 sort-bound dedup and multiplicity (decision 19), rule 5 per-condition costing with flat constants, no free tier, and the superlinear stub declined with a Phase 4 set-growth revisit pre-registered (decision 25, divergences C21 and C22). The stage frame and recombination classes are decisions 11 and 12. Every condition-layer cost constant is PROVISIONAL pending the Phase 4 measurement pass.
- [x] Invariant suite (hypothesis): conservation, matching injectivity, reorder invariance, removal monotonicity, metamorphic output mutations.
- [x] Adversarial regression corpus: 241 validation cases at close, the duplicate-CREATE_OUTPUT theft case as vector #1, each case citing its rule.
- [x] Chia cross-check subset translated family by family, provenance in `docs/condition-record.md` section 2.

**Done 2026-08-09:** 184 tests, 984 vector cases, lint and diff harness clean at a fresh seed. Owed forward: the fresh-reader predictability exercise transfers to Phase 5 hostile-review preparation.

**Claude Code fit:** strong. Design decisions stay in Fable 5 sessions and land in spec prose first; Claude Code implements and generates vectors.

---

## Phase 3: Execution front end + language v0 + compiler

*Added 2026-07-30 and restructured into serial units 2026-08-09, decisions by Evan, recorded skeleton changes under ground rule 6.*

**Goal:** a human-usable execution front end over the Phase 2 engine, then a v0 authoring language and compiler good enough to write the four benchmark puzzles well, so every Phase 4 artifact is written in it. Tooling, not consensus: nothing in this phase changes `spec/` or `python/bitlisp/` behavior.

**Serial units, in order, one per session, each landing as its own reviewed PR:**

- [x] **Unit 0, the gate: fork-vs-scratch and implementation language.** Decided 2026-08-10 (decision by Evan): scratch, in Python, confirming the recorded lean. Carried by the frozen clvm_tools compiler, the dialect ladder in clvm_tools_rs, and pre-1.0 Rue; the dated evidence snapshot lives in the gate record (git history) and also serves the typed v1 gate. Expected scale for the whole phase: 3,000 to 5,000 lines. Pre-registered overturn: a Phase 4 vbyte threshold missed by compiled output, cleared by hand-optimization, and traced to optimization infrastructure rather than a fixable codegen choice reopens the fork question. Licensing note, corrected 2026-08-15: bllsh adopted MIT upstream on 2026-08-03; the unit 4 studies ran against a stale unlicensed clone and said otherwise. Copying stays prohibited by the reference policy regardless.
- [x] **Unit 1: parser and printer.** Landed 2026-08-11 (PR 46) as the assembler and disassembler, syntax stated in `docs/lang/syntax.md`. Decisions by Evan: unknown bare symbols rejected rather than becoming name bytes (2026-08-10), and the printer's decimal window is sign-split, eight bytes non-negative and two negative (2026-08-11).
- [x] **Unit 2: single-spend runner.** Landed 2026-08-14 (PR 48) as `bitlisp-run`. Decisions by Evan: brun's argument conventions and default budget, and the exit-code boundary, 1 for a consensus verdict and 2 for authoring input. Schema-aware condition rendering (2026-08-11). Pinned by a corpus replay test.
- [x] **Unit 3: REPL with stepper.** Landed 2026-08-15 (PR 49) as `bitlisp`, with `bitlisp-asm` and `bitlisp-disasm` beside it, surface stated in `docs/lang/repl.md`. Decisions by Evan, 2026-08-14: a standalone DebugMachine in the tools package, the consensus loop untouched, pinned differentially to `machine.run`; the command names; `def` is constants-only at the reader's unknown-symbol seam. The rendering seam and step-over predicate landed for unit 4 to consume.
- [x] **Unit 4: language core.** Landed 2026-08-15 (PR 50) as the compiler, `bitlisp-compile`, and the REPL language surface, the language stated in `docs/lang/language.md`. Decisions by Evan, 2026-08-15: the module form is named `program`; `if` and `list` ship as compiler special forms; the symbol table keys on compiled-body tree hashes (refining this bullet's earlier "bytecode positions" wording); the REPL accepts source forms at the prompt under the raw-first rule, raw VM text never changing meaning. Constants inline with no optimizer, the function tree orders by declaration, one namespace covers declarations, bindings, condition constants, and reserved words. Compiled representatives pinned in `vectors/vm/compiled-programs.json`.
- [x] **Unit 5: currying and program identity.** Added 2026-08-15 (decision by Evan, skeleton change under ground rule 6) and landed 2026-08-16 (PR 51): `curry` and `uncurry` as library, one-shot (`bitlisp-curry`, `bitlisp-uncurry`), and REPL surfaces, plus the tree-hash flag, the surfaces stated in `docs/lang/curry.md`. Decisions by Evan, 2026-08-15 and 2026-08-16: the standalone commands ship beside the REPL commands, the flag covers all three converters including `bitlisp-compile`, the identity story gets its own doc, and the surfaces are named `treehash` and `-T` rather than the `opc -H` spelling. The curried shape matches Chialisp tooling byte for byte, and uncurry is deliberately stricter than Chia's deployed uncurry, a divergence stated in the doc and pinned by a test. Discrete from unit 4 (no call-semantics contact) and from macros (operates on programs, not source). The unit 7 puzzles consume all three. The Phase 4 commitment-hash deferral stands.
- [x] **Unit 6: macros.** Landed 2026-08-16 (PR 52) as `defmacro` with `qq` and `unquote`, classic Chialisp semantics stated in `docs/lang/macros.md`. Decisions by Evan, 2026-08-16: macros only, includes split to their own unit below (skeleton change under ground rule 6). `if` and `list` stay compiler forms, so macros cannot shadow built-ins. Expansion is depth-capped and cost-budgeted, a recorded deviation from Chialisp's unbounded expansion. No `function` or `com` reflection form, the laziness expressiveness gap recorded in the language doc. No refactor rode along, the shared emission-primitives cleanup stays a candidate for a standalone PR. Expansion runs as a source pre-pass before reachability, macro bodies compile at declaration against earlier macros only, and read-back diverges from clvm_tools by one hop only (decision by Evan, 2026-08-16, steelmanned both ways, then narrowed twice as four review rounds showed every wider evidence scheme unsound on post-reader bytes): names the caller writes in a call's own arguments error when unresolved, REPL def spellings are barred resolution-side, and capture plus stale template spellings stay as Chialisp has them, documented sharp edges. The three new reserved words are a deliberate source and symbol-file compatibility break for earlier programs that used them as names, pinned by a loader test. Compiled representatives pinned in `vectors/vm/macro-programs.json`. Kept after the 2026-08-16 public-record review (decision by Evan): the fixed special forms and capped expansion avoid the macro-built-language failure mode on that record, and re-evaluation stays open at unit 7. Reversed by unit 6c the same day.
- [x] **Unit 6b: includes and the compile-time forms.** Split from unit 6 (decision by Evan, 2026-08-16): an include mechanism needs its own recorded decision against the self-containment rule, a program compiling identically pasted into the REPL. Scope expanded and resequenced ahead of unit 7 (decision by Evan, 2026-08-16, on a two-corpus census of tibetswap and chia-gaming): source-level include of shared constants and functions, computed compile-time constants, and inline functions. Every production puzzle file in both corpora imports shared definitions, and tibetswap defines nine of every ten functions inline. The census corrected the earlier deferral's premise: chia-gaming never abandoned source-level import, its compiled-sibling hash plumbing lives in its build layer outside the language, and that import stays deferred with `bitlisp-compile -T` covering the need manually in v0. `let` stays out, two uses across both corpora, both in tests. `assign` stays held on unit 7 evidence with a pre-registered trigger: benchmark-puzzle helpers that exist only to name intermediate values. Landed 2026-08-16 as `include`, computed `defconstant`, and `defun-inline`, stated in `docs/lang/language.md`. Decisions by Evan, 2026-08-16, via the approved unit plan: the self-containment rule is amended to the form plus its include files resolved through the same explicit search path everywhere, a repeat include dedupes by resolved file and a cycle errors where the classic reference dies on the collision or recurses without bound, `defconstant` evaluates its value on the reference VM under the default budget (a pinned break with unit 4's verbatim semantics, the modern defconst behavior under the classic keyword), and `defun-inline` keeps call-by-name laziness while closing classic's probe-verified sharp edges: arity checked, quoted content untouched, shadowing impossible, expansion depth-capped. Compiled representatives joined `compiled-programs.json`.
- [x] **Unit 6c: the macro reversal.** Landed 2026-08-16 as the removal of `defmacro`, `qq`, and `unquote` and the addition of `assert`, `and`, and `or` as fixed compiler forms with classic utility_macros semantics, reversing unit 6 (decision by Evan, 2026-08-16, both sides steelmanned under ground rule 3). The evidence: three usage surveys (Chia's canonical 91-puzzle corpus, the corpora vendored in references/, and chia-gaming) found no novel macro in any deployed puzzle, short-circuit assert, and, and or the entire production vocabulary, and chia-gaming's production referee choosing built-in destructuring over the structural macro sitting unbuilt beside it. The reserved-word set change breaks compatibility in both directions, pinned by the loader test. Compiled representatives joined `vectors/vm/compiled-programs.json`, and `macro-programs.json` left with the feature.
- [ ] **Unit 7: the four benchmark puzzles, written in the language, as the acceptance artifact:** vault, payment pool, async offer, singleton wrapper. This phase makes them exist and run, Phase 4 measures them. One PR per puzzle where size warrants. Style constraint (decision by Evan, 2026-08-16, simplified by unit 6c, widened by unit 6b's resequencing): the puzzles are plain functions, the fixed forms, and the unit 6b surfaces, there being no macro system, and the authoring experience feeds the typed v1 gate's ledger note on whether unit 6c's cut ever binds. Vault first, resequenced ahead of the pool (decision by Evan, 2026-08-16): core semantics match BIP-345, one PR, plus the keyless leader/follower consolidation path over the message ledger with its theft vectors, the evaluation doc's section 3.2 benchmark. Recovery posture is a curried per-instance choice, keyless or keyed (decision by Evan, 2026-08-16). The vault's dispatch helpers exist only to name a reconstructed root once, the pre-registered assign trigger firing, evidence for the unit 7 ledger note.

**Standing constraints:**

- **Hard scope boundary.** v0 is a small s-expression language with Chialisp-class ergonomics, BitLisp-native, no BLS vocabulary. Out of scope: static types, a Rue-class frontend, editor tooling, optimization beyond the obvious. The typed v1 question is a separate gate after Phase 5 review (ledger notes: 2026-08-11, types would let the REPL print by known type. 2026-08-16, whether the unit 6c macro cut holds for v1, decided on the unit 7 authoring experience).
- **Compiler correctness story.** The compiler sits outside spec-before-code, but compiler bugs become fund-loss bugs for users: every construct gets compile-and-run tests against the reference VM, and every compiled benchmark puzzle is pinned as a vector the same day.
- **Fallback, pre-registered:** if v0 slips, Phase 4 proceeds with the stock Chialisp toolchain off-tree, constrained to the CLVM intersection. The stopgap never enters the tree. The fallback covers the language units only; the front end does not slip out of the phase.

**Done when:** the runner and the REPL with stepper ship, all four benchmark puzzles compile, run on the reference VM, and are pinned as vectors, the compiler test suite is green in CI, and a language reference doc exists that a puzzle author can use without reading the compiler, with its examples runnable through the REPL.

**Claude Code fit:** strong. Language-design decisions stay in Fable 5 sessions and land in the language reference doc before Claude Code implements them.

---

## Phase 4 — Measured artifacts + hardened-language gate

**Goal:** replace every (est.) in the evaluation doc; make the gate empirical; settle the hardened-impl structure.

- [ ] Serialize the four benchmark puzzles. Measure bytes.
- [ ] Commitment-hash utility for the front end (queued 2026-08-14): a command printing what a scriptPubKey commits to. Deferred here because the commitment scheme decides its output.
- [ ] Compute actual vbyte totals vs the pre-registered thresholds (526 vb single exit @1B; amortization curve for k = 1..64; nested-pool exit).
- [ ] Witness-compression experiments as compiler features where possible; recompile, re-measure.
- [ ] If hand-optimization beats compiler output on a gate-relevant measurement, publish both numbers; the gap becomes a tracked language v1 requirement.
- [ ] Measure the guess-and-assert overhead per puzzle against direct asserts and the exit-gate thresholds (added 2026-08-06). Computed-over-context claims are an identified concentrated risk, settled by measurement.
- [ ] Condition-cost measurement pass (pre-registered 2026-08-09, decision 25): re-price every PROVISIONAL constant, isolate per-spend overhead (the C21 falsifier), run the set-growth model that can reintroduce a superlinear CREATE_OUTPUT schedule. Constants freeze at publication.
- [ ] Measure the reachable live-memory peak under the real budget mapping, then decide the peak-memory and evaluation-order question, entry 8 in `docs/vm-record.md` (added 2026-08-16, decision by Evan, skeleton change under ground rule 6).
- [ ] Decide surplus-solution strictness, entry 9 in `docs/vm-record.md`, before the witness format freezes (added 2026-08-16, decision by Evan, skeleton change under ground rule 6).
- [ ] Update evaluation doc and essay numbers; a threshold that fails post-compression goes in the essay verbatim (publish the miss).
- [ ] **Decision gate, hardened implementation integration.** The language is settled: C++, in tree with the deployment target (2026-07-29, decision by Evan, skeleton change under ground rule 6; the FFI-seam rationale lives in that record). The deserializer and evaluator get libFuzzer differential fuzzing against the Python reference and the oracle wheels. The gate decides with Phase 4 evidence: in-tree module vs standalone library, Boost.Test harness, fuzz throughput. The language ADR is written at the gate.

**Done when:** zero (est.) markers remain in the evaluation doc; gate verdicts are measured; language ADR written.

---

## Phase 5 — Essay + hostile review (overlaps Phase 4)

**Goal:** the confidence experiment.

- [ ] Essay from the evaluation doc spine, open problems stated plainly.
- [ ] Publish `spec/` publicly with the essay.
- [ ] Website: bitlisp.org (bitlisp.com and .net redirect) serving the essay, rendered spec, and docs from a pinned commit. The site never gates sharing.
- [ ] In-web playground once the site exists: Pyodide running the real Python reference VM and the v0 compiler. A JavaScript reimplementation is explicitly rejected.
- [ ] Delving Bitcoin post; direct note to AJ with the measured artifacts and an invitation to break VALIDATION.md.
- [ ] Track objections and revise the evaluation doc against them, including downward.
- [ ] Owed from Phase 2: the fresh-reader predictability exercise.

**Done when:** essay live; at least 3 substantive external technical responses engaged; the evaluation doc revised against actual objections.

---

## Phase 6 — Hardened implementation + Inquisition (post-review, contingent on Phase 5 not breaking the design)

- [ ] `cpp/bitlisp` per the language ADR, targeting the Core toolchain; differential CI against the Python reference (full corpus) and oracle wheels (intersection); libFuzzer on the validation layer with invariant oracles.
- [ ] Minimal Inquisition patch (new tapleaf version, validation hook, weight/cost mapping), no FFI layer.
- [ ] BIP-style draft for the tapleaf commitment + validator, extracted from `/spec`.
- [ ] Signet demo: the measured pool + offer puzzles live, exit-aggregation flow end-to-end.

---

## Working rhythm with Claude Code + Fable 5

- **Division of labor:** Fable 5 = architecture, spec prose, validation-rule design, divergence review, essay drafting. Claude Code = implementation, corpus and vector generation, harness plumbing, measurement tooling. Nothing crosses from design to code except through `/spec` (or `docs/lang/` for the tooling phase).
- **Session hygiene:** one unit per session; every session ends with vectors committed and CI green; sessions start from CLAUDE.md and the relevant spec section, not chat history.
- **Recurring checkpoint:** divergence-report review, invariant-failure triage, upstream release triage (adopt, take, decline), spec drift audit, plan re-sequencing when a done-criterion slips.
- **Risk watch-list, standing:** correlated blind spots (same author both sides of the diff harness; invariants now, external implementers post-Phase 5); witness numbers failing the gate (publish regardless); vocabulary scope creep before validation hardening; language scope creep delaying hostile review (the hard boundary and the Chialisp fallback); the witness-byte cost of computed-over-context claims (the Phase 4 measurement settles it); the identity and recombination classification (decision 12), the one part of the condition layer with no upstream fixed point, where hostile review is the test.
