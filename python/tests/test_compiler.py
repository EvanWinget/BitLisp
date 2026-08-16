"""Compiler tests: codegen pins, compile-and-run against the
reference VM, the condition-constant table pin, symbol table
round-trips, and the error paths."""

import json
import sys
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from bitlisp import deserialize, run, serialize  # noqa: E402
from bitlisp.conditions import CONDITION_COSTS  # noqa: E402
from bitlisp.errors import BitLispError  # noqa: E402
from bitlisp.sexp import NIL, int_to_atom  # noqa: E402
from bitlisp_tools import assemble, disassemble  # noqa: E402
from bitlisp_tools.compiler import (  # noqa: E402
    CONDITION_CONSTANTS,
    RESERVED_WORDS,
    CompileError,
    Definitions,
    bind_values,
    compile_expression,
    compile_program,
    load_symbols,
    parse_source,
    source_text,
    symbols_to_json,
    tree_hash,
)
from bitlisp_tools.runner import load_context, run_spend  # noqa: E402

BUDGET = 11_000_000_000


def _run_program(source, solution_text="()"):
    program, table = compile_program(source)
    cost, result = run(program, assemble(solution_text), BUDGET)
    return program, table, result


def _defs(*declarations):
    defs = Definitions()
    for declaration in declarations:
        tree = parse_source(declaration)
        if declaration.startswith("(defun"):
            defs.add_defun(tree)
        else:
            defs.add_defconstant(tree)
    return defs


# The CONDITIONS.md section 2 table, transcribed row by row so a
# vocabulary change must be made here too, in the test_syntax
# doc-table style.
CONDITION_TABLE_ROWS = [
    (0x01, "CREATE_OUTPUT"),
    (0x02, "CREATE_OUTPUT_TAPROOT"),
    (0x10, "ASSERT_SIG_MY_TXID"),
    (0x11, "ASSERT_SIG_MY_SCRIPTPUBKEY"),
    (0x12, "ASSERT_SIG_MY_AMOUNT"),
    (0x13, "ASSERT_SIG_MY_SCRIPTPUBKEY_AMOUNT"),
    (0x14, "ASSERT_SIG_MY_TXID_AMOUNT"),
    (0x15, "ASSERT_SIG_MY_TXID_SCRIPTPUBKEY"),
    (0x16, "ASSERT_SIG_RAW"),
    (0x17, "ASSERT_SIG_MY_OUTPOINT"),
    (0x20, "ASSERT_LOCKTIME_HEIGHT"),
    (0x21, "ASSERT_LOCKTIME_TIME"),
    (0x22, "ASSERT_SEQUENCE_HEIGHT"),
    (0x23, "ASSERT_SEQUENCE_TIME"),
    (0x30, "ASSERT_MY_OUTPOINT"),
    (0x31, "ASSERT_MY_TXID"),
    (0x32, "ASSERT_MY_SCRIPTPUBKEY"),
    (0x33, "ASSERT_MY_AMOUNT"),
    (0x37, "ASSERT_MY_TAPROOT"),
    (0x40, "ANNOUNCE"),
    (0x41, "ASSERT_ANNOUNCEMENT"),
    (0x42, "SEND_MESSAGE"),
    (0x43, "RECEIVE_MESSAGE"),
    (0x50, "RESERVE_FEE"),
    (0x60, "SEAL"),
    (0x61, "SEAL_OUTPUTS"),
]


def test_condition_constants_match_spec_table():
    assert len(CONDITION_TABLE_ROWS) == 26
    assert CONDITION_CONSTANTS == {
        name: int_to_atom(opcode) for opcode, name in CONDITION_TABLE_ROWS
    }


def test_condition_constants_cover_the_costed_vocabulary():
    table = {opcode for opcode, _ in CONDITION_TABLE_ROWS}
    assert table == set(CONDITION_COSTS)


# Exact codegen pins.


def test_pin_single_function():
    program, _, result = _run_program(
        "(program (X) (defun double (N) (* 2 N)) (double X))", "(21)"
    )
    assert disassemble(program) == "(a (q 2 2 (c 2 (c 5 ()))) (c (q 18 (q . 2) 5) 1))"
    assert result == int_to_atom(42)


