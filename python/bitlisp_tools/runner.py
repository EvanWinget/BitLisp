"""Single-spend execution over the consensus package.

Loads a transaction context shaped like a validation vector's tx
object, runs one input's program and solution through evaluation,
condition parsing, and full validation, and renders the parsed
conditions for display. Consensus behavior all lives in the bitlisp
package. This module only sequences it and formats its results.
"""

from dataclasses import fields, replace

from bitlisp import (
    BitLispError,
    Transaction,
    TxInput,
    TxOutput,
    deserialize,
    parse_conditions,
    run,
    validate_transaction,
)
from bitlisp.conditions import (
    SPECIFIER_OPERANDS,
    Announce,
    AssertAnnouncement,
    AssertLocktimeHeight,
    AssertLocktimeTime,
    AssertMyAmount,
    AssertMyOutpoint,
    AssertMyScriptPubKey,
    AssertMyTaproot,
    AssertMyTaptree,
    AssertMyTxid,
    AssertSequenceHeight,
    AssertSequenceTime,
    AssertSig,
    Assure,
    CreateOutput,
    CreateOutputTaproot,
    Require,
    Reserved,
    ReserveFee,
    Seal,
    SealOutputs,
    Specifier,
)

from .printer import disassemble

# The inclusive budget applied when the caller names none, the same
# default the vector corpus runs under.
DEFAULT_MAX_COST = 11_000_000_000


class ContextError(Exception):
    """A transaction context the runner cannot use: a shape defect in
    the tx object, or a spend selection it cannot support. Never a
    spend verdict, which is BitLispError's job."""


def _int_field(value, what):
    # bool is an int subclass, so a JSON true would otherwise pass
    # as 1 through every integer range check downstream.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContextError(f"{what} must be an integer")
    return value


