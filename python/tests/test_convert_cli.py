"""The one-shot command tests: bitlisp-asm, bitlisp-disasm,
bitlisp-compile, bitlisp-curry, bitlisp-uncurry, bitlisp-commit, the
tree-hash flag, and the corpus pin."""

import io
import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from bitlisp_tools import cli  # noqa: E402

# The published add_2_3 vector, both spellings.
ADD_HEX = "ff10ffff0102ffff010380"
ADD_TEXT = "(+ (q . 2) (q . 3))"


# The commands, literal arguments.


def test_asm_literal(capsys):
    assert cli.asm_main([ADD_TEXT]) == 0
    assert capsys.readouterr().out == ADD_HEX + "\n"


def test_disasm_literal(capsys):
    assert cli.disasm_main([ADD_HEX]) == 0
    assert capsys.readouterr().out == ADD_TEXT + "\n"


def test_asm_atom(capsys):
    assert cli.asm_main(["(q . 1)"]) == 0
    assert capsys.readouterr().out == "ff0101\n"


def test_disasm_whitespace_padded_hex(capsys):
    assert cli.disasm_main([f"  {ADD_HEX}\n"]) == 0
    assert capsys.readouterr().out == ADD_TEXT + "\n"


# File arguments.


def test_asm_file(tmp_path, capsys):
    path = tmp_path / "add.bl"
    path.write_text(ADD_TEXT)
    assert cli.asm_main([str(path)]) == 0
    assert capsys.readouterr().out == ADD_HEX + "\n"


def test_disasm_file(tmp_path, capsys):
    path = tmp_path / "add.hex"
    path.write_text(ADD_HEX + "\n")
    assert cli.disasm_main([str(path)]) == 0
    assert capsys.readouterr().out == ADD_TEXT + "\n"


