# BitLisp Cost Model

Status: Phase 1 in progress. This table is normative for the evaluator
core and for every operator family listed as implemented at the head
of VM.md section 4. It inherits the
CLVM cost table for the operator intersection, verified against the
pinned oracles by the diff harness. The weight mapping is filled with
Phase 3 measurements.

## 1. General rules

- Cost accrues as evaluation proceeds and is checked against the
  budget at every charge. The budget is inclusive (see VM.md 3.3).
- **Dispatch cost.** Every operator application except quote charges
  1 in addition to the operator's own cost. This includes apply and
  the reserved empty-atom operator. The constant is implicit in both
  CLVM implementations and was pinned empirically. It is charged at
  operator identification, before any argument evaluates. Apply's 90
  accrues later, after both of its arguments have evaluated, and
  without an immediate budget check: the check rides on the applied
  program's first charge, so a pre-charge failure inside the applied
  program is reported first. Pinned by boundary vectors.
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
  - `>s`, `strlen`, `substr`: arity check first, then every argument
    check in argument order (`substr`: the data atom check, then each
    index's four-byte atom check, then the bounds check), then one
    checked charge of the operator's full cost, malloc included for
    `strlen`. Every check wins over `cost_exceeded`, pinned by
    boundary vectors.
  - `concat`: the base cost accrues without a budget check. Then per
    argument, in list order: that argument's atom check, then one
    checked charge of everything accrued so far plus that argument's
    `CONCAT_COST_PER_ARG` and per-byte cost. With no arguments the
    base cost is checked at completion. A pair in the first argument
    is therefore reported even when the base cost alone would burst
    the budget, and a pair in a later argument only after every
    earlier argument's charge fits, pinned by boundary vectors.
  - `logand`, `logior`, `logxor`: the same loop shape as `+` with the
    log constants. The base cost accrues without a budget check, then
    per argument, in list order: the argument's atom check, then one
    checked charge of everything accrued so far plus that argument's
    `LOG_COST_PER_ARG` and per-byte cost. With no arguments the base
    cost is checked at the end. Malloc last. A pair in the second
    argument is therefore reported only after the base cost and the
    first argument's charge fit the budget, pinned at the exact
    boundary by vectors.
  - `lognot`: arity check, then the atom check, then one checked
    charge of base plus per-byte cost, then malloc. Both checks win
    over `cost_exceeded`.
  - `ash`, `lsh`: every check precedes every charge, in this order:
    arity, the value's atom check, the count's shape check (atom of
    at most four bytes), the count's range check (magnitude at most
    65535). Then one checked charge of the full formula, then malloc.
    A pair value is reported before any count defect, and every check
    wins over `cost_exceeded`, pinned by boundary vectors.
  - `not`, `any`, `all`: arity check (`not` only), then one checked
    charge of the operator's full cost. There are no argument checks:
    pairs are legal boolean arguments. No malloc, the results are the
    shared TRUE and nil constants.
  - `sha256`: the same loop shape as `concat`. The base cost accrues
    without a budget check, then per argument, in list order: that
    argument's atom check, then one checked charge of everything
    accrued so far plus that argument's `SHA256_COST_PER_ARG` and
    per-byte cost. With no arguments the base cost is checked at
    completion. The result's malloc is one final charge after the
    loop. A pair in the first argument is therefore reported even
    when the base cost alone would burst the budget, and a pair in a
    later argument only after every earlier argument's charge fits,
    pinned at the exact boundary by vectors.
  - `secp_verify`: every check precedes the single flat charge, in
    this order: arity, then each argument's atom check in argument
    order, then each argument's shape check in argument order
    (pubkey width, message width, signature width). The
    empty-signature branch and the verification work come after the
    charge. A shape defect therefore wins over `cost_exceeded`, and
    neither the empty-signature nil nor a verification outcome is
    ever reported when the budget cannot cover the charge, pinned by
    boundary vectors.
- Evaluation cost does not include deserialization. A per-byte cost on
  the serialized program belongs to the weight mapping (section 9).

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

The raise operator `x` has no cost of its own. The dispatch cost is
charged at operator identification, each argument charges its own
costs as it evaluates, and the raise follows with no further charge,
so a budget burst by any of those charges reports `cost_exceeded`
rather than `user_raise`. Pinned by boundary vectors.

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

## 5. Bytes and strings family

| Operator | Formula |
| --- | --- |
| `>s` | `117 + 1 * total_arg_bytes`, no malloc, the same constants as `=` |
| `substr` | `1`, no malloc: the result is a portion of an existing atom |
| `strlen` | `173 + 1 * arg_bytes + malloc(result)` |
| `concat` | `142 + 135 * n_args + 13 * total_arg_bytes`, no separate result malloc |

