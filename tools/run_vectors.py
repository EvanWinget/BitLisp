#!/usr/bin/env python3
"""BitLisp vector corpus runner.

Discovers every vector file under vectors/ (excluding vectors/upstream/,
which holds vendored third-party data in its original format), validates
the envelope, and dispatches each suite to its runner.

Envelope format (v0), one JSON object per file:

    {
        "schema": "bitlisp-vector-v0",
        "suite": "vm" | "conditions" | "spend" | "validation",
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
import traceback
from dataclasses import fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VECTOR_ROOT = REPO_ROOT / "vectors"
sys.path.insert(0, str(REPO_ROOT / "python"))

SCHEMA = "bitlisp-vector-v0"
SUITES = ("vm", "conditions", "spend", "validation")


class VectorError(Exception):
    """A vector file is malformed or a case failed."""


class MalformedCase(VectorError):
    """A case raised outside the error taxonomy: a malformed vector,
    or an implementation raising something no vector can expect.
    Distinct so tooling that judges implementations by vector verdict
    (the mutation harness) can tell the two apart. A suite raises it
    only after every other case in the file has run, so a case that
    reaches a verdict is never hidden behind one that escaped."""


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

    Case shape, closed like the envelope (unknown keys rejected, a
    typo'd max_cost would otherwise silently rerun the case at the
    default budget and pass while pinning nothing):
        {
            "name": "<unique within the file>",
            "program": "<hex>",
            "env": "<hex>",
            "max_cost": <int, optional, default 11_000_000_000>,
            "expect": {"result": "<hex>", "cost": <int>}
                      or {"error": "<bitlisp error code>"}
        }
    """
    from bitlisp import BitLispError, run_serialized
    from bitlisp.errors import CODES

    required = {"name", "program", "env", "expect"}
    keys = set(case)
    if missing := required - keys:
        raise VectorError(f"missing keys {sorted(missing)}")
    if extra := keys - required - {"max_cost"}:
        raise VectorError(f"unknown keys {sorted(extra)}")
    expect = case["expect"]
    if not isinstance(expect, dict) or set(expect) not in (
        {"result", "cost"},
        {"error"},
    ):
        raise VectorError(
            "expect must be exactly {result, cost} or {error}, "
            f"got {sorted(expect) if isinstance(expect, dict) else expect!r}"
        )
    program = bytes.fromhex(case["program"])
    env = bytes.fromhex(case["env"])
    max_cost = case.get("max_cost", 11_000_000_000)
    try:
        cost, result = run_serialized(program, env, max_cost)
        outcome = {"result": result.hex(), "cost": cost}
    except BitLispError as exc:
        outcome = {"error": exc.code}
    if "error" in expect and expect["error"] not in CODES:
        raise VectorError(f"unknown expected error code {expect['error']!r}")
    if outcome != expect:
        raise VectorError(f"expected {expect}, got {outcome}")


