#!/usr/bin/env python3
"""Differential harness for secp_verify.

The operator has no CLVM oracle, so the differential runs against
Bitcoin Core's test-framework BIP 340 implementation, vendored with
provenance in tools/oracle/bitcoincore/. Core's signer generates valid
triples, then every verifier checks the valid triple and a mutation
battery derived from it, and every verdict must agree. The operator
layer runs the same cases end to end, checking the tri-state result,
the flat cost, and the error classes.

When a system libsecp256k1 with the schnorrsig module is present
(Homebrew's secp256k1 formula, Ubuntu's libsecp256k1-dev), the C
library Bitcoin Core itself links joins as a third verifier: it first
re-runs all 19 official vectors, then votes on every triple. The two
pinned oracles never depend on it, so the harness still runs without
it, and --require-libsecp makes its absence an error so CI cannot
lose the leg silently.

Any disagreement fails the run and prints the disagreeing case. The
summary line includes the seed, so a failure reproduces with the same
seed and a count at least as large:

    tools/diff_secp.py --count 100 --seed <seed>
"""

import argparse
import csv
import ctypes
import ctypes.util
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

BIP340_CSV = REPO_ROOT / "vectors" / "upstream" / "bip340" / "test-vectors.csv"

# x = 5 lifts to no curve point: 5^3 + 7 is not a quadratic residue.
OFF_CURVE_X = (5).to_bytes(32, "big")


def load_libsecp():
    """Bind the system libsecp256k1's BIP 340 verifier, or None.

    Returns a verify(pubkey, msg, sig) callable backed by the C
    library, with the discovered path attached as .path, or None when
    the library or its schnorrsig module is absent.
    """
    path = ctypes.util.find_library("secp256k1")
    if path is None:
        return None
    lib = ctypes.CDLL(path)
    try:
        parse = lib.secp256k1_xonly_pubkey_parse
        schnorr = lib.secp256k1_schnorrsig_verify
        create = lib.secp256k1_context_create
    except AttributeError:
        return None
    create.restype = ctypes.c_void_p
    create.argtypes = [ctypes.c_uint]
    parse.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    schnorr.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
    ]
    context = create(1)  # SECP256K1_CONTEXT_NONE
    if not context:
        return None

    def libsecp_verify(pubkey, msg, sig):
        parsed = ctypes.create_string_buffer(64)
        if not parse(context, parsed, pubkey):
            return False
        return bool(schnorr(context, sig, msg, len(msg), parsed))

    libsecp_verify.path = path
    return libsecp_verify


def check_csv_against_libsecp(libsecp):
    """Every official vector through the C library. Returns failures."""
    failures = []
    with open(BIP340_CSV, newline="") as fh:
        for row in csv.DictReader(fh):
            got = libsecp(
                bytes.fromhex(row["public key"]),
                bytes.fromhex(row["message"]),
                bytes.fromhex(row["signature"]),
            )
            want = row["verification result"] == "TRUE"
            if got is not want:
                failures.append(f"csv #{row['index']}: libsecp={got} expected={want}")
    return failures


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


def check_agreement(failures, libsecp, label, pubkey, msg, sig, expect_operator):
    """Every verifier and the operator must agree on one triple."""
    verdicts = {
        "bitlisp": bitlisp_verify(pubkey, msg, sig),
        "core": verify_schnorr(pubkey, sig, msg),
    }
    if libsecp is not None:
        verdicts["libsecp256k1"] = libsecp(pubkey, msg, sig)
    if len(set(verdicts.values())) != 1:
        failures.append(
            f"{label}: {verdicts} pk={pubkey.hex()} msg={msg.hex()} sig={sig.hex()}"
        )
        return
    operator = operator_outcome(pubkey, msg, sig)
    if operator != expect_operator:
        failures.append(
            f"{label}: operator={operator} expected={expect_operator} "
            f"pk={pubkey.hex()} msg={msg.hex()} sig={sig.hex()}"
        )


def run(count, seed, require_libsecp):
    libsecp = load_libsecp()
    if libsecp is None:
        if require_libsecp:
            print("diff_secp: libsecp256k1 required but not found")
            return 1
        print("diff_secp: no system libsecp256k1, running two verifiers")
    else:
        print(f"diff_secp: third verifier libsecp256k1 at {libsecp.path}")
    rng = random.Random(seed)
    failures = []
    if libsecp is not None:
        failures.extend(check_csv_against_libsecp(libsecp))
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
        check_agreement(failures, libsecp, f"#{index} valid", pubkey, msg, sig, ok)
        valid += 1

        fail = ("err", "secp_verify_failed")
        check_agreement(
            failures,
            libsecp,
            f"#{index} sig bitflip",
            pubkey,
            msg,
            flip_bit(rng, sig),
            fail,
        )
        check_agreement(
            failures,
            libsecp,
            f"#{index} msg bitflip",
            pubkey,
            flip_bit(rng, msg),
            sig,
            fail,
        )
        pk_flipped = flip_bit(rng, pubkey)
        check_agreement(
            failures, libsecp, f"#{index} pk bitflip", pk_flipped, msg, sig, fail
        )
        check_agreement(
            failures,
            libsecp,
            f"#{index} s past order",
            pubkey,
            msg,
            sig[:32] + (N + 1).to_bytes(32, "big"),
            fail,
        )
        check_agreement(
            failures,
            libsecp,
            f"#{index} r past field",
            pubkey,
            msg,
            (P + 1).to_bytes(32, "big") + sig[32:],
            fail,
        )
        check_agreement(
            failures, libsecp, f"#{index} off-curve pk", OFF_CURVE_X, msg, sig, fail
        )
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
    legs = "three verifiers" if libsecp is not None else "two verifiers"
    print(
        f"diff_secp: seed {seed}, {legs}, {valid} valid triples, "
        f"{mutated} mutations, {shape} operator shape cases, "
        f"{len(failures)} failures"
    )
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--require-libsecp",
        action="store_true",
        help="fail instead of degrading to two verifiers",
    )
    args = parser.parse_args()
    sys.exit(run(args.count, args.seed, args.require_libsecp))


if __name__ == "__main__":
    main()
