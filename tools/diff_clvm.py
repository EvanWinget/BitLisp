#!/usr/bin/env python3
"""Differential harness: bitlisp vs the pinned CLVM oracles.

Generates a randomized program corpus over the implemented operator
intersection and runs every program through three implementations:

- bitlisp (python/bitlisp), the executable spec
- chia-rs (flags 0), the consensus oracle
- clvm (Python package), the secondary oracle

Success requires identical (cost, result bytes) or an identical error
class. Three disagreements with the Python oracle are tolerated and
counted, all library behavior rather than consensus: its policy
rejection of negative division operands (consensus does floor
division), its budget check running only after an operator completes,
and its lack of the consensus operand size limits. The generator never
emits the recorded BitLisp divergences: unknown operators, pairs in
operator position, and non-canonical serializations cannot arise
because programs are emitted by bitlisp's own canonical serializer
over the implemented opcode set. Anything else is a finding and fails
the run.

Usage:
    python3 tools/diff_clvm.py --count 10000 --seed 1
"""

import argparse
import io
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

import chia_rs  # noqa: E402
from bitlisp import (  # noqa: E402
    BitLispError,
    int_to_atom,
    run_serialized,
    serialize,
)
from clvm import SExp  # noqa: E402
from clvm import run_program as clvm_run_program  # noqa: E402
from clvm.operators import OPERATOR_LOOKUP  # noqa: E402
from clvm.serialize import sexp_from_stream, sexp_to_stream  # noqa: E402

MAX_COST = 11_000_000_000

# Error message fragments mapped to bitlisp error codes.
RS_ERRORS = {
    "path into atom": "path_into_atom",
    "Division by zero": "div_by_zero",
    "takes exactly": "wrong_arg_count",
    "Requires Int Argument": "arg_not_atom",
    "= used on list": "arg_not_atom",
    "first of non-cons": "arg_not_pair",
    "rest of non-cons": "arg_not_pair",
    "Invalid Nil Terminator": "bad_arg_list",
    "clvm raise": "user_raise",
    "cost exceeded": "cost_exceeded",
    "Reserved operator": "reserved_operator",
    "bad encoding": "bad_encoding",
    # Bare InvalidOperatorArg (no more specific fragment above) is the
    # consensus operand size limit. Keep it last: fragment matching is
    # first-hit in insertion order.
    "InvalidOperatorArg": "arg_too_long",
}
# The Python oracle also reports an improper argument list as
# first/rest of non-cons, indistinguishable from f or r on an atom.
# The generator only emits proper argument lists, so the mapping to
# arg_not_pair is unambiguous here.
PY_ERRORS = {
    "path into atom": "path_into_atom",
    "div with 0": "div_by_zero",
    "divmod with 0": "div_by_zero",
    "takes exactly": "wrong_arg_count",
    "requires int args": "arg_not_atom",
    "= on list": "arg_not_atom",
    "first of non-cons": "arg_not_pair",
    "rest of non-cons": "arg_not_pair",
    "clvm raise": "user_raise",
    "cost exceeded": "cost_exceeded",
    "reserved operator": "reserved_operator",
}
PY_POLICY_DIV = "div operator with negative operands is deprecated"


def classify(message, table):
    for fragment, code in table.items():
        if fragment in message:
            return code
    return f"UNMAPPED({message})"


def run_bitlisp(program, env, max_cost):
    try:
        cost, result = run_serialized(program, env, max_cost)
        return ("ok", cost, result.hex())
    except BitLispError as exc:
        return ("err", exc.code)


def run_rs(program, env, max_cost):
    try:
        cost, node = chia_rs.run_chia_program(program, env, max_cost, 0)
    except Exception as exc:  # chia_rs raises ValueError
        return ("err", classify(str(exc), RS_ERRORS))
    out = bytearray()
    stack = [node]
    while stack:
        n = stack.pop()
        if n.atom is not None:
            buf = io.BytesIO()
            sexp_to_stream(SExp.to(n.atom), buf)
            out += buf.getvalue()
        else:
            out.append(0xFF)
            left, right = n.pair
            stack.append(right)
            stack.append(left)
    return ("ok", cost, bytes(out).hex())


def run_py(program, env, max_cost):
    try:
        prog = sexp_from_stream(io.BytesIO(program), SExp.to)
        env_node = sexp_from_stream(io.BytesIO(env), SExp.to)
        cost, result = clvm_run_program(
            prog, env_node, OPERATOR_LOOKUP, max_cost=max_cost
        )
    except Exception as exc:
        message = str(exc)
        if PY_POLICY_DIV in message:
            return ("policy_div",)
        return ("err", classify(message, PY_ERRORS))
    buf = io.BytesIO()
    sexp_to_stream(result, buf)
    return ("ok", cost, buf.getvalue().hex())


