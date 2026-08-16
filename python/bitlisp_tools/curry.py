"""Currying: fixing argument values into a program to make a new
program, and reading them back out.

curry wraps a program tree and fixed values into

    (a (q . program) (c (q . value1) (c (q . value2) ... 1)))

a program that applies the quoted original to an environment
holding the quoted fixed values in front of whatever environment
the curried program itself receives. Each value is quoted, so it is
committed data the environment cannot rewrite, and the chain ends
in the environment root path 1, so the received environment becomes
the tail. The shape is byte-for-byte the one Chialisp tooling
builds, so a curried program keeps one identity across ecosystems.

uncurry inverts the shape. It returns (inner program, fixed values)
on an exact match and (program, None) on anything else, so a curry
of zero values, which is valid, stays distinguishable from a
program that is not a curry at all.
"""

from bitlisp.sexp import NIL, is_pair

from .compiler import _APPLY, _CONS, _QUOTE, _proper_list, _quote

# The path to the whole environment, terminating the value chain.
_ENV_ROOT = b"\x01"


def curry(program, values):
    """The program with the values fixed in front, a new program
    tree. The first value lands first in the wrapped program's
    environment."""
    core = _ENV_ROOT
    for value in reversed(list(values)):
        core = _proper_list(_CONS, _quote(value), core)
    return _proper_list(_APPLY, _quote(program), core)


def uncurry(program):
    """The inner program and the list of fixed values, or
    (program, None) when the tree is not exactly the curried shape.
    A curry of zero values returns (inner, []), a different answer
    from not curried."""
    parts = _operands(program, _APPLY)
    if parts is None:
        return program, None
    quoted, core = parts
    inner = _unquote(quoted)
    if inner is None:
        return program, None
    values = []
    while core != _ENV_ROOT:
        parts = _operands(core, _CONS)
        if parts is None:
            return program, None
        quoted, core = parts
        value = _unquote(quoted)
        if value is None:
            return program, None
        values.append(value)
    return inner, values


def _operands(node, operator):
    """The two operands of an exactly-two-operand application of
    the operator, or None. A third operand, an improper tail, or a
    different head all decline."""
    if not is_pair(node) or node[0] != operator:
        return None
    rest = node[1]
    if not is_pair(rest):
        return None
    tail = rest[1]
    if not is_pair(tail) or tail[1] != NIL:
        return None
    return rest[0], tail[0]


def _unquote(node):
    """The quoted value, or None when the node is not a quote
    pair. A quoted nil is b"", so callers test against None."""
    if not is_pair(node) or node[0] != _QUOTE:
        return None
    return node[1]