def test_pin_two_functions_balanced_tree():
    source = """(program (X Y)
        (defun square (N) (* N N))
        (defun hyp (A B) (+ (square A) (square B)))
        (hyp X Y))"""
    program, table, result = _run_program(source, "(3 4)")
    # Two functions split into the pair (square . hyp) in declaration
    # order: square at path 4, hyp at 6, main args at 5 and 11.
    assert disassemble(program) == (
        "(a (q 2 6 (c 2 (c 5 (c 11 ())))) "
        "(c (q (* 5 5) 16 (a 4 (c 2 (c 5 ()))) (a 4 (c 2 (c 11 ())))) 1))"
    )
    assert result == int_to_atom(25)
    assert sorted(name for name, _ in table["functions"].values()) == [
        "hyp",
        "square",
    ]


def test_pin_no_functions_emits_bare():
    program, _, result = _run_program("(program (X Y) (+ X Y))", "(2 3)")
    assert disassemble(program) == "(+ 2 5)"
    assert result == int_to_atom(5)


def test_pin_if_shape():
    program, _, _ = _run_program("(program (X) (if X 1 2))", "(1)")
    assert disassemble(program) == "(a (i 2 (q 1 . 1) (q 1 . 2)) 1)"


def test_pin_list_and_nil():
    program, _, result = _run_program("(program () (list 1 () (list)))")
    assert disassemble(program) == "(c (q . 1) (c () (c () ())))"
    assert result == assemble("(1 () ())")


def test_pin_constant_inlines():
    program, _, result = _run_program(
        "(program (AMT) (defconstant FEE 500) (- AMT FEE))", "(1200)"
    )
    assert disassemble(program) == "(- 2 (q . 500))"
    assert result == int_to_atom(700)


def test_pin_condition_constant_inlines():
    program, _, _ = _run_program("(program () CREATE_OUTPUT)")
    assert disassemble(program) == "(q . 1)"


def test_pin_assert_shapes():
    # One operand has nothing to check and compiles bare. Each
    # condition adds one lazy if level whose untaken branch is the
    # raise.
    program, _, _ = _run_program("(program (V) (assert V))", "(1)")
    assert disassemble(program) == "2"
    program, _, _ = _run_program("(program (C V) (assert C V))", "(1 7)")
    assert disassemble(program) == "(a (i 2 (q . 5) (q 8)) 1)"
    program, _, _ = _run_program("(program (C1 C2 V) (assert C1 C2 V))", "(1 1 7)")
    assert disassemble(program) == "(a (i 2 (q 2 (i 5 (q . 11) (q 8)) 1) (q 8)) 1)"


def test_pin_and_shapes():
    # Empty and is the constant 1. Single-operand and and or emit
    # the identical boolean-normalizing tree, pinned in both tests
    # so a value-returning regression fails loudly.
    program, _, _ = _run_program("(program (A) (and))", "(1)")
    assert disassemble(program) == "(q . 1)"
    program, _, _ = _run_program("(program (A) (and A))", "(1)")
    assert disassemble(program) == "(a (i 2 (q 1 . 1) (q)) 1)"
    program, _, _ = _run_program("(program (A B) (and A B))", "(1 1)")
    assert disassemble(program) == "(a (i 2 (q 2 (i 5 (q 1 . 1) (q)) 1) (q)) 1)"


def test_pin_or_shapes():
    # Empty or is bare nil, the one-byte emission every nil literal
    # gets.
    program, _, _ = _run_program("(program (A) (or))", "(1)")
    assert disassemble(program) == "()"
    program, _, _ = _run_program("(program (A) (or A))", "(1)")
    assert disassemble(program) == "(a (i 2 (q 1 . 1) (q)) 1)"
    program, _, _ = _run_program("(program (A B) (or A B))", "(1 1)")
    assert disassemble(program) == "(a (i 2 (q 1 . 1) (q 2 (i 5 (q 1 . 1) (q)) 1)) 1)"


# Compile-and-run: language constructs against the reference VM.


def test_recursion():
    source = """(program (N)
        (defun fact (N) (if (= N 1) 1 (* N (fact (- N 1)))))
        (fact N))"""
    _, _, result = _run_program(source, "(6)")
    assert result == int_to_atom(720)


def test_mutual_recursion():
    source = """(program (N)
        (defun even (N) (if (= N 0) 1 (odd (- N 1))))
        (defun odd (N) (if (= N 0) 0 (even (- N 1))))
        (even N))"""
    for value, expect in ((7, NIL), (8, int_to_atom(1))):
        program, _, _ = _run_program(source, f"({value})")
        cost, result = run(program, (int_to_atom(value), NIL), BUDGET)
        assert result == expect


