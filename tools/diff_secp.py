#!/usr/bin/env python3
"""Differential harness for secp_verify.

The operator has no CLVM oracle, so the differential runs against
Bitcoin Core's test-framework BIP 340 implementation, vendored with
provenance in tools/oracle/bitcoincore/. Core's signer generates valid
triples, then both implementations verify the valid triple and a
mutation battery derived from it, and every verdict must agree. The
operator layer runs the same cases end to end, checking the tri-state
result, the flat cost, and the error classes.

Any disagreement fails the run and prints the triple, so a failure
reproduces with the printed seed:

    tools/diff_secp.py --count 300 --seed <seed>
"""

import argparse
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "oracle" / "bitcoincore"))

from bitlisp import BitLispError, run_serialized, serialize  # noqa: E402
from bitlisp.secp256k1 import N, P  # noqa: E402
from bitlisp.secp256k1 import verify as bitlisp_verify  # noqa: E402
from test_framework.key import (  # noqa: E402
    compute_xonly_pubkey,
    sign_schnorr,
    verify_schnorr,
)

MAX_COST = 11_000_000_000
SECP_VERIFY_TOTAL = 20 * 3 + 1 + 1_300_000
QUOTE = b"\x01"
SECP_VERIFY_OP = b"\x0f"
NIL = b""

# x = 5 lifts to no curve point: 5^3 + 7 is not a quadratic residue.
OFF_CURVE_X = (5).to_bytes(32, "big")


def operator_outcome(pubkey, msg, sig):
    """Run (secp_verify (q . pubkey) (q . msg) (q . sig)) end to end."""
    program = serialize(
        (SECP_VERIFY_OP, ((QUOTE, pubkey), ((QUOTE, msg), ((QUOTE, sig), NIL))))
    )
    try:
        cost, result = run_serialized(program, serialize(NIL), MAX_COST)
        return ("ok", cost, result.hex())
    except BitLispError as exc:
        return ("err", exc.code)


def flip_bit(rng, data):
    index = rng.randrange(len(data) * 8)
    flipped = bytearray(data)
    flipped[index // 8] ^= 1 << (index % 8)
    return bytes(flipped)


def check_agreement(failures, label, pubkey, msg, sig, expect_operator):
    """Both verifiers and the operator must agree on one triple."""
    ours = bitlisp_verify(pubkey, msg, sig)
    core = verify_schnorr(pubkey, sig, msg)
    if ours is not core:
        failures.append(
            f"{label}: bitlisp={ours} core={core} "
            f"pk={pubkey.hex()} msg={msg.hex()} sig={sig.hex()}"
        )
        return
    operator = operator_outcome(pubkey, msg, sig)
    if operator != expect_operator:
        failures.append(
            f"{label}: operator={operator} expected={expect_operator} "
            f"pk={pubkey.hex()} msg={msg.hex()} sig={sig.hex()}"
        )


def run(count, seed):
    rng = random.Random(seed)
    failures = []
    valid = mutated = shape = 0
    for index in range(count):
        privkey = rng.randbytes(32)
        keypair = compute_xonly_pubkey(privkey)
        if keypair[0] is None:
            continue
        pubkey = keypair[0]
        msg = rng.randbytes(32)
        sig = sign_schnorr(privkey, msg, aux=rng.randbytes(32))
        if sig is None:
            continue

        ok = ("ok", SECP_VERIFY_TOTAL, "01")
        check_agreement(failures, f"#{index} valid", pubkey, msg, sig, ok)
        valid += 1

        fail = ("err", "secp_verify_failed")
        check_agreement(
            failures, f"#{index} sig bitflip", pubkey, msg, flip_bit(rng, sig), fail
        )
        check_agreement(
            failures, f"#{index} msg bitflip", pubkey, flip_bit(rng, msg), sig, fail
        )
        pk_flipped = flip_bit(rng, pubkey)
        check_agreement(failures, f"#{index} pk bitflip", pk_flipped, msg, sig, fail)
        check_agreement(
            failures,
            f"#{index} s past order",
            pubkey,
            msg,
            sig[:32] + (N + 1).to_bytes(32, "big"),
            fail,
        )
        check_agreement(
            failures,
            f"#{index} r past field",
            pubkey,
            msg,
            (P + 1).to_bytes(32, "big") + sig[32:],
            fail,
        )
        check_agreement(failures, f"#{index} off-curve pk", OFF_CURVE_X, msg, sig, fail)
        mutated += 6

        # Operator-only shapes: the tri-state empty signature and the
        # width defects, outside the verifiers' domain.
        empty = operator_outcome(pubkey, msg, NIL)
        if empty != ("ok", SECP_VERIFY_TOTAL, "80"):
            failures.append(f"#{index} empty sig: operator={empty}")
        truncated = operator_outcome(pubkey, msg, sig[:63])
        if truncated != ("err", "secp_verify_failed"):
            failures.append(f"#{index} 63-byte sig: operator={truncated}")
        shape += 2

    for failure in failures:
        print(f"MISMATCH {failure}")
    print(
        f"diff_secp: {valid} valid triples, {mutated} mutations, "
        f"{shape} operator shape cases, {len(failures)} failures"
    )
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    sys.exit(run(args.count, args.seed))


if __name__ == "__main__":
    main()
