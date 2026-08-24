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


def test_mirror_shares_data_and_copies_code():
    root = mutate._build_mirror()
    try:
        assert (root / "vectors").is_symlink()
        assert (root / "puzzles").is_symlink()
        assert not (root / "python" / "bitlisp").is_symlink()
        assert (root / "tools" / "run_vectors.py").is_file()
    finally:
        shutil.rmtree(root)


def test_corpus_kills_a_broken_error_code_table():
    # Any mutant of the error-code table breaks the first vector file
    # the corpus opens, so this integration test stays fast.
    mutants = mutate.inventory({"errors"})
    broken = next(m for m in mutants if m.description != "raise deleted")
    mutant_id, corpus, suite = mutate.evaluate(broken, timeout=120, tests=False)
    assert (mutant_id, corpus, suite) == (broken.id, "killed", None)