def test_if_is_lazy():
    # The untaken branch raises, so the eager i operator would fail
    # and only a lazy if can produce a value.
    _, _, result = _run_program("(program (X) (if X 7 (x)))", "(1)")
    assert result == int_to_atom(7)
    _, _, result = _run_program("(program (X) (if X (x) 9))", "(())")
    assert result == int_to_atom(9)


def test_assert_passes_its_value_and_raises_on_falsy():
    program, _, result = _run_program("(program (X) (assert X (* X 3)))", "(14)")
    assert result == int_to_atom(42)
    with pytest.raises(BitLispError) as excinfo:
        run(program, assemble("(())"), BUDGET)
    assert excinfo.value.code == "user_raise"


def test_and_or_are_boolean_and_lazy():
    # The result is 1 or nil, never an operand value, and the
    # guarded raise proves the short circuit: an eager reading
    # would fail.
    _, _, result = _run_program("(program () (and 1 2))")
    assert result == int_to_atom(1)
    _, _, result = _run_program("(program () (or () 3))")
    assert result == int_to_atom(1)
    _, _, result = _run_program("(program (X) (and X (x)))", "(())")
    assert result == NIL
    _, _, result = _run_program("(program (X) (or X (x)))", "(1)")
    assert result == int_to_atom(1)


def test_destructured_parameters():
    source = "(program ((A B) C) (+ A (* B C)))"
    program, _, _ = _run_program(source, "((2 3) 10)")
    cost, result = run(program, assemble("((2 3) 10)"), BUDGET)
    assert result == int_to_atom(32)


def test_dotted_and_bare_parameters():
    _, _, result = _run_program(
        "(program (HEAD . REST) (defun second ((A . B)) (f B)) (second REST))",
        "(1 2 3)",
    )
    assert result == int_to_atom(3)
    _, _, result = _run_program("(program ALL (f ALL))", "(9 8)")
    assert result == int_to_atom(9)


def test_function_arguments_evaluate():
    _, _, result = _run_program(
        "(program (X) (defun add1 (N) (+ N 1)) (add1 (add1 (* X X))))", "(4)"
    )
    assert result == int_to_atom(18)


def test_native_sha256tree():
    program, _, result = _run_program("(program (X) (sha256tree X))", "((1 2))")
    cost, expected = run(assemble("(sha256tree 1)"), assemble("(1 2)"), BUDGET)
    cost, got = run(program, assemble("((1 2))"), BUDGET)
    assert got == tree_hash(assemble("(1 2)")) == expected


def test_quote_passes_structure_verbatim():
    _, _, result = _run_program("(program () (f (q 7 8)))")
    assert result == int_to_atom(7)


def test_operator_names_stay_operators_and_atoms_self_quote():
    _, _, result = _run_program("(program () (c 16 (q . ())))")
    # The decimal 16 is + only in operator position, data here.
    assert result == (int_to_atom(16), NIL)


def test_explicit_apply_compiles():
    _, _, result = _run_program("(program (P) (a P (q 2 3)))", "((+ 2 5))")
    assert result == int_to_atom(5)


def test_unused_functions_prune():
    lean, _, _ = _run_program("(program (X) (defun keep (N) N) (keep X))", "(1)")
    padded, _, _ = _run_program(
        "(program (X) (defun keep (N) N) (defun drop (N) (drop N)) (keep X))",
        "(1)",
    )
    assert serialize(lean) == serialize(padded)


def test_expression_compiles_against_session_definitions():
    defs = _defs("(defun triple (N) (* 3 N))", "(defconstant BASE 100)")
    program, table = compile_expression("(+ BASE (triple 7))", defs)
    cost, result = run(program, NIL, BUDGET)
    assert result == int_to_atom(121)
    assert table["main_params"] is None


