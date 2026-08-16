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
    # The unbound name now falls through to the compiler, where a
    # quoted 'fee' is data that cannot hold names.
    shell.onecmd("eval (q . fee)")
    assert "'fee' in quoted content" in capsys.readouterr().out


def test_asm_uses_definitions(shell, capsys):
    shell.onecmd("def fee 500")
    shell.onecmd("asm (q . fee)")
    assert capsys.readouterr().out == "ff018201f4\n"


def test_disasm_rejection_prints_error(shell, capsys):
    # A converter issues no spend verdict, so its rejection prints
    # with the error prefix, matching bitlisp-disasm.
    shell.onecmd("disasm c00161")
    assert capsys.readouterr().out == (
        "error: bad_encoding: non-minimal length encoding\n"
    )


def test_def_unicode_space_name(shell, capsys):
    # Unicode whitespace is part of a bare token to the reader, so
    # a name carrying a no-break space binds whole and reads back.
    shell.onecmd("def x\u00a0y (q . 1)")
    shell.onecmd("eval x\u00a0y")
    assert capsys.readouterr().out == f"1\ncost: 20 of {BUDGET}\n"


def test_def_rejects_comment_carrying_name(shell, capsys):
    shell.onecmd("def foo;c (q . 1)")
    assert "is not definable" in capsys.readouterr().out
    shell.onecmd("defs")
    assert capsys.readouterr().out == ""


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


def test_input_selection_reaches_spend(shell, tmp_path, capsys):
    # Two inputs with different amounts, and a program asserting
    # the selected input's own amount, so validating the wrong
    # input cannot pass. ASSERT_MY_AMOUNT is opcode 51.
    obj = {
        "version": 2,
        "locktime": 0,
        "inputs": [
            {
                "txid": "11" * 32,
                "index": 0,
                "script_pubkey": SPK_TAPROOT,
                "amount": 1000,
            },
            {
                "txid": "22" * 32,
                "index": 0,
                "script_pubkey": SPK_TAPROOT,
                "amount": 700,
            },
        ],
        "outputs": [{"script_pubkey": SPK_P2WPKH, "amount": 600}],
    }
    path = tmp_path / "two.json"
    path.write_text(json.dumps(obj))
    shell.onecmd(f"tx {path}")
    capsys.readouterr()
    shell.onecmd("spend (q (51 700))")
    assert capsys.readouterr().out.startswith("invalid: ")
    shell.onecmd("input 1")
    capsys.readouterr()
    shell.onecmd("spend (q (51 700))")
    out = capsys.readouterr().out
    assert "valid: 1 condition(s)" in out


def test_spend_with_solution(shell, ctx_file, capsys):
    # Program 1 is the path to the whole environment, so the
    # solution itself becomes the condition list.
    shell.onecmd(f"tx {ctx_file}")
    capsys.readouterr()
    shell.onecmd(f"spend 1 ((1 0x{SPK_P2WPKH} 600) (80 400))")
    out = capsys.readouterr().out
    assert "valid: 2 condition(s)" in out


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


def test_debug_with_solution(shell, capsys):
    shell.onecmd("debug 1 (q . 7)")
    capsys.readouterr()
    shell.onecmd("cont")
    out = capsys.readouterr().out
    assert out.startswith("result: (q . 7)\n")


def test_interrupt_discards_broken_session(shell, capsys, monkeypatch):
    # An interrupt mid-task poisons the machine, and the shell must
    # drop that session instead of stepping it into a wrong result.
    from bitlisp.operators import OPERATORS

    def boom(args, charge):
        raise KeyboardInterrupt

    shell.onecmd("debug (+ (q . 1) (q . 2))")
    capsys.readouterr()
    monkeypatch.setitem(OPERATORS, b"\x10", boom)
    shell.onecmd("cont")
    out = capsys.readouterr().out
    assert "interrupted" in out
    assert "debug session discarded" in out
    assert shell.session is None
    shell.onecmd("step")
    assert capsys.readouterr().out == "no debug session, use debug <program>\n"


def test_interrupt_keeps_paused_session(shell, capsys, monkeypatch):
    # An interrupt during an unrelated command must not touch a
    # paused session.
    from bitlisp.operators import OPERATORS

    def boom(args, charge):
        raise KeyboardInterrupt

    shell.onecmd("debug (q . 1)")
    capsys.readouterr()
    monkeypatch.setitem(OPERATORS, b"\x10", boom)
    shell.onecmd("eval (+ (q . 1) (q . 2))")
    out = capsys.readouterr().out
    assert "interrupted" in out
    assert "discarded" not in out
    assert shell.session is not None


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


