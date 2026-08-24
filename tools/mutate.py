#!/usr/bin/env python3
"""Mutation harness: does the vector corpus guard every line of the reference?

Generates small semantic mutants of every module in python/bitlisp
(a flipped comparison, a swapped arithmetic operator, an off-by-one
constant, a deleted raise, a negated branch) and runs the vector
corpus against each one. A mutant the corpus fails is killed. A
mutant the corpus passes survived: either no vector pins the behavior
that line implements, or the mutant is equivalent to the original.
Both readings need a human, so every survivor is reported with its
diff. A mutant that makes the reference raise something outside its
error taxonomy, so the runner stops on an escaping exception rather
than a vector's verdict, crashed: detected, but by Python rather than
by the corpus, and counted apart so the corpus's own coverage is not
overstated.

The corpus is the source of truth between sessions, so the corpus is
the primary oracle. With --tests, each survivor is additionally run
through the pytest suite (hypothesis invariants, oracle differentials,
unit tests), separating survivors nothing catches from survivors the
tests catch but the corpus does not. The first class is a gap in the
tests too. The second is a missing vector.

Each worker runs in its own mirror of the repository under a temporary
directory (python/ and tools/ copied, vectors/ and puzzles/ linked),
so mutants never touch the checkout and workers never see each
other's edits. The unmutated tree must pass every oracle the mutants
face before any mutant runs.

    tools/mutate.py                  run everything, summary on stdout
    tools/mutate.py --list           print the mutant inventory, run nothing
    tools/mutate.py --module costs   restrict to one module
    tools/mutate.py --only ID        run one mutant and print its diff
    tools/mutate.py --tests          second pass over survivors
    tools/mutate.py --report out.json  machine-readable results

Exit status: 0 when every mutant was killed or crashed, 1 when any
survived, 2 on a harness error (baseline failure, bad arguments).
"""

import argparse
import ast
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = REPO_ROOT / "python" / "bitlisp"

COMPARE_SWAPS = {
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
}

BINOP_SWAPS = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Add,
    ast.FloorDiv: ast.Mult,
    ast.Mod: ast.FloorDiv,
    ast.LShift: ast.RShift,
    ast.RShift: ast.LShift,
    ast.BitAnd: ast.BitOr,
    ast.BitOr: ast.BitAnd,
    ast.BitXor: ast.BitAnd,
}


@dataclass(frozen=True)
class Mutant:
    """One mutation site: which module, which line, what changed."""

    id: str
    module: str
    line: int
    description: str
    source: str


def _op_name(op):
    return type(op).__name__


class _Sites(ast.NodeVisitor):
    """Enumerates mutation sites in one module, in source order."""

    def __init__(self):
        self.sites = []

    def _add(self, node, description, mutate):
        self.sites.append((node.lineno, len(self.sites), description, mutate))

    def visit_Compare(self, node):
        for index, op in enumerate(node.ops):
            swap = COMPARE_SWAPS.get(type(op))
            if swap is not None:

                def mutate(index=index, swap=swap):
                    node.ops[index] = swap()

                self._add(node, f"{_op_name(op)} -> {swap.__name__}", mutate)
        self.generic_visit(node)

    def visit_BinOp(self, node):
        swap = BINOP_SWAPS.get(type(node.op))
        if swap is not None:

            def mutate(swap=swap):
                node.op = swap()

            self._add(node, f"{_op_name(node.op)} -> {swap.__name__}", mutate)
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        swap = ast.Or if isinstance(node.op, ast.And) else ast.And

        def mutate():
            node.op = swap()

        self._add(node, f"{_op_name(node.op)} -> {swap.__name__}", mutate)
        self.generic_visit(node)

    def visit_Constant(self, node):
        value = node.value
        if isinstance(value, bool):

            def mutate():
                node.value = not value

            self._add(node, f"{value} -> {not value}", mutate)
        elif isinstance(value, int):
            for delta in (1, -1):

                def mutate(delta=delta):
                    node.value = value + delta

                self._add(node, f"{value} -> {value + delta}", mutate)

    def visit_If(self, node):
        test = node.test

        def mutate():
            node.test = ast.UnaryOp(op=ast.Not(), operand=test)

        self._add(node, "if test negated", mutate)
        self.generic_visit(node)

    def visit_Raise(self, node):
        def mutate():
            node.__class__ = ast.Pass
            node.__dict__.clear()

        self._add(node, "raise deleted", mutate)
        self.generic_visit(node)

    def visit_Break(self, node):
        def mutate():
            node.__class__ = ast.Continue

        self._add(node, "break -> continue", mutate)

    def visit_Continue(self, node):
        def mutate():
            node.__class__ = ast.Break

        self._add(node, "continue -> break", mutate)


