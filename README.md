# BitLisp

An executable specification for a Bitcoin Script successor: a CLVM-derived
predicate VM plus a condition vocabulary and validation layer,
committed under a new taproot leaf version.

Status: Phase 1 (VM core via CLVM intersection) complete as of
2026-07-29, Phase 2 (the condition layer and the validation spec)
complete as of 2026-08-09. The evaluator core, the complete v0
operator table, the 26-entry condition vocabulary, and all eight
validation rules are normative and implemented, pinned by the
vector corpus, with the VM diffed against both oracle wheels with
zero unexplained divergence and every condition-layer cost
constant provisional pending the Phase 4 measurements. Phase 3
(the authoring language and compiler) is next. Nothing here is
consensus-ready. The phased plan is in
[docs/execution-plan.md](docs/execution-plan.md).

## Layout

| Path | Contents |
| --- | --- |
| `spec/` | The specification. `SPEC.md` (architecture), `VM.md` (evaluator), `CONDITIONS.md` (condition vocabulary), `VALIDATION.md` (condition validation rules), `COSTS.md` (cost model) |
| `python/bitlisp/` | Python reference implementation, the executable spec artifact |
| `vectors/` | Test vector corpus: `vm/`, `conditions/`, `validation/`, plus `upstream/` for vendored Chia vectors |
| `tools/` | Vector runner, corpus generators, measurement tooling |
| `ci/` | Lint tooling with pinned versions |
| `docs/` | Evaluation doc, execution plan, the VM record and the condition record (divergence tables, oracle provenance, design decisions), essay drafts |

## Running the suite

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,oracles]"
.venv/bin/pytest python/tests
.venv/bin/python tools/run_vectors.py
ci/lint/lint.sh
```

Working rules for agent sessions are in [CLAUDE.md](CLAUDE.md).

## License

Apache-2.0. This matches upstream `clvm_rs`/`chia_rs` and simplifies
test-vector reuse.
