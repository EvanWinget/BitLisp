#!/usr/bin/env python3
"""BitLisp vector corpus runner.

Discovers every vector file under vectors/ (excluding vectors/upstream/,
which holds vendored third-party data in its original format), validates
the envelope, and dispatches each suite to its runner.

Envelope format (v0), one JSON object per file:

    {
        "schema": "bitlisp-vector-v0",
        "suite": "vm" | "conditions" | "validation",
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
sys.path.insert(0, str(REPO_ROOT / "python"))

SCHEMA = "bitlisp-vector-v0"
SUITES = ("vm", "conditions", "validation")


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


def _specifier_json(specifier):
    """The pinned JSON form of a participant specifier: the
    commitment value and the fields in operand order, amounts as
    integers, everything else as hex."""
    return {
        "commitment": specifier.commitment,
        "fields": [
            field if isinstance(field, int) else field.hex()
            for field in specifier.fields
        ],
    }


def _condition_json(cond):
    """The pinned JSON form of one parsed condition."""
    from bitlisp import serialize
    from bitlisp.conditions import (
        Announce,
        AssertAnnouncement,
        AssertLocktimeHeight,
        AssertLocktimeTime,
        AssertMyAmount,
        AssertMyOutpoint,
        AssertMyScriptPubKey,
        AssertMyTaproot,
        AssertMyTxid,
        AssertSequenceHeight,
        AssertSequenceTime,
        AssertSig,
        CreateOutput,
        CreateOutputTaproot,
        ReceiveMessage,
        Reserved,
        ReserveFee,
        Seal,
        SealOutputs,
        SendMessage,
    )

    if isinstance(cond, AssertLocktimeHeight):
        return {"opcode": cond.opcode, "height": cond.height}
    if isinstance(cond, AssertLocktimeTime):
        return {"opcode": cond.opcode, "time": cond.time}
    if isinstance(cond, AssertSequenceHeight):
        return {"opcode": cond.opcode, "blocks": cond.blocks}
    if isinstance(cond, AssertSequenceTime):
        return {"opcode": cond.opcode, "units": cond.units}
    if isinstance(cond, CreateOutput):
        return {
            "opcode": cond.opcode,
            "script_pubkey": cond.script_pubkey.hex(),
            "amount": cond.amount,
        }
    if isinstance(cond, CreateOutputTaproot):
        return {
            "opcode": cond.opcode,
            "internal_key": cond.internal_key.hex(),
            "merkle_root": cond.merkle_root.hex(),
            "amount": cond.amount,
            "script_pubkey": cond.script_pubkey.hex(),
        }
    if isinstance(cond, AssertSig):
        return {
            "opcode": cond.opcode,
            "pubkey": cond.pubkey.hex(),
            "message": cond.message.hex(),
            "signature": cond.signature.hex(),
        }
    if isinstance(cond, AssertMyOutpoint):
        return {"opcode": cond.opcode, "outpoint": cond.outpoint.hex()}
    if isinstance(cond, AssertMyTxid):
        return {"opcode": cond.opcode, "txid": cond.txid.hex()}
    if isinstance(cond, AssertMyScriptPubKey):
        return {"opcode": cond.opcode, "script_pubkey": cond.script_pubkey.hex()}
    if isinstance(cond, AssertMyAmount):
        return {"opcode": cond.opcode, "amount": cond.amount}
    if isinstance(cond, AssertMyTaproot):
        return {
            "opcode": cond.opcode,
            "internal_key": cond.internal_key.hex(),
            "merkle_root": cond.merkle_root.hex(),
            "script_pubkey": cond.script_pubkey.hex(),
        }
    if isinstance(cond, Announce):
        return {
            "opcode": cond.opcode,
            "namespace": cond.namespace.hex(),
            "payload": cond.payload.hex(),
        }
    if isinstance(cond, AssertAnnouncement):
        return {
            "opcode": cond.opcode,
            "announcer": _specifier_json(cond.announcer),
            "namespace": cond.namespace.hex(),
            "payload": cond.payload.hex(),
        }
    if isinstance(cond, SendMessage):
        return {
            "opcode": cond.opcode,
            "sender_commitment": cond.sender_commitment,
            "receiver": _specifier_json(cond.receiver),
            "message": cond.message.hex(),
        }
    if isinstance(cond, ReceiveMessage):
        return {
            "opcode": cond.opcode,
            "sender": _specifier_json(cond.sender),
            "receiver_commitment": cond.receiver_commitment,
            "message": cond.message.hex(),
        }
    if isinstance(cond, ReserveFee):
        return {"opcode": cond.opcode, "reserve": cond.reserve}
    if isinstance(cond, Seal):
        return {"opcode": cond.opcode, "txid": cond.txid.hex()}
    if isinstance(cond, SealOutputs):
        return {"opcode": cond.opcode, "outputs_hash": cond.outputs_hash.hex()}
    if isinstance(cond, Reserved):
        return {
            "opcode": cond.opcode,
            "cost": cond.cost,
            "args": [serialize(arg).hex() for arg in cond.args],
        }
    raise VectorError(f"no JSON form for condition type {type(cond).__name__}")


def run_conditions_case(case):
    """One conditions case: parse a serialized condition-list node.

    Case shape, closed like the envelope:
        {
            "name": "<unique within the file>",
            "conditions": "<hex, strict canonical serialization>",
            "expect": {"parsed": [<condition JSON>]}
                      or {"error": "<bitlisp error code>"}
        }

    Condition JSON is {"opcode", "script_pubkey", "amount"} for
    CREATE_OUTPUT, {"opcode", "internal_key", "merkle_root", "amount",
    "script_pubkey"} for CREATE_OUTPUT_TAPROOT with script_pubkey the
    derived taproot script, {"opcode"} plus the operand under its
    entry's name ("height", "time", "blocks", "units") for the time
    asserts, and {"opcode", "cost", "args": [<hex node>]} for
    reserved conditions.

    The self asserts pin {"opcode"} plus their operand under its
    entry's name ("outpoint", "txid", "script_pubkey", "amount"),
    amounts as integers, bytes as hex. ASSERT_MY_TAPROOT pins
    {"opcode", "internal_key", "merkle_root", "script_pubkey"} with
    script_pubkey the derived taproot script, exactly as
    CREATE_OUTPUT_TAPROOT pins it.

    The message family pins specifiers as {"commitment", "fields"}
    with fields in operand order, amounts as integers, all other
    fields hex. ANNOUNCE is {"opcode", "namespace", "payload"},
    ASSERT_ANNOUNCEMENT adds "announcer" (a specifier),
    SEND_MESSAGE is {"opcode", "sender_commitment", "receiver",
    "message"}, and RECEIVE_MESSAGE is {"opcode", "sender",
    "receiver_commitment", "message"}.

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
    if extra := keys - required:
        raise VectorError(f"unknown keys {sorted(extra)}")
    expect = case["expect"]
    if not isinstance(expect, dict) or set(expect) not in ({"parsed"}, {"error"}):
        raise VectorError("expect must be exactly {parsed} or {error}")
    if "error" in expect and expect["error"] not in CODES:
        raise VectorError(f"unknown expected error code {expect['error']!r}")
    try:
        node = deserialize(bytes.fromhex(case["conditions"]))
    except BitLispError as exc:
        raise VectorError(f"conditions field does not deserialize: {exc}") from None
    try:
        parsed = parse_conditions(node)
        outcome = {"parsed": [_condition_json(c) for c in parsed]}
    except BitLispError as exc:
        outcome = {"error": exc.code}
    if outcome != expect:
        raise VectorError(f"expected {expect}, got {outcome}")


