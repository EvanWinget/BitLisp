"""Shared helpers for the test suite.

A plain module rather than pytest's conftest hook file: importing
helpers by name from conftest works only through conftest's special
loading, so the library lives here and no conftest exists.

Every condition-carrying input of the transaction model must carry
the execution-identity triple. Tests that exercise other layers
carry the filler triple below, which no assert in any test pool
names, so the identity satisfies the model without touching any
outcome. The audit at the bottom is the other side of the trust:
every real identity a validation vector file carries must derive
the scriptPubKey it sits behind.
"""

import json
from pathlib import Path

from bitlisp.secp256k1 import taproot_output_key

REPO_ROOT = Path(__file__).resolve().parents[2]

# The BIP341 nothing-up-my-sleeve point: no key-path spend exists.
NUMS = bytes.fromhex("50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0")

FILLER_TAPLEAF = b"\x0a" * 32
FILLER_MERKLE_ROOT = b"\x0b" * 32
FILLER_INTERNAL_KEY = b"\x0c" * 32


def filler_identity():
    """The filler triple as TxInput keyword arguments."""
    return {
        "tapleaf": FILLER_TAPLEAF,
        "merkle_root": FILLER_MERKLE_ROOT,
        "internal_key": FILLER_INTERNAL_KEY,
    }


def filler_identity_json():
    """The filler triple as the hex fields a tx context carries."""
    return {key: value.hex() for key, value in filler_identity().items()}


def load_vector(name):
    """The named vector file's cases, keyed by case name."""
    path = REPO_ROOT / "vectors" / name
    return {case["name"]: case for case in json.loads(path.read_text())["cases"]}


def condition_inputs(files):
    """Yields (case, input entry) for every condition-carrying input
    across the given vector case maps."""
    for cases in files:
        for case in cases.values():
            for entry in case["tx"]["inputs"]:
                if "conditions" in entry:
                    yield case, entry


def assert_corpus_identities(files, internal_key, filler_expected):
    """Audits every condition-carrying input in the given vector
    case maps: the input's scriptPubKey must be the taproot output
    of its internal key tweaked by its merkle root, with the
    single-leaf tree's root equal to its leaf hash and the internal
    key the one the caller pins. Inputs carrying the filler triple
    are exempt but counted against filler_expected, so the
    exemption cannot widen unnoticed. The tweak is derived once per
    distinct root: the corpus reuses a few instance roots across
    many cases and the point multiplication dominates the audit."""
    filler = (
        FILLER_TAPLEAF.hex(),
        FILLER_MERKLE_ROOT.hex(),
        FILLER_INTERNAL_KEY.hex(),
    )
    derived = {}
    filler_seen = 0
    for case, entry in condition_inputs(files):
        identity = (entry["tapleaf"], entry["merkle_root"], entry["internal_key"])
        if identity == filler:
            filler_seen += 1
            continue
        assert entry["tapleaf"] == entry["merkle_root"]
        assert entry["internal_key"] == internal_key.hex()
        root = entry["merkle_root"]
        if root not in derived:
            spk = b"\x51\x20" + taproot_output_key(internal_key, bytes.fromhex(root))
            derived[root] = spk.hex()
        assert entry["script_pubkey"] == derived[root], case["name"]
    assert filler_seen == filler_expected
