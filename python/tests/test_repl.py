"""REPL session tests, driven through onecmd with captured output."""

import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from bitlisp_tools import repl  # noqa: E402
from bitlisp_tools.repl import BitLispShell  # noqa: E402

BUDGET = 11_000_000_000

SPK_TAPROOT = "5120" + "aa" * 32
SPK_P2WPKH = "0014" + "99" * 20
CLAIM_PROGRAM = f"(q (1 0x{SPK_P2WPKH} 600) (80 400))"


@pytest.fixture
def shell():
    return BitLispShell()


@pytest.fixture
def ctx_file(tmp_path):
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
    path = tmp_path / "ctx.json"
    path.write_text(json.dumps(obj))
    return str(path)


# Evaluation.


def test_eval(shell, capsys):
    shell.onecmd("eval (+ (q . 2) (q . 3))")
    assert capsys.readouterr().out == f"5\ncost: 796 of {BUDGET}\n"


def test_eval_with_solution(shell, capsys):
    shell.onecmd("eval 1 (q . 7)")
    out = capsys.readouterr().out
    assert out.startswith("(q . 7)\n")


def test_bare_paren_line_is_eval(shell, capsys):
    shell.onecmd("(+ (q . 2) (q . 3))")
    assert capsys.readouterr().out == f"5\ncost: 796 of {BUDGET}\n"


def test_eval_error_survives(shell, capsys):
    shell.onecmd("eval (x)")
    assert capsys.readouterr().out == "invalid: user_raise: clvm raise\n"
    shell.onecmd("eval (q . 1)")
    assert capsys.readouterr().out == f"1\ncost: 20 of {BUDGET}\n"


def test_eval_argument_count(shell, capsys):
    shell.onecmd("eval (q . 1) (q . 2) (q . 3)")
    assert capsys.readouterr().out.startswith("error: eval takes a program")
    shell.onecmd("eval")
    assert capsys.readouterr().out.startswith("error: eval takes a program")


def test_asm_disasm(shell, capsys):
    shell.onecmd("asm (+ (q . 2) (q . 3))")
    assert capsys.readouterr().out == "ff10ffff0102ffff010380\n"
    shell.onecmd("disasm ff10ffff0102ffff010380")
    assert capsys.readouterr().out == "(+ (q . 2) (q . 3))\n"


# Definitions.


def test_def_substitutes(shell, capsys):
    shell.onecmd("def fee 500")
    shell.onecmd("eval (q . fee)")
    assert capsys.readouterr().out == f"500\ncost: 20 of {BUDGET}\n"


def test_def_snapshot(shell, capsys):
    shell.onecmd("def alpha (q . 1)")
    shell.onecmd("def beta alpha")
    shell.onecmd("def alpha (q . 2)")
    shell.onecmd("defs")
    assert capsys.readouterr().out == "alpha = (q . 2)\nbeta = (q . 1)\n"
    shell.onecmd("eval beta")
    assert capsys.readouterr().out == f"1\ncost: 20 of {BUDGET}\n"


def test_def_rejects_names(shell, capsys):
    for name in ("q", "12", "0xff", "(a)"):
        shell.onecmd(f"def {name} (q . 1)")
        assert "is not definable" in capsys.readouterr().out
    shell.onecmd("def onlyname")
    assert capsys.readouterr().out.startswith("error: def takes a name")


def test_undef(shell, capsys):
    shell.onecmd("def fee 500")
    shell.onecmd("undef fee")
    shell.onecmd("defs")
    assert capsys.readouterr().out == ""
    shell.onecmd("undef fee")
    assert "is not defined" in capsys.readouterr().out
    shell.onecmd("eval (q . fee)")
    assert "unknown symbol 'fee'" in capsys.readouterr().out


# Transaction context.


def test_tx_load_and_show(shell, ctx_file, capsys):
    shell.onecmd(f"tx {ctx_file}")
    line = capsys.readouterr().out
    assert line == f"{ctx_file}: 1 input(s), 1 output(s), input 0 selected\n"
    shell.onecmd("tx")
    assert capsys.readouterr().out == line


