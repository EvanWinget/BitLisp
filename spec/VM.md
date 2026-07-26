# BitLisp VM

Status: stub. Operator set and semantics land in Phase 1, one operator
family per session, each with vectors.

The evaluator is CLVM-derived. The shared core must be bit-for-bit
equivalent to the pinned oracle on the operator intersection. Everything
else appears in the divergence table below.

## 1. Values and representation

TODO: cons cells, atoms, serialization format.

## 2. Evaluation

TODO: apply semantics, environment lookup, quoting, cost accounting hooks.

## 3. Operator set

CLVM core minus the BLS operators, plus `secp_verify` (BIP340 verification
as an operator, assertive signature semantics are the condition layer's
job). TODO: full table with per-operator semantics and cost references.

## 4. Divergence from CLVM

Every entry names the divergence, the rationale, and the vectors that pin
it. No divergence exists outside this table.

| # | Area | CLVM behavior | BitLisp behavior | Rationale | Vectors |
| --- | --- | --- | --- | --- | --- |
| D1 | BLS operators | `bls_*`, `g1_*`, `g2_*` present | absent | Bitcoin has no BLS. Removing them removes their entire attack and cost surface. | TODO |
| D2 | secp256k1 | `secp256k1_verify` (post-hardfork op) | `secp_verify`, BIP340 Schnorr | Native curve, native signature scheme. Semantics per BIP340 vectors. | TODO |

## 5. Oracle provenance

Oracles are released artifacts pinned as dev dependencies in
`pyproject.toml` (extra `oracles`). Pin bumps follow the
adopt/take/decline triage in `docs/execution-plan.md`.

| Oracle | Version | Pinned | Upstream commit | Notes |
| --- | --- | --- | --- | --- |
| `clvm` (PyPI) | 0.9.15 | 2026-07-26 | TODO on first triage | Python oracle |
| `chia-rs` (PyPI) | 0.46.0 | 2026-07-26 | TODO on first triage | Rust oracle, via Python wheel |

Divergent operators are tested against their own oracles. `secp_verify`
uses the official BIP340 vectors plus libsecp256k1 via `coincurve`.
