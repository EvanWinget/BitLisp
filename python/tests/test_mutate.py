"""The mutation harness generates well-formed, distinct mutants and
judges them through the real corpus runner."""

import ast
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import mutate  # noqa: E402

MODULES = sorted(p.stem for p in mutate.PACKAGE.glob("*.py") if p.stem != "__init__")


def test_every_module_yields_parseable_distinct_mutants():
    mutants = mutate.inventory(set())
    assert {m.module for m in mutants} == set(MODULES)
    ids = [m.id for m in mutants]
    assert len(ids) == len(set(ids))
    for mutant in mutants:
        ast.parse(mutant.source)
        original = (mutate.PACKAGE / f"{mutant.module}.py").read_text()
        assert ast.unparse(ast.parse(original)) != mutant.source, mutant.id


def test_constant_mutant_changes_exactly_one_constant():
    mutants = [m for m in mutate.inventory({"costs"}) if m.description == "20 -> 21"]
    quote = [m for m in mutants if "QUOTE_COST = 21" in m.source]
    assert quote, "QUOTE_COST = 20 should yield a 21 mutant"
    diff = mutate.mutant_diff(quote[0])
    changed = [
        line
        for line in diff.splitlines()
        if line[:1] in "+-" and not line.startswith(("---", "+++"))
    ]
    assert changed == ["-QUOTE_COST = 20", "+QUOTE_COST = 21"]


def test_sites_cover_augassign_and_expression_tests_without_duplicates():
    source = (
        "x = 0\n"
        "x += 1\n"
        "if a == b:\n"
        "    pass\n"
        "if a < b:\n"
        "    pass\n"
        "while not c:\n"
        "    pass\n"
        "y = 1 if d < 2 else 3\n"
    )
    descriptions = [m.description for m in mutate.mutants_of("sample", source)]
    # The augmented assignment is swapped like a binary operator.
    assert "Add -> Sub" in descriptions
    # `a == b` negated would duplicate the Eq -> NotEq swap, and
    # `not c` negated would duplicate the `not` removal. `a < b` has
    # no negation among the swaps, so its negation stays.
    assert descriptions.count("if test negated") == 1
    assert "while test negated" not in descriptions
    assert "ifexp test negated" in descriptions
    assert "not removed" in descriptions


def test_mirror_shares_data_and_copies_code():
    root = mutate._build_mirror()
    try:
        assert (root / "vectors").is_symlink()
        assert (root / "puzzles").is_symlink()
        assert not (root / "python" / "bitlisp").is_symlink()
        assert (root / "tools" / "run_vectors.py").is_file()
        assert (root / "python" / "tests" / "conftest.py").is_file()
    finally:
        shutil.rmtree(root)


def test_verdict_separates_the_oracle_from_an_escaping_exception():
    # Exit 0 survives, the oracle's own code kills, any other exit is
    # an exception escaping the reference and counts apart.
    root = mutate._build_mirror()
    try:
        verdicts = {
            code: mutate._run(
                root, [sys.executable, "-c", f"raise SystemExit({code})"], 30, {3}
            )[0]
            for code in (0, 3, 1)
        }
    finally:
        shutil.rmtree(root)
    assert verdicts == {0: "survived", 3: "killed", 1: "crashed"}


def test_corpus_judges_a_wrong_cost_and_a_poisoned_error_table_apart():
    # A wrong cost constant fails a vector's expectation: a kill the
    # corpus earns. A poisoned error-code table makes every failure
    # construction raise ValueError before any verdict: a crash.
    costs = next(
        m
        for m in mutate.inventory({"costs"})
        if m.description == "20 -> 21" and "QUOTE_COST = 21" in m.source
    )
    poisoned = next(
        m for m in mutate.inventory({"errors"}) if m.description == "NotIn -> In"
    )
    assert mutate.evaluate(costs, timeout=120, tests=False)[:3] == (
        costs.id,
        "killed",
        None,
    )
    assert mutate.evaluate(poisoned, timeout=120, tests=False)[:3] == (
        poisoned.id,
        "crashed",
        None,
    )