class Generator:
    """Random programs over the implemented operator set."""

    # opcode -> arity, None for variadic (0 to 4 arguments). The
    # generator always emits a valid arity: wrong_arg_count paths are
    # pinned by hand-written vectors instead.
    ARITIES = {
        b"\x03": 3,  # i
        b"\x04": 2,  # c
        b"\x05": 1,  # f
        b"\x06": 1,  # r
        b"\x07": 1,  # l
        b"\x09": 2,  # =
        b"\x10": None,  # +
        b"\x11": None,  # -
        b"\x12": None,  # *
        b"\x13": 2,  # /
        b"\x14": 2,  # divmod
        b"\x15": 2,  # >
    }
    OPCODES = sorted(ARITIES)

    def __init__(self, rng, max_depth):
        self.rng = rng
        self.max_depth = max_depth

    def atom_int(self):
        r = self.rng
        choice = r.random()
        if choice < 0.3:
            value = r.randint(-128, 127)
        elif choice < 0.6:
            value = r.randint(-(2**31), 2**31)
        elif choice < 0.8:
            value = r.randint(-(2**200), 2**200)
        elif choice < 0.85:
            # Large atoms cross serialization length-prefix forms and
            # exercise superlinear multiplication costs. A generator
            # capped at small atoms missed a length-encoding bug once.
            value = r.randint(-(2 ** (8 * 400)), 2 ** (8 * 400))
        else:
            value = 0
        atom = int_to_atom(value)
        if r.random() < 0.15:
            # Redundant integer encoding, legal as an argument input.
            pad = b"\xff" if value < 0 else b"\x00"
            atom = pad * r.randint(1, 3) + atom
        return atom

    def value_tree(self, depth):
        if depth <= 0 or self.rng.random() < 0.5:
            return self.atom_int()
        return (self.value_tree(depth - 1), self.value_tree(depth - 1))

    def program(self, depth):
        r = self.rng
        roll = r.random()
        if depth <= 0 or roll < 0.25:
            return (b"\x01", self.value_tree(1))  # quoted value
        if roll < 0.35:
            return int_to_atom(r.randint(0, 15))  # environment path
        if roll < 0.42:
            return (
                b"\x02",
                (
                    (b"\x01", self.program(depth - 1)),
                    ((b"\x01", self.value_tree(2)), b""),
                ),
            )  # (a (q . prog) (q . env))
        if roll < 0.44:
            return (b"\x08", b"")  # (x)
        opcode = r.choice(self.OPCODES)
        arity = self.ARITIES[opcode]
        arg_count = r.randint(0, 4) if arity is None else arity
        args = b""
        for _ in range(arg_count):
            args = (self.program(depth - 1), args)
        return (opcode, args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--max-fails", type=int, default=10)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    gen = Generator(rng, args.max_depth)
    stats = {
        "ok": 0,
        "err_agree": 0,
        "policy_div": 0,
        "py_budget_timing": 0,
        "py_no_operand_limit": 0,
    }
    failures = 0

    for i in range(args.count):
        program_node = gen.program(args.max_depth)
        env_node = gen.value_tree(3)
        program = serialize(program_node)
        env = serialize(env_node)
        max_cost = MAX_COST if rng.random() < 0.9 else rng.randint(1, 5000)

        bl = run_bitlisp(program, env, max_cost)
        rs = run_rs(program, env, max_cost)
        py = run_py(program, env, max_cost)

        # bitlisp vs consensus oracle: exact agreement required.
        if bl != rs:
            failures += 1
            print(f"MISMATCH bl-vs-rs #{i}: prog={program.hex()} env={env.hex()}")
            print(f"  max_cost={max_cost} bitlisp={bl} chia_rs={rs}")
            if failures >= args.max_fails:
                break
            continue

        # Secondary oracle. Two tolerated disagreements, both library
        # behavior rather than consensus: the negative-division policy
        # error (a recorded divergence, it aborts the Python oracle
        # where consensus keeps evaluating), and budget timing (the
        # Python oracle checks the budget only after an operator
        # completes, so it can report an operator error where
        # consensus already reported cost_exceeded).
        if py[0] == "policy_div":
            stats["policy_div"] += 1
        elif bl == ("err", "cost_exceeded") and py[0] == "err":
            stats["py_budget_timing"] += 1
        elif bl == ("err", "arg_too_long"):
            # The Python oracle has no operand size limits, so once
            # consensus rejects an oversized operand its outcome is
            # unconstrained.
            stats["py_no_operand_limit"] += 1
        elif py != bl:
            failures += 1
            print(f"MISMATCH bl-vs-py #{i}: prog={program.hex()} env={env.hex()}")
            print(f"  max_cost={max_cost} bitlisp={bl} clvm={py}")
            if failures >= args.max_fails:
                break

        stats["ok" if bl[0] == "ok" else "err_agree"] += 1

    total = stats["ok"] + stats["err_agree"]
    print(
        f"diff_clvm: {total} compared, {stats['ok']} ok, "
        f"{stats['err_agree']} errors agreed, "
        f"{stats['policy_div']} tolerated py policy-div, "
        f"{stats['py_budget_timing']} tolerated py budget-timing, "
        f"{stats['py_no_operand_limit']} tolerated py no-operand-limit, "
        f"{failures} failures"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
