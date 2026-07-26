#!/usr/bin/env python3
"""BitLisp vector corpus runner.

Discovers every vector file under vectors/ (excluding vectors/upstream/,
which holds vendored third-party data in its original format), validates
the envelope, and dispatches each suite to its runner.

Envelope format (v0), one JSON object per file:

    {
        "schema": "bitlisp-vector-v0",
        "suite": "vm" | "conditions" | "matching",
        "spec": "<citation of the spec section the cases pin>",
        "cases": [ ... ]
    }

Case shapes are suite-specific, each runner below documents its own.
Failure policy is loud by design: a vector file for a suite with no
runner yet is an error, never a skip. Silent skips are how corpora
rot.

Exit status: 0 when every case in every suite passes, 1 otherwise.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VECTOR_ROOT = REPO_ROOT / "vectors"

SCHEMA = "bitlisp-vector-v0"
SUITES = ("vm", "conditions", "matching")


class VectorError(Exception):
    """A vector file is malformed or a case failed."""


def validate_envelope(obj, path="<memory>"):
    """Checks the envelope shape. Returns the validated object.

    Raises VectorError on any deviation. Unknown top-level keys are
    rejected: an unrecognized key is more likely a typo'd field than an
    extension, and consensus tooling rejects rather than guesses.
    """
    if not isinstance(obj, dict):
        raise VectorError(f"{path}: envelope must be a JSON object")
    required = {"schema", "suite", "spec", "cases"}
    keys = set(obj)
    if missing := required - keys:
        raise VectorError(f"{path}: missing keys {sorted(missing)}")
    if extra := keys - required:
        raise VectorError(f"{path}: unknown keys {sorted(extra)}")
    if obj["schema"] != SCHEMA:
        raise VectorError(f"{path}: schema must be {SCHEMA!r}, got {obj['schema']!r}")
    if obj["suite"] not in SUITES:
        raise VectorError(
            f"{path}: suite must be one of {SUITES}, got {obj['suite']!r}"
        )
    if not isinstance(obj["spec"], str) or not obj["spec"]:
        raise VectorError(f"{path}: spec citation must be a non-empty string")
    if not isinstance(obj["cases"], list):
        raise VectorError(f"{path}: cases must be a list")
    return obj


def discover(root=VECTOR_ROOT):
    """Yields vector file paths in sorted order, skipping upstream/."""
    for path in sorted(root.rglob("*.json")):
        if "upstream" in path.relative_to(root).parts:
            continue
        yield path


def run_vm_case(case):
    """One vm case: run serialized (program, env) under a budget.

    Case shape:
        {
            "name": "<unique within the file>",
            "program": "<hex>",
            "env": "<hex>",
            "max_cost": <int, optional, default 11_000_000_000>,
            "expect": {"result": "<hex>", "cost": <int>}
                      or {"error": "<bitlisp error code>"}
        }
    """
    sys.path.insert(0, str(REPO_ROOT / "python"))
    from bitlisp import BitLispError, run_serialized
    from bitlisp.errors import CODES

    program = bytes.fromhex(case["program"])
    env = bytes.fromhex(case["env"])
    max_cost = case.get("max_cost", 11_000_000_000)
    expect = case["expect"]
    try:
        cost, result = run_serialized(program, env, max_cost)
        outcome = {"result": result.hex(), "cost": cost}
    except BitLispError as exc:
        outcome = {"error": exc.code}
    if "error" in expect and expect["error"] not in CODES:
        raise VectorError(f"unknown expected error code {expect['error']!r}")
    if outcome != expect:
        raise VectorError(f"expected {expect}, got {outcome}")


def run_vm(envelope, path):
    names = set()
    for index, case in enumerate(envelope["cases"]):
        name = case.get("name", f"case {index}")
        if name in names:
            raise VectorError(f"{path}: duplicate case name {name!r}")
        names.add(name)
        try:
            run_vm_case(case)
        except VectorError as exc:
            raise VectorError(f"{path}: {name}: {exc}") from None
        except (KeyError, ValueError) as exc:
            raise VectorError(f"{path}: {name}: malformed case: {exc!r}") from None


# Suite runners land with their implementations: conditions and
# matching in Phase 2. Each takes (envelope, path) and raises
# VectorError on the first failing case.
RUNNERS = {"vm": run_vm}


def run_file(path):
    """Runs one vector file. Returns the number of cases executed."""
    with open(path, encoding="utf-8") as fh:
        try:
            obj = json.load(fh)
        except json.JSONDecodeError as exc:
            raise VectorError(f"{path}: invalid JSON: {exc}") from exc
    envelope = validate_envelope(obj, path=str(path))
    suite = envelope["suite"]
    runner = RUNNERS.get(suite)
    if runner is None:
        if envelope["cases"]:
            raise VectorError(
                f"{path}: suite {suite!r} has {len(envelope['cases'])} case(s) "
                "but no runner is implemented yet"
            )
        return 0
    runner(envelope, path)
    return len(envelope["cases"])


def main():
    files = list(discover())
    total_cases = 0
    failures = 0
    for path in files:
        try:
            total_cases += run_file(path)
        except VectorError as exc:
            print(f"FAIL {exc}", file=sys.stderr)
            failures += 1
    print(
        f"run_vectors: {len(files)} file(s), {total_cases} case(s), "
        f"{failures} failure(s)"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