def _tx_from_json(obj):
    """Builds the transaction model from a validation case's tx object.

    Parses each input's optional serialized condition list. A
    BitLispError from condition parsing is a case outcome (the spend
    is invalid), so it propagates to the caller. Everything else
    wrong with the tx object is a malformed vector: unknown or
    missing keys, a conditions field that does not deserialize (the
    validation stage receives already-materialized evaluation results,
    so a serialization failure is not a possible outcome here), and
    ValueError from any model constructor."""
    from bitlisp import (
        BitLispError,
        Transaction,
        TxInput,
        TxOutput,
        deserialize,
        parse_conditions,
    )

    required = {"version", "locktime", "inputs", "outputs"}
    keys = set(obj)
    if missing := required - keys:
        raise VectorError(f"tx missing keys {sorted(missing)}")
    if extra := keys - required:
        raise VectorError(f"tx unknown keys {sorted(extra)}")
    decoded_inputs = []
    for entry in obj["inputs"]:
        entry_required = {"txid", "index", "script_pubkey", "amount"}
        entry_optional = {"sequence", "conditions", "script_sig"}
        entry_keys = set(entry)
        if missing := entry_required - entry_keys:
            raise VectorError(f"input missing keys {sorted(missing)}")
        if extra := entry_keys - entry_required - entry_optional:
            raise VectorError(f"input unknown keys {sorted(extra)}")
        conditions = None
        if "conditions" in entry:
            try:
                node = deserialize(bytes.fromhex(entry["conditions"]))
            except BitLispError as exc:
                raise VectorError(
                    f"conditions field does not deserialize: {exc}"
                ) from None
            conditions = parse_conditions(node)
        decoded_inputs.append((entry, conditions))
    for entry in obj["outputs"]:
        entry_keys = set(entry)
        if missing := {"script_pubkey", "amount"} - entry_keys:
            raise VectorError(f"output missing keys {sorted(missing)}")
        if extra := entry_keys - {"script_pubkey", "amount"}:
            raise VectorError(f"output unknown keys {sorted(extra)}")
    try:
        return Transaction(
            version=obj["version"],
            locktime=obj["locktime"],
            inputs=tuple(
                TxInput(
                    txid=bytes.fromhex(entry["txid"]),
                    index=entry["index"],
                    script_pubkey=bytes.fromhex(entry["script_pubkey"]),
                    amount=entry["amount"],
                    sequence=entry.get("sequence", 0xFFFFFFFF),
                    conditions=conditions,
                    script_sig=bytes.fromhex(entry.get("script_sig", "")),
                )
                for entry, conditions in decoded_inputs
            ),
            outputs=tuple(
                TxOutput(bytes.fromhex(o["script_pubkey"]), o["amount"])
                for o in obj["outputs"]
            ),
        )
    except ValueError as exc:
        raise VectorError(f"tx violates the model's base rules: {exc}") from None


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
                            "conditions": "<hex node, optional>"}],
                "outputs": [{"script_pubkey": "<hex>", "amount": <int>}]
            },
            "expect": {"valid": true} or {"error": "<bitlisp error code>"}
        }

    An input without a conditions key is a non-BitLisp input. An
    input with one is a BitLisp input whose program evaluation
    produced that condition list.
    """
    from bitlisp import BitLispError, validate_transaction
    from bitlisp.errors import CODES

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
        tx = _tx_from_json(case["tx"])
        validate_transaction(tx)
        outcome = {"valid": True}
    except BitLispError as exc:
        outcome = {"error": exc.code}
    if outcome != expect:
        raise VectorError(f"expected {expect}, got {outcome}")


def _make_suite_runner(case_runner):
    def run_suite(envelope, path):
        names = set()
        for index, case in enumerate(envelope["cases"]):
            name = case.get("name", f"case {index}")
            if name in names:
                raise VectorError(f"{path}: duplicate case name {name!r}")
            names.add(name)
            try:
                case_runner(case)
            except VectorError as exc:
                raise VectorError(f"{path}: {name}: {exc}") from None
            except (KeyError, ValueError) as exc:
                raise VectorError(f"{path}: {name}: malformed case: {exc!r}") from None

    return run_suite


RUNNERS = {
    "vm": _make_suite_runner(run_vm_case),
    "conditions": _make_suite_runner(run_conditions_case),
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
            failures += 1
    print(
        f"run_vectors: {len(files)} file(s), {total_cases} case(s), "
        f"{failures} failure(s)"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