def test_spend_pipeline_accepts_compiled_conditions():
    source = """(program (SCRIPT AMT)
        (defconstant FEE 400)
        (list (list CREATE_OUTPUT SCRIPT (- AMT FEE))))"""
    program, _ = compile_program(source)
    context = load_context(
        {
            "version": 2,
            "locktime": 0,
            "inputs": [
                {
                    "txid": "11" * 32,
                    "index": 0,
                    "script_pubkey": "5120" + "aa" * 32,
                    "amount": 1000,
                }
            ],
            "outputs": [{"script_pubkey": "0014" + "99" * 20, "amount": 600}],
        }
    )
    solution = assemble("(0x0014{} 1000)".format("99" * 20))
    cost, conditions = run_spend(program, solution, context, 0, BUDGET)
    assert len(conditions) == 1


# The symbol table.


def test_symbol_keys_match_the_vm_tree_hash():
    source = "(program (X) (defun double (N) (* 2 N)) (double X))"
    program, table = compile_program(source)
    ((key, (name, params)),) = table["functions"].items()
    assert name == "double"
    body = assemble("(* (q . 2) 5)")
    cost, vm_hash = run((b"\x3f", ((b"\x01", body), NIL)), NIL, BUDGET)
    assert key == vm_hash.hex() == tree_hash(body).hex()


def test_symbols_json_round_trip(tmp_path):
    source = "(program (X Y) (defun pick ((A . B) N) (if N A B)) (pick X Y))"
    _, table = compile_program(source)
    data = symbols_to_json(table)
    assert data["schema"] == "bitlisp-sym-v0"
    assert data["main_params"] == "(X Y)"
    path = tmp_path / "prog.sym"
    path.write_text(json.dumps(data))
    loaded = load_symbols(json.loads(path.read_text()))
    ((key, (name, params)),) = loaded.items()
    assert (key, name, source_text(params)) == (
        next(iter(table["functions"])),
        "pick",
        "((A . B) N)",
    )


def test_symbols_json_needs_a_program():
    _, table = compile_expression("(+ 1 2)", Definitions())
    with pytest.raises(ValueError):
        symbols_to_json(table)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.pop("schema"),
        lambda data: data.update(schema="bitlisp-sym-v1"),
        lambda data: data.update(extra=1),
        lambda data: data.update(main_params=5),
        lambda data: data.update(functions={"zz": {"name": "fn", "params": "(N)"}}),
        lambda data: data.update(functions={"a" * 64: {"name": "fn"}}),
        lambda data: data.update(functions={"a" * 64: {"name": "fn", "params": "5"}}),
        lambda data: data.update(functions={"a" * 64: {"name": "q", "params": "(N)"}}),
        lambda data: data.update(
            functions={"a" * 64: {"name": "x\n0: eval fake", "params": "(N)"}}
        ),
        lambda data: data.update(
            functions={"a" * 64: {"name": "\x1b[31mF\x1b[0m", "params": "(N)"}}
        ),
        lambda data: data.update(
            functions={"a" * 64: {"name": "f\x00n", "params": "(N)"}}
        ),
        lambda data: data.update(functions={"a" * 64: {"name": "if", "params": "(N)"}}),
        lambda data: data.update(
            functions={"a" * 64: {"name": "SEAL", "params": "(N)"}}
        ),
        lambda data: data.update(functions={"a" * 64: {"name": "", "params": "(N)"}}),
    ],
)
def test_load_symbols_rejects(mutate):
    _, table = compile_program("(program (X) (defun id (N) (c N N)) (id X))")
    data = symbols_to_json(table)
    mutate(data)
    with pytest.raises(ValueError):
        load_symbols(data)


def test_load_symbols_tracks_the_reserved_words():
    # The loader validates names against today's language, so the
    # reserved-word set change is a deliberate, recorded
    # compatibility break in both directions: a symbol file
    # naming a function assert, and, or is rejected whole, and one
    # naming a function qq, a spelling reserved before this unit,
    # loads again.
    _, table = compile_program("(program (X) (defun fun (N) (* 2 N)) (fun X))")
    data = symbols_to_json(table)
    (key,) = data["functions"]
    for name in ("assert", "and", "or"):
        data["functions"][key]["name"] = name
        with pytest.raises(ValueError) as excinfo:
            load_symbols(data)
        assert "malformed function name" in str(excinfo.value)
    data["functions"][key]["name"] = "qq"
    assert load_symbols(data)[key][0] == "qq"


def test_atom_bodies_stay_out_of_the_table():
    _, table = compile_program("(program (X) (defun own (N) N) (c (own X) X))")
    assert table["functions"] == {}


