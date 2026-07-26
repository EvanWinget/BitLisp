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
suite-specific and will be documented here as each runner lands
(`vm` in Phase 1, `conditions` and `matching` in Phase 2).

Run the corpus with `python3 tools/run_vectors.py`. A vector file whose
suite has no runner yet fails loudly rather than being skipped.
