"""Curry tests: shape pins, compile-and-run behavior of curried
programs, the strict uncurry contract, round-trip properties, and
the differential checks against the chia_rs wheel."""

import sys
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

try:
    import chia_rs
except ImportError:
    chia_rs = None

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from bitlisp import deserialize, run, serialize  # noqa: E402
from bitlisp.sexp import NIL  # noqa: E402
from bitlisp_tools import (  # noqa: E402
    assemble,
    curry,
    disassemble,
    tree_hash,
    uncurry,
)
from bitlisp_tools.compiler import compile_program  # noqa: E402

BUDGET = 11_000_000_000

# The whole-environment path as a program: evaluating it returns
# the environment itself, making argument placement visible.
_ENV_PROGRAM = b"\x01"


# Shape pins.


def test_pin_the_curried_shape():
    curried = curry(assemble("(+ 2 5)"), [assemble("10")])
    assert disassemble(curried) == "(a (q 16 2 5) (c (q . 10) 1))"
    assert serialize(curried).hex() == "ff02ffff01ff10ff02ff0580ffff04ffff010aff018080"


def test_pin_against_chia_rs_bytes():
    # The serialization chia_rs's clvm-utils crate pins for
    # currying the atom "xyz" with the atoms "a", "b", "c", so the
    # shape is byte-identical across ecosystems.
    curried = curry(b"xyz", [b"a", b"b", b"c"])
    assert serialize(curried).hex() == (
        "ff02ffff018378797affff04ffff0161ffff04ffff0162ffff04ffff0163ff0180808080"
    )


def test_zero_value_curry_shape():
    curried = curry(assemble("(+ 2 5)"), [])
    assert disassemble(curried) == "(a (q 16 2 5) 1)"


# Behavior on the reference VM.


def test_curried_values_land_before_the_environment():
    curried = curry(assemble("(+ 2 5)"), [assemble("10")])
    cost, result = run(curried, assemble("(32)"), BUDGET)
    assert result == assemble("42")


def test_zero_value_curry_passes_the_environment_through():
    curried = curry(assemble("(+ 2 5)"), [])
    cost, result = run(curried, assemble("(7 35)"), BUDGET)
    assert result == assemble("42")


def test_nested_curry_orders_inner_values_first():
    inner = curry(assemble("(- 2 5)"), [assemble("50")])
    curried = curry(inner, [assemble("8")])
    # The outer value is consed on last, so the inner curry's value
    # sits first in the wrapped program's environment.
    cost, result = run(curried, NIL, BUDGET)
    assert result == assemble("42")


def test_curried_compiled_program_takes_remaining_parameters():
    program, _ = compile_program("(program (X Y) (* X Y))")
    curried = curry(program, [assemble("6")])
    cost, result = run(curried, assemble("(7)"), BUDGET)
    assert result == assemble("42")


def test_curried_program_survives_serialization():
    curried = curry(assemble("(+ 2 5)"), [assemble("10")])
    assert deserialize(serialize(curried)) == curried


# The uncurry contract.


def test_uncurry_recovers_program_and_values():
    program = assemble("(+ 2 5)")
    values = [assemble("10"), assemble("0xdead")]
    inner, recovered = uncurry(curry(program, values))
    assert inner == program
    assert recovered == values


def test_uncurry_distinguishes_zero_values_from_not_curried():
    program = assemble("(+ 2 5)")
    inner, recovered = uncurry(curry(program, []))
    assert inner == program
    assert recovered == []
    same, sentinel = uncurry(program)
    assert same is program
    assert sentinel is None


def test_uncurry_of_a_quoted_nil_value():
    # A fixed nil quotes as (q . ()), whose unquoted value is the
    # empty atom, and the sentinel test is identity with None, so
    # falsy values survive.
    inner, recovered = uncurry(curry(assemble("(+ 2 5)"), [NIL]))
    assert recovered == [NIL]


@pytest.mark.parametrize(
    "text",
    [
        "5",
        "()",
        "(+ 2 5)",
        "(a (q . 5))",
        "(a . 5)",
        "(a (q . 5) 1 ())",
        "(a 5 1)",
        "(a (q . 5) 2)",
        "(a (q . 5) (q . 1))",
        "(a (q . 5) (c (q . 3) 2))",
        "(a (q . 5) (c (q . 3) (q . 1)))",
        "(a (q . 5) (c 3 1))",
        "(a (q . 5) (c (q . 3) 1 ()))",
        "(a (q . 5) (c (q . 3) . 1))",
        "(a (q . 5) (c (q . 3)))",
    ],
)
def test_uncurry_rejects_near_miss_shapes(text):
    node = assemble(text)
    program, values = uncurry(node)
    assert program is node
    assert values is None


# Properties.

_node_trees = st.recursive(
    st.binary(max_size=8), lambda child: st.tuples(child, child), max_leaves=25
)


@given(_node_trees, st.lists(_node_trees, max_size=5))
def test_uncurry_inverts_curry(program, values):
    inner, recovered = uncurry(curry(program, values))
    assert inner == program
    assert recovered == values


@given(_node_trees, st.lists(_node_trees, max_size=5))
def test_curried_output_survives_serialization(program, values):
    curried = curry(program, values)
    assert deserialize(serialize(curried)) == curried


@given(st.lists(st.binary(max_size=8), max_size=5), st.binary(max_size=8))
def test_curried_values_prefix_the_environment(values, env):
    # The whole-environment program returns what it runs against,
    # so the result exposes the constructed environment exactly:
    # the fixed values in order, then the given environment as the
    # tail.
    curried = curry(_ENV_PROGRAM, values)
    cost, result = run(curried, env, BUDGET)
    expected = env
    for value in reversed(values):
        expected = (value, expected)
    assert result == expected


# Differential against the pinned oracle wheel.

_needs_wheel = pytest.mark.skipif(chia_rs is None, reason="chia_rs not installed")


def _lazy_to_node(lazy):
    if lazy.pair is None:
        return lazy.atom
    first, rest = lazy.pair
    return (_lazy_to_node(first), _lazy_to_node(rest))


@_needs_wheel
@given(_node_trees, st.lists(_node_trees, max_size=4))
def test_uncurry_matches_chia_rs(program, values):
    curried = curry(program, values)
    wheel = chia_rs.Program.from_bytes(serialize(curried))
    mod, args = wheel.uncurry_rust()
    assert _lazy_to_node(mod) == program
    expected = NIL
    for value in reversed(values):
        expected = (value, expected)
    assert _lazy_to_node(args) == expected


@_needs_wheel
def test_uncurry_stricter_than_the_wheel():
    # The wheel's uncurry never checks the chain terminator, so it
    # accepts this near miss as a curry of one value. BitLisp
    # returns the sentinel: the strictness is a deliberate,
    # documented divergence from the deployed implementation, and
    # this pin fails loudly if either side moves.
    node = assemble("(a (q . 5) (c (q . 3) 2))")
    assert uncurry(node) == (node, None)
    mod, args = chia_rs.Program.from_bytes(serialize(node)).uncurry_rust()
    assert _lazy_to_node(mod) == b"\x05"
    assert _lazy_to_node(args) == (b"\x03", NIL)


@_needs_wheel
def test_curried_tree_hash_matches_chia_rs():
    curried = curry(assemble("(+ 2 5)"), [assemble("10"), assemble("0xdead")])
    assert tree_hash(curried) == chia_rs.tree_hash(serialize(curried))
