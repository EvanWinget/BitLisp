"""Runner library and bitlisp-run command tests, plus the corpus pin."""

import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from bitlisp import (  # noqa: E402
    BitLispError,
    deserialize,
    parse_conditions,
    run,
)
from bitlisp.conditions import (  # noqa: E402
    ASSERT_SIG_MY_TXID,
    ASSERT_SIG_RAW,
    SIG_BINDINGS,
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
    Specifier,
)
from bitlisp.machine import QUOTE  # noqa: E402
from bitlisp_tools import assemble, cli  # noqa: E402
from bitlisp_tools.runner import (  # noqa: E402
    ContextError,
    load_context,
    render_condition,
    run_spend,
)

SPK_TAPROOT = "5120" + "aa" * 32
SPK_P2WPKH = "0014" + "99" * 20


def _context(**overrides):
    obj = {
        "version": 2,
        "locktime": 0,
        "inputs": [
            {
                "txid": "11" * 32,
                "index": 0,
                "script_pubkey": SPK_TAPROOT,
                "amount": 1000,
            }
        ],
        "outputs": [{"script_pubkey": SPK_P2WPKH, "amount": 600}],
    }
    obj.update(overrides)
    return obj


def _input(**overrides):
    return {**_context()["inputs"][0], **overrides}


# The program behind most cases: claim the one output slot and
# reserve the remaining 400 satoshis as fee.
CLAIM_PROGRAM = f"(q (1 0x{SPK_P2WPKH} 600) (80 400))"


# Schema-aware rendering, every condition class pinned literally.

RENDER_CASES = [
    (
        CreateOutput(bytes.fromhex(SPK_P2WPKH), 600),
        f"CREATE_OUTPUT script_pubkey=0x{SPK_P2WPKH} amount=600",
    ),
    (
        CreateOutputTaproot(b"\x02" * 32, b"", 5, bytes.fromhex(SPK_TAPROOT)),
        "CREATE_OUTPUT_TAPROOT internal_key=0x"
        + "02" * 32
        + " merkle_root=0x amount=5 script_pubkey=0x"
        + SPK_TAPROOT,
    ),
    (AssertLocktimeHeight(500), "ASSERT_LOCKTIME_HEIGHT height=500"),
    (AssertLocktimeTime(500_000_000), "ASSERT_LOCKTIME_TIME time=500000000"),
    (AssertSequenceHeight(3), "ASSERT_SEQUENCE_HEIGHT blocks=3"),
    (AssertSequenceTime(7), "ASSERT_SEQUENCE_TIME units=7"),
    (
        AssertMyOutpoint(b"\x11" * 36),
        "ASSERT_MY_OUTPOINT outpoint=0x" + "11" * 36,
    ),
    (AssertMyTxid(b"\x22" * 32), "ASSERT_MY_TXID txid=0x" + "22" * 32),
    (AssertMyScriptPubKey(b""), "ASSERT_MY_SCRIPTPUBKEY script_pubkey=0x"),
    (AssertMyAmount(0), "ASSERT_MY_AMOUNT amount=0"),
    (
        AssertMyTaproot(b"\x02" * 32, b"\x04" * 32, bytes.fromhex(SPK_TAPROOT)),
        "ASSERT_MY_TAPROOT internal_key=0x"
        + "02" * 32
        + " merkle_root=0x"
        + "04" * 32
        + " script_pubkey=0x"
        + SPK_TAPROOT,
    ),
    (
        AssertSig(ASSERT_SIG_RAW, b"\x05" * 32, b"", b"\x06" * 64),
        "ASSERT_SIG_RAW pubkey=0x" + "05" * 32 + " message=0x signature=0x" + "06" * 64,
    ),
    (
        AssertSig(ASSERT_SIG_MY_TXID, b"\x05" * 32, b"m", b"\x06" * 64),
        "ASSERT_SIG_MY_TXID pubkey=0x"
        + "05" * 32
        + " message=0x6d signature=0x"
        + "06" * 64,
    ),
    (Announce(b"ns", b""), "ANNOUNCE namespace=0x6e73 payload=0x"),
    (
        AssertAnnouncement(Specifier(0, ()), b"", b"\x01"),
        "ASSERT_ANNOUNCEMENT announcer={commitment=0} namespace=0x payload=0x01",
    ),
    (
        AssertAnnouncement(
            Specifier(0b011, (bytes.fromhex(SPK_P2WPKH), 600)), b"n", b"p"
        ),
        "ASSERT_ANNOUNCEMENT announcer={commitment=3 script_pubkey=0x"
        + SPK_P2WPKH
        + " amount=600} namespace=0x6e payload=0x70",
    ),
    (
        SendMessage(5, Specifier(0b111, (b"\x08" * 36,)), b"hi"),
        "SEND_MESSAGE sender_commitment=5 receiver={commitment=7 outpoint=0x"
        + "08" * 36
        + "} message=0x6869",
    ),
    (
        ReceiveMessage(Specifier(0b001, (0,)), 2, b""),
        "RECEIVE_MESSAGE sender={commitment=1 amount=0}"
        " receiver_commitment=2 message=0x",
    ),
    (ReserveFee(400), "RESERVE_FEE reserve=400"),
    (Seal(b"\x0a" * 32), "SEAL txid=0x" + "0a" * 32),
    (SealOutputs(b"\x0b" * 32), "SEAL_OUTPUTS outputs_hash=0x" + "0b" * 32),
    (Reserved(0x83, 600, ()), "RESERVED_0x83 cost=600 args=[]"),
    (
        Reserved(0x9F, 500, (b"\x07", (b"\x01", b""))),
        "RESERVED_0x9f cost=500 args=[7 (q)]",
    ),
]


