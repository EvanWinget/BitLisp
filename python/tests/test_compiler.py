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
    MACRO_DEPTH_LIMIT,
    MACRO_EXPANSION_LIMIT,
    CompileError,
    Definitions,
    Symbol,
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
        if declaration.startswith("(defmacro"):
            defs.add_defmacro(tree)
        elif declaration.startswith("(defun"):
            defs.add_defun(tree)
        else:
            defs.add_defconstant(tree)
    return defs


# The Chialisp self-splicing idiom, verbatim from the clvm_tools
# regression corpus: the template conses the macro's own name onto
# the shortened argument list, so each expansion round consumes one
# element and the recursion terminates at nil.
LIST1 = (
    "(defmacro list1 args (if args "
    "(qq (c (unquote (f args)) (unquote (c list1 (r args))))) ()))"
)


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


def test_load_symbols_rejects_newly_reserved_names():
    # A symbol file written before this unit may name a function
    # qq, unquote, or defmacro, spellings the compiler accepted
    # then. The loader validates against today's language, so such
    # a file is rejected whole: a deliberate compatibility break,
    # recorded in the execution plan.
    _, table = compile_program("(program (X) (defun fun (N) (* 2 N)) (fun X))")
    data = symbols_to_json(table)
    (key,) = data["functions"]
    for name in ("qq", "unquote", "defmacro"):
        data["functions"][key]["name"] = name
        with pytest.raises(ValueError) as excinfo:
            load_symbols(data)
        assert "malformed function name" in str(excinfo.value)


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


# Macros: expansion runs at compile time on the reference VM over
# the raw unevaluated argument source, classic Chialisp semantics.


def test_pin_macro_constant_folds():
    program, _ = compile_program(
        "(program () (defmacro add (n1 n2) (+ n1 n2)) (add 50 60))"
    )
    assert disassemble(program) == "(q . 110)"


def test_computed_name_collision_is_rejected():
    # 110 spells the letter n. Classic Chialisp would capture: the
    # folded atom becomes a reference to the caller's parameter n.
    # BitLisp's recorded divergence rejects it instead, because the
    # spelling is in scope but the macro never wrote it.
    with pytest.raises(CompileError) as excinfo:
        compile_program("(program (n) (defmacro add (n1 n2) (+ n1 n2)) (add 50 60))")
    assert "0x6e spells 'n', a name the macro never wrote" in str(excinfo.value)


def test_written_names_lift_computed_data_stays():
    # The same fold with no colliding name in scope stays data, so
    # constant folding works, and a spliced caller-written name
    # still lifts: the two evidence sources side by side.
    program, _ = compile_program(
        "(program () (defmacro add (n1 n2) (+ n1 n2)) (add 50 60))"
    )
    assert disassemble(program) == "(q . 110)"
    program, _ = compile_program(
        "(program (n) (defmacro keep (e) (qq (+ (unquote e) 1))) (keep n))"
    )
    assert disassemble(program) == "(+ 2 (q . 1))"


def test_pin_qq_escapes_compile_in_place():
    program, _ = compile_program(
        "(program (X) (defmacro inc (e) (qq (+ (unquote e) 1))) (inc X))"
    )
    assert disassemble(program) == "(+ 2 (q . 1))"


def test_pin_nested_qq_rebuilds_heads_as_data():
    # A nested qq deepens the level, so its unquote does not escape
    # and both heads come back as spellings in the built data.
    _, _, result = _run_program("(program () (qq (qq (unquote (+ 1 2)))))")
    assert result == (
        b"qq",
        ((b"unquote", ((b"\x10", (b"\x01", (b"\x02", NIL))), NIL)), NIL),
    )


def test_pin_list1_macro_matches_builtin_list():
    macro_program, _, macro_result = _run_program(
        f"(program () {LIST1} (list1 300 40 50))"
    )
    builtin_program, _, builtin_result = _run_program("(program () (list 300 40 50))")
    assert macro_program == builtin_program
    assert macro_result == builtin_result


def test_list1_of_nothing_is_nil():
    _, _, result = _run_program(f"(program () {LIST1} (list1))")
    assert result == NIL


def test_macro_depth_boundary_is_exact():
    # A self-splicing call spends one level per argument plus one
    # for the final empty round, so 99 arguments is the last count
    # that compiles under the cap.
    spelled = " ".join("1" for _ in range(99))
    compile_program(f"(program () {LIST1} (list1 {spelled}))")
    with pytest.raises(CompileError) as excinfo:
        compile_program(f"(program () {LIST1} (list1 {spelled} 1))")
    assert f"depth exceeded {MACRO_DEPTH_LIMIT} levels" in str(excinfo.value)


