# BitLisp Cost Model

Status: Phase 1 in progress. This table is normative for the evaluator
core, the tree ops family, and the arithmetic family. It inherits the CLVM cost table for the
operator intersection, verified against the pinned oracles by the diff
harness. The weight mapping is filled with Phase 3 measurements.

## 1. General rules

- Cost accrues as evaluation proceeds and is checked against the
  budget at every charge. The budget is inclusive (see VM.md 3.3).
- **Dispatch cost.** Every operator application except quote charges
  1 in addition to the operator's own cost. This includes apply and
  the reserved empty-atom operator. The constant is implicit in both
  CLVM implementations and was pinned empirically. It is charged at
  operator identification, before any argument evaluates. Apply's 90
  is charged later, after both of its arguments have evaluated.
- **Malloc cost.** Operators that return freshly built atoms charge
  `MALLOC_COST_PER_BYTE = 10` per byte of each result atom. Operators
  that return shared constants (TRUE, nil) or existing nodes charge no
  malloc. Building a pair (`c`'s result, divmod's result) charges no
  malloc beyond any freshly built atoms inside it.
- Per-byte argument costs count the argument atom's actual byte
  length, including redundant integer encoding bytes.
- **Charge order is consensus-visible.** Near the budget boundary,
  which of `cost_exceeded` and an operator error fires depends on the
  order of charges, checks, and argument validation. The order,
  matching the consensus oracle and pinned by vectors:
  - `+`: the base cost accrues without a budget check. Then per
    argument, in list order: the argument's atom check, then one
    checked charge of everything accrued so far plus that argument's
    `ARITH_COST_PER_ARG` and per-byte cost. With no arguments the
    base cost is checked at the end. Malloc last. A pair in the first
    argument is therefore reported even when the base cost alone
    would burst the budget.
  - `-`: same constants, different loop. One checked charge of base
    plus `ARITH_COST_PER_ARG` before the first argument's atom check,
    then per subsequent argument one checked charge of
    `ARITH_COST_PER_ARG` plus the *previous* argument's per-byte
    cost before that argument's atom check, then a final charge of
    the last argument's per-byte cost, then malloc. Totals equal
    `+` exactly, the interleaving does not. The consensus oracle
    implements the two loops differently and the difference is
    observable, so it is specified.
  - `*`: the first argument's atom check happens before any charge.
    Then per subsequent argument, in order: that argument's atom
    check, then one checked charge of the step cost (the base cost
    rides along with the first step's charge). With zero or one
    argument the base cost is charged after the checks. Malloc last.
    A pair in the second argument is therefore reported before the
    base cost is checked, a pair in the third only after the first
    step's charge fits the budget.
  - `/`, `divmod`, `>`: arity check, then both atom checks, then one
    checked charge of base plus per-byte cost, then the zero-divisor
    check where applicable, then malloc. Division by zero is reported
    only if the base charge fits the budget.
  - The operand size limits (VM.md section 4) precede every charge.
    For `*` they ride with each argument's atom check. For `/` and
    `divmod` they run after both atom checks and before the base
    charge.
  - `i`, `c`, `f`, `r`, `l`, `=`: arity check first, then the node
    checks (`f` and `r` require a pair, `=` checks both arguments for
    atomness), then one checked charge of the operator's full cost.
    Every check therefore wins over `cost_exceeded` when both would
    fire, pinned by boundary vectors.
- Evaluation cost does not include deserialization. A per-byte cost on
  the serialized program belongs to the weight mapping (section 5).

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

## 3. Tree ops family

No tree op charges malloc.

| Operator | Formula |
| --- | --- |
| `i` | `33`, returns the selected argument node |
| `c` | `50`, the pair itself is not malloc-charged |
| `f`, `r` | `30`, returns an existing node |
| `l` | `19` |
| `=` | `117 + 1 * total_arg_bytes`, no operand size limit |

Worked example, pinned by vectors: `(= (q . 1) (q . 1))` costs
`20 + 20 + 1 + 117 + 2 = 160`.

## 4. Arithmetic family

| Operator | Formula |
| --- | --- |
| `+`, `-` | `99 + 320 * n_args + 3 * total_arg_bytes + malloc(result)` |
| `*` | `92 + sum over steps + malloc(result)`, one step per argument after the first: `885 + 6 * (len(acc) + len(arg)) + (len(acc) * len(arg)) / 128` (integer division). `len(arg)` is the argument atom's actual length. For the first step `len(acc)` is the first argument atom's actual length, afterwards it is the accumulated product's *magnitude* byte length (`ceil(bit_length / 8)`), one less than the minimal signed encoding when the top magnitude bit is set: an accumulator of 128 counts 1 byte. Pinned by vectors. |
| `/` | `988 + 4 * total_arg_bytes + malloc(quotient)` |
| `divmod` | `1116 + 6 * total_arg_bytes + malloc(quotient) + malloc(remainder)` |
| `>` | `498 + 2 * total_arg_bytes`, no malloc |

Worked example, pinned by vectors: `(+ (q . 2) (q . 3))` costs
`20 + 20 + 99 + 320 * 2 + 3 * 2 + 10 + 1 = 796`.

## 5. Weight mapping

TODO (Phase 3): mapping from VM cost units to Bitcoin transaction
weight, derived from benchmark data on the measured artifacts,
including the per-byte cost of the serialized program itself.

## 6. Condition costs

TODO (Phase 2): per-condition base costs and the superlinear
`CREATE_COIN` schedule.
