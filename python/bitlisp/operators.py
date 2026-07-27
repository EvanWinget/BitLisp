"""The operator table: tree ops, arithmetic, and bytes families.

Each operator takes the evaluated argument list and the machine's
charge callback, and returns the result node. The machine charges
OP_DISPATCH_COST before the operator runs. Quote and apply never reach
this table, the machine handles both.

The interleaving of argument validation, charges, and value checks is
consensus-visible: near the budget boundary it decides which of
cost_exceeded, wrong_arg_count, arg_not_atom, arg_not_pair, and
div_by_zero is reported. Every function below performs them in the
consensus oracle's order, and the boundary cases are pinned by
vectors.
"""

from . import costs
from .errors import BitLispError
from .sexp import NIL, TRUE, atom_to_int, int_to_atom, is_atom, is_pair


def _int_arg(arg, op_name, max_bytes=None):
    if not is_atom(arg):
        raise BitLispError("arg_not_atom", f"{op_name} requires int args")
    # The limit is on the atom's length as given, redundant encoding
    # bytes included, and only on operands as supplied: intermediate
    # values (a multiplication accumulator) are never limited.
    if max_bytes is not None and len(arg) > max_bytes:
        raise BitLispError(
            "arg_too_long", f"{op_name} operand exceeds {max_bytes} bytes"
        )
    return atom_to_int(arg)


# Consensus operand size limits. Multiplication limits every operand,
# division limits the numerator and, more loosely, the divisor.
# Addition, subtraction, and comparison are unlimited.
MUL_OPERAND_MAX_BYTES = 256
DIV_NUMERATOR_MAX_BYTES = 256
DIV_DIVISOR_MAX_BYTES = 1024


def _exactly(args, count, op_name):
    if len(args) != count:
        raise BitLispError(
            "wrong_arg_count", f"{op_name} takes exactly {count} arguments"
        )


def _malloc(charge, atom):
    charge(costs.MALLOC_COST_PER_BYTE * len(atom))


def op_if(args, charge):
    # All three arguments were evaluated before dispatch reached this
    # table: there is no lazy branch. nil is the only false value, the
    # one-byte atom 0x00 and every pair select the second argument.
    _exactly(args, 3, "i")
    charge(costs.IF_COST)
    return args[2] if args[0] == NIL else args[1]


def op_cons(args, charge):
    _exactly(args, 2, "c")
    # The freshly built pair is never malloc-charged, only freshly
    # built atoms are, and both children here are existing nodes.
    charge(costs.CONS_COST)
    return (args[0], args[1])


def _pair_arg(args, op_name, noun):
    _exactly(args, 1, op_name)
    if not is_pair(args[0]):
        raise BitLispError("arg_not_pair", f"{noun} of non-cons")
    return args[0]


def op_first(args, charge):
    # The pair check precedes the charge: an atom argument is reported
    # even when the budget is already spent.
    pair = _pair_arg(args, "f", "first")
    charge(costs.FIRST_COST)
    return pair[0]


def op_rest(args, charge):
    pair = _pair_arg(args, "r", "rest")
    charge(costs.REST_COST)
    return pair[1]


def op_listp(args, charge):
    _exactly(args, 1, "l")
    charge(costs.LISTP_COST)
    return TRUE if is_pair(args[0]) else NIL


def op_eq(args, charge):
    _exactly(args, 2, "=")
    # Both atom checks precede the single charge. The comparison is on
    # raw bytes: redundantly encoded integers are distinct values, and
    # there is no operand size limit.
    for arg in args:
        if not is_atom(arg):
            raise BitLispError("arg_not_atom", "= used on list")
    charge(costs.EQ_BASE_COST + costs.EQ_COST_PER_BYTE * (len(args[0]) + len(args[1])))
    return TRUE if args[0] == args[1] else NIL


def op_add(args, charge):
    # The base cost accrues without a budget check: it is checked
    # together with the first argument's charge, after that argument's
    # atom check. A pair in the first argument therefore wins over
    # cost_exceeded even when the base cost alone would burst the
    # budget. The subtraction loop below interleaves differently, the
    # consensus oracle implements the two separately and the
    # difference is observable near the budget boundary.
    unchecked = costs.ARITH_BASE_COST
    total = 0
    for arg in args:
        value = _int_arg(arg, "+")
        charge(
            unchecked + costs.ARITH_COST_PER_ARG + costs.ARITH_COST_PER_BYTE * len(arg)
        )
        unchecked = 0
        total += value
    charge(unchecked)
    result = int_to_atom(total)
    _malloc(charge, result)
    return result


