# BitLisp

A CLVM-derived predicate VM plus a condition/matching layer for Bitcoin,
committed under a new taproot leaf version. The design case and the four
design obligations live in `docs/bitcoin-script-successor-evaluation.md`
(section 7). The phased plan lives in `docs/execution-plan.md`.

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
   touching semantics references its spec section.
2. **Vectors are the source of truth between sessions.** Sessions are
   stateless, the vector corpus is not. Any behavior worth keeping becomes
   a vector in `vectors/` the same day.
3. **Divergence is documented, never silent.** Anywhere BitLisp differs
   from CLVM, the divergence table in `spec/VM.md` says so and why.
4. **The novel layer gets adversarial treatment first.** The matching rules
   (`spec/MATCHING.md`) have no external reference. They get
   property-based invariants and theft-bug regression vectors before any
   feature work builds on them.
5. **Nothing in Phases 0 to 2 depends on the hardened-implementation
   language.** That decision is the Phase 3 gate.

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

- Oracles are released artifacts only: the `clvm` and `chia-rs` wheels
  pinned in `pyproject.toml` under the `oracles` extra. Provenance is
  recorded in `spec/VM.md`.
- Chia test vectors are vendored as data into `vectors/upstream/` with
  provenance headers. CI never fetches from the network.
- `tools/fetch-references.sh` clones upstream repos into git-ignored
  `references/` for human browsing only. Open `references/` only in
  divergence-triage sessions, never in implementation sessions. Never copy
  code from it. Differential testing only detects bugs the two
  implementations do not share, and implementation-by-paraphrase destroys
  that independence.
- Upstream pin bumps are governance events: adopt, take, or decline per
  `docs/execution-plan.md`, one reviewed commit each, reasons recorded.

## Commands

```
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,oracles]"
.venv/bin/pytest python/tests            # unit + invariant suites
.venv/bin/python tools/run_vectors.py    # full vector corpus
ci/lint/lint.sh                          # codespell, ruff, whitespace, prose
```

The diff harness (`tools/diff_clvm.py`) arrives in Phase 1.

## Prose style

No em dashes anywhere. No semicolons in Markdown prose. Enforced by
`ci/lint/lint_prose.py`.