@pytest.mark.parametrize(("condition", "expected"), RENDER_CASES)
def test_render_condition(condition, expected):
    assert render_condition(condition) == expected


# Every binding row pinned separately so a failure names its opcode.
@pytest.mark.parametrize("opcode", sorted(SIG_BINDINGS))
def test_render_sig_name(opcode):
    condition = AssertSig(opcode, b"\x05" * 32, b"", b"\x06" * 64)
    assert render_condition(condition).startswith(SIG_BINDINGS[opcode][0] + " ")


# Context loading.


def test_load_context_round_trip():
    tx = load_context(_context())
    assert tx.version == 2
    assert tx.inputs[0].txid == b"\x11" * 32
    assert tx.inputs[0].sequence == 0xFFFFFFFF
    assert tx.inputs[0].conditions is None
    assert tx.outputs[0].amount == 600


def test_load_context_carried_conditions_parse():
    tx = load_context(_context(inputs=[_input(conditions="80")]))
    assert tx.inputs[0].conditions == ()


@pytest.mark.parametrize(
    "obj",
    [
        [],
        _context(extra=1),
        {k: v for k, v in _context().items() if k != "outputs"},
        {
            "schema": "bitlisp-vector-v0",
            "suite": "validation",
            "spec": "x",
            "cases": [],
        },
        _context(inputs={}),
        _context(inputs=["x"]),
        _context(inputs=[{"txid": "11" * 32}]),
        _context(inputs=[_input(extra=1)]),
        _context(outputs=[{"script_pubkey": SPK_P2WPKH}]),
        _context(outputs=[{"script_pubkey": SPK_P2WPKH, "amount": 600, "x": 1}]),
        # Base-rule violations from the model constructors.
        _context(inputs=[_input(txid="11")]),
        _context(outputs=[{"script_pubkey": SPK_P2WPKH, "amount": 2000}]),
        # JSON booleans, which pass isinstance int checks unrejected.
        _context(version=True),
        _context(inputs=[_input(amount=True)]),
        _context(outputs=[{"script_pubkey": SPK_P2WPKH, "amount": True}]),
        # A carried conditions field that does not deserialize.
        _context(inputs=[_input(conditions="zz")]),
        _context(inputs=[_input(conditions="ff")]),
    ],
)
def test_load_context_rejects(obj):
    with pytest.raises(ContextError):
        load_context(obj)


