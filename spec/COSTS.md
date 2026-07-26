# BitLisp Cost Model

Status: stub. The inherited table lands with Phase 1 operators. The
weight mapping is filled with Phase 3 measurements.

## 1. Cost table

BitLisp inherits the CLVM cost table for the operator intersection.
Divergent operators (see the divergence table in [VM.md](VM.md)) get
their own entries with measurement-backed rationale.

TODO: full table, imported alongside the Phase 1 operator families.

## 2. Condition costs

TODO: per-condition base costs and the superlinear `CREATE_COIN`
schedule (Phase 2 stub, Phase 3 tuning).

## 3. Weight mapping

TODO (Phase 3): mapping from VM cost units to Bitcoin transaction weight,
derived from benchmark data on the measured artifacts.
