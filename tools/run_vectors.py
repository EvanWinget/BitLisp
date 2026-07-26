#!/usr/bin/env python3
"""BitLisp vector corpus runner.

Discovers every vector file under vectors/ (excluding vectors/upstream/,
which holds vendored third-party data in its original format), validates
the envelope, and dispatches each suite to its runner.

Envelope format (v0), one JSON object per file:

    {
        "schema": "bitlisp-vector-v0",
        "suite": "vm" | "conditions" | "matching",
        "spec": "<spec file and section the cases pin, e.g. VM.md#4-D1>",
        "cases": [ ... ]
    }

Case shapes are suite-specific and documented in vectors/README.md as
each suite's runner lands. Failure policy is loud by design: a vector
file for a suite with no runner yet is an error, never a skip. Silent
skips are how corpora rot.

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


# Suite runners land with their implementations: vm in Phase 1,
# conditions and matching in Phase 2. Each takes (envelope, path) and
# raises VectorError on the first failing case.
RUNNERS = {}


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