def test_tx_not_loaded(shell, capsys):
    shell.onecmd("tx")
    assert capsys.readouterr().out == "no context loaded\n"


def test_input_selection(shell, ctx_file, capsys):
    shell.onecmd("input 0")
    assert "no transaction context loaded" in capsys.readouterr().out
    shell.onecmd(f"tx {ctx_file}")
    capsys.readouterr()
    shell.onecmd("input 5")
    assert capsys.readouterr().out == "error: input 5 out of range\n"
    shell.onecmd("input 0")
    assert capsys.readouterr().out == ""


def test_spend_valid(shell, ctx_file, capsys):
    shell.onecmd(f"tx {ctx_file}")
    capsys.readouterr()
    shell.onecmd(f"spend {CLAIM_PROGRAM}")
    out = capsys.readouterr().out
    assert out == (
        f"CREATE_OUTPUT script_pubkey=0x{SPK_P2WPKH} amount=600\n"
        "RESERVE_FEE reserve=400\n"
        f"valid: 2 condition(s), cost 1350220 of {BUDGET}\n"
    )


def test_spend_without_context(shell, capsys):
    shell.onecmd("spend (q)")
    assert capsys.readouterr().out == (
        "error: no transaction context loaded, use tx <path>\n"
    )


def test_invalid_spend_survives(shell, ctx_file, capsys):
    shell.onecmd(f"tx {ctx_file}")
    capsys.readouterr()
    shell.onecmd("spend (x)")
    assert capsys.readouterr().out == "invalid: user_raise: clvm raise\n"
    shell.onecmd(f"spend {CLAIM_PROGRAM}")
    assert "valid: 2 condition(s)" in capsys.readouterr().out


def test_maxcost(shell, capsys):
    shell.onecmd("maxcost")
    assert capsys.readouterr().out == f"maxcost: {BUDGET}\n"
    shell.onecmd("maxcost 10")
    assert capsys.readouterr().out == "maxcost: 10\n"
    shell.onecmd("eval (+ (q . 2) (q . 3))")
    assert capsys.readouterr().out == "invalid: cost_exceeded: cost exceeded\n"
    shell.onecmd("maxcost -1")
    assert capsys.readouterr().out == "error: the budget cannot be negative\n"


# The debugger.


def test_debug_initial_display(shell, capsys):
    shell.onecmd("debug (+ (q . 2) (q . 3))")
    assert capsys.readouterr().out == (
        f"cost: 0 of {BUDGET}\n  0: eval (+ (q . 2) (q . 3)) env=()\n"
    )


def test_debug_step_display(shell, capsys):
    shell.onecmd("debug (+ (q . 2) (q . 3))")
    capsys.readouterr()
    shell.onecmd("step")
    assert capsys.readouterr().out == (
        f"cost: 1 of {BUDGET}\n"
        "  0: eval (q . 3) env=()\n"
        "  1: eval (q . 2) env=()\n"
        "  2: apply + over 2 value(s)\n"
    )
    shell.onecmd("step")
    assert "values: 3\n" in capsys.readouterr().out


def test_debug_next_steps_over_subtree(shell, capsys):
    shell.onecmd("debug (+ (q . 2) (* (q . 3) (q . 4)))")
    capsys.readouterr()
    shell.onecmd("step")
    capsys.readouterr()
    shell.onecmd("next")
    out = capsys.readouterr().out
    assert "values: 12\n" in out
    assert "eval (* (q . 3) (q . 4))" not in out


def test_debug_cont_prints_result(shell, capsys):
    shell.onecmd("debug (+ (q . 2) (q . 3))")
    capsys.readouterr()
    shell.onecmd("cont")
    assert capsys.readouterr().out == f"result: 5\ncost: 796 of {BUDGET}\n"
    shell.onecmd("step")
    assert capsys.readouterr().out == "no debug session, use debug <program>\n"


