#!/usr/bin/env python3
"""Runner for the vendored Chia CLVM command tests.

Each case under vectors/upstream/clvm/ is one brun invocation with its
expected stdout, produced upstream by clvm_tools over the Python clvm
package. This runner never compares stdout text. It re-derives every
expectation semantically: the program, environment, and expected result
texts are parsed with the reader below, serialized canonically, and the
expectation becomes (cost, result bytes) or a bitlisp error class
mapped from the FAIL message. bitlisp must then reproduce the
expectation exactly, and on every success expectation the consensus
oracle (chia_rs, flags 0) must reproduce it too, the single py_limits
case below excepted, so a file whose expectation drifted from
consensus cannot pass silently. That includes the divergence-bucket
success cases: where bitlisp rejects by design, the consensus oracle
still has to produce the file's exact (cost, result).

Cases bitlisp intentionally rejects fall into divergence buckets, each
asserting the exact BitLisp outcome rather than skipping:

- D1: programs dispatching point_add or pubkey_for_exp must raise
  unknown_operator.
- D3: programs dispatching any other operator outside the BitLisp
  table (unknown opcodes the oracles accept, their malformed-opcode
  and argument errors, and softfork) must raise unknown_operator.
- D4: programs with a pair in operator position must raise
  operator_not_atom.
- D6: negative division, which the Python clvm package rejects as
  deprecated, must succeed in bitlisp with exactly the consensus
  oracle's (cost, result).

One bucket covers expectations that predate consensus rather than
diverging from BitLisp: the Python clvm package enforces no operand
size limits, so a success expectation whose program bursts a limit
(the multiplication accumulator cap) lands in py_limits, and bitlisp
and the consensus oracle must both reject it.

Cases whose expected FAIL is a text-reader error ("missing )",
"illegal dot expression") pin the upstream assembler, not the VM. They
land in a reader bucket: this runner's reader must reject them too,
and a program our reader rejects that upstream executed fails the run.

Any case that fits no bucket is a finding and fails the run.

Usage:
    python3 tools/run_upstream.py [--root vectors/upstream/clvm] [-v]
"""

import argparse
import shlex
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

import chia_rs  # noqa: E402
from bitlisp import (  # noqa: E402
    NIL,
    BitLispError,
    int_to_atom,
    run_serialized,
    serialize,
)

MAX_COST = 11_000_000_000

# The CLVM assembler's keyword table over the corpus's operator set.
# point_add, pubkey_for_exp, and softfork parse to their CLVM opcodes,
# atoms BitLisp's evaluator rejects, so the divergence cases reach the
# evaluator instead of failing in this reader.
KEYWORD_OPCODES = {
    "q": 0x01,
    "a": 0x02,
    "i": 0x03,
    "c": 0x04,
    "f": 0x05,
    "r": 0x06,
    "l": 0x07,
    "x": 0x08,
    "=": 0x09,
    ">s": 0x0A,
    "sha256": 0x0B,
    "substr": 0x0C,
    "strlen": 0x0D,
    "concat": 0x0E,
    "+": 0x10,
    "-": 0x11,
    "*": 0x12,
    "/": 0x13,
    "divmod": 0x14,
    ">": 0x15,
    "ash": 0x16,
    "lsh": 0x17,
    "logand": 0x18,
    "logior": 0x19,
    "logxor": 0x1A,
    "lognot": 0x1B,
    "point_add": 0x1D,
    "pubkey_for_exp": 0x1E,
    "not": 0x20,
    "any": 0x21,
    "all": 0x22,
    "softfork": 0x24,
}
KEYWORD_ATOMS = {name: bytes([op]) for name, op in KEYWORD_OPCODES.items()}

# FAIL-message fragments, first match wins. Each maps to a bitlisp
# error class the case must reproduce, or to a bucket: "reader" for
# upstream text-reader errors, and a divergence row for behavior
# BitLisp rejects by design.
FAIL_RULES = (
    ("missing )", "reader"),
    ("illegal dot expression", "reader"),
    ("div operator with negative operands is deprecated", "D6"),
    ("point_add", "D1"),
    ("pubkey_for_exp", "D1"),
    ("softfork", "D3"),
    ("cost must be > 0", "D3"),
    ("unknown op ", "D3"),
    ("in ((", "D4"),
    ("unimplemented operator", "unknown_operator"),
    ("invalid operator", "unknown_operator"),
    ("path into atom", "path_into_atom"),
    ("first of non-cons", "arg_not_pair"),
    ("rest of non-cons", "arg_not_pair"),
    ("apply requires exactly 2 parameters", "wrong_arg_count"),
    ("takes exactly", "wrong_arg_count"),
    ("takes at least", "wrong_arg_count"),
    ("takes no more than", "wrong_arg_count"),
    ("requires int32 args", "bad_index"),
    ("requires int args", "arg_not_atom"),
    (" on list", "arg_not_atom"),
    ("invalid indices", "index_out_of_range"),
    ("shift too large", "shift_too_large"),
    ("div with 0", "div_by_zero"),
    ("divmod with 0", "div_by_zero"),
    ("clvm raise", "user_raise"),
    ("cost exceeded", "cost_exceeded"),
)