def test_source_honors_exit(shell, tmp_path, capsys):
    # An exit in a sourced file ends the session, as it would in
    # the same script piped, so no line after it runs.
    path = tmp_path / "stopper.bl"
    path.write_text("def fee (q . 5)\nexit\neval fee\n(x)\n")
    assert shell.onecmd(f"source {path}") is True
    assert capsys.readouterr().out == ""


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


def test_main_input_without_context_exits_two(capsys):
    assert repl.main(["--input", "2"]) == 2
    assert capsys.readouterr().err == ("error: --input needs a transaction context\n")


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


def test_piped_max_cost_flag():
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT / "python"))
    completed = subprocess.run(
        [sys.executable, "-m", "bitlisp_tools.repl", "--max-cost", "10"],
        input="eval (+ (q . 2) (q . 3))\nexit\n",
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0
    assert completed.stdout == "invalid: cost_exceeded: cost exceeded\n"


def test_piped_non_utf8_exits_two():
    # One undecodable byte ends the run with an error line and
    # exit 2, never a traceback. Strict decoding is forced because
    # platforms whose stdin decodes with surrogateescape never
    # raise here: their bad bytes become lone surrogates, which the
    # reader's totality already rejects line by line.
    env = dict(
        os.environ,
        PYTHONPATH=str(REPO_ROOT / "python"),
        PYTHONIOENCODING="utf-8:strict",
    )
    completed = subprocess.run(
        [sys.executable, "-m", "bitlisp_tools.repl"],
        input=b"\xff\xfe(q . 1)\n",
        capture_output=True,
        env=env,
    )
    assert completed.returncode == 2
    assert completed.stderr.startswith(b"error: input is not valid UTF-8")
    assert b"Traceback" not in completed.stderr


# The language surface: declarations, the compile fallback, and the
# symbol table in the debugger.


def test_defun_line_and_call(shell, capsys):
    shell.onecmd("(defun double (N) (* 2 N))")
    assert capsys.readouterr().out == ""
    shell.onecmd("(double 21)")
    out = capsys.readouterr().out
    assert out.startswith("42\n")


def test_raw_meaning_is_unchanged(shell, capsys):
    # Numbers in raw VM text are environment paths, and a line that
    # parses raw never reaches the compiler, definitions or not.
    shell.onecmd("(defun double (N) (* 2 N))")
    shell.onecmd("eval (f 1) (7 . 8)")
    assert capsys.readouterr().out.startswith("7\n")
    shell.onecmd("eval (+ 1 2)")
    assert "invalid: path_into_atom" in capsys.readouterr().out


def test_defconstant_line_inlines(shell, capsys):
    shell.onecmd("(defconstant FEE 500)")
    shell.onecmd("eval (- 1000 FEE)")
    assert capsys.readouterr().out.startswith("500\n")


def test_program_form_runs_with_solution(shell, capsys):
    shell.onecmd("eval (program (X Y) (+ X Y)) (2 3)")
    assert capsys.readouterr().out.startswith("5\n")


def test_solution_never_compiles(shell, capsys):
    shell.onecmd("(defconstant FEE 500)")
    shell.onecmd("eval (program (X) X) (FEE)")
    out = capsys.readouterr().out
    assert out.startswith("error: ")
    assert "'FEE' in the solution" in out


def test_conditions_and_list_at_the_prompt(shell, capsys):
    shell.onecmd(f"(list (list CREATE_OUTPUT 0x{SPK_P2WPKH} 600))")
    out = capsys.readouterr().out
    assert out.splitlines()[0] == f"((q 0x{SPK_P2WPKH} 600))"


def test_declaration_errors_print(shell, capsys):
    # An operator name resolves before the compiler sees it, so it
    # can never name a function.
    shell.onecmd("(defun q (N) N)")
    assert "name must be a bare name" in capsys.readouterr().out
    shell.onecmd("(defun dup (N N) N)")
    assert "duplicate parameter" in capsys.readouterr().out
    shell.onecmd("(defconstant CREATE_OUTPUT 9)")
    assert "condition constant" in capsys.readouterr().out
    shell.onecmd("(defun keep (N) N)")
    shell.onecmd("(defun keep (N) N)")
    assert "already defined" in capsys.readouterr().out


def test_def_and_defun_share_one_namespace(shell, capsys):
    shell.onecmd("def fee 500")
    shell.onecmd("(defconstant fee 400)")
    assert "'fee' is already defined" in capsys.readouterr().out
    shell.onecmd("(defun pay (N) N)")
    shell.onecmd("def pay (q . 1)")
    assert "'pay' is already defined" in capsys.readouterr().out
    shell.onecmd("def SEAL (q . 1)")
    assert "reserved by the language" in capsys.readouterr().out
    shell.onecmd("def list (q . 1)")
    assert "reserved by the language" in capsys.readouterr().out


def test_undef_removes_declarations(shell, capsys):
    shell.onecmd("(defun keep (N) N)")
    shell.onecmd("undef keep")
    shell.onecmd("(keep 1)")
    assert "unknown name 'keep'" in capsys.readouterr().out


def test_defs_lists_all_three_kinds(shell, capsys):
    shell.onecmd("def raw (q . 1)")
    shell.onecmd("(defconstant FEE 500)")
    shell.onecmd("(defun double (N) (* 2 N))")
    shell.onecmd("defs")
    assert capsys.readouterr().out == (
        "raw = (q . 1)\n(defconstant FEE 500)\n(defun double (N) (* 2 N))\n"
    )


def test_compile_command_shows_canonical_text(shell, capsys):
    shell.onecmd("(defun double (N) (* 2 N))")
    shell.onecmd("compile (double 3)")
    assert capsys.readouterr().out == (
        "(a (q 2 2 (c 2 (c (q . 3) ()))) (c (q 18 (q . 2) 5) 1))\n"
    )


def test_debugger_names_compiled_functions(shell, capsys):
    shell.onecmd("(defun fact (N) (if (= N 1) 1 (* N (fact (- N 1)))))")
    shell.onecmd("debug (fact 3)")
    capsys.readouterr()
    seen = ""
    while shell.session is not None:
        shell.onecmd("step")
        out = capsys.readouterr().out
        if "eval fact [N=3]" in out:
            seen = out
            break
    assert "eval fact [N=3]" in seen
    shell.onecmd("abort")
    capsys.readouterr()


def test_sym_load_names_foreign_bytecode(shell, tmp_path, capsys):
    import json as _json

    from bitlisp_tools.compiler import compile_program, symbols_to_json

    source = "(program (X) (defun double (N) (* 2 N)) (double X))"
    _, table = compile_program(source)
    path = tmp_path / "double.sym"
    path.write_text(_json.dumps(symbols_to_json(table)))
    shell.onecmd(f"sym {path}")
    assert "1 function name(s) loaded" in capsys.readouterr().out
    shell.onecmd("debug (program (X) (defun double (N) (* 2 N)) (double X)) (21)")
    out = capsys.readouterr().out
    assert "(q . double)" in out
    shell.onecmd("abort")
    capsys.readouterr()


def test_sym_rejects_bad_file(shell, tmp_path, capsys):
    path = tmp_path / "bad.sym"
    path.write_text('{"schema": "wrong"}')
    shell.onecmd(f"sym {path}")
    assert capsys.readouterr().out.startswith("error: ")


def test_source_file_with_declarations(shell, tmp_path, capsys):
    path = tmp_path / "defs.bl"
    path.write_text(
        "(defconstant FEE 500)\n(defun charge (AMT) (- AMT FEE))\n(charge 1200)\n"
    )
    shell.onecmd(f"source {path}")
    assert capsys.readouterr().out.startswith("700\n")


def test_spend_accepts_compiled_program(shell, ctx_file, capsys):
    shell.onecmd(f"tx {ctx_file}")
    capsys.readouterr()
    shell.onecmd(f"spend (program () (list (list CREATE_OUTPUT 0x{SPK_P2WPKH} 600)))")
    out = capsys.readouterr().out
    assert "CREATE_OUTPUT" in out
    assert "valid: 1 condition(s)" in out


def test_defconstant_opcode_valued_atom_displays_as_value(shell, capsys):
    # 16 is the + opcode byte, and a constant's value is data, so
    # the listing must show the number the user typed.
    shell.onecmd("(defconstant SIXTEEN 16)")
    shell.onecmd("defs")
    assert capsys.readouterr().out == "(defconstant SIXTEEN 16)\n"


def test_deferred_body_error_names_its_function(shell, capsys):
    shell.onecmd("(defun broken (N) (+ N MISSING))")
    assert capsys.readouterr().out == ""
    shell.onecmd("(broken 1)")
    out = capsys.readouterr().out
    assert "in 'broken':" in out
    assert "unknown name 'MISSING'" in out


# Currying and identity.

PATHS_HASH = "19c7b1ed29e8f501f6985cd6addd3b6e5bd7ccc251f1a4018550837b3006239b"


def test_curry_prints_canonical_text(shell, capsys):
    shell.onecmd("curry (+ 2 5) 10")
    assert capsys.readouterr().out == "(a (q 16 2 5) (c (q . 10) 1))\n"


def test_curry_zero_values(shell, capsys):
    shell.onecmd("curry (+ 2 5)")
    assert capsys.readouterr().out == "(a (q 16 2 5) 1)\n"


def test_curry_output_evals(shell, capsys):
    shell.onecmd("eval (a (q 16 2 5) (c (q . 10) 1)) (32)")
    assert capsys.readouterr().out == f"42\ncost: 1082 of {BUDGET}\n"


def test_curry_takes_at_least_a_program(shell, capsys):
    shell.onecmd("curry")
    assert capsys.readouterr().out.startswith("error: curry takes a program")


def test_curry_compiles_language_source(shell, capsys):
    shell.onecmd("curry (program (X Y) (* X Y)) 6")
    out = capsys.readouterr().out
    shell.onecmd(f"eval {out.strip()} (7)")
    assert capsys.readouterr().out == f"42\ncost: 1326 of {BUDGET}\n"


def test_curry_values_stay_data(shell, capsys):
    # The program half compiles, so the whole line takes the
    # language reading, where a value is data exactly as a
    # solution is: a name inside one is an error.
    shell.onecmd("(defconstant FEE 400)")
    shell.onecmd("curry (program (X) (- X FEE)) FEE")
    out = capsys.readouterr().out
    assert out.startswith("error: ")
    assert "'FEE' in a fixed value" in out


def test_curry_def_binding_participates_raw(shell, capsys):
    # Under a def binding the line parses raw, so the bound name
    # splices into program and value alike.
    shell.onecmd("def ten (q . 10)")
    shell.onecmd("curry (+ 2 5) ten")
    assert capsys.readouterr().out == "(a (q 16 2 5) (c (q 1 . 10) 1))\n"


def test_uncurry_round_trips(shell, capsys):
    shell.onecmd("uncurry (a (q 16 2 5) (c (q . 10) 1))")
    assert capsys.readouterr().out == "program: (+ 2 5)\nvalue: 10\n"


def test_uncurry_zero_value_curry(shell, capsys):
    shell.onecmd("uncurry (a (q 16 2 5) 1)")
    assert capsys.readouterr().out == "program: (+ 2 5)\n"


def test_uncurry_not_curried_prints_error(shell, capsys):
    shell.onecmd("uncurry (+ 2 5)")
    assert capsys.readouterr().out == "error: not a curried program\n"


def test_uncurry_takes_one_program(shell, capsys):
    shell.onecmd("uncurry (+ 2 5) (+ 2 5)")
    assert capsys.readouterr().out.startswith("error: uncurry takes one program")


def test_hash_prints_the_tree_hash(shell, capsys):
    shell.onecmd("hash (+ 2 5)")
    assert capsys.readouterr().out == PATHS_HASH + "\n"


def test_hash_of_compiled_source_matches_compile_flag(shell, capsys):
    # The same digest bitlisp-compile -H prints for this program,
    # so identity does not depend on the entry point.
    shell.onecmd("hash (program (X Y) (* X Y))")
    out = capsys.readouterr().out.strip()
    from bitlisp_tools import cli

    assert cli.compile_main(["(program (X Y) (* X Y))", "-H"]) == 0
    assert capsys.readouterr().out.strip() == out


def test_hash_takes_one_program(shell, capsys):
    shell.onecmd("hash")
    assert capsys.readouterr().out.startswith("error: ")


def test_curry_then_debug_keeps_symbol_names(shell, capsys):
    # Currying wraps the compiled tree without touching the
    # function bodies inside, so the in-REPL compile registers
    # double and the debugger still renames it in the curried tree.
    source = "(program (X Y) (defun double (N) (* 2 N)) (double (* X Y)))"
    shell.onecmd(f"curry {source} 3")
    curried = capsys.readouterr().out.strip()
    shell.onecmd(f"debug {curried} (7)")
    capsys.readouterr()
    shell.onecmd("trace")
    out = capsys.readouterr().out
    assert "result: 42" in out
    assert "double" in out
