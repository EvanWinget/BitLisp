"""Error taxonomy.

Errors are consensus-relevant only as "the spend is invalid". The
classes exist so vectors and the diff harness can assert that BitLisp
fails for the same reason as the oracles.
"""

CODES = frozenset(
    {
        "bad_encoding",
        "path_into_atom",
        "operator_not_atom",
        "reserved_operator",
        "unknown_operator",
        "bad_arg_list",
        "wrong_arg_count",
        "arg_not_atom",
        "arg_not_pair",
        "arg_too_long",
        "bad_index",
        "index_out_of_range",
        "div_by_zero",
        "user_raise",
        "cost_exceeded",
    }
)


class BitLispError(Exception):
    """A validation failure. Consensus-relevant only as "invalid".

    The code is one of CODES, stable across releases so vectors can
    pin it.
    """

    def __init__(self, code, message):
        # A typo'd code must fail loudly even under python -O, where
        # an assert would vanish and let it become a live error class.
        if code not in CODES:
            raise ValueError(f"unknown error code {code!r}")
        super().__init__(message)
        self.code = code