DIVERGENCE_BUCKETS = ("D1", "D3", "D4", "D6")

# Specific chia_rs argument-error fragments. The operand size limit is
# the bare InvalidOperatorArg carrying none of these, matched with the
# same last-resort discipline the diff harness applies.
RS_SPECIFIC_ARG_ERRORS = (
    "Requires Int Argument",
    "requires an atom",
    "used on list",
    "concat on list",
    "requires int32",
    "Invalid Indices",
)


class ReaderError(Exception):
    pass


class CaseError(Exception):
    """A corpus file this runner cannot interpret. Always a finding."""


def tokenize(text):
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in "()":
            tokens.append(ch)
            i += 1
        elif ch in "\"'":
            end = text.find(ch, i + 1)
            if end < 0:
                raise ReaderError(f"unterminated string: {text[i:]!r}")
            tokens.append(("string", text[i + 1 : end]))
            i = end + 1
        else:
            start = i
            while i < n and not text[i].isspace() and text[i] not in "()":
                i += 1
            tokens.append(("token", text[start:i]))
    return tokens


def atom_from_token(text):
    if text.lower().startswith("0x"):
        digits = text[2:]
        if len(digits) % 2:
            digits = "0" + digits
        try:
            return bytes.fromhex(digits)
        except ValueError:
            raise ReaderError(f"bad hex atom: {text}") from None
    stripped = text.removeprefix("-")
    if stripped.isdigit():
        return int_to_atom(int(text))
    if text in KEYWORD_ATOMS:
        return KEYWORD_ATOMS[text]
    # The upstream assembler turns any other symbol into the bytes of
    # its name, which is how the corpus spells atoms like foo-bar.
    return text.encode()


def parse_expr(tokens, pos):
    if pos >= len(tokens):
        raise ReaderError("unexpected end of input")
    tok = tokens[pos]
    if tok == ")":
        raise ReaderError("unexpected )")
    if tok != "(":
        kind, text = tok
        if kind == "string":
            return text.encode(), pos + 1
        if text == ".":
            raise ReaderError("dot outside a pair tail")
        return atom_from_token(text), pos + 1
    pos += 1
    items = []
    while True:
        if pos >= len(tokens):
            raise ReaderError("missing )")
        tok = tokens[pos]
        if tok == ")":
            tail = NIL
            pos += 1
            break
        if tok == ("token", "."):
            if not items:
                raise ReaderError("dot with no head")
            tail, pos = parse_expr(tokens, pos + 1)
            if pos >= len(tokens) or tokens[pos] != ")":
                raise ReaderError("illegal dot expression")
            pos += 1
            break
        item, pos = parse_expr(tokens, pos)
        items.append(item)
    node = tail
    for item in reversed(items):
        node = (item, node)
    return node, pos


def read_text(text):
    tokens = tokenize(text)
    node, pos = parse_expr(tokens, 0)
    if pos != len(tokens):
        raise ReaderError(f"trailing tokens: {text!r}")
    return node


