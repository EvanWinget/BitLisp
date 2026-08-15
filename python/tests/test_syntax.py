"""Round-trip properties for the text syntax, plus the corpus pin."""

import json
import sys
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from bitlisp import deserialize, serialize  # noqa: E402
from bitlisp.machine import APPLY, QUOTE  # noqa: E402
from bitlisp.operators import OPERATORS  # noqa: E402
from bitlisp_tools import (  # noqa: E402
    ATOM_TO_NAME,
    NAME_TO_ATOM,
    ParseError,
    assemble,
    disassemble,
)

# Atom sizes cross the string, decimal, and hex display thresholds
# and the one-byte and two-byte serialization length prefixes.
atoms = st.binary(max_size=300)
nodes = st.recursive(atoms, lambda children: st.tuples(children, children))


@given(nodes)
def test_roundtrip_identity(node):
    assert assemble(disassemble(node)) == node


@given(nodes)
def test_printer_fixed_point(node):
    text = disassemble(node)
    assert disassemble(assemble(text)) == text


@given(st.text())
def test_reader_total(text):
    try:
        node = assemble(text)
    except ParseError:
        return
    assert isinstance(node, bytes | tuple)


# st.text() never generates surrogates, so the totality claim gets a
# second alphabet that mixes them with the syntax's own characters.
@given(st.text(alphabet=list("()\"';.x0 -q\n") + ["\ud800", "\udfff"]))
def test_reader_total_surrogates(text):
    try:
        node = assemble(text)
    except ParseError:
        return
    assert isinstance(node, bytes | tuple)


def test_decimal_past_digit_limit():
    # CPython caps decimal string conversion at a digit limit, and
    # the reader turns that cap into ParseError instead of leaking
    # ValueError. Hex has no cap, so any magnitude stays writable.
    for text in ("1" * 5000, "-" + "1" * 5000):
        with pytest.raises(ParseError):
            assemble(text)
    assert len(assemble("0x" + "11" * 5000)) == 5000


# The name table mirrors the consensus operator set exactly.


def test_table_matches_operator_set():
    assert set(NAME_TO_ATOM.values()) == set(OPERATORS) | {QUOTE, APPLY}
    assert len(ATOM_TO_NAME) == len(NAME_TO_ATOM)
    for name, atom in NAME_TO_ATOM.items():
        assert ATOM_TO_NAME[atom] == name


# Every row pinned separately so a table typo names its operator.
TABLE_ROWS = [
    ("q", "01"),
    ("a", "02"),
    ("i", "03"),
    ("c", "04"),
    ("f", "05"),
    ("r", "06"),
    ("l", "07"),
    ("x", "08"),
    ("=", "09"),
    (">s", "0a"),
    ("sha256", "0b"),
    ("substr", "0c"),
    ("strlen", "0d"),
    ("concat", "0e"),
    ("secp_verify", "0f"),
    ("+", "10"),
    ("-", "11"),
    ("*", "12"),
    ("/", "13"),
    ("divmod", "14"),
    (">", "15"),
    ("ash", "16"),
    ("lsh", "17"),
    ("logand", "18"),
    ("logior", "19"),
    ("logxor", "1a"),
    ("lognot", "1b"),
    ("not", "20"),
    ("any", "21"),
    ("all", "22"),
    ("sha256tree", "3f"),
]


@pytest.mark.parametrize("name,opcode_hex", TABLE_ROWS)
def test_table_row(name, opcode_hex):
    atom = bytes.fromhex(opcode_hex)
    assert NAME_TO_ATOM[name] == atom
    assert assemble(f"({name})") == (atom, b"")
    assert disassemble((atom, b"")) == f"({name})"


def test_table_complete():
    assert len(TABLE_ROWS) == 31
    assert dict((n, bytes.fromhex(h)) for n, h in TABLE_ROWS) == NAME_TO_ATOM


# The published vector example, both directions.


def test_arith_vector_example():
    raw = bytes.fromhex("ff10ffff0102ffff010380")
    node = deserialize(raw)
    assert assemble("(+ (q . 2) (q . 3))") == node
    assert disassemble(node) == "(+ (q . 2) (q . 3))"
    assert serialize(assemble(disassemble(node))) == raw


# Reader behavior.


