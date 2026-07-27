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
from diff_clvm import Generator, run_bitlisp, run_rs  # noqa: E402


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