class Case:
    def __init__(self, path):
        self.path = path
        lines = path.read_text().splitlines()
        while lines and lines[0].startswith("#"):
            lines.pop(0)
        if not lines:
            raise CaseError("no command line")
        self.command = lines[0]
        self._parse_command(shlex.split(self.command))
        self._parse_expected(lines[1:])

    def _parse_command(self, args):
        if not args or args[0] != "brun":
            raise CaseError(f"not a brun command: {self.command}")
        self.show_cost = False
        self.dump = False
        self.verbose = False
        self.max_cost = None
        positional = []
        i = 1
        while i < len(args):
            arg = args[i]
            if arg in ("-c", "--cost"):
                self.show_cost = True
            elif arg == "--strict":
                # Only changes which FAIL spelling the file records:
                # strict brun rejects unknown operators that bitlisp
                # rejects unconditionally.
                pass
            elif arg in ("-n", "--no-keywords"):
                pass  # changes brun's result printing, not its semantics
            elif arg in ("-d", "--dump"):
                self.dump = True
            elif arg in ("-v", "--verbose"):
                self.verbose = True
            elif arg in ("-m", "--max-cost"):
                i += 1
                try:
                    self.max_cost = int(args[i])
                except IndexError, ValueError:
                    raise CaseError(f"bad max cost: {self.command}") from None
                if self.max_cost <= 0:
                    raise CaseError(f"non-positive max cost: {self.command}")
            elif arg.startswith("--backend"):
                pass  # selects among upstream backends with equal semantics
            elif arg.startswith("-") and not arg[1:].isdigit():
                raise CaseError(f"unrecognized flag {arg}: {self.command}")
            else:
                positional.append(arg)
            i += 1
        if not 1 <= len(positional) <= 2:
            raise CaseError(f"expected program [env]: {self.command}")
        self.program_text = positional[0]
        self.env_text = positional[1] if len(positional) == 2 else "()"

    def _parse_expected(self, lines):
        # Everything past the primary lines is the -v trace, present
        # only in verbose cases.
        def check_trailing(rest):
            if any(line.strip() for line in rest) and not self.verbose:
                raise CaseError(f"unexpected trailing output: {self.path}")

        if not lines:
            raise CaseError(f"no expected output: {self.path}")
        if lines[0].startswith("FAIL: "):
            message = lines[0][len("FAIL: ") :]
            for fragment, outcome in FAIL_RULES:
                if fragment in message:
                    self.expected = ("err", outcome)
                    check_trailing(lines[1:])
                    return
            raise CaseError(f"unmapped FAIL message: {message}")
        index = 0
        self.expected_cost = None
        if self.show_cost:
            if not lines[0].startswith("cost = "):
                raise CaseError(f"missing cost line: {self.path}")
            self.expected_cost = int(lines[0][len("cost = ") :])
            index = 1
        if index >= len(lines):
            raise CaseError(f"missing result line: {self.path}")
        self.expected = ("ok", lines[index])
        check_trailing(lines[index + 1 :])


def run_bitlisp(program_bytes, env_bytes, max_cost):
    try:
        cost, result = run_serialized(program_bytes, env_bytes, max_cost)
    except BitLispError as exc:
        return ("err", exc.code)
    return ("ok", cost, result)


def run_consensus(program_bytes, env_bytes, max_cost):
    try:
        cost, node = chia_rs.run_chia_program(program_bytes, env_bytes, max_cost, 0)
    except Exception as exc:  # chia_rs raises ValueError
        return ("err", str(exc))
    stack = [node]
    build = []
    while stack:
        item = stack.pop()
        if item.atom is not None:
            build.append(item.atom)
        else:
            left, right = item.pair
            build.append(None)
            stack.append(right)
            stack.append(left)
    tree = []
    for item in reversed(build):
        if item is None:
            left = tree.pop()
            right = tree.pop()
            tree.append((left, right))
        else:
            tree.append(item)
    (root,) = tree
    return ("ok", cost, serialize(root))


def expected_result_bytes(case):
    _, result_text = case.expected
    if case.dump:
        try:
            return bytes.fromhex(result_text)
        except ValueError:
            raise CaseError(f"bad dump hex: {result_text!r}") from None
    return serialize(read_text(result_text))