def _json_value(value):
    """The pinned JSON form of one parsed operand: integers as
    integers, bytes as hex, a participant specifier as its
    commitment value and its fields in operand order."""
    from bitlisp.conditions import Specifier

    if isinstance(value, bool) or not isinstance(value, int | bytes | Specifier):
        raise VectorError(f"no JSON form for operand {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, bytes):
        return value.hex()
    return {
        "commitment": value.commitment,
        "fields": [_json_value(field) for field in value.fields],
    }


def _condition_json(cond):
    """The pinned JSON form of one parsed condition: its opcode, then
    every operand under its model field name. A reserved condition's
    raw argument nodes pin as serialized hex."""
    from bitlisp import serialize
    from bitlisp.conditions import Reserved

    if isinstance(cond, Reserved):
        return {
            "opcode": cond.opcode,
            "cost": cond.cost,
            "args": [serialize(arg).hex() for arg in cond.args],
        }
    return {
        "opcode": cond.opcode,
        **{
            field.name: _json_value(getattr(cond, field.name))
            for field in fields(cond)
            if field.name != "opcode"
        },
    }


def run_conditions_case(case):
    """One conditions case: parse a serialized condition-list node.

    Case shape, closed like the envelope:
        {
            "name": "<unique within the file>",
            "conditions": "<hex, strict canonical serialization>",
            "max_cost": <int, optional, default unlimited>,
            "expect": {"parsed": [<condition JSON>]}
                      or {"parsed": [...], "cost": <int>}
                      or {"error": "<bitlisp error code>"}
        }

    max_cost is the inclusive per-input budget of the parse, with
    the accrued total starting at zero: these cases pin the
    condition layer's own charges in isolation. Cases that pin
    costs state the expected total in expect.cost.

    Condition JSON is {"opcode", "script_pubkey", "amount"} for
    CREATE_OUTPUT, {"opcode", "internal_key", "merkle_root", "amount",
    "script_pubkey"} for CREATE_OUTPUT_TAPROOT with script_pubkey the
    derived taproot script, {"opcode"} plus the operand under its
    entry's name ("height", "time", "blocks", "units") for the time
    asserts, and {"opcode", "cost", "args": [<hex node>]} for
    reserved conditions.

    The self asserts pin {"opcode"} plus their operand under its
    entry's name ("outpoint", "txid", "script_pubkey", "amount"),
    amounts as integers, bytes as hex. ASSERT_MY_TAPTREE pins
    {"opcode", "internal_key", "merkle_root"}, its two operands and
    nothing derived. ASSERT_MY_ANNEX pins {"opcode", "annex_hash"}.

    The message family pins specifiers as {"commitment", "fields"}
    with fields in operand order, amounts as integers, all other
    fields hex. ANNOUNCE is {"opcode", "namespace", "payload"},
    ASSERT_ANNOUNCEMENT adds "announcer" (a specifier),
    ASSURE is {"opcode", "assurer_commitment", "requirer",
    "message"}, and REQUIRE is {"opcode", "assurer",
    "requirer_commitment", "message"}.

    RESERVE_FEE pins {"opcode", "reserve"} with the reserve as an
    integer.

    The signature asserts pin {"opcode", "pubkey", "message",
    "signature"}, all three operands hex, the same shape for every
    family opcode since the variant lives in the opcode.

    The seals pin {"opcode"} plus their operand under its entry's
    name ("txid", "outputs_hash"), as hex.
    """
    from bitlisp import BitLispError, deserialize, parse_conditions
    from bitlisp.errors import CODES

    required = {"name", "conditions", "expect"}
    keys = set(case)
    if missing := required - keys:
        raise VectorError(f"missing keys {sorted(missing)}")
    if extra := keys - required - {"max_cost"}:
        raise VectorError(f"unknown keys {sorted(extra)}")
    expect = case["expect"]
    if not isinstance(expect, dict) or set(expect) not in (
        {"parsed"},
        {"parsed", "cost"},
        {"error"},
    ):
        raise VectorError("expect must be exactly {parsed}, {parsed, cost}, or {error}")
    if "error" in expect and expect["error"] not in CODES:
        raise VectorError(f"unknown expected error code {expect['error']!r}")
    try:
        node = deserialize(bytes.fromhex(case["conditions"]))
    except BitLispError as exc:
        raise VectorError(f"conditions field does not deserialize: {exc}") from None
    try:
        cost, parsed = parse_conditions(node, case.get("max_cost"))
        outcome = {"parsed": [_condition_json(c) for c in parsed]}
        if "cost" in expect:
            outcome["cost"] = cost
    except BitLispError as exc:
        outcome = {"error": exc.code}
    if outcome != expect:
        raise VectorError(f"expected {expect}, got {outcome}")


def run_spend_case(case):
    """One spend case: one input's witness through the per-input
    stages, from witness shape to the parsed condition list.

    Case shape, closed like the envelope:
        {
            "name": "<unique within the file>",
            "script_pubkey": "<hex, the spent taproot scriptPubKey>",
            "witness": ["<hex>", ...],
            "max_cost": <int>,
            "expect": {"conditions": [<condition JSON>],
                       "tapleaf": "<32-byte hex>",
                       "merkle_root": "<32-byte hex>",
                       "internal_key": "<32-byte hex>",
                       "annex_hash": "<32-byte hex, only with an annex>",
                       "cost": <int>}
                      or {"error": "<bitlisp error code>"}
        }

    witness is the input's elements as the transaction serializes
    them, the control block last, an annex after it when present.
    max_cost is required: the budget function is not fixed yet, so
    every case states the budget it runs under. The condition JSON
    is the conditions suite's. tapleaf, merkle_root, and
    internal_key are the execution identity read from the control
    block, annex_hash the sha_annex digest of the annex.

    Every case is a spend base consensus accepts: a witness base
    consensus would reject, or one that is not a BitLisp spend, has
    no outcome under this layer and is a malformed vector.
    """
    from bitlisp import BaseConsensusError, BitLispError, TxInput, evaluate_spend
    from bitlisp.errors import CODES

    required = {"name", "script_pubkey", "witness", "max_cost", "expect"}
    keys = set(case)
    if missing := required - keys:
        raise VectorError(f"missing keys {sorted(missing)}")
    if extra := keys - required:
        raise VectorError(f"unknown keys {sorted(extra)}")
    expect = case["expect"]
    success_keys = {"conditions", "tapleaf", "merkle_root", "internal_key", "cost"}
    if not isinstance(expect, dict) or set(expect) not in (
        success_keys,
        success_keys | {"annex_hash"},
        {"error"},
    ):
        raise VectorError(
            "expect must be exactly {conditions, tapleaf, merkle_root, "
            "internal_key, cost}, those plus annex_hash, or {error}"
        )
    if "error" in expect and expect["error"] not in CODES:
        raise VectorError(f"unknown expected error code {expect['error']!r}")
    if not isinstance(case["witness"], list):
        raise VectorError("witness must be a list of hex elements")
    # The outpoint, amount, and sequence are filler: nothing before
    # the transaction stage reads them.
    tx_input = TxInput(
        txid=b"\x00" * 32,
        index=0,
        script_pubkey=bytes.fromhex(case["script_pubkey"]),
        amount=1,
        sequence=0xFFFFFFFF,
    )
    witness = [bytes.fromhex(element) for element in case["witness"]]
    try:
        cost, spent = evaluate_spend(tx_input, witness, case["max_cost"])
        outcome = {
            "conditions": [_condition_json(c) for c in spent.conditions],
            "tapleaf": spent.tapleaf.hex(),
            "merkle_root": spent.merkle_root.hex(),
            "internal_key": spent.internal_key.hex(),
            "cost": cost,
        }
        if spent.annex_hash is not None:
            outcome["annex_hash"] = spent.annex_hash.hex()
    except BaseConsensusError as exc:
        raise VectorError(f"outside BitLisp, base consensus decides: {exc}") from None
    except BitLispError as exc:
        outcome = {"error": exc.code}
    if outcome != expect:
        raise VectorError(f"expected {expect}, got {outcome}")


def run_validation_case(case):
    """One validation case: validate a transaction's condition lists.

    Case shape, closed like the envelope:
        {
            "name": "<unique within the file>",
            "tx": {
                "version": <int>, "locktime": <int>,
                "inputs": [{"txid": "<hex>", "index": <int>,
                            "script_pubkey": "<hex>", "amount": <int>,
                            "sequence": <int, optional, default 0xffffffff>,
                            "script_sig": "<hex, optional, default empty>",
                            "conditions": "<hex node, optional>",
                            "tapleaf": "<32-byte hex, required with conditions>",
                            "merkle_root": "<32-byte hex, required with conditions>",
                            "internal_key": "<32-byte hex, required with conditions>",
                            "annex_hash": "<32-byte hex, optional>"}],
                "outputs": [{"script_pubkey": "<hex>", "amount": <int>}]
            },
            "expect": {"valid": true} or {"error": "<bitlisp error code>"}
        }

    An input without a conditions key is a non-BitLisp input. An
    input with one is a BitLisp input whose program evaluation
    produced that condition list. annex_hash is the sha_annex digest
    of the annex the input's witness carries, absent without one.
    """
    from bitlisp import BitLispError, validate_transaction
    from bitlisp.errors import CODES

    # The tx model builder lives with the single-spend runner, one
    # statement of the corpus tx shape for both consumers. Its
    # ContextError marks a malformed tx object, mapped to
    # VectorError here, while a BitLispError from a carried
    # condition list is a case outcome and propagates.
    from bitlisp_tools.runner import ContextError, load_context

    required = {"name", "tx", "expect"}
    keys = set(case)
    if missing := required - keys:
        raise VectorError(f"missing keys {sorted(missing)}")
    if extra := keys - required:
        raise VectorError(f"unknown keys {sorted(extra)}")
    expect = case["expect"]
    if not isinstance(expect, dict) or set(expect) not in ({"valid"}, {"error"}):
        raise VectorError("expect must be exactly {valid} or {error}")
    if "valid" in expect and expect["valid"] is not True:
        raise VectorError("expect.valid must be true, invalidity pins an error code")
    if "error" in expect and expect["error"] not in CODES:
        raise VectorError(f"unknown expected error code {expect['error']!r}")
    try:
        tx = load_context(case["tx"])
        validate_transaction(tx)
        outcome = {"valid": True}
    except ContextError as exc:
        raise VectorError(str(exc)) from None
    except BitLispError as exc:
        outcome = {"error": exc.code}
    if outcome != expect:
        raise VectorError(f"expected {expect}, got {outcome}")


def _make_suite_runner(case_runner):
    def run_suite(envelope, path):
        names = set()
        escaped = None
        for index, case in enumerate(envelope["cases"]):
            name = case.get("name", f"case {index}")
            if name in names:
                raise VectorError(f"{path}: duplicate case name {name!r}")
            names.add(name)
            try:
                case_runner(case)
            except VectorError as exc:
                raise VectorError(f"{path}: {name}: {exc}") from None
            except Exception as exc:
                # The remaining cases still run: a verdict on any of
                # them outranks an exception that escaped this one.
                if escaped is None:
                    escaped = (name, exc)
        if escaped is not None:
            name, exc = escaped
            raise MalformedCase(f"{path}: {name}: malformed case: {exc!r}") from exc

    return run_suite


RUNNERS = {
    "vm": _make_suite_runner(run_vm_case),
    "conditions": _make_suite_runner(run_conditions_case),
    "spend": _make_suite_runner(run_spend_case),
    "validation": _make_suite_runner(run_validation_case),
}


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
            if isinstance(exc, MalformedCase):
                traceback.print_exception(exc.__cause__, file=sys.stderr)
            failures += 1
    print(
        f"run_vectors: {len(files)} file(s), {total_cases} case(s), "
        f"{failures} failure(s)"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
