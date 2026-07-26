# Vector corpus

Vectors are the source of truth between sessions. Any behavior worth
keeping becomes a vector the same day it is implemented. Never modify a
vector to make a failing test pass without a spec citation explaining
why the vector was wrong (CLAUDE.md).

## Layout

| Directory | Suite | Pins |
| --- | --- | --- |
| `vm/` | `vm` | (puzzle, solution) to (result, cost) or error |
| `conditions/` | `conditions` | condition-list parsing and validation |
| `matching/` | `matching` | tx-context matching, including the adversarial regression corpus |
| `upstream/` | none | Chia's official vectors vendored as data, original format, provenance headers required |

## File format

Every file outside `upstream/` is one JSON object in the
`bitlisp-vector-v0` envelope:

```json
{
    "schema": "bitlisp-vector-v0",
    "suite": "vm",
    "spec": "VM.md#4-D2",
    "cases": []
}
```

The `spec` field cites the spec section the cases pin. Case shapes are
suite-specific (`conditions` and `matching` land in Phase 2).

## vm case shape

```json
{
    "name": "unique within the file",
    "program": "<hex, strict canonical serialization>",
    "env": "<hex>",
    "max_cost": 796,
    "expect": {"result": "<hex>", "cost": 796}
}
```

`max_cost` is optional and defaults to 11000000000. `expect` is either
`{"result", "cost"}` for success or `{"error": "<code>"}` with a code
from `spec/VM.md` section 5. Many cases pin budget-boundary behavior
in adjacent pairs (same program, `max_cost` off by one), the
interleaving rules they pin are in `spec/COSTS.md` section 1.

Every intersection case was cross-checked against the consensus oracle
(`chia-rs`, flags 0) when it was written. Divergence cases
(`vm/serialize.json` strictness, unknown and pair operators in
`vm/dispatch.json`) pin BitLisp behavior that intentionally differs,
each cites its divergence row.

Run the corpus with `python3 tools/run_vectors.py`. A vector file whose
suite has no runner yet fails loudly rather than being skipped.
