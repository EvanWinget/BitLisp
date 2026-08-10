"""Cost constants, inherited from the CLVM cost table.

OP_DISPATCH_COST was pinned empirically against the oracle binaries:
every operator application except quote charges it on top of the
operator's own cost.
"""

QUOTE_COST = 20
APPLY_COST = 90
OP_DISPATCH_COST = 1
PATH_LOOKUP_BASE_COST = 40
PATH_LOOKUP_COST_PER_LEG = 4
PATH_LOOKUP_COST_PER_ZERO_BYTE = 4
MALLOC_COST_PER_BYTE = 10

IF_COST = 33
CONS_COST = 50
FIRST_COST = 30
REST_COST = 30
LISTP_COST = 19
EQ_BASE_COST = 117
EQ_COST_PER_BYTE = 1

ARITH_BASE_COST = 99
ARITH_COST_PER_ARG = 320
ARITH_COST_PER_BYTE = 3
MUL_BASE_COST = 92
MUL_COST_PER_OP = 885
MUL_LINEAR_COST_PER_BYTE = 6
MUL_SQUARE_COST_PER_BYTE_DIVIDER = 128
DIV_BASE_COST = 988
DIV_COST_PER_BYTE = 4
DIVMOD_BASE_COST = 1116
DIVMOD_COST_PER_BYTE = 6
GR_BASE_COST = 498
GR_COST_PER_BYTE = 2

LOG_BASE_COST = 100
LOG_COST_PER_ARG = 264
LOG_COST_PER_BYTE = 3
LOGNOT_BASE_COST = 331
LOGNOT_COST_PER_BYTE = 3
ASHIFT_BASE_COST = 596
ASHIFT_COST_PER_BYTE = 3
SHIFT_BASE_COST = 277
SHIFT_COST_PER_BYTE = 3

BOOL_BASE_COST = 200
BOOL_COST_PER_ARG = 300

SHA256_BASE_COST = 87
SHA256_COST_PER_ARG = 134
SHA256_COST_PER_BYTE = 2
# PROVISIONAL: secp_verify has no CLVM oracle to inherit from. The
# value adopts the magnitude of the consensus oracle's ECDSA verify
# pending the Phase 4 measurement. Flat: every argument width is
# fixed by the operator's shape checks.
SECP_VERIFY_COST = 1_300_000

# sha256tree charges per visited node during its walk: the base cost
# rides on the first node's charge, each visited pair charges the
# pair cost, each visited atom charges the per-byte cost on its
# length plus one for the leaf tag byte, and the 32-byte result
# charges plain malloc. The constants are the consensus oracle's own
# sha256tree, carried behind its release flag (a recorded
# divergence: at flags 0 the oracle treats the opcode as unknown).
SHA256TREE_BASE_COST = 270
SHA256TREE_PAIR_COST = 460
SHA256TREE_COST_PER_BYTE = 2

GRS_BASE_COST = 117
GRS_COST_PER_BYTE = 1
SUBSTR_COST = 1
STRLEN_BASE_COST = 173
STRLEN_COST_PER_BYTE = 1
CONCAT_BASE_COST = 142
CONCAT_COST_PER_ARG = 135
CONCAT_COST_PER_BYTE = 3

# Condition costs, charged as a condition list parses, on the same
# per-input budget the VM run accrues against. Every constant is
# flat: operand bytes are already priced upstream, at
# MALLOC_COST_PER_BYTE when evaluation builds an atom or by the
# serialized witness's per-byte weight when the solution carries
# one, so a per-byte term here would charge the same bytes twice.
# Every condition constant is PROVISIONAL: the magnitudes adopt the
# deployed Chia condition-cost table where a deployed precedent
# exists, and the Phase 4 measurement pass re-prices all five.
CONDITION_GENERIC_COST = 200
CONDITION_MESSAGE_COST = 700
# Equals SECP_VERIFY_COST deliberately. Both constants price one
# BIP340 verification, so one Phase 4 measurement settles the price
# in both layers and a program can never buy the same verification
# cheaper as a condition than as an operator.
CONDITION_SIG_ASSERT_COST = SECP_VERIFY_COST
# The point derivation the two taproot condition entries perform, a
# lift and one fixed-base multiplication. That is less work than a
# verification's two multiplications, so the verify magnitude is a
# deliberate overprice pending the Phase 4 measurement.
TAPROOT_TWEAK_COST = 1_300_000
# Each output claim. Adopts the deployed Chia coin-creation
# magnitude. Deliberately flat: a high linear price with the
# per-input budget as the cap.
CREATE_OUTPUT_COST = 1_350_000