def test_macro_expansion_reaches_a_function():
    # The expansion calls a defun the pre-expansion source never
    # names, so reachability has to run over expanded bodies.
    program, table, result = _run_program(
        "(program (X) (defun dbl (v) (* v 2)) "
        "(defmacro twice (e) (qq (dbl (unquote e)))) (twice X))",
        "(21)",
    )
    assert result == int_to_atom(42)
    assert {name for name, _ in table["functions"].values()} == {"dbl"}


def test_macro_uses_earlier_macro():
    _, _, result = _run_program(
        "(program (X) (defmacro inc (e) (qq (+ (unquote e) 1))) "
        "(defmacro inc2 (e) (qq (inc (inc (unquote e))))) (inc2 X))",
        "(40)",
    )
    assert result == int_to_atom(42)


def test_macro_in_function_body_ignores_declaration_order():
    # A macro body sees only macros declared before it, but a defun
    # body expands when the program compiles, against every macro.
    _, _, result = _run_program(
        "(program (X) (defun bump (v) (inc v)) "
        "(defmacro inc (e) (qq (+ (unquote e) 1))) (bump X))",
        "(41)",
    )
    assert result == int_to_atom(42)


def test_macro_body_sees_condition_constants():
    _, _, result = _run_program("(program () (defmacro seal () SEAL) (seal))")
    assert result == CONDITION_CONSTANTS["SEAL"]


def test_macro_quoted_output_passes_verbatim():
    # The expansion is (q . "X"): quote-headed output stays data
    # even though its bytes spell an in-scope parameter name.
    _, _, result = _run_program(
        "(program (X) (defmacro lit () (c (q . 1) 'X')) (lit))", "(7)"
    )
    assert result == b"X"


def test_qq_in_ordinary_code_builds_data():
    _, _, result = _run_program("(program (X) (qq (foo (unquote X))))", "(7)")
    assert result == (b"foo", (int_to_atom(7), NIL))


def test_expression_compiles_against_session_macros():
    defs = _defs("(defmacro inc (e) (qq (+ (unquote e) 1)))")
    program, _ = compile_expression("(inc 41)", defs)
    cost, result = run(program, NIL, BUDGET)
    assert result == int_to_atom(42)


def test_branching_macro_hits_the_execution_cap():
    # Every chain stays far under the depth cap and every run far
    # under the cost budget, but the template splices two calls to
    # itself, doubling the work per level, so only the total
    # execution guard stops the compile.
    source = (
        "(program (N) (defmacro m (n) (if n "
        "(qq (c (unquote (c m (c (- n 1) ()))) "
        "(unquote (c m (c (- n 1) ()))))) (q . 1))) (m 20))"
    )
    with pytest.raises(CompileError) as excinfo:
        compile_program(source)
    assert f"exceeded {MACRO_EXPANSION_LIMIT} executions" in str(excinfo.value)


def test_expansion_errors_name_the_first_declared_function():
    # The reachability sweep runs in declaration order, so which
    # function an expansion error is attributed to cannot vary
    # with string-hash randomization.
    source = (
        "(program (X) (defmacro boom (e) (x)) "
        "(defun zz (v) (boom v)) (defun aa (v) (boom v)) (c (zz X) (aa X)))"
    )
    with pytest.raises(CompileError) as excinfo:
        compile_program(source)
    assert str(excinfo.value).startswith("in 'zz':")


def test_caller_written_typo_is_an_unknown_name():
    # The caller wrote Y as a name, so it is evidence, and it
    # resolves nowhere: the macro path reports exactly what the
    # direct spelling would, never compiling the typo as data.
    with pytest.raises(CompileError) as excinfo:
        compile_program(
            "(program (X) (defmacro inc (e) (qq (+ (unquote e) 1))) (inc Y))"
        )
    assert "unknown name 'Y'" in str(excinfo.value)


def test_stale_template_name_is_an_unknown_name():
    # The template spells gone, so it is evidence, and nothing
    # defines it: the rejection names the source token instead of
    # letting the spelling land as operator bytes.
    defs = _defs("(defmacro call-gone (e) (qq (gone (unquote e))))")
    with pytest.raises(CompileError) as excinfo:
        compile_expression("(call-gone 1)", defs)
    assert "unknown name 'gone'" in str(excinfo.value)


def test_computed_operator_bytes_error_with_their_spelling():
    # Bytes with no evidence stay data even when they spell a
    # would-be name, and in head position the operator error spells
    # them so the hex is traceable.
    defs = _defs("(defmacro bad () (c 'zzz' ()))")
    with pytest.raises(CompileError) as excinfo:
        compile_expression("(bad)", defs)
    assert "unknown operator 0x7a7a7a, which spells 'zzz'" in str(excinfo.value)


