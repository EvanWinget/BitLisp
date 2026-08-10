"""Property-based invariants for condition cost accounting.

The vectors pin exact totals and orderings for chosen lists. These
properties quantify over generated lists: conservation (the meter's
total is exactly the sum of the parsed conditions' costs), reorder
invariance, append additivity, per-occurrence charging, and the
inclusive budget boundary.
"""

import random
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bitlisp import BitLispError, condition_cost, parse_conditions  # noqa: E402
from bitlisp.sexp import NIL, int_to_atom  # noqa: E402

# The taproot menu entries derive a point per parse in pure Python,
# so these properties run over few examples with no deadline, the
# convention of the other EC-heavy invariant suites.
EXAMPLES = settings(max_examples=25, deadline=None)

GOOD_KEY = bytes.fromhex(
    "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
)


def clist(*items):
    node = NIL
    for item in reversed(items):
        node = (item, node)
    return node


def cond(opcode, *args):
    return clist(bytes([opcode]), *args)


# One well-formed condition per cost tier, plus a second generic
# and a reserved declaration off the floor.
MENU = (
    cond(0x33, int_to_atom(1000)),
    cond(0x20, int_to_atom(800_000)),
    cond(0x40, b"ns", b"payload"),
    cond(0x16, b"\x02" * 32, b"msg", b"\x03" * 64),
    cond(0x01, b"\x51", int_to_atom(1000)),
    cond(0x02, GOOD_KEY, b"", int_to_atom(1000)),
    cond(0x37, GOOD_KEY, b""),
    cond(0x80, int_to_atom(600)),
)

condition_lists = st.lists(st.sampled_from(MENU), max_size=6)


@EXAMPLES
@given(condition_lists)
def test_total_is_the_sum_of_condition_costs(items):
    cost, parsed = parse_conditions(clist(*items), None)
    assert cost == sum(condition_cost(c) for c in parsed)


@EXAMPLES
@given(condition_lists, st.integers(0, 2**32))
def test_total_is_invariant_under_reordering(items, seed):
    shuffled = items[:]
    random.Random(seed).shuffle(shuffled)
    cost, _ = parse_conditions(clist(*items), None)
    shuffled_cost, _ = parse_conditions(clist(*shuffled), None)
    assert cost == shuffled_cost


@EXAMPLES
@given(condition_lists, st.sampled_from(MENU))
def test_appending_adds_exactly_the_appended_cost(items, extra):
    cost, _ = parse_conditions(clist(*items), None)
    appended_cost, appended = parse_conditions(clist(*items, extra), None)
    assert appended_cost == cost + condition_cost(appended[-1])


@EXAMPLES
@given(st.sampled_from(MENU), st.integers(1, 4))
def test_every_occurrence_charges_individually(item, count):
    single_cost, _ = parse_conditions(clist(item), None)
    total, _ = parse_conditions(clist(*[item] * count), None)
    assert total == single_cost * count


@EXAMPLES
@given(condition_lists)
def test_budget_boundary_is_inclusive(items):
    node = clist(*items)
    total, _ = parse_conditions(node, None)
    exact_cost, _ = parse_conditions(node, max_cost=total)
    assert exact_cost == total
    if total > 0:
        with pytest.raises(BitLispError) as excinfo:
            parse_conditions(node, max_cost=total - 1)
        assert excinfo.value.code == "cost_exceeded"
