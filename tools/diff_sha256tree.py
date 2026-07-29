#!/usr/bin/env python3
"""Differential harness for sha256tree.

Deployed consensus at flags 0 treats opcode 0x3f as unknown (a
recorded divergence), so the operator cannot ride the intersection
harness. It is pinned against the released oracle artifacts on four
legs instead:

1. The pinned consensus wheel dispatches the same operator behind its
   ENABLE_SHA256_TREE release flag. Every generated program runs
   through bitlisp and the flag-enabled wheel, and the (cost, result)
   or error class must match exactly, including at budgets within a
   few units of the measured cost, where the budget boundary decides
   the outcome. This is the only leg that checks cost, so the cost
   constants rest on the flag-enabled wheel alone.
2. The wheel separately exports the tree_hash puzzle-hash utility,
   the algorithm Chia consensus has applied to puzzle commitments
   since genesis. Every hashed tree's result must equal the utility's
   digest. Legs 1 and 2 are two views of the one pinned wheel.
3. An in-language tree-hash program built from intersection operators
   (a, i, l, c, sha256, paths) runs through bitlisp and both pinned
   oracles at flags 0, and every implementation's result must equal
   the operator's. This leg ties the operator to semantics every
   deployed binary can confirm without the flag.
4. The divergence itself: every generated program also runs through
   both oracles at flags 0, which must accept the opcode as unknown
   and return nil. This pins the recorded oracle-side behavior, that
   deployed consensus does not dispatch 0x3f, on every run.

The generator draws leaf-heavy and pair-heavy trees, atom sizes that
cross the one-byte and length-prefixed serialization forms, redundant
integer encodings, and cons-built shared structure ((c X X) chains),
where the walk must charge a node once per visit. Arity defects run
against the flag-enabled wheel each round. Any disagreement fails the
run and prints the case with the seed, so a failure reproduces with:

    tools/diff_sha256tree.py --count 400 --seed <printed seed>
"""

import argparse
import io
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

import chia_rs  # noqa: E402
from bitlisp import BitLispError, run_serialized, serialize  # noqa: E402
from clvm import SExp  # noqa: E402
from clvm import run_program as clvm_run_program  # noqa: E402
from clvm.operators import OPERATOR_LOOKUP  # noqa: E402
from clvm.serialize import sexp_from_stream, sexp_to_stream  # noqa: E402

MAX_COST = 11_000_000_000
OP = b"\x3f"
NIL = b""
Q = b"\x01"


def q(node):
    return (Q, node)


def lst(*items):
    node = NIL
    for item in reversed(items):
        node = (item, node)
    return node


# The in-language tree hash, leg 3. Env shape is (self tree): path 2
# is self, path 5 the tree, paths 9 and 13 the tree's children. An
# atom hashes as (sha256 (q . 1) 5), a pair recurses through apply on
# both children and hashes the tag byte 2 with the two child digests.
ATOM_BRANCH = lst(b"\x0b", q(b"\x01"), b"\x05")
PAIR_BRANCH = lst(
    b"\x0b",
    q(b"\x02"),
    lst(b"\x02", b"\x02", lst(b"\x04", b"\x02", lst(b"\x04", b"\x09", q(NIL)))),
    lst(b"\x02", b"\x02", lst(b"\x04", b"\x02", lst(b"\x04", b"\x0d", q(NIL)))),
)
SELF_PROG = lst(
    b"\x02",
    lst(b"\x03", lst(b"\x07", b"\x05"), q(PAIR_BRANCH), q(ATOM_BRANCH)),
    b"\x01",
)


def in_language_program(tree):
    return lst(
        b"\x02",
        q(SELF_PROG),
        lst(b"\x04", q(SELF_PROG), lst(b"\x04", q(tree), q(NIL))),
    )


def run_bitlisp(program, env, max_cost):
    try:
        cost, result = run_serialized(program, env, max_cost)
        return ("ok", cost, result.hex())
    except BitLispError as exc:
        return ("err", exc.code)


def run_rs(program, env, max_cost, flags):
    try:
        cost, node = chia_rs.run_chia_program(program, env, max_cost, flags)
    except Exception as exc:  # chia_rs raises ValueError
        message = str(exc)
        if "cost exceeded" in message:
            return ("err", "cost_exceeded")
        if "takes exactly" in message:
            return ("err", "wrong_arg_count")
        return ("err", message)
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
        return ("err", str(exc))
    buf = io.BytesIO()
    sexp_to_stream(result, buf)
    return ("ok", cost, buf.getvalue().hex())


