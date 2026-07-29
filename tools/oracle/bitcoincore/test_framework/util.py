# Minimal stub of the two test_framework.util helpers the vendored
# Core files import. Both are used only by the embedded unittest
# classes in those files, which BitLisp never runs. Semantics match
# upstream.

import random


def assert_not_equal(thing1, thing2, *, error_message=""):
    if thing1 == thing2:
        raise AssertionError(
            f"Both values are {thing1}"
            f"{f', {error_message}' if error_message else ''}"
        )


def random_bitflip(data):
    data = list(data)
    data[random.randrange(len(data))] ^= 1 << random.randrange(8)
    return bytes(data)
