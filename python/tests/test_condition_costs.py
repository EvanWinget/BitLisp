"""Unit tests for condition cost accounting.

The vector corpus pins the consensus-visible surface (totals,
boundaries, charge order). These tests cover the pieces a vector
cannot express: the initial-cost threading the consensus pipeline
uses to continue the VM run's meter, the unlimited reference-tool
budget, and the cost-table values as named constants.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bitlisp import BitLispError, condition_cost, parse_conditions  # noqa: E402
from bitlisp.conditions import (  # noqa: E402
    ANNOUNCE,
    ASSERT_MY_AMOUNT,
    ASSERT_MY_TAPTREE,
    ASSERT_SIG_RAW,
    ASSURE,
    CONDITION_COSTS,
    CREATE_OUTPUT,
    CREATE_OUTPUT_TAPROOT,
    RESERVE_FEE,
    SEAL,
)
from bitlisp.sexp import NIL, int_to_atom  # noqa: E402

# An x above the field prime lifts to no curve point, so this key
# passes every width check and fails the derivation.
BAD_INTERNAL_KEY = b"\xff" * 32
# A generator-point x, always liftable.
GOOD_INTERNAL_KEY = bytes.fromhex(
    "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
)


def clist(*items):
    node = NIL
    for item in reversed(items):
        node = (item, node)
    return node


def cond(opcode, *args):
    return clist(bytes([opcode]), *args)


AMOUNT_ASSERT = cond(ASSERT_MY_AMOUNT, int_to_atom(1000))
CREATE = cond(CREATE_OUTPUT, b"\x51", int_to_atom(1000))
MALFORMED = cond(CREATE_OUTPUT, b"", int_to_atom(1000))


def test_cost_table_values_match_spec():
    assert CONDITION_COSTS[ASSERT_MY_AMOUNT] == 200
    assert CONDITION_COSTS[SEAL] == 200
    assert CONDITION_COSTS[RESERVE_FEE] == 200
    assert CONDITION_COSTS[ANNOUNCE] == 700
    assert CONDITION_COSTS[ASSURE] == 700
    assert CONDITION_COSTS[ASSERT_SIG_RAW] == 1_300_000
    assert CONDITION_COSTS[CREATE_OUTPUT] == 1_350_000
    assert CONDITION_COSTS[CREATE_OUTPUT_TAPROOT] == 2_650_000
    assert CONDITION_COSTS[ASSERT_MY_TAPTREE] == 200


def test_returned_cost_is_the_sum_of_condition_costs():
    cost, parsed = parse_conditions(clist(CREATE, AMOUNT_ASSERT, AMOUNT_ASSERT), None)
    assert cost == sum(condition_cost(c) for c in parsed) == 1_350_400


def test_budget_is_inclusive_at_the_exact_total():
    node = clist(CREATE, AMOUNT_ASSERT)
    cost, _ = parse_conditions(node, max_cost=1_350_200)
    assert cost == 1_350_200
    with pytest.raises(BitLispError) as excinfo:
        parse_conditions(node, max_cost=1_350_199)
    assert excinfo.value.code == "cost_exceeded"


def test_initial_cost_threads_through_the_meter():
    node = clist(AMOUNT_ASSERT)
    cost, _ = parse_conditions(node, max_cost=241, cost=41)
    assert cost == 241
    with pytest.raises(BitLispError) as excinfo:
        parse_conditions(node, max_cost=240, cost=41)
    assert excinfo.value.code == "cost_exceeded"


def test_no_budget_means_no_check():
    cost, _ = parse_conditions(clist(*[CREATE] * 100), None)
    assert cost == 135_000_000


def test_empty_list_satisfies_a_zero_budget():
    assert parse_conditions(NIL, max_cost=0) == (0, ())


def test_checks_win_over_cost_exceeded_within_a_condition():
    with pytest.raises(BitLispError) as excinfo:
        parse_conditions(clist(MALFORMED), max_cost=0)
    assert excinfo.value.code == "bad_condition_arg"
    with pytest.raises(BitLispError) as excinfo:
        parse_conditions(clist(cond(0x70)), max_cost=0)
    assert excinfo.value.code == "bad_condition_opcode"


def test_earlier_charge_precedes_later_checks():
    node = clist(AMOUNT_ASSERT, MALFORMED)
    with pytest.raises(BitLispError) as excinfo:
        parse_conditions(node, max_cost=199)
    assert excinfo.value.code == "cost_exceeded"
    with pytest.raises(BitLispError) as excinfo:
        parse_conditions(node, max_cost=200)
    assert excinfo.value.code == "bad_condition_arg"


def test_derivation_defect_reported_only_when_paid():
    node = clist(cond(CREATE_OUTPUT_TAPROOT, BAD_INTERNAL_KEY, b"", int_to_atom(1)))
    with pytest.raises(BitLispError) as excinfo:
        parse_conditions(node, max_cost=2_650_000)
    assert excinfo.value.code == "bad_condition_arg"
    with pytest.raises(BitLispError) as excinfo:
        parse_conditions(node, max_cost=2_649_999)
    assert excinfo.value.code == "cost_exceeded"


def test_reserved_charges_exactly_the_declared_cost():
    node = clist(cond(0x80, int_to_atom(600)))
    cost, parsed = parse_conditions(node, max_cost=600)
    assert cost == 600
    assert condition_cost(parsed[0]) == 600
    with pytest.raises(BitLispError) as excinfo:
        parse_conditions(node, max_cost=599)
    assert excinfo.value.code == "cost_exceeded"


def test_floor_check_wins_over_the_budget():
    with pytest.raises(BitLispError) as excinfo:
        parse_conditions(clist(cond(0x80, int_to_atom(499))), max_cost=0)
    assert excinfo.value.code == "reserved_cost_too_low"
