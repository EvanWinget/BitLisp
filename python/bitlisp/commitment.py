"""The commitment scheme: how an output commits to a program and how
a spend's control block names the tree it executes in.

A program is committed as one leaf of a BIP341 script tree under
BitLisp's leaf version. The leaf script is the program's 32-byte tree
hash, never executed, and the program itself travels in the witness
to be checked against it. Everything here is hashing: the tree hash
over a node, BIP341's tagged hashes over the leaf, the branch fold,
and the annex digest. Point arithmetic stays in secp256k1.
"""

import hashlib
from dataclasses import dataclass

from . import secp256k1
from .errors import BaseConsensusError
from .sexp import is_pair

# PROVISIONAL: fixed at deployment. Any compliant byte works, the low
# bit clear, and nothing else in the scheme depends on which one.
BITLISP_LEAF_VERSION = 0xD0

# BIP341's control block: one leaf-version-and-parity byte, the 32-byte
# x-only internal key, then 32 bytes per merkle path element, at most
# 128 of them.
CONTROL_BLOCK_BASE_SIZE = 33
MERKLE_PATH_MAX_DEPTH = 128
LEAF_VERSION_MASK = 0xFE

# The first byte of a BIP341 annex.
ANNEX_TAG = 0x50


def tree_hash(node):
    """The tree hash of a node, the value sha256tree computes: an atom
    hashes as SHA-256 of 0x01 then its bytes, a pair as SHA-256 of
    0x02 then the first child's hash then the rest child's hash. An
    explicit stack, so a deep program never meets the recursion
    limit. Uncharged: the caller prices the bytes that carried the
    node, not the hashing."""
    hashes = []
    stack = [(False, node)]
    while stack:
        combine, current = stack.pop()
        if combine:
            first = hashes.pop()
            rest = hashes.pop()
            hashes.append(hashlib.sha256(b"\x02" + first + rest).digest())
        elif is_pair(current):
            stack.append((True, None))
            stack.append((False, current[0]))
            stack.append((False, current[1]))
        else:
            hashes.append(hashlib.sha256(b"\x01" + current).digest())
    return hashes[0]


def tagged_hash(tag, data):
    """BIP340's tagged hash: SHA-256 of the tag's digest twice, then
    the data. tag is the ASCII tag name."""
    tag_hash = hashlib.sha256(tag.encode("ascii")).digest()
    return hashlib.sha256(tag_hash + tag_hash + data).digest()


def compact_size(n):
    """Bitcoin's variable-length count prefix."""
    if n < 0xFD:
        return n.to_bytes(1, "little")
    if n <= 0xFFFF:
        return b"\xfd" + n.to_bytes(2, "little")
    if n <= 0xFFFFFFFF:
        return b"\xfe" + n.to_bytes(4, "little")
    return b"\xff" + n.to_bytes(8, "little")


def tapleaf_hash(leaf_version, leaf_script):
    """BIP341's leaf hash: the TapLeaf tagged hash of the leaf version
    byte, the compact-size length of the leaf script, and the leaf
    script."""
    return tagged_hash(
        "TapLeaf", bytes([leaf_version]) + compact_size(len(leaf_script)) + leaf_script
    )


def merkle_root(tapleaf, path):
    """BIP341's path fold: starting from the leaf hash, each 32-byte
    path element is combined under TapBranch with the running value,
    the two sorted lexicographically. An empty path leaves the leaf
    hash as the root."""
    node = tapleaf
    for offset in range(0, len(path), 32):
        sibling = path[offset : offset + 32]
        pair = node + sibling if node < sibling else sibling + node
        node = tagged_hash("TapBranch", pair)
    return node


def sha_annex(annex):
    """BIP341's annex digest: SHA-256 of the compact-size length of
    the annex element and the element's bytes, its leading 0x50
    included."""
    return hashlib.sha256(compact_size(len(annex)) + annex).digest()


def taproot_script_pubkey(internal_key, root):
    """The 34-byte scriptPubKey of an output committing to root under
    internal_key, or None when the key does not lift or the tweak
    fails, the same value defects taproot_output_key reports."""
    output_key = secp256k1.taproot_output_key(internal_key, root)
    if output_key is None:
        return None
    return b"\x51\x20" + output_key


@dataclass(frozen=True)
class ControlBlock:
    """A parsed BIP341 control block: the leaf version, the output
    key's parity bit, the x-only internal key, and the merkle path as
    the concatenated 32-byte elements."""

    leaf_version: int
    parity: int
    internal_key: bytes
    path: bytes

    @classmethod
    def parse(cls, data):
        """Splits a control block, else BaseConsensusError: its length
        must be 33 plus a multiple of 32, at most 128 path elements."""
        path_length = len(data) - CONTROL_BLOCK_BASE_SIZE
        depth, remainder = divmod(path_length, 32)
        if path_length < 0 or remainder or depth > MERKLE_PATH_MAX_DEPTH:
            raise BaseConsensusError(
                f"control block of {len(data)} bytes is not 33 plus 32m, m at most 128"
            )
        return cls(
            leaf_version=data[0] & LEAF_VERSION_MASK,
            parity=data[0] & 1,
            internal_key=data[1:CONTROL_BLOCK_BASE_SIZE],
            path=data[CONTROL_BLOCK_BASE_SIZE:],
        )

    def identity(self, leaf_script):
        """The execution identity this block names for a revealed leaf
        script: (tapleaf, merkle root)."""
        tapleaf = tapleaf_hash(self.leaf_version, leaf_script)
        return tapleaf, merkle_root(tapleaf, self.path)

    def check(self, leaf_script, script_pubkey):
        """Base consensus's script-path check: the internal key lifts,
        tweaked by the root of this path it gives the spent
        scriptPubKey's output key, and the parity bit matches. Returns
        (tapleaf, merkle root), else BaseConsensusError."""
        tapleaf, root = self.identity(leaf_script)
        tweaked = secp256k1.taproot_output_point(self.internal_key, root)
        if tweaked is None:
            raise BaseConsensusError(
                "internal key lifts to no curve point, or its tweak by this "
                "root is no point"
            )
        x, y = tweaked
        expected = b"\x51\x20" + x.to_bytes(32, "big")
        if script_pubkey != expected:
            raise BaseConsensusError(
                f"spent scriptPubKey {script_pubkey.hex()} is not the taproot "
                f"output {expected.hex()} of this control block and leaf"
            )
        if y % 2 != self.parity:
            raise BaseConsensusError("control block parity bit does not match")
        return tapleaf, root
