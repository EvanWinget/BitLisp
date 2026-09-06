"""BIP 340 Schnorr verification and BIP 341 output-key derivation.

Self-contained on purpose: the reference implementation is the spec
artifact and carries no dependencies, so the secp256k1 arithmetic
lives here as plain integer math in affine coordinates, the same
shape the algorithms have in the BIPs. The test suite cross-checks
both jobs against the official BIP 340 and BIP 341 vectors and
against Bitcoin Core's test-framework implementations. This module
favors reviewability over speed and does not run in constant time,
which is safe here because every input it sees, signatures under
verification and taproot tweak inputs alike, is public. A
consensus-facing implementation must use a hardened curve library
instead.
"""

import hashlib

# The secp256k1 field prime, group order, and base point.
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)


def tagged_hash(tag, data):
    """BIP340's tagged hash: SHA-256 of the tag's digest twice, then
    the data. tag is the ASCII tag name. Every tagged digest the
    package computes comes through here, so the tags in use are the
    strings this function is called with."""
    tag_hash = hashlib.sha256(tag.encode("ascii")).digest()
    return hashlib.sha256(tag_hash + tag_hash + data).digest()


def _challenge_hash(data):
    return tagged_hash("BIP0340/challenge", data)


def _tap_tweak_scalar(internal_key, merkle_root):
    """The taproot tweak scalar: the TapTweak tagged hash of the
    internal key followed by the merkle root, as an integer.

    An empty merkle_root leaves the internal key alone, which is the
    key-only tweak of an output committing to no script tree.
    """
    return int.from_bytes(tagged_hash("TapTweak", internal_key + merkle_root), "big")


def _tweaked_point(point, t):
    """The point point + t*G, or None.

    None when t is not below the group order or the sum is the point
    at infinity. Both are rejected rather than reduced or folded, so
    a caller never sees a key derived from out-of-range inputs.
    """
    if t >= N:
        return None
    return point_add(point, point_mul(t, G))


def taproot_output_point(internal_key, merkle_root):
    """The taproot output point (x, y), or None.

    internal_key is 32 bytes and merkle_root 0 or 32 bytes, widths
    the caller guarantees. Every value defect (an internal key that
    lifts to no curve point, a tweak scalar at or above the group
    order, a tweaked point at infinity) returns None, never raises.
    The full point, so a caller checking a control block can read
    the parity of y.
    """
    if len(internal_key) != 32 or len(merkle_root) not in (0, 32):
        raise ValueError(
            "taproot_output_point requires a 32-byte key and a 0- or 32-byte root"
        )
    point = lift_x(int.from_bytes(internal_key, "big"))
    if point is None:
        return None
    return _tweaked_point(point, _tap_tweak_scalar(internal_key, merkle_root))


def taproot_output_key(internal_key, merkle_root):
    """The 32-byte x-only taproot output key, or None as
    taproot_output_point."""
    tweaked = taproot_output_point(internal_key, merkle_root)
    if tweaked is None:
        return None
    return tweaked[0].to_bytes(32, "big")


def lift_x(x):
    """The even-y curve point with x coordinate `x`, or None.

    None when x is not a canonical field element or no curve point
    has that x coordinate.
    """
    if x >= P:
        return None
    y_sq = (pow(x, 3, P) + 7) % P
    # P is congruent to 3 mod 4, so this power is a square root of
    # y_sq exactly when y_sq is a quadratic residue.
    y = pow(y_sq, (P + 1) // 4, P)
    if y * y % P != y_sq:
        return None
    return (x, y if y % 2 == 0 else P - y)


def point_add(a, b):
    """Affine point addition. None is the point at infinity."""
    if a is None:
        return b
    if b is None:
        return a
    ax, ay = a
    bx, by = b
    if ax == bx and (ay + by) % P == 0:
        return None
    if a == b:
        lam = 3 * ax * ax * pow(2 * ay, P - 2, P) % P
    else:
        lam = (by - ay) * pow(bx - ax, P - 2, P) % P
    x = (lam * lam - ax - bx) % P
    return (x, (lam * (ax - x) - ay) % P)


def point_mul(k, point):
    """Double-and-add scalar multiplication of a point or None."""
    result = None
    while k:
        if k & 1:
            result = point_add(result, point)
        point = point_add(point, point)
        k >>= 1
    return result


def verify(pubkey, msg, sig):
    """BIP 340 Verify: True exactly when sig is valid for (pubkey, msg).

    pubkey is the 32-byte x-only public key and sig the 64-byte
    signature, widths the caller guarantees. The message may be any
    length here: BitLisp's exactly-32-bytes message rule belongs to
    the operator layer, and keeping full BIP 340 semantics in this
    module lets the official vectors, variable-length messages
    included, run against it unmodified. Every value defect (a pubkey
    that lifts to no curve point, a non-canonical r or s, a failed
    group equation) returns False, never raises.
    """
    if len(pubkey) != 32 or len(sig) != 64:
        raise ValueError("verify requires a 32-byte pubkey and a 64-byte sig")
    point = lift_x(int.from_bytes(pubkey, "big"))
    if point is None:
        return False
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:], "big")
    if r >= P or s >= N:
        return False
    e = int.from_bytes(_challenge_hash(sig[:32] + pubkey + msg), "big") % N
    # R = s*G + (-e)*point, negating a point by flipping its y. No
    # curve point has y = 0 (the group order is an odd prime, so
    # there is no 2-torsion), so the flip stays in range.
    e_point = point_mul(e, point)
    neg_e_point = None if e_point is None else (e_point[0], P - e_point[1])
    result = point_add(point_mul(s, G), neg_e_point)
    if result is None or result[1] % 2 != 0:
        return False
    return result[0] == r