def test_debug_step_to_finish_closes(shell, capsys):
    shell.onecmd("debug (q . 1)")
    capsys.readouterr()
    shell.onecmd("step")
    assert capsys.readouterr().out == f"result: 1\ncost: 20 of {BUDGET}\n"
    shell.onecmd("step")
    assert capsys.readouterr().out == "no debug session, use debug <program>\n"


def test_debug_trace(shell, capsys):
    shell.onecmd("debug (+ (q . 2) (q . 3))")
    capsys.readouterr()
    shell.onecmd("trace")
    out = capsys.readouterr().out
    assert out.count("cost: ") == 4
    assert out.endswith(f"result: 5\ncost: 796 of {BUDGET}\n")


def test_debug_error_closes_with_post_mortem(shell, capsys):
    shell.onecmd("debug (x)")
    capsys.readouterr()
    shell.onecmd("cont")
    out = capsys.readouterr().out
    assert out.startswith("invalid: user_raise: clvm raise\n")
    assert "cost: " in out
    shell.onecmd("step")
    assert capsys.readouterr().out == "no debug session, use debug <program>\n"


def test_debug_refuses_while_open(shell, capsys):
    shell.onecmd("debug (q . 1)")
    capsys.readouterr()
    shell.onecmd("debug (q . 2)")
    assert "a debug session is open" in capsys.readouterr().out
    shell.onecmd("abort")
    assert capsys.readouterr().out == "debug session discarded\n"
    shell.onecmd("debug (q . 2)")
    assert capsys.readouterr().out.startswith("cost: 0")


def test_debug_uses_maxcost(shell, capsys):
    shell.onecmd("maxcost 10")
    capsys.readouterr()
    shell.onecmd("debug (+ (q . 2) (q . 3))")
    capsys.readouterr()
    shell.onecmd("cont")
    out = capsys.readouterr().out
    assert out.startswith("invalid: cost_exceeded: cost exceeded\n")


def test_no_session_guards_print_one_line(shell, capsys):
    for command in ("step", "next", "cont", "trace", "abort"):
        shell.onecmd(command)
        assert capsys.readouterr().out == ("no debug session, use debug <program>\n")


# Line handling.


def test_comment_line(shell, capsys):
    shell.onecmd("; a comment")
    assert capsys.readouterr().out == ""


def test_empty_line_does_not_repeat(shell, capsys):
    shell.onecmd("eval (q . 1)")
    capsys.readouterr()
    shell.onecmd("")
    assert capsys.readouterr().out == ""


def test_unknown_command(shell, capsys):
    shell.onecmd("bogus arg")
    assert capsys.readouterr().out == (
        "error: unknown command 'bogus', type help for the list\n"
    )


def test_source_runs_file(shell, tmp_path, capsys):
    path = tmp_path / "defs.bl"
    path.write_text("; a def library\ndef fee 500\n\neval (q . fee)\n")
    shell.onecmd(f"source {path}")
    assert capsys.readouterr().out == f"500\ncost: 20 of {BUDGET}\n"


def test_source_missing_file(shell, capsys):
    shell.onecmd("source /nonexistent/defs.bl")
    assert capsys.readouterr().out.startswith("error: ")


# The command registration and the piped end to end.


def test_console_script_resolves_to_main():
    (entry,) = metadata.entry_points(group="console_scripts", name="bitlisp")
    assert entry.load() is repl.main


def test_main_bad_context_exits_two(tmp_path, capsys):
    assert repl.main([str(tmp_path / "absent.json")]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_main_input_out_of_range_exits_two(tmp_path, capsys):
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
    path = tmp_path / "ctx.json"
    path.write_text(json.dumps(obj))
    assert repl.main([str(path), "--input", "3"]) == 2
    assert capsys.readouterr().err == "error: input 3 out of range\n"


def test_piped_session_end_to_end():
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT / "python"))
    script = "eval (+ (q . 2) (q . 3))\nexit\n"
    completed = subprocess.run(
        [sys.executable, "-m", "bitlisp_tools.repl"],
        input=script,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0
    assert completed.stdout == f"5\ncost: 796 of {BUDGET}\n"
    assert "bitlisp>" not in completed.stdout
    assert completed.stderr == ""