def test_qq_levels_agree_between_expansion_and_emission():
    # The expansion pre-pass and template emission each walk qq
    # nesting levels, and they must locate the same escapes: the
    # level-one unquote expands its macro call, the one under a
    # nested qq keeps the call as spelled data.
    _, _, result = _run_program(
        "(program (X) (defmacro inc (e) (qq (+ (unquote e) 1))) "
        "(qq ((unquote (inc X)) (qq (unquote (inc X))))))",
        "(41)",
    )
    nested = (b"qq", ((b"unquote", ((b"inc", (b"X", NIL)), NIL)), NIL))
    assert result == (int_to_atom(42), (nested, NIL))


def test_macro_budget_matches_the_runner_default():
    from bitlisp_tools import compiler, runner

    assert compiler.MACRO_COST_BUDGET == runner.DEFAULT_MAX_COST


def test_macro_cost_burst_is_reported(monkeypatch):
    from bitlisp_tools import compiler

    monkeypatch.setattr(compiler, "MACRO_COST_BUDGET", 100)
    with pytest.raises(CompileError) as excinfo:
        compile_program("(program () (defmacro m (e) (+ e 1)) (m 5))")
    assert "macro 'm' failed: cost_exceeded" in str(excinfo.value)


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
        ("(program (X) (defmacro m N) X)", "defmacro takes 3 parts"),
        ("(program (qq) 1)", "'qq' is a reserved word"),
        ("(program (unquote) 1)", "'unquote' is a reserved word"),
        ("(program (X) (defmacro list (N) N) X)", "'list' is a reserved word"),
        (
            "(program (X) (defmacro m (N) N) (defun m (N) N) X)",
            "already defined",
        ),
        (
            "(program (X) (defun m (N) N) (defmacro m (N) N) X)",
            "already defined",
        ),
        ("(program (X) (defmacro m (N) N) (c m X))", "macro 'm' used as a value"),
        ("(program (X) (defmacro m (N) N) (m 1 2))", "'m' takes 1 argument(s)"),
        ("(program (X) (defmacro m (N . R) N) (m))", "at least 1 argument(s)"),
        ("(program (X) (defmacro m (N) N) (m 1 . 2))", "proper argument list"),
        ("(program (X) (unquote X))", "unquote outside a qq template"),
        ("(program (X) (qq X X))", "qq takes 1 part"),
        ("(program (X) (qq (unquote X X)))", "unquote takes 1 part"),
        (
            "(program (X) (defmacro m (N) (x)) (m X))",
            "macro 'm' failed: user_raise",
        ),
        (
            "(program (X) (defun dbl (v) v) (defmacro m (N) (dbl N)) (m X))",
            "unknown name 'dbl'",
        ),
        (
            "(program (X) (defconstant K 1) (defmacro m (N) K) (m X))",
            "unknown name 'K'",
        ),
        (
            "(program (X) (defmacro m (N) (uses N)) (defmacro uses (N) N) X)",
            "unknown name 'uses'",
        ),
        (
            "(program (X) (defmacro m (N) (m N)) (m X))",
            "macro 'm' cannot be called inside its own body",
        ),
        (
            "(program () (defmacro m args (qq (m 1 (unquote args)))) (m 1))",
            f"macro expansion depth exceeded {MACRO_DEPTH_LIMIT} levels",
        ),
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


@given(_node_trees)
def test_macro_quoted_output_survives_arbitrary_trees(node):
    # A macro whose value is (q . tree) expands to exactly that
    # quoted tree for any tree: the lift never enters quote-headed
    # output, whatever the content's bytes spell. The form is built
    # as a tree because arbitrary bytes have no source spelling.
    body = (b"\x04", ((b"\x01", b"\x01"), ((b"\x01", node), NIL)))
    form = (
        Symbol("defmacro", 0),
        (Symbol("m", 0), (NIL, (body, NIL))),
    )
    defs = Definitions()
    defs.add_defmacro(form)
    program, _ = compile_expression("(m)", defs)
    cost, result = run(program, NIL, BUDGET)
    assert result == node


@given(st.lists(st.integers(min_value=0, max_value=2**63 - 1), max_size=6))
def test_list1_matches_builtin_list(values):
    spelled = " ".join(str(value) for value in values)
    macro_program, _ = compile_program(f"(program () {LIST1} (list1 {spelled}))")
    builtin_program, _ = compile_program(f"(program () (list {spelled}))")
    assert macro_program == builtin_program