class TreeGenerator:
    def __init__(self, rng, max_depth):
        self.rng = rng
        self.max_depth = max_depth

    def atom(self):
        r = self.rng
        roll = r.random()
        if roll < 0.3:
            return b"" if r.random() < 0.3 else bytes([r.randint(0, 255)])
        if roll < 0.75:
            size = r.randint(2, 40)
        elif roll < 0.95:
            # Crosses the one-byte serialization form's 0x40 ceiling.
            size = r.randint(41, 300)
        else:
            size = r.randint(301, 3000)
        data = r.randbytes(size)
        if r.random() < 0.15:
            # Redundant integer spellings are legal leaves and must
            # hash as given.
            data = (b"\x00" if r.random() < 0.5 else b"\xff") * r.randint(1, 3) + data
        return data

    def tree(self, depth):
        if depth <= 0 or self.rng.random() < 0.4:
            return self.atom()
        return (self.tree(depth - 1), self.tree(depth - 1))

    def shared_program(self):
        # (c X X) chains reach 2^k leaf-tree visits for k conses: the
        # walk must charge per visit, and the budget must bound the
        # work. Half the chains hash a quoted tree, half the
        # environment.
        r = self.rng
        k = r.randint(1, 8)
        node = q(self.tree(2)) if r.random() < 0.5 else b"\x01"
        for _ in range(k):
            node = lst(b"\x04", node, node)
        return lst(OP, node)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=400)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--max-depth", type=int, default=6)
    args = parser.parse_args()

    flag = chia_rs.ENABLE_SHA256_TREE
    rng = random.Random(args.seed)
    gen = TreeGenerator(rng, args.max_depth)
    failures = 0
    stats = {
        "full": 0,
        "boundary": 0,
        "utility": 0,
        "in_language": 0,
        "arity": 0,
        "exponential": 0,
        "flags0": 0,
    }

    def fail(kind, detail):
        nonlocal failures
        failures += 1
        print(f"MISMATCH {kind} seed={args.seed}: {detail}")

    for i in range(args.count):
        shared = rng.random() < 0.25
        if shared:
            program_node = gen.shared_program()
            env_node = gen.tree(2)
        else:
            tree = gen.tree(rng.randint(0, args.max_depth))
            program_node = lst(OP, q(tree))
            env_node = NIL
        program = serialize(program_node)
        env = serialize(env_node)

        bl = run_bitlisp(program, env, MAX_COST)
        rs = run_rs(program, env, MAX_COST, flag)
        if bl != rs:
            fail("full", f"#{i} prog={program.hex()} env={env.hex()} {bl} vs {rs}")
            continue
        stats["full"] += 1

        # Leg 4: at flags 0 both oracles must treat 0x3f as an
        # unknown operator, accepted with result nil, the oracle side
        # of the recorded divergence. Costs are not compared, the
        # unknown-op charge has nothing to do with the operator's.
        # Guarded on success so an erroring argument's failure is
        # never misread as unknown-op rejection.
        if bl[0] == "ok":
            rs0 = run_rs(program, env, MAX_COST, 0)
            py0 = run_py(program, env, MAX_COST)
            if rs0[0] != "ok" or rs0[2] != "80" or py0[0] != "ok" or py0[2] != "80":
                fail(
                    "flags0",
                    f"#{i} prog={program.hex()} env={env.hex()} rs={rs0} py={py0}",
                )
            else:
                stats["flags0"] += 1

        if bl[0] == "ok":
            budget = bl[1] + rng.choice((-2, -1, 0))
            bl_b = run_bitlisp(program, env, budget)
            rs_b = run_rs(program, env, budget, flag)
            if bl_b != rs_b:
                fail(
                    "boundary",
                    f"#{i} prog={program.hex()} env={env.hex()} "
                    f"budget={budget} {bl_b} vs {rs_b}",
                )
            else:
                stats["boundary"] += 1

        if not shared and bl[0] == "ok":
            digest = bytes(chia_rs.tree_hash(serialize(tree))).hex()
            if bl[2] != "a0" + digest:
                fail(
                    "utility", f"#{i} tree={serialize(tree).hex()} {bl[2]} vs {digest}"
                )
            else:
                stats["utility"] += 1

        if not shared and bl[0] == "ok" and rng.random() < 0.25:
            ref_program = serialize(in_language_program(tree))
            ref_bl = run_bitlisp(ref_program, env, MAX_COST)
            ref_rs = run_rs(ref_program, env, MAX_COST, 0)
            ref_py = run_py(ref_program, env, MAX_COST)
            outcomes = {
                "bitlisp": ref_bl[2] if ref_bl[0] == "ok" else ref_bl,
                "chia_rs": ref_rs[2] if ref_rs[0] == "ok" else ref_rs,
                "clvm": ref_py[2] if ref_py[0] == "ok" else ref_py,
            }
            if any(value != bl[2] for value in outcomes.values()):
                fail(
                    "in_language",
                    f"#{i} tree={serialize(tree).hex()} op={bl[2]} {outcomes}",
                )
            else:
                stats["in_language"] += 1

    for argc in (0, 2, 3):
        node = NIL
        for _ in range(argc):
            node = (q(gen.atom()), node)
        program = serialize((OP, node))
        env = serialize(NIL)
        bl = run_bitlisp(program, env, MAX_COST)
        rs = run_rs(program, env, MAX_COST, flag)
        if bl != rs or bl != ("err", "wrong_arg_count"):
            fail("arity", f"argc={argc} {bl} vs {rs}")
        else:
            stats["arity"] += 1

    # Exponential shared-environment DAG: k nested applies of
    # (a (q . inner) (c 1 1)) double the reachable environment per
    # level in linear program bytes, so the walk faces 2^k visits
    # under a budget that covers a few thousand. Both sides must
    # report cost_exceeded, and must do so in bounded time: an
    # implementation that hashes before charging would hang here.
    k = rng.randint(25, 50)
    node = b"\x01"
    for _ in range(k):
        node = lst(b"\x02", q(node), lst(b"\x04", b"\x01", b"\x01"))
    program = serialize(lst(OP, node))
    env = serialize(gen.atom())
    budget = rng.randint(50_000, 2_000_000)
    bl = run_bitlisp(program, env, budget)
    rs = run_rs(program, env, budget, flag)
    if bl != rs or bl != ("err", "cost_exceeded"):
        fail("exponential", f"k={k} budget={budget} {bl} vs {rs}")
    else:
        stats["exponential"] += 1

    print(
        f"diff_sha256tree: seed={args.seed}, {stats['full']} full, "
        f"{stats['flags0']} flags0, {stats['boundary']} boundary, "
        f"{stats['utility']} utility, {stats['in_language']} in-language, "
        f"{stats['arity']} arity, {stats['exponential']} exponential, "
        f"{failures} failures"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
