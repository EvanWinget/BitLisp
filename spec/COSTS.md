# BitLisp Cost Model

Status: Phase 1 in progress. This table is normative for the evaluator
core and the arithmetic family. It inherits the CLVM cost table for the
operator intersection, verified against the pinned oracles by the diff
harness. The weight mapping is filled with Phase 3 measurements.

## 1. General rules

- Cost accrues as evaluation proceeds and is checked against the
  budget at every charge. The budget is inclusive (see VM.md 3.3).
- **Dispatch cost.** Every operator application except quote charges
  1 in addition to the operator's own cost. This includes apply. The
  constant is implicit in both CLVM implementations and was pinned
  empirically, nested applications charge it once per application.
- **Malloc cost.** Operators that return freshly built atoms charge
  `MALLOC_COST_PER_BYTE = 10` per byte of each result atom. Operators
  that return shared constants (TRUE, nil) or existing nodes charge no
  malloc. Building a pair (divmod's result) charges no malloc beyond
  the two atoms.
- Per-byte argument costs count the argument atom's actual byte
  length, including redundant integer encoding bytes.
- Evaluation cost does not include deserialization. A per-byte cost on
  the serialized program belongs to the weight mapping (section 4).

## 2. Core evaluation costs

| Constant | Value | Charged for |
| --- | --- | --- |
| `QUOTE_COST` | 20 | Each quote (no dispatch cost) |
| `APPLY_COST` | 90 | Each apply (plus dispatch cost 1) |
| `OP_DISPATCH_COST` | 1 | Every non-quote operator application |
| `PATH_LOOKUP_BASE_COST` | 40 | Each path lookup |
| `PATH_LOOKUP_COST_PER_LEG` | 4 | Times `max(1, bit_length(path))` |
| `PATH_LOOKUP_COST_PER_ZERO_BYTE` | 4 | Per leading zero byte of the path atom |
| `MALLOC_COST_PER_BYTE` | 10 | Per byte of freshly built result atoms |

## 3. Arithmetic family

| Operator | Formula |
| --- | --- |
| `+`, `-` | `99 + 320 * n_args + 3 * total_arg_bytes + malloc(result)` |
| `*` | `92 + sum over steps + malloc(result)`, one step per argument after the first: `885 + 6 * (len(acc) + len(arg)) + (len(acc) * len(arg)) / 128` (integer division), where `len(acc)` is the minimal byte length of the accumulated product and `len(arg)` the argument atom's actual length |
| `/` | `988 + 4 * total_arg_bytes + malloc(quotient)` |
| `divmod` | `1116 + 6 * total_arg_bytes + malloc(quotient) + malloc(remainder)` |
| `>` | `498 + 2 * total_arg_bytes`, no malloc |

Worked example, pinned by vectors: `(+ (q . 2) (q . 3))` costs
`20 + 20 + 99 + 320 * 2 + 3 * 2 + 10 + 1 = 796`.

## 4. Weight mapping

TODO (Phase 3): mapping from VM cost units to Bitcoin transaction
weight, derived from benchmark data on the measured artifacts,
including the per-byte cost of the serialized program itself.

## 5. Condition costs

TODO (Phase 2): per-condition base costs and the superlinear
`CREATE_COIN` schedule.
