"""Shared test helpers: the corpus filler execution identity.

Every condition-carrying input of the transaction model must carry
the execution-identity triple. Tests that exercise other layers
carry this filler triple, which no assert in any test pool names,
so the identity satisfies the model without touching any outcome.
"""

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