def test_bind_values():
    params = parse_source("((A . B) C)")
    env = (b"tree", ((int_to_atom(1), int_to_atom(2)), (int_to_atom(3), NIL)))
    assert bind_values(params, env) == {
        "A": int_to_atom(1),
        "B": int_to_atom(2),
        "C": int_to_atom(3),
    }
    assert bind_values(params, (b"tree", (int_to_atom(1), NIL))) is None
    assert bind_values(params, b"atom") is None


def test_parameters_shadow_constants_and_functions():
    source = """(program (X)
        (defconstant K 5)
        (defun bump (K) (+ K 1))
        (bump X))"""
    _, _, result = _run_program(source, "(10)")
    assert result == int_to_atom(11)
    source = """(program (X)
        (defun own (N) (c N N))
        (defun wrap (own) (c own ()))
        (wrap X))"""
    _, _, result = _run_program(source, "(7)")
    assert result == (int_to_atom(7), NIL)


def test_pair_defconstant_binds_the_tree_verbatim():
    _, _, result = _run_program("(program () (defconstant K (+ 1 2)) K)")
    assert result == assemble("(+ 1 2)")
    assert result != int_to_atom(3)


def test_variadic_call_binds_the_rest():
    source = "(program (X) (defun spread (A . REST) REST) (spread X 2 3))"
    _, _, result = _run_program(source, "(1)")
    assert result == assemble("(2 3)")
    source = "(program (X) (defun spread (A . REST) REST) (spread X))"
    _, _, result = _run_program(source, "(1)")
    assert result == NIL


# Error paths.


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("(+ 1 2)", "must be a (program ...) form"),
        ("(program (X))", "program takes parameters"),
        ("(program (X) (defun fun (N) N) (fun X) (fun X))", "expected defun"),
        ("(program (X) (deffun fun (N) N) (fun X))", "expected defun"),
        ("(program (X X) X)", "duplicate parameter"),
        ("(program (5) 1)", "parameter must be a bare name"),
        ("(program (if) 1)", "reserved word"),
        ("(program (CREATE_OUTPUT) 1)", "condition constant"),
        ("(program (X) (defun f (N) N) X)", "name must be a bare name"),
        (
            "(program (X) (defun fun (N) N) (defun fun (N) N) (fun X))",
            "already defined",
        ),
        (
            "(program (X) (defun fun (N) N) (defconstant fun 1) (fun X))",
            "already defined",
        ),
        ("(program (X) (defconstant K Y) K)", "'Y' in a defconstant value"),
        ("(program (X) (defun fun (N) N) (fun))", "'fun' takes 1 argument(s)"),
        ("(program (X) (defun fun (A . B) N) (fun))", "at least 1 argument(s)"),
        ("(program (X) (q . X))", "'X' in quoted content"),
        ("(program (X) Y)", "unknown name 'Y'"),
        ("(program (X) (Y 1))", "unknown name 'Y'"),
        ("(program (X) (defun fun (N) N) (c fun X))", "'fun' used as a value"),
        ("(program (X) (defconstant K 1) (K 2))", "'K' is a constant"),
        ("(program (X) (X 1))", "'X' is a parameter"),
        (
            "(program (X) (defun own (N) N) (defun wrap (own) (own 1)) (wrap X))",
            "'own' is a parameter, not a function",
        ),
        ("(program (X) (defun fun (N) N) (fun 1 . 2))", "proper argument list"),
        ("(program (X) (+ 1 . 2))", "proper argument list"),
        ("(program (X) (0x99 1))", "unknown operator 0x99"),
        ("(program (X) (() 1))", "unknown operator ()"),
        (
            "(program (X) (defun fun (N) MISSING) (fun X))",
            "in 'fun': unknown name 'MISSING'",
        ),
        ("(program (X) ((f 1) 2))", "expression in operator position"),
        ("(program (X) (if X 1))", "if takes a condition and two branches"),
        ("(program (X) (program (Y) Y))", "program form is not an expression"),
        ("(program (X) (defun list (N) N) X)", "reserved word"),
        ("(program (X) (defun SEAL (N) N) X)", "condition constant"),
        ("(program (X) (defun f N) X)", "defun takes 3 parts"),
        ("(program (X) (defconstant K) X)", "defconstant takes 2 parts"),
        ("(program (X) (assert))", "assert takes conditions and a final value"),
        ("(program (assert) 1)", "'assert' is a reserved word"),
        ("(program (X) (defun and (N) N) X)", "'and' is a reserved word"),
        ("(program (X) (defconstant or 1) X)", "'or' is a reserved word"),
    ],
)
def test_compile_errors(source, message):
    with pytest.raises(CompileError) as excinfo:
        compile_program(source)
    assert message in str(excinfo.value)