def op_sub(args, charge):
    # Unlike op_add, every charge precedes its argument's atom check:
    # base plus per-arg cost before the first argument, then per-arg
    # plus the previous argument's byte cost before each subsequent
    # one, with the last argument's byte cost charged at the end.
    # Totals match op_add exactly, the interleaving does not.
    if not args:
        charge(costs.ARITH_BASE_COST)
        result = int_to_atom(0)
        _malloc(charge, result)
        return result
    total = 0
    pending = costs.ARITH_BASE_COST
    previous_bytes = 0
    for index, arg in enumerate(args):
        charge(
            pending
            + costs.ARITH_COST_PER_ARG
            + costs.ARITH_COST_PER_BYTE * previous_bytes
        )
        pending = 0
        value = _int_arg(arg, "-")
        total = value if index == 0 else total - value
        previous_bytes = len(arg)
    charge(costs.ARITH_COST_PER_BYTE * previous_bytes)
    result = int_to_atom(total)
    _malloc(charge, result)
    return result


def op_mul(args, charge):
    # The first argument's atom check precedes any charge, and each
    # later argument's atom check precedes its own step's charge, with
    # the base cost riding along on the first step. A pair in the
    # second argument therefore wins over cost_exceeded, a pair in
    # the third does not unless the first step's charge fits.
    if not args:
        charge(costs.MUL_BASE_COST)
        result = TRUE
        _malloc(charge, result)
        return result
    acc = _int_arg(args[0], "*", MUL_OPERAND_MAX_BYTES)
    # Step costs count the incoming argument atom's actual length,
    # redundant bytes included, but the accumulator's MAGNITUDE byte
    # length, which is one less than its minimal signed encoding when
    # the top magnitude bit is set (128 counts 1 byte, not 2).
    acc_len = len(args[0])
    pending = costs.MUL_BASE_COST
    for arg in args[1:]:
        value = _int_arg(arg, "*", MUL_OPERAND_MAX_BYTES)
        charge(
            pending
            + costs.MUL_COST_PER_OP
            + costs.MUL_LINEAR_COST_PER_BYTE * (acc_len + len(arg))
            + (acc_len * len(arg)) // costs.MUL_SQUARE_COST_PER_BYTE_DIVIDER
        )
        pending = 0
        acc *= value
        acc_len = (acc.bit_length() + 7) // 8
    charge(pending)
    result = int_to_atom(acc)
    _malloc(charge, result)
    return result


def _div_args(args, charge, op_name, base_cost, cost_per_byte):
    _exactly(args, 2, op_name)
    # Both atom checks precede both size checks: a pair in either
    # argument is reported before an oversized operand, unlike
    # multiplication where each argument's checks happen together.
    numerator = _int_arg(args[0], op_name)
    divisor = _int_arg(args[1], op_name)
    for arg, limit in (
        (args[0], DIV_NUMERATOR_MAX_BYTES),
        (args[1], DIV_DIVISOR_MAX_BYTES),
    ):
        if len(arg) > limit:
            raise BitLispError(
                "arg_too_long", f"{op_name} operand exceeds {limit} bytes"
            )
    charge(base_cost + cost_per_byte * (len(args[0]) + len(args[1])))
    # After the charge, so div_by_zero is reported only if the base
    # cost fits the budget.
    if divisor == 0:
        raise BitLispError("div_by_zero", f"{op_name} with 0")
    return numerator, divisor


