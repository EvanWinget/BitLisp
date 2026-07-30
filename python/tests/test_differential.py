"""Fixed-seed differential smoke test against the consensus oracle.

A fast CI gate, not the full harness: tools/diff_clvm.py runs larger
corpora against both oracles. This test pins a fixed slice so every CI
run exercises the machine, the operators, and the serializer against
chia_rs end to end.
"""

import random
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

# The oracle wheels are the `oracles` extra, not `dev`: skip cleanly
# instead of failing collection when only `dev` is installed.
pytest.importorskip("chia_rs")
import diff_clvm  # noqa: E402
import diff_sha256tree  # noqa: E402
from diff_clvm import Generator, run_bitlisp, run_rs  # noqa: E402


def test_fixed_seed_sha256tree_agrees_with_flag_enabled_oracle():
    # A fast fixed slice of tools/diff_sha256tree.py: trees through
    # the operator versus the wheel's flag-enabled dispatch, and
    # results versus its tree_hash puzzle-hash utility.
    import chia_rs

    flag = chia_rs.ENABLE_SHA256_TREE
    rng = random.Random(7777)
    gen = diff_sha256tree.TreeGenerator(rng, max_depth=4)
    mismatches = []
    for i in range(150):
        tree = gen.tree(rng.randint(0, 4))
        program = diff_sha256tree.serialize(
            diff_sha256tree.lst(b"\x3f", (b"\x01", tree))
        )
        env = diff_sha256tree.serialize(b"")
        bl = diff_sha256tree.run_bitlisp(program, env, 11_000_000_000)
        rs = diff_sha256tree.run_rs(program, env, 11_000_000_000, flag)
        digest = bytes(chia_rs.tree_hash(diff_sha256tree.serialize(tree))).hex()
        if bl != rs or bl[0] != "ok" or bl[2] != "a0" + digest:
            mismatches.append((i, program.hex(), bl, rs, digest))
    assert not mismatches, mismatches[:3]


def test_fixed_seed_corpus_agrees_with_consensus_oracle():
    rng = random.Random(7777)
    gen = Generator(rng, max_depth=5)
    mismatches = []
    for i in range(300):
        program = diff_clvm.serialize(gen.program(5))
        env = diff_clvm.serialize(gen.value_tree(3))
        max_cost = 11_000_000_000 if rng.random() < 0.8 else rng.randint(1, 5000)
        bl = run_bitlisp(program, env, max_cost)
        rs = run_rs(program, env, max_cost)
        if bl != rs:
            mismatches.append((i, program.hex(), env.hex(), max_cost, bl, rs))
    assert not mismatches, mismatches[:3]