def test_load_context_propagates_invalid_carried_list():
    # ffff7f8080 deserializes to ((0x7f)), whose opcode is invalid,
    # an invalid spend rather than a malformed context.
    with pytest.raises(BitLispError) as excinfo:
        load_context(_context(inputs=[_input(conditions="ffff7f8080")]))
    assert excinfo.value.code == "bad_condition_opcode"


# The consensus chain.


def test_run_spend_cost_matches_manual_chain():
    tx = load_context(_context())
    program = assemble(CLAIM_PROGRAM)
    cost, conditions = run_spend(program, b"", tx)
    vm_cost, result = run(program, b"", 11_000_000_000)
    expected_cost, expected_conditions = parse_conditions(result, None, cost=vm_cost)
    assert cost == expected_cost
    assert conditions == expected_conditions


def test_run_spend_invalid_pins_code():
    tx = load_context(_context())
    program = assemble(f"(q (1 0x{SPK_P2WPKH} 700))")
    with pytest.raises(BitLispError) as excinfo:
        run_spend(program, b"", tx)
    assert excinfo.value.code == "unsatisfied_output_claim"


def test_run_spend_nil_result_is_valid():
    tx = load_context(_context())
    assert run_spend(assemble("(q)"), b"", tx) == (20, ())


def test_run_spend_tiny_budget():
    tx = load_context(_context())
    with pytest.raises(BitLispError) as excinfo:
        run_spend(assemble(CLAIM_PROGRAM), b"", tx, max_cost=10)
    assert excinfo.value.code == "cost_exceeded"


@pytest.mark.parametrize("index", [-1, 1, 100])
def test_run_spend_index_out_of_range(index):
    tx = load_context(_context())
    with pytest.raises(ContextError):
        run_spend(assemble("(q)"), b"", tx, input_index=index)


def test_run_spend_rejects_carried_target():
    tx = load_context(_context(inputs=[_input(conditions="80")]))
    with pytest.raises(ContextError):
        run_spend(assemble("(q)"), b"", tx)


# The command.


@pytest.fixture
def ctx_file(tmp_path):
    path = tmp_path / "ctx.json"
    path.write_text(json.dumps(_context()))
    return str(path)


def test_cli_valid_transcript(ctx_file, capsys):
    assert cli.main([CLAIM_PROGRAM, ctx_file]) == 0
    assert capsys.readouterr().out == (
        f"CREATE_OUTPUT script_pubkey=0x{SPK_P2WPKH} amount=600\n"
        "RESERVE_FEE reserve=400\n"
        "valid: 2 condition(s), cost 1350220 of 11000000000\n"
    )