def judge(case):
    """Returns a bucket name, or raises CaseError with the finding."""
    try:
        program = read_text(case.program_text)
    except ReaderError as exc:
        if case.expected == ("err", "reader"):
            return "reader"
        raise CaseError(f"reader rejected the program: {exc}") from None
    if case.expected == ("err", "reader"):
        raise CaseError("upstream's reader rejected this, ours parsed it")
    program_bytes = serialize(program)
    env_bytes = serialize(read_text(case.env_text))
    budget = case.max_cost if case.max_cost is not None else MAX_COST
    outcome = run_bitlisp(program_bytes, env_bytes, budget)

    kind = case.expected[1] if case.expected[0] == "err" else None
    if kind in DIVERGENCE_BUCKETS or case.expected[0] == "ok":
        bucket = divergence_bucket(case, outcome)
        if bucket is not None:
            if kind is not None and kind != bucket:
                raise CaseError(f"expected divergence {kind}, bitlisp gave {bucket}")
            if bucket == "D6":
                check_d6(case, outcome, program_bytes, env_bytes, budget)
            elif case.expected[0] == "ok":
                check_consensus_reproduces(case, program_bytes, env_bytes, budget)
            return bucket
        if kind is not None:
            raise CaseError(f"expected divergence {kind}, bitlisp gave {outcome}")

    if case.expected[0] == "ok":
        if outcome == ("err", "arg_too_long"):
            # The corpus expectation predates the consensus operand
            # limits, which the Python clvm package never enforced.
            # bitlisp must agree with the consensus oracle instead. A
            # bare InvalidOperatorArg with no more specific fragment is
            # the oracle's operand size limit, so any of its argument
            # errors carrying a specific fragment does not qualify.
            consensus = run_consensus(program_bytes, env_bytes, budget)
            if (
                consensus[0] == "err"
                and "InvalidOperatorArg" in consensus[1]
                and not any(f in consensus[1] for f in RS_SPECIFIC_ARG_ERRORS)
            ):
                return "py_limits"
            raise CaseError(f"arg_too_long but consensus oracle gave {consensus}")
        if outcome[0] != "ok":
            raise CaseError(f"expected success, bitlisp raised {outcome[1]}")
        _, cost, result = outcome
        expected = expected_result_bytes(case)
        if result != expected:
            raise CaseError(f"result {result.hex()} != expected {expected.hex()}")
        if case.expected_cost is not None and cost != case.expected_cost:
            raise CaseError(f"cost {cost} != expected {case.expected_cost}")
        consensus = run_consensus(program_bytes, env_bytes, budget)
        if consensus != ("ok", cost, result):
            raise CaseError(f"consensus oracle disagrees: {consensus}")
        return "match"

    if outcome[0] != "err":
        raise CaseError(f"expected {kind}, bitlisp succeeded: {outcome}")
    code = outcome[1]
    if code == kind:
        return "match"
    raise CaseError(f"expected {kind}, bitlisp raised {code}")


def divergence_bucket(case, outcome):
    if case.expected == ("err", "D6"):
        # Not an error bucket: bitlisp must succeed where the Python
        # oracle deprecates. check_d6 asserts the successful outcome.
        return "D6"
    if outcome[0] != "err":
        return None
    code = outcome[1]
    if code == "unknown_operator":
        bls = ("point_add", "pubkey_for_exp")
        return "D1" if any(name in case.command for name in bls) else "D3"
    if code == "operator_not_atom":
        return "D4"
    return None


def check_d6(case, outcome, program_bytes, env_bytes, budget):
    if outcome[0] != "ok":
        raise CaseError(f"D6 expects floor division, bitlisp: {outcome}")
    consensus = run_consensus(program_bytes, env_bytes, budget)
    if consensus != outcome:
        raise CaseError(f"D6 consensus mismatch: bitlisp {outcome}, oracle {consensus}")


def check_consensus_reproduces(case, program_bytes, env_bytes, budget):
    """A divergence-bucket success expectation is still consensus behavior.

    bitlisp rejects these programs by design, so the file's (cost,
    result) can only be validated against the consensus oracle, and a
    drifted expectation must fail loudly rather than ride the bucket.
    """
    expected = expected_result_bytes(case)
    consensus = run_consensus(program_bytes, env_bytes, budget)
    if consensus[0] != "ok" or consensus[2] != expected:
        raise CaseError(f"consensus oracle does not reproduce the file: {consensus}")
    if case.expected_cost is not None and consensus[1] != case.expected_cost:
        raise CaseError(
            f"consensus cost {consensus[1]} != expected {case.expected_cost}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="vectors/upstream/clvm")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    root = REPO_ROOT / args.root

    paths = sorted(root.rglob("*.txt"))
    if not paths:
        print(f"no cases under {root}", file=sys.stderr)
        return 1
    counts = {}
    failures = []
    for path in paths:
        name = path.relative_to(root).as_posix()
        try:
            bucket = judge(Case(path))
        except (CaseError, ReaderError) as exc:
            failures.append(f"{name}: {exc}")
            continue
        counts[bucket] = counts.get(bucket, 0) + 1
        if args.verbose and bucket != "match":
            print(f"{bucket}: {name}")

    total = len(paths)
    summary = ", ".join(
        f"{counts[key]} {key}"
        for key in ("match", "D1", "D3", "D4", "D6", "py_limits", "reader")
        if key in counts
    )
    print(f"{total} cases: {summary}, {len(failures)} findings")
    for failure in failures:
        print(f"FINDING {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
