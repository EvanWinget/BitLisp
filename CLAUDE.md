# BitLisp

A CLVM-derived predicate VM plus a condition and validation layer for Bitcoin,
committed under a new taproot leaf version. The design case and the four
design obligations live in `docs/bitcoin-script-successor-evaluation.md`
(section 5). The phased plan lives in `docs/execution-plan.md`.

## Branch workflow

All new development happens on feature branches. Never commit directly
to `main` unless told by Evan. Each unit of work gets its own branch
and lands on `main` through a pull request that is reviewed before
merging.

- CI runs on every pull request. A PR merges only when CI is green
  and Evan has reviewed it.
- Keep PRs small and complete: one spec section, one operator family,
  one tool. The session-hygiene rule (one unit of work per session)
  and the PR boundary should usually coincide.
- Review is also how Evan builds expertise in this codebase. Every PR
  description includes a short review guide: what changed, the spec
  sections that authorize it, the order to read the commits in, and
  the commands that verify the claims independently (vector suite,
  diff harness with a fresh seed, tests). Write it for a careful
  reader who did not watch the work happen.
- Spec commits, implementation commits, and vector commits stay
  separate within the PR so they can be reviewed in that order.

## Quality mandate (overrides everything else)

Clean, simple, professional code is the point of this project. Speed of
development and iteration is explicitly NOT a priority. It is better for
this project to take a long time and be right than to move quickly with
sloppy code.

In practice this means:

- Never leave placeholder implementations, commented-out code, or "fix
  later" TODOs in committed code. If something is not ready, do not
  commit it.
- Prefer the simple, obvious design over the clever one. Consensus code
  is read far more often than it is written, and it is read by skeptics.
- Small, complete, well-tested units of work. A half-finished feature
  across many files is worse than one finished piece.
- When a shortcut would save time at the cost of clarity, correctness
  margin, or test coverage, do not take it. Raise the tradeoff with Evan
  instead.
- Comments must be self-documenting. Never reference a documentation
  file (spec/VM.md, spec/COSTS.md, a README) in a code comment, whether
  as a citation or a pointer: the reader must not need to open another
  file to understand the code. State the fact inline, preferably by
  naming the code constant or function that embodies it. Describe a
  divergence from the oracle in place and mark it as "a recorded
  divergence" without naming the log file. Spec citations belong in
  commit messages and PR descriptions, not in code.
- Treat every commit as if a Bitcoin Core reviewer will read it cold.

## Ground rules

1. **Spec before code.** No consensus-relevant behavior lands in
   `python/bitlisp/` without a section in `spec/` it can cite. Every PR
   touching semantics references its spec section. The spec states
   behavior only, and stays complete enough on its own to predict
   every vector's outcome. Rationale, oracle provenance, and decision
   records live in `docs/` (for the VM, `docs/vm-record.md`), with
   no exception: a curation-note carve-out was ratified 2026-07-29
   and reversed 2026-08-08 (decisions 5 and 17 in
   `docs/condition-record.md`).
2. **Vectors are the source of truth between sessions.** Sessions are
   stateless, the vector corpus is not. Any behavior worth keeping becomes
   a vector in `vectors/` the same day.
3. **Divergence is documented, never silent.** Anywhere BitLisp differs
   from CLVM, the divergence table in `docs/vm-record.md` says so and
   why. Anywhere the condition layer differs from Chia's deployed
   condition semantics, the table in `docs/condition-record.md` says
   so and why.
4. **The novel layer gets adversarial treatment first.** The validation rules
   (`spec/VALIDATION.md`) have no external reference. They get
   property-based invariants and theft-bug regression vectors before any
   feature work builds on them.
5. **Nothing in Phases 0 to 3 depends on the hardened-implementation
   language.** The language is decided: C++ (decision by Evan,
   2026-07-29, recorded in `docs/execution-plan.md`). The remaining
   integration questions stay at the Phase 4 gate, and no Phase 0 to 3
   artifact may assume the language. Phase 3 (the authoring language
   and compiler, added 2026-07-30) is tooling, not consensus, and is
   covered by the same independence rule.

## Consensus mindset

Prefer rejecting valid-looking input over accepting invalid input. Every
error path is a vector. When a behavior is ambiguous, stop and flag it for
a spec decision rather than picking a plausible reading.

## Commit discipline

- Spec change and implementation change go in separate commits.
- Vectors are updated in the same PR as the behavior they pin.
- Never modify `vectors/` to make a failing test pass without a spec
  citation in the commit message explaining why the vector was wrong.

## Reference material policy

- Oracles are released artifacts: the `clvm` and `chia-rs` wheels
  pinned in `pyproject.toml` under the `oracles` extra, and, where no
  usable wheel exists, snapshots vendored verbatim from tagged
  upstream releases (the Bitcoin Core test framework under
  `tools/oracle/`). Provenance is recorded in `docs/vm-record.md`.
- Chia test vectors are vendored as data into `vectors/upstream/` with
  provenance headers. CI never fetches from the network.
- `tools/fetch-references.sh` clones upstream repos into git-ignored
  `references/`. Reading upstream source (clvm, clvm_rs, chia_rs) is
  allowed at any time, including during implementation (decision by
  Evan, 2026-07-26, amending the original triage-only rule). Reading
  is safe for the operator intersection because correctness there is
  defined by the deployed binary, not by anyone's source, and the
  diff harness always compares against the binary.
- Reading comes with three guardrails that protect the deliverable:
  1. Copying code into the tree remains prohibited. The
     implementation stays ours, under one license, small enough to
     review whole.
  2. Spec before code still governs. A behavior enters the
     implementation only through a `spec/` statement, and spec
     statements are established by evidence against the consensus
     binary (probes and cross-checked vectors), never by "matches
     upstream source." Reading generates hypotheses, the binary
     confirms them. The spec must stay complete enough that a reader
     never needs upstream source to predict a vector.
  3. When upstream source materially informed an implementation or
     design choice, say so in the commit message. Reviewers get the
     provenance trail.
- Upstream pin bumps are governance events: adopt, take, or decline per
  `docs/execution-plan.md`, one reviewed commit each, reasons recorded.

## Commands

```
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,oracles]"
.venv/bin/pytest python/tests            # unit + invariant suites
.venv/bin/python tools/run_vectors.py    # full vector corpus
.venv/bin/python tools/diff_clvm.py --count 10000 --seed 1   # diff harness
ci/lint/lint.sh                          # codespell, ruff, whitespace, prose
```

The diff harness generates a randomized corpus and compares bitlisp
against both oracle wheels. Any unexplained divergence fails the run.
Use fresh seeds when extending an operator family, and add every
behavior the harness pins down as a vector the same day.

## Prose style

No em dashes anywhere. No semicolons in Markdown prose. Enforced by
`ci/lint/lint_prose.py`.

## Terminology

BitLisp is aimed at Bitcoin developers and always favors
Bitcoin-native vocabulary in every artifact: spec, code, docs,
vectors (decision by Evan, 2026-07-31). Chia-name continuity is
subordinate to this. Cross-blockchain term mappings live in
`docs/glossary.md`, and a new term gets its glossary row in the
same PR that introduces it.