def test_cli_invalid_exit_one(ctx_file, capsys):
    assert cli.main([f"(q (1 0x{SPK_P2WPKH} 700))", ctx_file]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("invalid: unsatisfied_output_claim: ")


def test_cli_parse_error_exit_two(ctx_file, capsys):
    assert cli.main(["(q (1", ctx_file]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_cli_hex_mode(ctx_file, capsys):
    # ff0180 is (q), a program returning the empty condition list.
    assert cli.main(["--hex", "ff0180", ctx_file]) == 0
    assert capsys.readouterr().out == (
        "valid: 0 condition(s), cost 20 of 11000000000\n"
    )


def test_cli_hex_explicit_nil_solution(ctx_file, capsys):
    assert cli.main(["--hex", "ff0180", "80", ctx_file]) == 0
    assert capsys.readouterr().out.endswith("cost 20 of 11000000000\n")


def test_cli_hex_bad_bytecode_is_a_verdict(ctx_file, capsys):
    assert cli.main(["--hex", "ff01", ctx_file]) == 1
    assert capsys.readouterr().err.startswith("invalid: bad_encoding: ")


def test_cli_hex_bad_digits_exit_two(ctx_file, capsys):
    assert cli.main(["--hex", "zz", ctx_file]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_cli_program_from_file(ctx_file, tmp_path, capsys):
    program_path = tmp_path / "claim.bl"
    program_path.write_text(CLAIM_PROGRAM + "\n")
    assert cli.main([str(program_path), ctx_file]) == 0
    assert capsys.readouterr().out.endswith(
        "valid: 2 condition(s), cost 1350220 of 11000000000\n"
    )


def test_cli_empty_solution_is_nil(ctx_file, capsys):
    assert cli.main([CLAIM_PROGRAM, "", ctx_file]) == 0
    assert capsys.readouterr().out.endswith("cost 1350220 of 11000000000\n")


def test_cli_program_directory_exit_two(ctx_file, tmp_path, capsys):
    # Only a missing file falls back to literal treatment. Any other
    # way the path fails to open is an error, never a program.
    assert cli.main([str(tmp_path), ctx_file]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_cli_deep_context_exit_two(ctx_file, capsys, monkeypatch):
    # A context nested past the JSON parser's stack raises
    # RecursionError, forced here so the pin does not depend on the
    # host's actual stack depth.
    def explode(handle):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(json, "load", explode)
    assert cli.main(["(q)", ctx_file]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_cli_broken_pipe_keeps_verdict(ctx_file):
    # Enough conditions to overfill the pipe buffer, read one line,
    # then hang up. The producer must exit 0 with a silent stderr.
    program = "(q " + "(80 0) " * 5000 + ")"
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT / "python"))
    process = subprocess.Popen(
        [sys.executable, "-m", "bitlisp_tools.cli", program, ctx_file],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    process.stdout.readline()
    process.stdout.close()
    stderr = process.stderr.read()
    process.stderr.close()
    assert process.wait() == 0
    assert stderr == b""


def test_cli_missing_context_exit_two(tmp_path, capsys):
    assert cli.main(["(q)", str(tmp_path / "absent.json")]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_cli_bad_json_exit_two(tmp_path, capsys):
    path = tmp_path / "ctx.json"
    path.write_text("{")
    assert cli.main(["(q)", str(path)]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_cli_input_out_of_range_exit_two(ctx_file, capsys):
    assert cli.main(["(q)", ctx_file, "--input", "5"]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_cli_max_cost_flag(ctx_file, capsys):
    assert cli.main([CLAIM_PROGRAM, ctx_file, "--max-cost", "10"]) == 1
    assert capsys.readouterr().err.startswith("invalid: cost_exceeded: ")


def test_console_script_resolves_to_main():
    (entry,) = metadata.entry_points(group="console_scripts", name="bitlisp-run")
    assert entry.load() is cli.main


# The corpus pin: every validation case, replayed through the
# runner by wrapping each carried condition list as a quoted
# program, must reach the vector's own verdict.


def _corpus_runs():
    runs = []
    for path in sorted((REPO_ROOT / "vectors" / "validation").glob("*.json")):
        for case in json.loads(path.read_text())["cases"]:
            for i, entry in enumerate(case["tx"]["inputs"]):
                if "conditions" in entry:
                    runs.append(
                        (path.name, case["name"], i, case["tx"], case["expect"])
                    )
    return runs


def test_corpus_cross_check():
    runs = _corpus_runs()
    # A floor so a path or key typo cannot silently empty the sweep.
    assert len(runs) >= 20
    # Two corpus properties carry the equivalence, and a vector that
    # broke either would fail here loudly. The replay budgets at the
    # default while the corpus parses unbudgeted, sound while no
    # carried list's parse cost approaches the budget. Siblings
    # parse before the target instead of in input order, sound
    # while no case carries two parse-defective lists.
    for file_name, case_name, index, tx_obj, expect in runs:
        tx_obj = json.loads(json.dumps(tx_obj))
        conditions_hex = tx_obj["inputs"][index].pop("conditions")
        program = (QUOTE, deserialize(bytes.fromhex(conditions_hex)))
        try:
            tx = load_context(tx_obj)
            _, conditions = run_spend(program, b"", tx, input_index=index)
            for condition in conditions:
                render_condition(condition)
            outcome = {"valid": True}
        except BitLispError as exc:
            outcome = {"error": exc.code}
        assert outcome == expect, f"{file_name}: {case_name}: input {index}"