@pytest.mark.parametrize(
    "text,expected",
    [
        ("()", b""),
        ("0", b""),
        ("0x", b""),
        ("0xf", b"\x0f"),
        ("0xAb", b"\xab"),
        ("0x01", b"\x01"),
        ("0x0001", b"\x00\x01"),
        ("-1", b"\xff"),
        ("-128", b"\x80"),
        ("128", b"\x00\x80"),
        ('"test"', b"test"),
        ("'test'", b"test"),
        ("'a\"b'", b'a"b'),
        ('";x"', b";x"),
        ('""', b""),
        ('"π≈3"', b"\xcf\x80\xe2\x89\x883"),
        ("-0", b""),
        ("007", b"\x07"),
        ("(1 . 2)", (b"\x01", b"\x02")),
        ("(1 2 . 3)", (b"\x01", (b"\x02", b"\x03"))),
        ("(q . q)", (b"\x01", b"\x01")),
        ("(() 1)", (b"", (b"\x01", b""))),
        ("(>s 0x00 0x01)", (b"\x0a", (b"\x00", (b"\x01", b"")))),
        ("(= 1 2)", (b"\x09", (b"\x01", (b"\x02", b"")))),
        ("(+ 1 2) ; trailing comment", (b"\x10", (b"\x01", (b"\x02", b"")))),
        ("; leading comment\n7", b"\x07"),
    ],
)
def test_reader_cases(text, expected):
    assert assemble(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "; only a comment",
        "1 2",
        "(1) 2",
        "( . 2)",
        "(1 . 2 3)",
        "(1 . . 2)",
        "(1 . )",
        "(1 .",
        ".",
        "(",
        ")",
        "+5",
        "foo",
        "sha256tre",
        "point_add",
        "pubkey_for_exp",
        "softfork",
        "0xg1",
        "0x0g",
        "0X01",
        '"unterminated',
        "'unterminated",
        '"\ud800"',
        "(1\xa02)",
        "(1\x1c2)",
        "٧",
        "(1 ７)",
        "(1 .2)",
        "(1. 2)",
    ],
)
def test_reader_rejects(text):
    with pytest.raises(ParseError):
        assemble(text)


def test_parse_error_carries_offset():
    with pytest.raises(ParseError) as excinfo:
        assemble("(+ 1 zzz)")
    assert excinfo.value.offset == 5


# Printer display rules.


@pytest.mark.parametrize(
    "node,text",
    [
        (b"", "()"),
        (b"\x01", "1"),
        (b"\xff", "-1"),
        (b"\x80\x00", "-32768"),
        (b"\xff\x00\x00", "0xff0000"),
        (b"\xde\xad\xbe\xef", "0xdeadbeef"),
        (b"\x00\x01", "0x0001"),
        (b"ab", "24930"),
        (b"abc", '"abc"'),
        (b'a"b', "'a\"b'"),
        (b"a\"b'c", "0x6122622763"),
        (b"\x01" * 8, "72340172838076673"),
        (b"\x01" * 9, "0x010101010101010101"),
        (b"\xff\xff\x01", "0xffff01"),
        ((b"", b""), "(())"),
        ((b"\x10", b""), "(+)"),
        ((b"\x01", b"\x01"), "(q . 1)"),
        ((b"\x01", (b"\x01", (b"\x02", b""))), "(q 1 2)"),
        ((b"\x00\x10", (b"\x01", b"")), "(0x0010 1)"),
        ((b"\xff\xff\x01", b""), "(0xffff01)"),
        ((b"\x34", b"\x05\xf5\xe1\x00"), "(52 . 100000000)"),
        ((b"\x08", (b"err", b"")), '(x "err")'),
    ],
)
def test_printer_cases(node, text):
    assert disassemble(node) == text
    assert assemble(text) == node


@pytest.mark.parametrize(
    "bad",
    [
        None,
        1,
        "x",
        (b"",),
        (b"", b"", b""),
        (b"", 5),
        [b"", b""],
        bytearray(b""),
        (b"", bytearray(b"")),
    ],
)
def test_printer_rejects_non_nodes(bad):
    with pytest.raises(ValueError):
        disassemble(bad)


# Tree depth must not be limited by the Python recursion limit.


def test_deep_trees():
    depth = 10_000
    left = b""
    right = b""
    for _ in range(depth):
        left = (left, b"")
        right = (b"", right)
    assert assemble(disassemble(left)) == left
    assert assemble(disassemble(right)) == right
    # The leaf must not be an opcode: in the innermost head position
    # an opcode atom would print as its operator name, not its number.
    text = "(" * depth + "99" + ")" * depth
    assert disassemble(assemble(text)) == text


# Re-serialization pinned against every program, environment, result,
# and condition node in the vector corpus. serialize.json is excluded
# because its cases are rejected encodings that never deserialize.


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
    for path in sorted((REPO_ROOT / "vectors" / "conditions").glob("*.json")):
        for case in json.loads(path.read_text())["cases"]:
            if "conditions" in case:
                collected.append(case["conditions"])
    for path in sorted((REPO_ROOT / "vectors" / "validation").glob("*.json")):
        for case in json.loads(path.read_text())["cases"]:
            for tx_input in case.get("tx", {}).get("inputs", []):
                if "conditions" in tx_input:
                    collected.append(tx_input["conditions"])
    return collected


def test_corpus_reserialization():
    corpus = _corpus_hex()
    # A floor so a path or key typo cannot silently empty the sweep.
    assert len(corpus) >= 200
    for hex_str in corpus:
        raw = bytes.fromhex(hex_str)
        node = deserialize(raw)
        assert assemble(disassemble(node)) == node
        assert serialize(assemble(disassemble(node))) == raw