class _NotRemover(ast.NodeTransformer):
    """Rewrites one chosen `not x` to `x`."""

    def __init__(self, target):
        self.target = target

    def visit_UnaryOp(self, node):
        if node is self.target:
            return node.operand
        return self.generic_visit(node)


def _not_sites(tree):
    """Mutation sites for `not` removal, applied by transformer."""
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            sites.append(node)
    return sites


def generate(module_path):
    """Yields every mutant of one module, deterministically ordered."""
    source = module_path.read_text(encoding="utf-8")
    name = module_path.stem
    baseline = ast.parse(source)
    visitor = _Sites()
    visitor.visit(baseline)
    total = len(visitor.sites)
    for ordinal in range(total):
        tree = ast.parse(source)
        visitor = _Sites()
        visitor.visit(tree)
        line, _, description, mutate = visitor.sites[ordinal]
        mutate()
        ast.fix_missing_locations(tree)
        yield Mutant(
            id=f"{name}:{ordinal}",
            module=name,
            line=line,
            description=description,
            source=ast.unparse(tree),
        )
    for ordinal, target in enumerate(_not_sites(ast.parse(source))):
        tree = ast.parse(source)
        target = _not_sites(tree)[ordinal]
        tree = _NotRemover(target).visit(tree)
        ast.fix_missing_locations(tree)
        yield Mutant(
            id=f"{name}:not{ordinal}",
            module=name,
            line=target.lineno,
            description="not removed",
            source=ast.unparse(tree),
        )


def inventory(modules):
    mutants = []
    for path in sorted(PACKAGE.glob("*.py")):
        if modules and path.stem not in modules:
            continue
        mutants.extend(generate(path))
    return mutants


def mutant_diff(mutant):
    """Unified diff between the module and the mutant, both unparsed
    so that formatting differences never appear."""
    original = ast.unparse(ast.parse((PACKAGE / f"{mutant.module}.py").read_text()))
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            mutant.source.splitlines(keepends=True),
            fromfile=f"{mutant.module}.py",
            tofile=f"{mutant.module}.py ({mutant.id})",
            n=1,
        )
    )


# Worker side. Each process builds one mirror and reuses it for every
# mutant it is handed.

_MIRROR = None
# The corpus driver exits with this code on a vector's verdict. Any
# other nonzero exit is an exception escaping the reference.
VECTOR_FAILURE = 3
_CORPUS_DRIVER = f"""
VECTOR_FAILURE = {VECTOR_FAILURE}
import sys
sys.path.insert(0, sys.argv[1])
import run_vectors
for path in run_vectors.discover():
    try:
        run_vectors.run_file(path)
    except run_vectors.VectorError as exc:
        print(exc)
        sys.exit(VECTOR_FAILURE)
"""


def _build_mirror():
    root = Path(tempfile.mkdtemp(prefix="bitlisp-mutate-"))
    ignore = shutil.ignore_patterns("__pycache__", "*.egg-info", ".hypothesis")
    shutil.copytree(REPO_ROOT / "python", root / "python", ignore=ignore)
    shutil.copytree(REPO_ROOT / "tools", root / "tools", ignore=ignore)
    shutil.copy(REPO_ROOT / "pyproject.toml", root / "pyproject.toml")
    for shared in ("vectors", "puzzles"):
        os.symlink(REPO_ROOT / shared, root / shared)
    return root


def _mirror():
    global _MIRROR
    if _MIRROR is None:
        _MIRROR = _build_mirror()
    return _MIRROR


def _install(root, mutant):
    (root / "python" / "bitlisp" / f"{mutant.module}.py").write_text(
        mutant.source, encoding="utf-8"
    )
    for cache in (root / "python" / "bitlisp").glob("__pycache__/*"):
        cache.unlink()


def _restore(root, module):
    shutil.copy(PACKAGE / f"{module}.py", root / "python" / "bitlisp" / f"{module}.py")


