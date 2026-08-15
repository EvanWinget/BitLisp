"""Debug machine tests: the differential pin against machine.run."""

import json
import sys
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from bitlisp import deserialize  # noqa: E402
from bitlisp.errors import BitLispError  # noqa: E402
from bitlisp.machine import APPLY, QUOTE, run  # noqa: E402
from bitlisp.operators import OPERATORS  # noqa: E402
from bitlisp.sexp import NIL  # noqa: E402
from bitlisp_tools import assemble  # noqa: E402
from bitlisp_tools.stepper import (  # noqa: E402
    APPLY_OP,
    EVAL,
    DebugMachine,
)

BUDGET = 11_000_000_000

# The published add_2_3 vector.
ADD_HEX = "ff10ffff0102ffff010380"


def _outcome_run(program, env, max_cost):
    try:
        cost, result = run(program, env, max_cost)
        return ("ok", cost, result)
    except BitLispError as exc:
        return ("err", exc.code)


def _outcome_debug(program, env, max_cost):
    machine = DebugMachine(program, env, max_cost)
    machine.run()
    if machine.error is not None:
        return ("err", machine.error.code)
    return ("ok", machine.cost, machine.result)


# The corpus differential: every VM vector case runs on both
# machines and both reach the vector's own verdict.


def _corpus_cases():
    cases = []
    for path in sorted((REPO_ROOT / "vectors" / "vm").glob("*.json")):
        if path.name == "serialize.json":
            continue
        cases.extend(json.loads(path.read_text())["cases"])
    return cases


def test_corpus_differential():
    cases = _corpus_cases()
    # A floor so a path or key typo cannot silently empty the sweep.
    assert len(cases) >= 400
    for case in cases:
        program = deserialize(bytes.fromhex(case["program"]))
        env = deserialize(bytes.fromhex(case["env"]))
        max_cost = case.get("max_cost", BUDGET)
        reference = _outcome_run(program, env, max_cost)
        debug = _outcome_debug(program, env, max_cost)
        assert debug == reference, case["name"]
        expect = case["expect"]
        if "error" in expect:
            assert debug == ("err", expect["error"]), case["name"]
        else:
            expected_result = deserialize(bytes.fromhex(expect["result"]))
            assert debug == ("ok", expect["cost"], expected_result), case["name"]


# The hypothesis differential: adversarial trees, operator-headed
# trees, and budgets small enough to burst mid-evaluation.

atoms = st.binary(max_size=64)
nodes = st.recursive(atoms, lambda children: st.tuples(children, children))
op_atoms = st.sampled_from(sorted(OPERATORS) + [QUOTE, APPLY])
op_nodes = st.recursive(
    atoms,
    lambda children: st.tuples(op_atoms, children) | st.tuples(children, children),
)
budgets = st.sampled_from([0, 10, 100, 10_000, BUDGET])


@given(nodes, nodes, budgets)
def test_differential_adversarial(program, env, max_cost):
    assert _outcome_debug(program, env, max_cost) == _outcome_run(
        program, env, max_cost
    )


@given(op_nodes, nodes, budgets)
def test_differential_operator_headed(program, env, max_cost):
    assert _outcome_debug(program, env, max_cost) == _outcome_run(
        program, env, max_cost
    )


# The step-by-step pin on the published vector: exact stacks after
# every task, the right-to-left argument order visible.


def test_step_pin_add():
    program = deserialize(bytes.fromhex(ADD_HEX))
    quote_two = (b"\x01", b"\x02")
    quote_three = (b"\x01", b"\x03")
    machine = DebugMachine(program, NIL, BUDGET)
    assert machine.tasks == [(EVAL, program, NIL)]
    assert machine.values == []

    machine.step()
    assert machine.tasks == [
        (APPLY_OP, b"\x10", 2),
        (EVAL, quote_two, NIL),
        (EVAL, quote_three, NIL),
    ]
    assert machine.values == []

    machine.step()
    assert machine.tasks == [(APPLY_OP, b"\x10", 2), (EVAL, quote_two, NIL)]
    assert machine.values == [b"\x03"]

    machine.step()
    assert machine.tasks == [(APPLY_OP, b"\x10", 2)]
    assert machine.values == [b"\x03", b"\x02"]

    machine.step()
    assert machine.tasks == []
    assert machine.values == [b"\x05"]
    assert machine.finished
    assert machine.result == b"\x05"
    assert machine.error is None
    assert machine.cost == 796


# Step-over.


def test_step_over_subtree():
    machine = DebugMachine(assemble("(+ (q . 2) (* (q . 3) (q . 4)))"), NIL, BUDGET)
    machine.step()
    # The multiply subtree is the pending task, three tasks deep.
    assert len(machine.tasks) == 3
    machine.step_over()
    assert len(machine.tasks) == 2
    assert machine.values == [b"\x0c"]
    assert not machine.finished


def test_step_over_atom_task():
    machine = DebugMachine(assemble("(+ (q . 2) 1)"), b"\x05", BUDGET)
    machine.step()
    # The pending task is the path lookup for 1, which pushes
    # nothing, so step-over is a single step.
    assert len(machine.tasks) == 3
    machine.step_over()
    assert len(machine.tasks) == 2
    assert machine.values == [b"\x05"]


def test_step_over_top_level_runs_to_completion():
    machine = DebugMachine(assemble("(+ (q . 2) (q . 3))"), NIL, BUDGET)
    machine.step_over()
    assert machine.finished
    assert machine.result == b"\x05"


# Error terminal states: the machine finishes with the error held
# and the stacks frozen, nothing propagates.


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("(x)", "user_raise"),
        ("(a (q . 1))", "wrong_arg_count"),
        ("(f (q . 1))", "arg_not_pair"),
    ],
)
def test_error_is_terminal_state(text, code):
    machine = DebugMachine(assemble(text), NIL, BUDGET)
    machine.run()
    assert machine.finished
    assert machine.error.code == code
    assert machine.result is None
    # The stacks stay renderable for the post-mortem display.
    assert isinstance(machine.tasks, list)
    assert isinstance(machine.values, list)


def test_cost_exceeded_mid_debug():
    machine = DebugMachine(assemble("(+ (q . 2) (q . 3))"), NIL, 10)
    steps = 0
    while not machine.finished:
        machine.step()
        steps += 1
    assert machine.error.code == "cost_exceeded"
    assert steps >= 1


def test_unknown_operator_uncharged():
    machine = DebugMachine((b"\xee", NIL), NIL, BUDGET)
    machine.run()
    assert machine.error.code == "unknown_operator"
    assert machine.cost == 0


def test_step_after_finished_raises():
    machine = DebugMachine(assemble("(q . 1)"), NIL, BUDGET)
    machine.run()
    assert machine.finished
    with pytest.raises(RuntimeError):
        machine.step()
    with pytest.raises(RuntimeError):
        machine.step_over()


# Program depth must not be limited by the Python recursion limit,
# the same property machine.run holds.


def test_deep_program():
    node = (b"\x01", b"\x01")
    for _ in range(10_000):
        node = (b"\x10", (node, NIL))
    assert _outcome_debug(node, NIL, BUDGET) == _outcome_run(node, NIL, BUDGET)
    machine = DebugMachine(node, NIL, BUDGET)
    machine.run()
    assert machine.result == b"\x01"
