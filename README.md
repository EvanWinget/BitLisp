# BitLisp

An executable specification for a Bitcoin Script successor: a CLVM-derived
predicate VM plus a condition vocabulary and transaction-matching layer,
committed under a new taproot leaf version.

Status: Phase 0 (bootstrap). Nothing here is consensus-ready. The phased
plan is in [docs/execution-plan.md](docs/execution-plan.md).

## Layout

| Path | Contents |
| --- | --- |
| `spec/` | The specification. `SPEC.md` (architecture), `VM.md` (evaluator + divergence table), `CONDITIONS.md` (condition vocabulary), `MATCHING.md` (tx matching rules), `COSTS.md` (cost model) |
| `python/bitlisp/` | Python reference implementation, the executable spec artifact |
| `vectors/` | Test vector corpus: `vm/`, `conditions/`, `matching/`, plus `upstream/` for vendored Chia vectors |
| `tools/` | Vector runner, corpus generators, measurement tooling |
| `ci/` | Lint tooling with pinned versions |
| `docs/` | Evaluation doc and essay drafts |

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