def _run(root, argv, timeout, verdict_codes):
    """Runs argv in the mirror. Returns 'survived' on exit 0, 'killed' on
    an exit code in verdict_codes (the oracle judged the mutant),
    'crashed' on any other exit, or 'timeout'."""
    env = dict(os.environ, PYTHONPATH=str(root / "python"), PYTHONDONTWRITEBYTECODE="1")
    try:
        proc = subprocess.run(
            argv,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "timeout"
    if proc.returncode == 0:
        return "survived"
    return "killed" if proc.returncode in verdict_codes else "crashed"


def run_corpus(root, timeout):
    argv = [sys.executable, "-c", _CORPUS_DRIVER, str(root / "tools")]
    return _run(root, argv, timeout, {VECTOR_FAILURE})


def run_tests(root, timeout):
    argv = [
        sys.executable,
        "-m",
        "pytest",
        str(root / "python" / "tests"),
        "-q",
        "-x",
        "-p",
        "no:cacheprovider",
    ]
    # pytest exits 1 on failing tests. Its other codes (interrupted,
    # internal error, usage error, no tests collected) judge nothing.
    return _run(root, argv, timeout, {1})


def evaluate(mutant, timeout, tests):
    root = _mirror()
    _install(root, mutant)
    try:
        corpus = run_corpus(root, timeout)
        suite = None
        if tests and corpus == "survived":
            suite = run_tests(root, timeout * 10)
    finally:
        _restore(root, mutant.module)
    return mutant.id, corpus, suite


def _evaluate_star(args):
    return evaluate(*args)


def baseline_passes(timeout, tests):
    """The unmutated tree must pass every oracle the mutants face,
    else a broken mirror would report every mutant killed."""
    root = _build_mirror()
    try:
        if run_corpus(root, timeout) != "survived":
            return False
        return not tests or run_tests(root, timeout * 10) == "survived"
    finally:
        shutil.rmtree(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        help="restrict to a module (repeatable)",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="run only this mutant id (repeatable), printing its diff when alone",
    )
    parser.add_argument(
        "--list", action="store_true", help="print the inventory and exit"
    )
    parser.add_argument(
        "--tests",
        action="store_true",
        help="run the pytest suite over corpus survivors",
    )
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument(
        "--timeout", type=float, default=120.0, help="seconds per corpus run"
    )
    parser.add_argument("--report", type=Path, help="write results as JSON")
    args = parser.parse_args()

    modules = set(args.module)
    if args.only:
        modules = {mutant_id.split(":")[0] for mutant_id in args.only}
    mutants = inventory(modules)
    if args.only:
        wanted = set(args.only)
        mutants = [m for m in mutants if m.id in wanted]
        if missing := wanted - {m.id for m in mutants}:
            print(f"no mutant {sorted(missing)}", file=sys.stderr)
            return 2
        if len(mutants) == 1:
            print(mutant_diff(mutants[0]))
    if args.list:
        for m in mutants:
            print(f"{m.id:<20} {m.module}.py:{m.line:<5} {m.description}")
        print(f"{len(mutants)} mutant(s)")
        return 0

    if not baseline_passes(args.timeout, args.tests):
        print(
            "the unmutated tree fails its oracle, refusing to mutate", file=sys.stderr
        )
        return 2

    by_id = {m.id: m for m in mutants}
    results = []
    work = [(m, args.timeout, args.tests) for m in mutants]
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for done, (mutant_id, corpus, suite) in enumerate(
            pool.map(_evaluate_star, work, chunksize=4), start=1
        ):
            results.append((mutant_id, corpus, suite))
            if done % 50 == 0 or done == len(work):
                print(f"{done}/{len(work)}", file=sys.stderr)

    survivors = [r for r in results if r[1] == "survived"]
    timeouts = [r for r in results if r[1] == "timeout"]

    verdicts = ("killed", "crashed", "survived", "timeout")
    per_module = {}
    for mutant_id, corpus, _ in results:
        counts = per_module.setdefault(
            by_id[mutant_id].module, dict.fromkeys(verdicts, 0)
        )
        counts[corpus] += 1
    totals = dict.fromkeys(verdicts, 0)
    header = f"{'module':<14} {'mutants':>7}" + "".join(f" {v:>8}" for v in verdicts)
    print(header)
    for module, counts in sorted(per_module.items()):
        row = f"{module:<14} {sum(counts.values()):>7}"
        print(row + "".join(f" {counts[v]:>8}" for v in verdicts))
        for verdict in verdicts:
            totals[verdict] += counts[verdict]
    row = f"{'total':<14} {len(results):>7}"
    print(row + "".join(f" {totals[v]:>8}" for v in verdicts))

    if survivors:
        print("\nsurvivors:")
        for mutant_id, _, suite in survivors:
            m = by_id[mutant_id]
            tag = "" if suite is None else f"  [tests: {suite}]"
            print(f"  {m.id:<20} {m.module}.py:{m.line:<5} {m.description}{tag}")
    if timeouts:
        print("\ntimeouts:")
        for mutant_id, _, _ in timeouts:
            m = by_id[mutant_id]
            print(f"  {m.id:<20} {m.module}.py:{m.line:<5} {m.description}")

    if args.report:
        report = [
            dict(
                asdict(by_id[mutant_id]),
                corpus=corpus,
                tests=suite,
                diff=mutant_diff(by_id[mutant_id]),
            )
            for mutant_id, corpus, suite in results
        ]
        for entry in report:
            del entry["source"]
        args.report.write_text(json.dumps(report, indent=1), encoding="utf-8")

    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