`concat`'s 13 per byte is its own `CONCAT_COST_PER_BYTE = 3` plus
`MALLOC_COST_PER_BYTE = 10`: the result atom's malloc is charged per
input byte inside the argument loop rather than on the freshly built
result, and a nil argument contributes only the per-argument 135.
The totals agree with charging malloc on the result, the interleaving
(section 1) does not.

`substr`'s flat cost is safe only under a shared-bytes result
representation. The consensus oracle returns a view into the parent
atom, doing constant work per slice, and the cost models that. An
implementation that copies on slice does work proportional to the
result while charging a cost that does not grow with it, and a
program can repeat large slices of one large atom until the copying
dwarfs the budget, a validation denial of service. A hardened
implementation must therefore slice by reference. The Python
reference copies, which is acceptable in a spec artifact that never
validates adversarial input, and any consensus-facing implementation
must not inherit that shortcut.

Worked example, pinned by vectors: `(concat (q . "ab") (q . "cd"))`
costs `20 + 20 + 1 + 142 + 135 * 2 + 13 * 4 = 505`.

## 6. Bitwise family

| Operator | Formula |
| --- | --- |
| `logand`, `logior`, `logxor` | `100 + 264 * n_args + 3 * total_arg_bytes + malloc(result)` |
| `lognot` | `331 + 3 * arg_bytes + malloc(result)` |
| `ash` | `596 + 3 * (value_bytes + result_magnitude_bytes) + malloc(result)` |
| `lsh` | `277 + 3 * (value_bytes + result_magnitude_bytes) + malloc(result)` |

Per-byte terms count argument atoms at their actual length, redundant
encoding bytes included, like everywhere else. The shifts are the
exception on the result side: their per-byte term counts the result's
*magnitude* byte length (`ceil(bit_length / 8)`), one less than the
minimal signed encoding when the top magnitude bit is set, exactly
the accumulator rule `*` has. A result of 128 counts one magnitude
byte there while its malloc charges the two bytes of `0x0080`. The
shift count atom's length never enters the cost. Pinned by vectors.

Worked examples, pinned by vectors: `(ash (q . 1) (q . 7))` costs
`20 + 20 + 1 + 596 + 3 * (1 + 1) + 20 = 663`, and
`(logand (q . 15) (q . 3))` costs
`20 + 20 + 1 + 100 + 264 * 2 + 3 * 2 + 10 = 685`.

## 7. Boolean family

| Operator | Formula |
| --- | --- |
| `not` | `200`, flat |
| `any`, `all` | `200 + 300 * n_args` |

No boolean op charges malloc (the results are the shared TRUE and nil
constants) and no boolean cost has a per-byte term: `not`'s cost has
no per-argument term either, its 200 is the whole cost. Pair
arguments are legal and charge the same as atoms.

Worked example, pinned by vectors: `(any (q . 1) (q . 2))` costs
`20 + 20 + 1 + 200 + 300 * 2 = 841`.

## 8. Crypto family

| Operator | Formula |
| --- | --- |
| `sha256` | `87 + 134 * n_args + 2 * total_arg_bytes + malloc(result)` |
| `secp_verify` | `1300000`, flat, no malloc (PROVISIONAL) |

The sha256 result atom is always exactly 32 bytes, so its malloc is a
flat 320 charged after the argument loop. Per-byte terms count
argument atoms at their actual length, redundant encoding bytes
included, like everywhere else, and the hashed bytes are exactly the
costed bytes.

`secp_verify` has no per-byte term because every argument width is
fixed by its shape checks, and no malloc because every result is a
shared constant. The constant is PROVISIONAL: the operator has no
CLVM oracle to inherit from, so the value adopts the magnitude of the
consensus oracle's ECDSA verify pending the Phase 3 measurement
recorded in VM.md section 8. The empty-signature branch charges the
same flat cost in v0, with a cheaper price explicitly left as a
Phase 3 question there.

Worked examples, pinned by vectors: `(sha256 (q . "ab") (q . "cd"))`
costs `20 + 20 + 1 + 87 + 134 * 2 + 2 * 4 + 320 = 724`, and a
`secp_verify` application on three quoted arguments costs
`20 * 3 + 1 + 1300000 = 1300061` when it returns, the same total for
a valid signature and for an empty one. The failing path charges
identically before it raises `secp_verify_failed`.

## 9. Weight mapping

TODO (Phase 3): mapping from VM cost units to Bitcoin transaction
weight, derived from benchmark data on the measured artifacts,
including the per-byte cost of the serialized program itself.

## 10. Condition costs

TODO (Phase 2): per-condition base costs and the superlinear
`CREATE_COIN` schedule.
