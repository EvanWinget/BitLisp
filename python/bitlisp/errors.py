"""Error taxonomy.

Errors are consensus-relevant only as "the spend is invalid". The
classes exist so vectors can pin the reason a spend fails: oracle
parity for the VM codes, the named rejection rule for the condition
and validation codes, which have no oracle.
"""

CODES = frozenset(
    {
        "bad_witness",
        "bad_encoding",
        "leaf_mismatch",
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
        "shift_too_large",
        "div_by_zero",
        "secp_verify_failed",
        "user_raise",
        "cost_exceeded",
        "bad_condition_list",
        "bad_condition_opcode",
        "bad_condition_arity",
        "bad_condition_arg",
        "reserved_cost_too_low",
        "unsatisfied_output_claim",
        "unsatisfied_locktime_assert",
        "unsatisfied_sequence_assert",
        "unsatisfied_outpoint_assert",
        "unsatisfied_scriptpubkey_assert",
        "unsatisfied_amount_assert",
        "unsatisfied_taptree_assert",
        "unasserted_annex",
        "unsatisfied_annex_assert",
        "unbalanced_message",
        "unsatisfied_announcement_assert",
        "unsatisfied_sig_assert",
        "unsatisfied_seal_assert",
        "insufficient_fee",
    }
)


class BaseConsensusError(Exception):
    """A spend that never reaches BitLisp's rules.

    Base consensus checks a script-path spend's control block before
    any rule of this layer runs: its length, that the internal key
    lifts to a curve point, and that the key tweaked by the revealed
    leaf's merkle root gives the spent scriptPubKey. A witness that
    fails those, or whose leaf version is not BitLisp's, is either
    rejected by base consensus or is not a BitLisp spend at all, and
    no error code of CODES describes it. Distinct from BitLispError
    so a vector can never pin one as the other.
    """


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