def test_asm_directory_exit_two(tmp_path, capsys):
    assert cli.asm_main([str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("error: ")


# Stdin, the default input.


def test_asm_stdin(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(ADD_TEXT + "\n"))
    assert cli.asm_main([]) == 0
    assert capsys.readouterr().out == ADD_HEX + "\n"


def test_disasm_stdin(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(ADD_HEX + "\n"))
    assert cli.disasm_main([]) == 0
    assert capsys.readouterr().out == ADD_TEXT + "\n"


# Rejected input, always exit 2. Exit 1 is reserved for a consensus
# verdict about a spend, which the converters never issue.


def test_asm_parse_error_exit_two(capsys):
    assert cli.asm_main(["(+ 1"]) == 2
    assert capsys.readouterr().err.startswith("error: missing )")


def test_asm_empty_input_exit_two(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.asm_main([]) == 2
    assert capsys.readouterr().err.startswith("error: empty input")


def test_asm_non_utf8_file_exit_two(tmp_path, capsys):
    # Raw bytecode piped or saved by mistake instead of text must
    # exit 2 with an error line, never a traceback.
    path = tmp_path / "raw.bin"
    path.write_bytes(b"\xff\xfe(q . 1)")
    assert cli.asm_main([str(path)]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_asm_non_utf8_stdin_exit_two(capsys, monkeypatch):
    stream = io.TextIOWrapper(io.BytesIO(b"\xff\xfe(q . 1)"), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stream)
    assert cli.asm_main([]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_disasm_non_hex_exit_two(capsys):
    assert cli.disasm_main(["zz"]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_disasm_empty_input_exit_two(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.disasm_main([]) == 2
    assert capsys.readouterr().err.startswith("error: bad_encoding: ")


def test_disasm_truncated_exit_two(capsys):
    assert cli.disasm_main(["ff10"]) == 2
    assert capsys.readouterr().err.startswith("error: bad_encoding: truncated")


def test_disasm_non_minimal_exit_two(capsys):
    # A one-byte atom spelled with the two-byte length prefix. The
    # error line keeps the consensus code for the rejection.
    assert cli.disasm_main(["c00161"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: bad_encoding: non-minimal")


def test_disasm_trailing_bytes_exit_two(capsys):
    assert cli.disasm_main(["8080"]) == 2
    assert capsys.readouterr().err.startswith("error: bad_encoding: trailing")


# The corpus pin: every corpus hex renders to text and assembles
# back to the same bytes through the command mains.


def _corpus_hex():
    collected = []
    for path in sorted((REPO_ROOT / "vectors" / "vm").glob("*.json")):
        if path.name == "serialize.json":
            continue
        for case in json.loads(path.read_text())["cases"]:
            for key in ("program", "env"):
                if key in case:
                    collected.append(case[key])
            if "result" in case.get("expect", {}):
                collected.append(case["expect"]["result"])
    return collected


def test_corpus_round_trip(capsys):
    corpus = _corpus_hex()
    # A floor so a path or key typo cannot silently empty the sweep.
    assert len(corpus) >= 200
    for hex_str in corpus:
        assert cli.disasm_main([hex_str]) == 0
        text = capsys.readouterr().out.rstrip("\n")
        assert cli.asm_main([text]) == 0
        assert capsys.readouterr().out == hex_str.lower() + "\n"


# The command registrations and the pipe behavior.


def test_console_scripts_resolve():
    (entry,) = metadata.entry_points(group="console_scripts", name="bitlisp-asm")
    assert entry.load() is cli.asm_main
    (entry,) = metadata.entry_points(group="console_scripts", name="bitlisp-disasm")
    assert entry.load() is cli.disasm_main
    (entry,) = metadata.entry_points(group="console_scripts", name="bitlisp-commit")
    assert entry.load() is cli.commit_main


# bitlisp-commit: its output against the spend suite's identity cases,
# which were cross-checked against the Bitcoin Core tagged hash.


def _identity_case(name):
    path = REPO_ROOT / "vectors" / "spend" / "identity.json"
    (case,) = [c for c in json.loads(path.read_text())["cases"] if c["name"] == name]
    return case


def _commit_lines(out):
    return dict(line.split(":", 1) for line in out.rstrip("\n").split("\n"))


def test_commit_single_leaf_matches_the_identity_vector(capsys):
    case = _identity_case("single_leaf")
    solution, program, leaf, block = case["witness"]
    assert cli.commit_main([program, "--hex"]) == 0
    lines = {k: v.strip() for k, v in _commit_lines(capsys.readouterr().out).items()}
    assert lines == {
        "leaf script": leaf,
        "tapleaf": case["expect"]["tapleaf"],
        "merkle root": case["expect"]["merkle_root"],
        "internal key": case["expect"]["internal_key"],
        "control block": block,
        "scriptPubKey": case["script_pubkey"],
    }


def test_commit_with_path_and_key_matches_the_identity_vector(capsys):
    case = _identity_case("internal_key_generator_with_path")
    solution, program, leaf, block = case["witness"]
    siblings = [block[66 + 64 * i : 66 + 64 * (i + 1)] for i in range(1)]
    argv = [program, "--hex", "-k", case["expect"]["internal_key"]]
    for sibling in siblings:
        argv += ["-s", sibling]
    assert cli.commit_main(argv) == 0
    lines = {k: v.strip() for k, v in _commit_lines(capsys.readouterr().out).items()}
    assert lines["merkle root"] == case["expect"]["merkle_root"]
    assert lines["control block"] == block
    assert lines["scriptPubKey"] == case["script_pubkey"]


def test_commit_text_program_and_stdin(capsys, monkeypatch):
    # The atom 1 spelled as text and as hex give one leaf script.
    assert cli.commit_main(["1"]) == 0
    from_text = capsys.readouterr().out
    monkeypatch.setattr(sys, "stdin", io.StringIO("01\n"))
    assert cli.commit_main(["--hex"]) == 0
    assert capsys.readouterr().out == from_text
    assert (
        _commit_lines(from_text)["leaf script"].strip() == cli.tree_hash(b"\x01").hex()
    )


def test_commit_rejects_bad_inputs(capsys):
    assert cli.commit_main(["(q . 1"]) == 2
    assert capsys.readouterr().err.startswith("error: ")
    assert cli.commit_main(["1", "-k", "ff" * 32]) == 2
    assert "does not lift" in capsys.readouterr().err
    assert cli.commit_main(["1", "-k", "ab" * 31]) == 2
    assert "32 bytes" in capsys.readouterr().err
    assert cli.commit_main(["1", "-s", "zz"]) == 2
    assert "not hex" in capsys.readouterr().err
    assert cli.commit_main(["c00101", "--hex"]) == 2
    assert capsys.readouterr().err.startswith("error: bad_encoding: ")


def test_asm_broken_pipe_keeps_exit_zero(tmp_path):
    # Output larger than the pipe buffer, and a reader that hangs up
    # without reading. The producer must exit 0 with a silent
    # stderr. The program travels as a file because an atom this
    # large would burst the argv size limit on some platforms.
    path = tmp_path / "big.bl"
    path.write_text("0x" + "ab" * 100_000)
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT / "python"))
    code = "import sys; from bitlisp_tools.cli import asm_main; sys.exit(asm_main())"
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    process.stdout.close()
    stderr = process.stderr.read()
    process.stderr.close()
    assert process.wait() == 0
    assert stderr == b""


# bitlisp-compile.

DOUBLE_SOURCE = "(program (X) (defun double (N) (* 2 N)) (double X))"
DOUBLE_HEX = (
    "ff02ffff01ff02ff02ffff04ff02ffff04ff05ff80808080"
    "ffff04ffff01ff12ffff0102ff0580ff018080"
)


def test_compile_literal(capsys):
    assert cli.compile_main([DOUBLE_SOURCE]) == 0
    assert capsys.readouterr().out == DOUBLE_HEX + "\n"


def test_compile_file(tmp_path, capsys):
    path = tmp_path / "double.bl"
    path.write_text(DOUBLE_SOURCE + "\n")
    assert cli.compile_main([str(path)]) == 0
    assert capsys.readouterr().out == DOUBLE_HEX + "\n"


def test_compile_stdin(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(DOUBLE_SOURCE))
    assert cli.compile_main([]) == 0
    assert capsys.readouterr().out == DOUBLE_HEX + "\n"


def test_compile_include_flag_resolves_and_is_required(tmp_path, capsys):
    (tmp_path / "lib.blib").write_text("((defun double (N) (* 2 N)))")
    source = tmp_path / "p.bl"
    source.write_text('(program (X) (include "lib.blib") (double X))\n')
    assert cli.compile_main([str(source), "-I", str(tmp_path)]) == 0
    included_hex = capsys.readouterr().out
    pasted = "(program (X) (defun double (N) (* 2 N)) (double X))"
    assert cli.compile_main([pasted]) == 0
    assert included_hex == capsys.readouterr().out
    assert cli.compile_main([str(source)]) == 2
    assert "the include search path is empty" in capsys.readouterr().err


def test_compile_include_flag_order_first_match_wins(tmp_path, capsys):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "k.blib").write_text("((defconstant K 1))")
    (second / "k.blib").write_text("((defconstant K 2))")
    source = '(program () (include "k.blib") K)'
    assert cli.compile_main([source, "-I", str(first), "-I", str(second)]) == 0
    winner = capsys.readouterr().out
    assert cli.compile_main(["(program () (defconstant K 1) K)"]) == 0
    assert winner == capsys.readouterr().out


def test_compile_output_disassembles(capsys):
    assert cli.compile_main([DOUBLE_SOURCE]) == 0
    hex_line = capsys.readouterr().out.strip()
    assert cli.disasm_main([hex_line]) == 0
    assert (
        capsys.readouterr().out == "(a (q 2 2 (c 2 (c 5 ()))) (c (q 18 (q . 2) 5) 1))\n"
    )


def test_compile_writes_symbols_only_when_asked(tmp_path, capsys, monkeypatch):
    # Without the flag, nothing lands in the working directory, the
    # clvm_tools always-write-main.sym behavior being declined.
    monkeypatch.chdir(tmp_path)
    assert cli.compile_main([DOUBLE_SOURCE]) == 0
    capsys.readouterr()
    assert list(tmp_path.iterdir()) == []
    sym_path = tmp_path / "double.sym"
    assert cli.compile_main([DOUBLE_SOURCE, "--symbols", str(sym_path)]) == 0
    capsys.readouterr()
    data = json.loads(sym_path.read_text())
    assert data["schema"] == "bitlisp-sym-v0"
    assert data["main_params"] == "(X)"
    ((key, entry),) = data["functions"].items()
    assert entry == {"name": "double", "params": "(N)"}
    assert len(key) == 64


def test_compile_rejects_bare_expression(capsys):
    assert cli.compile_main(["(+ (q . 1) (q . 2))"]) == 2
    assert "must be a (program ...) form" in capsys.readouterr().err


def test_compile_rejects_bad_source(capsys):
    assert cli.compile_main(["(program (X) (undefined X))"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert "unknown name 'undefined'" in err


def test_compile_rejects_unparseable(capsys):
    assert cli.compile_main(["(program (X"]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_compile_console_script_resolves():
    (entry,) = metadata.entry_points(group="console_scripts", name="bitlisp-compile")
    assert entry.load() is cli.compile_main


# The tree-hash flag: the digest names the tree, not the encoding,
# so every command prints the same hash for the same program.

PATHS_TEXT = "(+ 2 5)"
PATHS_HEX = "ff10ff02ff0580"
PATHS_HASH = "19c7b1ed29e8f501f6985cd6addd3b6e5bd7ccc251f1a4018550837b3006239b"
CURRIED_HEX = "ff02ffff01ff10ff02ff0580ffff04ffff010aff018080"
CURRIED_HASH = "8227d2eef6f1cdb6d949e075e8c185d1316af6a65d9241ba473a0e8fc72aa880"


def test_asm_tree_hash_replaces_the_hex(capsys):
    assert cli.asm_main([PATHS_TEXT, "-T"]) == 0
    assert capsys.readouterr().out == PATHS_HASH + "\n"


def test_disasm_tree_hash_replaces_the_text(capsys):
    assert cli.disasm_main([PATHS_HEX, "-T"]) == 0
    assert capsys.readouterr().out == PATHS_HASH + "\n"


def test_compile_tree_hash_matches_disasm(capsys):
    assert cli.compile_main([DOUBLE_SOURCE, "-T"]) == 0
    compiled_hash = capsys.readouterr().out
    assert cli.disasm_main([DOUBLE_HEX, "-T"]) == 0
    assert capsys.readouterr().out == compiled_hash
    assert len(compiled_hash.strip()) == 64


def test_compile_tree_hash_still_writes_symbols(tmp_path, capsys):
    sym_path = tmp_path / "double.sym"
    assert cli.compile_main([DOUBLE_SOURCE, "-T", "--symbols", str(sym_path)]) == 0
    capsys.readouterr()
    assert json.loads(sym_path.read_text())["schema"] == "bitlisp-sym-v0"


# bitlisp-curry and bitlisp-uncurry.


def test_curry_literal(capsys):
    assert cli.curry_main([PATHS_HEX, "-a", "10"]) == 0
    assert capsys.readouterr().out == CURRIED_HEX + "\n"


def test_curry_stdin(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(PATHS_HEX + "\n"))
    assert cli.curry_main(["-a", "10"]) == 0
    assert capsys.readouterr().out == CURRIED_HEX + "\n"


def test_curry_file(tmp_path, capsys):
    path = tmp_path / "add.hex"
    path.write_text(PATHS_HEX + "\n")
    assert cli.curry_main([str(path), "-a", "10"]) == 0
    assert capsys.readouterr().out == CURRIED_HEX + "\n"


def test_curry_tree_hash(capsys):
    assert cli.curry_main([PATHS_HEX, "-a", "10", "-T"]) == 0
    assert capsys.readouterr().out == CURRIED_HASH + "\n"


def test_curry_zero_values(capsys):
    assert cli.curry_main([PATHS_HEX]) == 0
    hex_line = capsys.readouterr().out.strip()
    assert cli.disasm_main([hex_line]) == 0
    assert capsys.readouterr().out == "(a (q 16 2 5) 1)\n"


def test_curry_values_fix_in_order(capsys):
    assert cli.curry_main([PATHS_HEX, "-a", "10", "-a", "0xdead"]) == 0
    hex_line = capsys.readouterr().out.strip()
    assert cli.uncurry_main([hex_line]) == 0
    assert capsys.readouterr().out == PATHS_HEX + "\n10\n-8531\n"


def test_uncurry_literal(capsys):
    assert cli.uncurry_main([CURRIED_HEX]) == 0
    assert capsys.readouterr().out == PATHS_HEX + "\n10\n"


def test_uncurry_stdin(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(CURRIED_HEX + "\n"))
    assert cli.uncurry_main([]) == 0
    assert capsys.readouterr().out == PATHS_HEX + "\n10\n"


def test_uncurry_zero_value_curry_prints_only_the_program(capsys):
    assert cli.curry_main([PATHS_HEX]) == 0
    hex_line = capsys.readouterr().out.strip()
    assert cli.uncurry_main([hex_line]) == 0
    assert capsys.readouterr().out == PATHS_HEX + "\n"


def test_uncurry_not_curried_exit_two(capsys):
    assert cli.uncurry_main([PATHS_HEX]) == 2
    assert capsys.readouterr().err == "error: not a curried program\n"


def test_uncurry_non_hex_exit_two(capsys):
    assert cli.uncurry_main(["zz"]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_curry_non_hex_exit_two(capsys):
    assert cli.curry_main(["zz", "-a", "10"]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_curry_unparseable_value_exit_two(capsys):
    assert cli.curry_main([PATHS_HEX, "-a", "(+ 1"]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_curry_unknown_symbol_value_exit_two(capsys):
    assert cli.curry_main([PATHS_HEX, "-a", "(secret)"]) == 2
    assert "unknown symbol" in capsys.readouterr().err


def test_curry_console_scripts_resolve():
    (entry,) = metadata.entry_points(group="console_scripts", name="bitlisp-curry")
    assert entry.load() is cli.curry_main
    (entry,) = metadata.entry_points(group="console_scripts", name="bitlisp-uncurry")
    assert entry.load() is cli.uncurry_main


def test_asm_pipe_closed_before_write_keeps_exit_zero():
    # The reader hangs up before the child prints, so the output
    # sits in the stream buffer until the shield's closing flush.
    # The failure must surface inside the shield, never at
    # interpreter shutdown, whose failed flush exits 120.
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT / "python"))
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; from bitlisp_tools.cli import asm_main;"
            " sys.exit(asm_main(['(q . 1)']))",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    process.stdout.close()
    stderr = process.stderr.read()
    process.stderr.close()
    assert process.wait() == 0
    assert stderr == b""
