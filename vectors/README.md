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
| `upstream/` | `tools/run_upstream.py` (clvm), unit suite (bip340, bip341) | Upstream vectors vendored as data, original format, provenance headers required |

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
suite-specific.

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
`vm/dispatch.json`, and all of `vm/sha256tree.json`, whose success
cases were cross-checked against the same wheel with its sha256tree
release flag enabled) pin BitLisp behavior that intentionally
differs, each cites its divergence row.

## conditions case shape

```json
{
    "name": "unique within the file",
    "conditions": "<hex, strict canonical serialization of the list node>",
    "expect": {"parsed": []}
}
```

`expect` is either `{"parsed": [...]}` with one JSON object per parsed
condition (`{"opcode", "script_pubkey", "amount"}` for CREATE_OUTPUT,
`{"opcode", "internal_key", "merkle_root", "amount", "script_pubkey"}`
for CREATE_OUTPUT_TAPROOT with `script_pubkey` the derived taproot
script, `{"opcode", "cost", "args": ["<hex node>"]}` for reserved
conditions) or `{"error": "<code>"}`. Every rejection rule in
CONDITIONS.md section 1 and MATCHING.md rule 6 has at least one case.

## matching case shape

```json
{
    "name": "unique within the file",
    "tx": {
        "version": 2,
        "locktime": 0,
        "inputs": [
            {
                "txid": "<hex, 32 bytes>",
                "index": 0,
                "script_pubkey": "<hex>",
                "amount": 60000,
                "sequence": 4294967295,
                "conditions": "<hex node>"
            }
        ],
        "outputs": [{"script_pubkey": "<hex>", "amount": 50000}]
    },
    "expect": {"valid": true}
}
```

`sequence` is optional and defaults to 4294967295. An input without a
`conditions` key is a non-BitLisp input, one with the key is a BitLisp
input whose puzzle evaluation produced that condition list. `expect`
is `{"valid": true}` or `{"error": "<code>"}`. The transaction must
satisfy the model's base rules (value conservation, ranges, distinct
outpoints): a case violating them is a malformed vector, not an
invalid spend. The adversarial regression corpus opens with the
duplicate-CREATE_OUTPUT theft case as vector #1 in
`matching/create-output.json`, per MATCHING.md rule 1.

Run the corpus with `python3 tools/run_vectors.py`. A vector file whose
suite has no runner yet fails loudly rather than being skipped.