def op_div(args, charge):
    numerator, divisor = _div_args(
        args, charge, "/", costs.DIV_BASE_COST, costs.DIV_COST_PER_BYTE
    )
    result = int_to_atom(numerator // divisor)
    _malloc(charge, result)
    return result


def op_divmod(args, charge):
    numerator, divisor = _div_args(
        args, charge, "divmod", costs.DIVMOD_BASE_COST, costs.DIVMOD_COST_PER_BYTE
    )
    quotient, remainder = divmod(numerator, divisor)
    q_atom, r_atom = int_to_atom(quotient), int_to_atom(remainder)
    _malloc(charge, q_atom)
    _malloc(charge, r_atom)
    return (q_atom, r_atom)


def op_gr(args, charge):
    _exactly(args, 2, ">")
    left = _int_arg(args[0], ">")
    right = _int_arg(args[1], ">")
    charge(costs.GR_BASE_COST + costs.GR_COST_PER_BYTE * (len(args[0]) + len(args[1])))
    return TRUE if left > right else NIL


def op_grs(args, charge):
    _exactly(args, 2, ">s")
    # Both atom checks precede the single charge, like =. Python bytes
    # comparison is exactly the consensus rule: unsigned lexicographic,
    # a proper prefix less than the longer string.
    for arg in args:
        if not is_atom(arg):
            raise BitLispError("arg_not_atom", ">s used on list")
    charge(
        costs.GRS_BASE_COST + costs.GRS_COST_PER_BYTE * (len(args[0]) + len(args[1]))
    )
    return TRUE if args[0] > args[1] else NIL


# A substr index atom is capped at four bytes. Within the cap its
# value is the ordinary signed big-endian reading, leading zero bytes
# included: 0x0000ffff is 65535 where 0xffff is -1.
INDEX_MAX_BYTES = 4


def _index_arg(arg, op_name):
    # A pair index and an oversized index atom share one error class,
    # matching the consensus oracle, which reports both identically.
    if not is_atom(arg) or len(arg) > INDEX_MAX_BYTES:
        raise BitLispError(
            "bad_index", f"{op_name} index must be an atom of at most 4 bytes"
        )
    return atom_to_int(arg)


def op_substr(args, charge):
    if len(args) not in (2, 3):
        raise BitLispError("wrong_arg_count", "substr takes 2 or 3 arguments")
    data = args[0]
    if not is_atom(data):
        raise BitLispError("arg_not_atom", "substr requires an atom")
    start = _index_arg(args[1], "substr")
    end = _index_arg(args[2], "substr") if len(args) == 3 else len(data)
    if start < 0 or end < 0 or end > len(data) or end < start:
        raise BitLispError("index_out_of_range", "invalid indices for substr")
    # Every check precedes the flat charge. The result is a portion of
    # an existing atom and charges no malloc.
    charge(costs.SUBSTR_COST)
    return data[start:end]


def op_strlen(args, charge):
    _exactly(args, 1, "strlen")
    if not is_atom(args[0]):
        raise BitLispError("arg_not_atom", "strlen requires an atom")
    result = int_to_atom(len(args[0]))
    # One checked charge with the malloc folded in, after the checks.
    charge(
        costs.STRLEN_BASE_COST
        + costs.STRLEN_COST_PER_BYTE * len(args[0])
        + costs.MALLOC_COST_PER_BYTE * len(result)
    )
    return result


def op_concat(args, charge):
    # The base cost accrues without a budget check, riding on the
    # first argument's charge like op_add's. Each argument's atom
    # check precedes its own charge, so a pair in the first argument
    # wins over cost_exceeded and a pair in a later argument loses to
    # an earlier argument's charge. The result's malloc is charged per
    # input byte inside the loop, never on the joined result.
    pending = costs.CONCAT_BASE_COST
    pieces = []
    for arg in args:
        if not is_atom(arg):
            raise BitLispError("arg_not_atom", "concat on list")
        charge(
            pending
            + costs.CONCAT_COST_PER_ARG
            + (costs.CONCAT_COST_PER_BYTE + costs.MALLOC_COST_PER_BYTE) * len(arg)
        )
        pending = 0
        pieces.append(arg)
    charge(pending)
    return b"".join(pieces)


def op_raise(args, charge):
    raise BitLispError("user_raise", "clvm raise")


OPERATORS = {
    b"\x03": op_if,
    b"\x04": op_cons,
    b"\x05": op_first,
    b"\x06": op_rest,
    b"\x07": op_listp,
    b"\x08": op_raise,
    b"\x09": op_eq,
    b"\x0a": op_grs,
    b"\x0c": op_substr,
    b"\x0d": op_strlen,
    b"\x0e": op_concat,
    b"\x10": op_add,
    b"\x11": op_sub,
    b"\x12": op_mul,
    b"\x13": op_div,
    b"\x14": op_divmod,
    b"\x15": op_gr,
}