def test_reserved_opcode_head_is_rejected():
    with pytest.raises(CompileError) as excinfo:
        compile_program("(program (X) (0x80 X))")
    assert "unknown operator 0x80" in str(excinfo.value)


def test_definitions_taken_names_conflict():
    defs = Definitions()
    with pytest.raises(CompileError) as excinfo:
        defs.add_defun(parse_source("(defun fee (N) N)"), taken={"fee"})
    assert "'fee' is already defined" in str(excinfo.value)


def test_reserved_words_are_pinned_and_all_dispatch():
    # The literal set, transcribed like the condition-name table, so
    # growing the language forces this test to grow with it. Every
    # reserved word must mean something in head position: a fixed
    # form added to dispatch but not the reserved set would let one
    # spelling be claimed as a definition and hijacked at its call
    # sites, one spelling meaning two things.
    assert RESERVED_WORDS == frozenset(
        {"program", "defun", "defconstant", "if", "list", "assert", "and", "or"}
    )
    for word in sorted(RESERVED_WORDS):
        try:
            compile_program(f"(program (X) ({word}))")
        except CompileError as exc:
            assert "unknown name" not in str(exc)


# Properties.

_atoms = st.binary(max_size=24)


@given(_atoms)
def test_literals_round_trip_through_compile_and_run(atom):
    defs = Definitions()
    literal = "0x" + atom.hex() if atom else "()"
    program, _ = compile_expression(f"(c {literal} ())", defs)
    cost, result = run(program, NIL, BUDGET)
    assert result == (atom, NIL)


@given(st.lists(st.integers(min_value=0, max_value=2**63 - 1), max_size=6))
def test_list_builds_the_literal_list(values):
    defs = Definitions()
    text = "(list {})".format(" ".join(str(value) for value in values))
    program, _ = compile_expression(text, defs)
    cost, result = run(program, NIL, BUDGET)
    expected = NIL
    for value in reversed(values):
        expected = (int_to_atom(value), expected)
    assert result == expected


@given(st.lists(st.integers(min_value=0, max_value=3), max_size=6))
def test_and_or_match_all_and_any(values):
    # The boolean value semantics against Python's own fold, empty
    # lists included, pinning that no operand value ever leaks out.
    defs = Definitions()
    spelled = " ".join(str(value) for value in values)
    program, _ = compile_expression(f"(and {spelled})", defs)
    _, result = run(program, NIL, BUDGET)
    assert result == (int_to_atom(1) if all(values) else NIL)
    program, _ = compile_expression(f"(or {spelled})", defs)
    _, result = run(program, NIL, BUDGET)
    assert result == (int_to_atom(1) if any(values) else NIL)


_node_trees = st.recursive(
    st.binary(max_size=8), lambda child: st.tuples(child, child), max_leaves=25
)


@given(_node_trees)
def test_compiled_output_survives_serialization(node):
    # Any tree spells as a quoted literal through the canonical
    # printer, so the property covers arbitrary compiled structure:
    # the artifact round-trips the wire format and still computes
    # the literal.
    source = f"(program () (c (q . {disassemble(node)}) ()))"
    program, _ = compile_program(source)
    assert deserialize(serialize(program)) == program
    cost, result = run(program, NIL, BUDGET)
    assert result == (node, NIL)


def test_recursive_compiled_output_runs():
    source = """(program (N)
        (defun down (N) (if (= N 0) () (c N (down (- N 1)))))
        (down N))"""
    program, _ = compile_program(source)
    assert deserialize(serialize(program)) == program
    cost, result = run(program, (int_to_atom(9), NIL), BUDGET)
    count = 0
    while result != NIL:
        count += 1
        result = result[1]
    assert count == 9


def test_runtime_errors_stay_pinned():
    program, _ = compile_program("(program (X) (/ X 0))")
    with pytest.raises(BitLispError) as excinfo:
        run(program, (int_to_atom(4), NIL), BUDGET)
    assert excinfo.value.code == "div_by_zero"
