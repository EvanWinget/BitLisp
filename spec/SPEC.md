# BitLisp Architecture

Status: stub. Filled in across Phases 1 and 2. Nothing normative yet.

This document specifies how a BitLisp program is committed to on chain and
how a spend supplies it: the taproot leaf version, the commitment scheme,
and the witness structure. Evaluator semantics live in [VM.md](VM.md),
the condition vocabulary in [CONDITIONS.md](CONDITIONS.md), transaction
condition validation in [VALIDATION.md](VALIDATION.md), and the cost model in
[COSTS.md](COSTS.md).

## 1. Overview

TODO: one-page architecture. Program committed in the output,
witness arguments supplied in the witness, evaluation yields a
condition list, conditions are matched against the transaction context.

## 2. Leaf version and commitment

TODO: new tapleaf version number, program hash commitment scheme, whether
standard-layer shorthands are part of the commitment scheme (Phase 4
experiment feeds this).

## 3. Witness structure

TODO: serialized program + witness-arguments layout, size limits, currying
discipline.

## 4. Validation pipeline

TODO: deserialize, evaluate under cost budget, parse condition list,
match against transaction. Each stage's failure modes are enumerated and
every failure mode has a vector.
