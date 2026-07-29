"""Unit tests for the upstream-corpus runner's reader and case parser.

The runner re-derives every vendored expectation semantically, so the
reader is the one piece that could silently mistranslate a case. These
tests pin its atom spellings, structure handling, and error behavior,
plus the command-line and expected-output parsing, and verify the
vendored tree against the digest recorded in its provenance file.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from run_upstream import (  # noqa: E402
    Case,
    CaseError,
    ReaderError,
    judge,
    read_text,
)

CORPUS = REPO_ROOT / "vectors" / "upstream" / "clvm"


class TestReaderAtoms:
    def test_keywords_map_to_opcodes(self):
        assert read_text("q") == b"\x01"
        assert read_text(">s") == b"\x0a"
        assert read_text("softfork") == b"\x24"
        assert read_text("point_add") == b"\x1d"

    def test_integers_encode_minimally(self):
        assert read_text("0") == b""
        assert read_text("1") == b"\x01"
        assert read_text("-1") == b"\xff"
        assert read_text("128") == b"\x00\x80"
        assert read_text("-129") == b"\xff\x7f"

    def test_hex_keeps_redundant_bytes(self):
        assert read_text("0x00ffffff") == b"\x00\xff\xff\xff"

    def test_odd_hex_gains_a_leading_zero(self):
        assert read_text("0x000") == b"\x00\x00"
        assert read_text("0xfffffffff") == b"\x0f\xff\xff\xff\xff"

    def test_bad_hex_is_rejected(self):
        with pytest.raises(ReaderError):
            read_text("0xzz")

    def test_strings_become_their_bytes(self):
        assert read_text('"A"') == b"A"
        assert read_text("'ab'") == b"ab"

    def test_unterminated_string_is_rejected(self):
        with pytest.raises(ReaderError):
            read_text('"ab')

    def test_other_symbols_become_their_bytes(self):
        assert read_text("foo-bar") == b"foo-bar"


class TestReaderStructure:
    def test_nil(self):
        assert read_text("()") == b""

    def test_proper_list(self):
        assert read_text("(1 2)") == (b"\x01", (b"\x02", b""))

    def test_dotted_pair(self):
        assert read_text("(q . -1)") == (b"\x01", b"\xff")

    def test_keyword_inside_a_list_is_the_same_atom(self):
        assert read_text("(q 1 2)") == read_text("(1 1 2)")

    def test_dot_without_closing_paren_is_rejected(self):
        with pytest.raises(ReaderError):
            read_text("(q . 1 2)")

    def test_dot_with_missing_tail_is_rejected(self):
        with pytest.raises(ReaderError):
            read_text("(q . )")

    def test_unbalanced_input_is_rejected(self):
        with pytest.raises(ReaderError):
            read_text("(q")
        with pytest.raises(ReaderError):
            read_text("(q . 1))")


def case_from(tmp_path, text):
    path = tmp_path / "case.txt"
    path.write_text(text)
    return Case(path)


class TestCaseParsing:
    def test_cost_flag_and_env(self, tmp_path):
        case = case_from(tmp_path, "brun -c '(f 1)' '(51)'\ncost = 74\n51\n")
        assert case.show_cost
        assert case.program_text == "(f 1)"
        assert case.env_text == "(51)"
        assert case.expected_cost == 74
        assert case.expected == ("ok", "51")

    def test_bare_int_program_with_cost_flag(self, tmp_path):
        case = case_from(tmp_path, "brun -n -c 0 '(8 . 9)'\ncost = 44\n()\n")
        assert case.program_text == "0"
        assert case.env_text == "(8 . 9)"

    def test_max_cost_value(self, tmp_path):
        case = case_from(tmp_path, "brun -m 73 '(q . 1)'\nFAIL: cost exceeded\n")
        assert case.max_cost == 73
        assert case.expected == ("err", "cost_exceeded")

    def test_fail_messages_map_to_buckets(self, tmp_path):
        expectations = {
            "unimplemented operator 0x00": ("err", "unknown_operator"),
            "point_add expects blob": ("err", "D1"),
            "cost must be > 0 ()": ("err", "D3"),
            "in ((X)...) syntax X must be lone atom": ("err", "D4"),
            "div operator with negative operands is deprecated": ("err", "D6"),
            "illegal dot expression at 8": ("err", "reader"),
        }
        for message, expected in expectations.items():
            case = case_from(tmp_path, f"brun '(q . 1)'\nFAIL: {message}\n")
            assert case.expected == expected, message

    def test_unmapped_fail_message_is_a_finding(self, tmp_path):
        with pytest.raises(CaseError):
            case_from(tmp_path, "brun '(q . 1)'\nFAIL: novel message\n")

    def test_unrecognized_flag_is_a_finding(self, tmp_path):
        with pytest.raises(CaseError):
            case_from(tmp_path, "brun -z '(q . 1)'\n()\n")

    def test_trailing_output_without_verbose_is_a_finding(self, tmp_path):
        with pytest.raises(CaseError):
            case_from(tmp_path, "brun '(q . 1)'\n1\nsurprise\n")

    def test_comments_are_skipped(self, tmp_path):
        case = case_from(tmp_path, "# a comment\nbrun '(q . 1)'\n1\n")
        assert case.program_text == "(q . 1)"


class TestJudge:
    def test_intersection_case_matches(self, tmp_path):
        case = case_from(tmp_path, "brun -c '(+ (q . 7) (q . 1))'\ncost = 796\n8\n")
        assert judge(case) == "match"

    def test_dump_case_compares_serialized_hex(self, tmp_path):
        case = case_from(tmp_path, "brun -d '(q . 32768)'\n83008000\n")
        assert judge(case) == "match"

    def test_wrong_cost_is_a_finding(self, tmp_path):
        case = case_from(tmp_path, "brun -c '(+ (q . 7) (q . 1))'\ncost = 795\n8\n")
        with pytest.raises(CaseError):
            judge(case)

    def test_deprecated_division_lands_in_d6(self, tmp_path):
        case = case_from(
            tmp_path,
            "brun '(/ (q . -1) (q . -1))'\n"
            "FAIL: div operator with negative operands is deprecated (-1 -1)\n",
        )
        assert judge(case) == "D6"

    def test_unknown_operator_acceptance_lands_in_d3(self, tmp_path):
        case = case_from(tmp_path, "brun -c '(0x03f )'\ncost = 2\n()\n")
        assert judge(case) == "D3"


def test_full_corpus_is_clean():
    """Every vendored case judges into a bucket with no findings."""
    buckets = {}
    for path in sorted(CORPUS.rglob("*.txt")):
        buckets.setdefault(judge(Case(path)), []).append(path.name)
    assert sorted(buckets) == [
        "D1",
        "D3",
        "D4",
        "D6",
        "match",
        "py_limits",
        "reader",
    ]
    assert buckets["py_limits"] == ["power-1.txt"]
    assert len(buckets["match"]) == 691


def test_vendored_tree_matches_provenance_digest():
    provenance = json.loads((CORPUS / "provenance.json").read_text())
    lines = []
    for path in sorted(p.relative_to(CORPUS).as_posix() for p in CORPUS.rglob("*.txt")):
        digest = hashlib.sha256((CORPUS / path).read_bytes()).hexdigest()
        lines.append(f"{digest}  ./{path}\n")
    tree_digest = hashlib.sha256("".join(lines).encode()).hexdigest()
    assert tree_digest == provenance["tree_sha256"]
