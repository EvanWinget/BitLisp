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
(the execution front end, authoring language, and compiler) is
underway: the front end shipped as of 2026-08-15 (assembler,
disassembler, single-spend runner, and a REPL with a stepping
debugger), and the language core is next. Nothing here is
consensus-ready. The phased plan is in
[docs/execution-plan.md](docs/execution-plan.md).

## Layout

| Path | Contents |
| --- | --- |
| `spec/` | The specification. `SPEC.md` (architecture), `VM.md` (evaluator), `CONDITIONS.md` (condition vocabulary), `VALIDATION.md` (condition validation rules), `COSTS.md` (cost model) |
| `python/bitlisp/` | Python reference implementation, the executable spec artifact |
| `python/bitlisp_tools/` | Authoring-side front end: assembler, disassembler, single-spend runner, and the REPL with its stepping debugger. Tooling, not consensus |
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

## Using the tools

The editable install adds four console scripts:

```
.venv/bin/bitlisp [tx.json]                            # REPL with stepping debugger
.venv/bin/bitlisp-run <program> [solution] <tx.json>   # single-spend runner
.venv/bin/bitlisp-asm [text]                           # text to serialized bytecode hex
.venv/bin/bitlisp-disasm [hex]                         # serialized bytecode hex to text
```

`bitlisp-run` reports the verdict, the emitted conditions, and the
cost for one spend, exiting 0 on a valid spend, 1 on an invalid
one, and 2 on input that could not be used. The converters read
stdin when no argument is given and compose in pipes. The REPL
loads the same transaction context, keeps a constants scratch
space, and drives the debugger with `step`, `next`, `cont`, and
`trace`. The text syntax is specified in
[docs/lang/syntax.md](docs/lang/syntax.md).

Working rules for agent sessions are in [CLAUDE.md](CLAUDE.md).

## License

MIT, matching Bitcoin Core and the wider Bitcoin ecosystem. Vendored
third-party material under `vectors/upstream/` and
`tools/oracle/bitcoincore/` stays under its upstream licenses, with
each license text carried beside the vendored files.
