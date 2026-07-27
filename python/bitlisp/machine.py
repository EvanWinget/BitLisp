"""The evaluator.

Explicit task stack on purpose: program depth must not be limited by
the Python recursion limit.
"""

from . import costs
from .errors import BitLispError
from .operators import OPERATORS
from .serialize import deserialize, serialize
from .sexp import NIL, is_atom, is_pair, iter_proper_list

QUOTE = b"\x01"
APPLY = b"\x02"

_EVAL, _APPLY_OP, _APPLY_PROGRAM = 0, 1, 2


def run(program, env, max_cost):
    """Evaluates program against env. Returns (cost, result node).

    Raises BitLispError with a code from errors.CODES.
    """
    cost = 0

    def charge(amount):
        nonlocal cost
        cost += amount
        if cost > max_cost:
            raise BitLispError("cost_exceeded", "cost exceeded")

    def accrue(amount):
        # Adds cost without checking the budget. The check rides on
        # the next charge, so an uncharged error raised in between
        # wins over cost_exceeded, matching the consensus oracle.
        nonlocal cost
        cost += amount

    values = []
    tasks = [(_EVAL, program, env)]
    while tasks:
        task = tasks.pop()
        kind = task[0]
        if kind == _EVAL:
            _, node, current_env = task
            if is_atom(node):
                values.append(_path_lookup(node, current_env, charge))
                continue
            op, args = node
            if is_pair(op):
                raise BitLispError("operator_not_atom", "pair in operator position")
            if op == QUOTE:
                charge(costs.QUOTE_COST)
                values.append(args)
                continue
            # The proper-list walk precedes every charge for this
            # application, then unknown operators are rejected
            # uncharged (a recorded divergence, CLVM accepts them).
            # Everything else, the reserved empty atom included,
            # charges the dispatch cost now, before any argument
            # evaluates.
            arg_list = list(iter_proper_list(args))
            if op != APPLY and op not in OPERATORS and op != NIL:
                raise BitLispError("unknown_operator", f"unknown operator {op.hex()}")
            charge(costs.OP_DISPATCH_COST)
            if op == APPLY:
                tasks.append((_APPLY_PROGRAM, len(arg_list)))
            else:
                tasks.append((_APPLY_OP, op, len(arg_list)))
            # Arguments evaluate right to left, the CLVM stack-machine
            # order, observable through which failing argument reports
            # its error. The task stack pops in reverse append order,
            # so appending in list order makes the rightmost argument
            # evaluate first.
            for arg in arg_list:
                tasks.append((_EVAL, arg, current_env))
        elif kind == _APPLY_OP:
            _, op, arg_count = task
            # Rightmost argument completed first, so the value stack
            # holds the arguments in reverse. Application-time errors
            # come only after every argument evaluated: the reserved
            # operator raises here, not at identification.
            args = values[len(values) - arg_count :][::-1]
            del values[len(values) - arg_count :]
            if op == NIL:
                raise BitLispError("reserved_operator", "reserved operator")
            values.append(OPERATORS[op](args, charge))
        else:
            _, arg_count = task
            if arg_count != 2:
                del values[len(values) - arg_count :]
                raise BitLispError("wrong_arg_count", "apply takes 2 arguments")
            # Right-to-left evaluation: the program result is on top.
            new_program = values.pop()
            new_env = values.pop()
            # The apply cost is checked only at the applied program's
            # first charge: its pre-charge failures (a path walk into
            # an atom, an improper argument list) are reported even
            # when the budget is already burst.
            accrue(costs.APPLY_COST)
            tasks.append((_EVAL, new_program, new_env))
    return cost, values[0]


def _path_lookup(path, env, charge):
    """Walks the path bits into env, low bit first after the top bit.

    Zero steps to nil, bit 0 steps left, bit 1 steps right. The cost
    formula counts every bit including the top marker bit (minimum
    one leg) plus each leading zero byte of the path atom.
    """
    zero_bytes = 0
    for byte in path:
        if byte:
            break
        zero_bytes += 1
    index = int.from_bytes(path, "big")
    # The walk precedes the charge: path_into_atom wins over
    # cost_exceeded regardless of the remaining budget, matching the
    # consensus oracle.
    node = NIL
    if index:
        node = env
        for bit in range(index.bit_length() - 1):
            if is_atom(node):
                raise BitLispError("path_into_atom", "path into atom")
            node = node[0] if (index >> bit) & 1 == 0 else node[1]
    charge(
        costs.PATH_LOOKUP_BASE_COST
        + costs.PATH_LOOKUP_COST_PER_LEG * max(1, index.bit_length())
        + costs.PATH_LOOKUP_COST_PER_ZERO_BYTE * zero_bytes
    )
    return node


def run_serialized(program_bytes, env_bytes, max_cost):
    """Deserializes strictly, runs, reserializes the result."""
    program = deserialize(program_bytes)
    env = deserialize(env_bytes)
    cost, result = run(program, env, max_cost)
    return cost, serialize(result)
