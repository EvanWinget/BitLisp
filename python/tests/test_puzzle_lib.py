"""List library tests: each helper against Python's own fold, the
edge cases, and the pruning pin that keeps library growth free for
programs reaching none of it."""

import sys
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from bitlisp import run, serialize  # noqa: E402
from bitlisp.errors import BitLispError  # noqa: E402
from bitlisp.sexp import NIL, int_to_atom  # noqa: E402
from bitlisp_tools import assemble  # noqa: E402
from bitlisp_tools.compiler import compile_program  # noqa: E402

BUDGET = 11_000_000_000
INCLUDES = (str(REPO_ROOT / "puzzles" / "lib"),)


def _run(source, solution_text):
    program, _ = compile_program(source, include_paths=INCLUDES)
    cost, result = run(program, assemble(solution_text), BUDGET)
    return result


def _one_list(body, values):
    source = f'(program (ITEMS) (include "list.blib") {body})'
    solution = "(({}))".format(" ".join(str(value) for value in values))
    return _run(source, solution)


def _proper(values):
    node = NIL
    for value in reversed(values):
        node = (int_to_atom(value), node)
    return node


_values = st.lists(st.integers(min_value=0, max_value=2**63 - 1), max_size=8)
_nonempty = st.lists(
    st.integers(min_value=0, max_value=2**63 - 1), min_size=1, max_size=6
)


@given(_values)
def test_length_matches_len(values):
    assert _one_list("(length ITEMS)", values) == int_to_atom(len(values))


@given(_nonempty)
def test_nth_matches_indexing(values):
    for index, value in enumerate(values):
        assert _one_list(f"(nth ITEMS {index})", values) == int_to_atom(value)


@given(_values, _values)
def test_append_matches_concatenation(left, right):
    source = '(program (L R) (include "list.blib") (append L R))'
    solution = "(({}) ({}))".format(
        " ".join(str(value) for value in left),
        " ".join(str(value) for value in right),
    )
    assert _run(source, solution) == _proper(left + right)


@given(_values)
def test_reverse_matches_reversed(values):
    assert _one_list("(reverse ITEMS)", values) == _proper(list(reversed(values)))


@given(_values)
def test_sum_matches_sum(values):
    assert _one_list("(sum ITEMS)", values) == int_to_atom(sum(values))


@given(_nonempty)
def test_last_matches_the_final_item(values):
    assert _one_list("(last ITEMS)", values) == int_to_atom(values[-1])


def test_append_keeps_an_improper_tail():
    # RIGHT is the tail as given, the list* shape a program uses
    # when it conses its conditions onto an inherited tail.
    source = '(program (L T) (include "list.blib") (append L T))'
    assert _run(source, "((1 2) 5)") == assemble("(1 2 . 5)")


def test_empty_list_edges():
    assert _one_list("(length ITEMS)", []) == int_to_atom(0)
    assert _one_list("(sum ITEMS)", []) == int_to_atom(0)
    assert _one_list("(reverse ITEMS)", []) == NIL


def test_last_and_nth_raise_past_the_end():
    with pytest.raises(BitLispError):
        _one_list("(last ITEMS)", [])
    with pytest.raises(BitLispError):
        _one_list("(nth ITEMS 3)", [1, 2, 3])


def test_growth_is_free_for_a_length_only_program():
    # The compiled bytes of a program reaching only length, pinned
    # before this unit's helpers joined the library: unreached
    # declarations prune, so library growth cannot move any
    # existing program's bytes.
    source = '(program (ITEMS) (include "list.blib") (length ITEMS))'
    program, _ = compile_program(source, include_paths=INCLUDES)
    assert serialize(program).hex() == (
        "ff02ffff01ff02ff02ffff04ff02ffff04ff05ff80808080ffff04ffff01ff02ffff03"
        "ff05ffff01ff10ffff0101ffff02ff02ffff04ff02ffff04ffff06ff0580ff80808080"
        "80ffff018080ff0180ff018080"
    )
