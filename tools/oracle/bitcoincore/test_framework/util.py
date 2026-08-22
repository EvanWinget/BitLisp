# Minimal stub of the three test_framework.util helpers the vendored
# Core files import. assert_not_equal runs on live paths (field
# division in crypto/secp256k1.py and the nonce check in key.py's
# sign_schnorr), and assert_equal runs at import time on messages.py's
# serialization sanity check, so their semantics must and do match
# upstream exactly. assert_equal omits only upstream's dict-difference
# error formatting, which changes no pass or fail outcome.
# random_bitflip is used only by the embedded self-tests, which
# BitLisp never runs.

import random


def assert_equal(thing1, thing2, *args):
    if thing1 != thing2 or any(thing1 != arg for arg in args):
        raise AssertionError(
            "not(%s)" % " == ".join(str(arg) for arg in (thing1, thing2) + args)
        )


def assert_not_equal(thing1, thing2, *, error_message=""):
    if thing1 == thing2:
        raise AssertionError(
            f"Both values are {thing1}{f', {error_message}' if error_message else ''}"
        )


def random_bitflip(data):
    data = list(data)
    data[random.randrange(len(data))] ^= 1 << random.randrange(8)
    return bytes(data)
