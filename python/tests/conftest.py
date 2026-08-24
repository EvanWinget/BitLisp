"""Shared test helpers: the corpus filler execution identity and
the corpus identity audit.

Every condition-carrying input of the transaction model must carry
the execution-identity triple. Tests that exercise other layers
carry this filler triple, which no assert in any test pool names,
so the identity satisfies the model without touching any outcome.
The audit below is the other side of the trust: every real
identity a validation vector file carries must derive the
scriptPubKey it sits behind.
"""

from bitlisp.secp256k1 import taproot_output_key

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
    filler = tuple(value.hex() for value in filler_identity().values())
    derived = {}
    filler_seen = 0
    for cases in files:
        for case in cases.values():
            for entry in case["tx"]["inputs"]:
                if "conditions" not in entry:
                    continue
                identity = (
                    entry["tapleaf"],
                    entry["merkle_root"],
                    entry["internal_key"],
                )
                if identity == filler:
                    filler_seen += 1
                    continue
                assert entry["tapleaf"] == entry["merkle_root"]
                assert entry["internal_key"] == internal_key.hex()
                root = entry["merkle_root"]
                if root not in derived:
                    spk = b"\x51\x20" + taproot_output_key(
                        internal_key, bytes.fromhex(root)
                    )
                    derived[root] = spk.hex()
                assert entry["script_pubkey"] == derived[root], case["name"]
    assert filler_seen == filler_expected