def load_context(obj):
    """Builds the transaction model from a corpus-shaped tx object.

    The shape is the validation corpus's, closed at every level:
    version, locktime, inputs, and outputs exactly, each input with
    txid, index, script_pubkey, and amount plus optional sequence,
    conditions, script_sig, tapleaf, merkle_root, and internal_key,
    each output with script_pubkey and amount exactly. Byte fields
    are plain hex strings. The transaction model requires the
    execution-identity triple on every condition-carrying input, and
    the runner's target input needs it too, since conditions are
    installed there after evaluation.

    A carried conditions field is an already-evaluated serialized
    condition list. One that does not deserialize is a shape defect,
    because evaluation only ever materializes well-formed nodes. One
    that deserializes but does not parse describes an invalid spend,
    so that BitLispError propagates. Every other defect, including
    ValueError from the model constructors, raises ContextError.
    """
    if not isinstance(obj, dict):
        raise ContextError("tx context must be a JSON object")
    required = {"version", "locktime", "inputs", "outputs"}
    keys = set(obj)
    if missing := required - keys:
        raise ContextError(f"tx missing keys {sorted(missing)}")
    if extra := keys - required:
        raise ContextError(f"tx unknown keys {sorted(extra)}")
    if not isinstance(obj["inputs"], list) or not isinstance(obj["outputs"], list):
        raise ContextError("tx inputs and outputs must be arrays")
    entry_required = {"txid", "index", "script_pubkey", "amount"}
    entry_optional = {
        "sequence",
        "conditions",
        "script_sig",
        "tapleaf",
        "merkle_root",
        "internal_key",
    }
    decoded_inputs = []
    for entry in obj["inputs"]:
        if not isinstance(entry, dict):
            raise ContextError("each input must be a JSON object")
        entry_keys = set(entry)
        if missing := entry_required - entry_keys:
            raise ContextError(f"input missing keys {sorted(missing)}")
        if extra := entry_keys - entry_required - entry_optional:
            raise ContextError(f"input unknown keys {sorted(extra)}")
        conditions = None
        if "conditions" in entry:
            try:
                node = deserialize(bytes.fromhex(entry["conditions"]))
            except (BitLispError, TypeError, ValueError) as exc:
                raise ContextError(
                    f"conditions field does not deserialize: {exc}"
                ) from None
            # Carried lists parse unbudgeted: their evaluations
            # happened elsewhere, each under its own budget.
            _, conditions = parse_conditions(node, None)
        decoded_inputs.append((entry, conditions))
    for entry in obj["outputs"]:
        if not isinstance(entry, dict):
            raise ContextError("each output must be a JSON object")
        entry_keys = set(entry)
        if missing := {"script_pubkey", "amount"} - entry_keys:
            raise ContextError(f"output missing keys {sorted(missing)}")
        if extra := entry_keys - {"script_pubkey", "amount"}:
            raise ContextError(f"output unknown keys {sorted(extra)}")
    try:
        return Transaction(
            version=_int_field(obj["version"], "version"),
            locktime=_int_field(obj["locktime"], "locktime"),
            inputs=tuple(
                TxInput(
                    txid=bytes.fromhex(entry["txid"]),
                    index=_int_field(entry["index"], "input index"),
                    script_pubkey=bytes.fromhex(entry["script_pubkey"]),
                    amount=_int_field(entry["amount"], "input amount"),
                    sequence=_int_field(entry.get("sequence", 0xFFFFFFFF), "sequence"),
                    conditions=conditions,
                    script_sig=bytes.fromhex(entry.get("script_sig", "")),
                    tapleaf=(
                        bytes.fromhex(entry["tapleaf"]) if "tapleaf" in entry else None
                    ),
                    merkle_root=(
                        bytes.fromhex(entry["merkle_root"])
                        if "merkle_root" in entry
                        else None
                    ),
                    internal_key=(
                        bytes.fromhex(entry["internal_key"])
                        if "internal_key" in entry
                        else None
                    ),
                )
                for entry, conditions in decoded_inputs
            ),
            outputs=tuple(
                TxOutput(
                    bytes.fromhex(o["script_pubkey"]),
                    _int_field(o["amount"], "output amount"),
                )
                for o in obj["outputs"]
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ContextError(f"tx violates the model's base rules: {exc}") from None


def run_spend(program, solution, tx, input_index=0, max_cost=DEFAULT_MAX_COST):
    """Runs one input's spend and validates the whole transaction.

    The consensus chain for the target input: evaluation, then
    condition parsing against the same inclusive budget, then every
    validation rule with the parsed list installed on that input.
    Returns (cost, conditions) on success, with cost the budget's
    accrued total across evaluation and parsing.

    Raises BitLispError when the spend is invalid, and ContextError
    when the selection is unusable: an index out of range, a
    target input that already carries conditions, since the runner
    exists to compute them, or a target missing the
    execution-identity pair its computed conditions will require.
    """
    if not 0 <= input_index < len(tx.inputs):
        raise ContextError(
            f"input index {input_index} out of range for {len(tx.inputs)} input(s)"
        )
    target = tx.inputs[input_index]
    if target.conditions is not None:
        raise ContextError(f"input {input_index} already carries conditions")
    if (
        target.tapleaf is None
        or target.merkle_root is None
        or target.internal_key is None
    ):
        raise ContextError(
            f"input {input_index} must carry tapleaf, merkle_root, and "
            "internal_key, the executing input's identity"
        )
    vm_cost, result = run(program, solution, max_cost)
    total_cost, conditions = parse_conditions(result, max_cost, cost=vm_cost)
    inputs = list(tx.inputs)
    inputs[input_index] = replace(target, conditions=conditions)
    validate_transaction(replace(tx, inputs=tuple(inputs)))
    return total_cost, conditions


# Display names match the condition vocabulary, spelled out because
# the class names alone cannot reproduce the underscore placement.
_CONDITION_NAMES = {
    CreateOutput: "CREATE_OUTPUT",
    CreateOutputTaproot: "CREATE_OUTPUT_TAPROOT",
    AssertLocktimeHeight: "ASSERT_LOCKTIME_HEIGHT",
    AssertLocktimeTime: "ASSERT_LOCKTIME_TIME",
    AssertSequenceHeight: "ASSERT_SEQUENCE_HEIGHT",
    AssertSequenceTime: "ASSERT_SEQUENCE_TIME",
    AssertMyOutpoint: "ASSERT_MY_OUTPOINT",
    AssertMyTxid: "ASSERT_MY_TXID",
    AssertMyScriptPubKey: "ASSERT_MY_SCRIPTPUBKEY",
    AssertMyAmount: "ASSERT_MY_AMOUNT",
    AssertMyTaproot: "ASSERT_MY_TAPROOT",
    AssertMyTaptree: "ASSERT_MY_TAPTREE",
    Announce: "ANNOUNCE",
    AssertAnnouncement: "ASSERT_ANNOUNCEMENT",
    Assure: "ASSURE",
    Require: "REQUIRE",
    ReserveFee: "RESERVE_FEE",
    Seal: "SEAL",
    SealOutputs: "SEAL_OUTPUTS",
}


def _specifier_text(specifier):
    names = SPECIFIER_OPERANDS[specifier.commitment]
    parts = [f"commitment={specifier.commitment}"]
    parts += [
        f"{name}={_value_text(value)}"
        for name, value in zip(names, specifier.fields, strict=True)
    ]
    return "{" + " ".join(parts) + "}"


def _value_text(value):
    if isinstance(value, bool) or not isinstance(value, int | bytes | Specifier):
        raise ValueError(f"no display form for {value!r}")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, bytes):
        return "0x" + value.hex()
    return _specifier_text(value)


def render_condition(cond):
    """One display line for a parsed condition.

    The vocabulary name, then field=value operands in the parsed
    model's field order. Integer operands print decimal and byte
    operands print 0x hex, so every operand shows in the shape its
    schema declares and the reader never guesses a type from a byte
    length. Empty bytes print as 0x, and every operand spelling
    assembles back to the same atom.
    """
    if isinstance(cond, Reserved):
        args = " ".join(disassemble(arg) for arg in cond.args)
        return f"RESERVED_{cond.opcode:#04x} cost={cond.cost} args=[{args}]"
    # opcode is a dataclass field only on AssertSig, whose name
    # already spells it, so one filter excludes it everywhere.
    name = cond.name if isinstance(cond, AssertSig) else _CONDITION_NAMES[type(cond)]
    operands = " ".join(
        f"{f.name}={_value_text(getattr(cond, f.name))}"
        for f in fields(cond)
        if f.name != "opcode"
    )
    return f"{name} {operands}"
