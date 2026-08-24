"""Condition-list parsing and validation.

A successful program evaluation yields a condition list: a proper list
of conditions, each a proper list opening with a one-byte opcode atom.
Opcode values fall in three tiers. Assigned values carry the
vocabulary's semantics under strict arity and minimal integer
encodings. Values 0x80 and above are reserved: accepted with a
declared cost and no enforced semantics, the forward-compatibility
hatch a later soft fork can tighten into real conditions. Everything
else is invalid, so a typo near a real opcode fails loudly instead of
becoming an accidental no-op.

Parsing is also where cost charges: each condition charges its flat
cost in list order after its own encoding checks, on the same
per-input budget the VM run accrued against, so a spend that cannot
pay for its conditions dies here before any validation rule does
work on them.
"""

from dataclasses import dataclass

from . import secp256k1
from .costs import (
    CONDITION_GENERIC_COST,
    CONDITION_MESSAGE_COST,
    CONDITION_SIG_ASSERT_COST,
    CREATE_OUTPUT_COST,
    TAPROOT_TWEAK_COST,
)
from .errors import BitLispError
from .sexp import NIL, atom_to_int, int_to_atom, is_atom, is_pair

MAX_MONEY = 2_100_000_000_000_000
MAX_SCRIPT_PUBKEY_SIZE = 10_000
RESERVED_COST_FLOOR = 500

CREATE_OUTPUT = 0x01
CREATE_OUTPUT_TAPROOT = 0x02
ASSERT_SIG_MY_TXID = 0x10
ASSERT_SIG_MY_SCRIPTPUBKEY = 0x11
ASSERT_SIG_MY_AMOUNT = 0x12
ASSERT_SIG_MY_SCRIPTPUBKEY_AMOUNT = 0x13
ASSERT_SIG_MY_TXID_AMOUNT = 0x14
ASSERT_SIG_MY_TXID_SCRIPTPUBKEY = 0x15
ASSERT_SIG_RAW = 0x16
ASSERT_SIG_MY_OUTPOINT = 0x17
ASSERT_LOCKTIME_HEIGHT = 0x20
ASSERT_LOCKTIME_TIME = 0x21
ASSERT_SEQUENCE_HEIGHT = 0x22
ASSERT_SEQUENCE_TIME = 0x23
ASSERT_MY_OUTPOINT = 0x30
ASSERT_MY_TXID = 0x31
ASSERT_MY_SCRIPTPUBKEY = 0x32
ASSERT_MY_AMOUNT = 0x33
ASSERT_MY_TAPROOT = 0x37
ASSERT_MY_TAPTREE = 0x38
ANNOUNCE = 0x40
ASSERT_ANNOUNCEMENT = 0x41
ASSURE = 0x42
REQUIRE = 0x43
RESERVE_FEE = 0x50
SEAL = 0x60
SEAL_OUTPUTS = 0x61
_RESERVED_START = 0x80

MAX_MESSAGE_SIZE = 1024
OUTPOINT_SIZE = 36
SIG_PUBKEY_SIZE = 32
SIG_SIGNATURE_SIZE = 64

# Each signature assert's name, digest tag, and binding fields. The
# digest is tagged_hash(tag, binding fields || message) with every
# binding field fixed-length before the variable-length message, so
# equal digests imply equal fields and equal messages. RAW binds
# nothing: its digest commits to the message alone, under its own
# tag, which is what keeps a RAW triple and a bound triple in
# disjoint domains with no further rule.
SIG_BINDINGS = {
    ASSERT_SIG_MY_TXID: (
        "ASSERT_SIG_MY_TXID",
        "BitLisp/sig/my_txid",
        ("txid",),
    ),
    ASSERT_SIG_MY_SCRIPTPUBKEY: (
        "ASSERT_SIG_MY_SCRIPTPUBKEY",
        "BitLisp/sig/my_scriptpubkey",
        ("spk_hash",),
    ),
    ASSERT_SIG_MY_AMOUNT: (
        "ASSERT_SIG_MY_AMOUNT",
        "BitLisp/sig/my_amount",
        ("amount8",),
    ),
    ASSERT_SIG_MY_SCRIPTPUBKEY_AMOUNT: (
        "ASSERT_SIG_MY_SCRIPTPUBKEY_AMOUNT",
        "BitLisp/sig/my_scriptpubkey_amount",
        ("spk_hash", "amount8"),
    ),
    ASSERT_SIG_MY_TXID_AMOUNT: (
        "ASSERT_SIG_MY_TXID_AMOUNT",
        "BitLisp/sig/my_txid_amount",
        ("txid", "amount8"),
    ),
    ASSERT_SIG_MY_TXID_SCRIPTPUBKEY: (
        "ASSERT_SIG_MY_TXID_SCRIPTPUBKEY",
        "BitLisp/sig/my_txid_scriptpubkey",
        ("txid", "spk_hash"),
    ),
    ASSERT_SIG_RAW: (
        "ASSERT_SIG_RAW",
        "BitLisp/sig/raw",
        (),
    ),
    ASSERT_SIG_MY_OUTPOINT: (
        "ASSERT_SIG_MY_OUTPOINT",
        "BitLisp/sig/my_outpoint",
        ("outpoint",),
    ),
}

# A participant specifier names an input's prevout data and
# execution identity at one of 32 precisions. The commitment
# value's low three bits select prevout fields: 0b100 the creating
# txid, 0b010 the spent scriptPubKey, 0b001 the amount, except
# that 0b111 commits to the whole outpoint as a single 36-byte
# value rather than the three fields separately.
_PREVOUT_OPERANDS = {
    0b000: (),
    0b001: ("amount",),
    0b010: ("script_pubkey",),
    0b011: ("script_pubkey", "amount"),
    0b100: ("txid",),
    0b101: ("txid", "amount"),
    0b110: ("txid", "script_pubkey"),
    0b111: ("outpoint",),
}
# Bit 3 appends the executing leaf's tapleaf hash and bit 4 the
# spending path's merkle root, each after the prevout operands,
# tapleaf first. All 32 combinations are valid commitment values.
SPECIFIER_OPERANDS = {
    prevout | (tapleaf << 3) | (root << 4): (
        operands
        + (("tapleaf",) if tapleaf else ())
        + (("merkle_root",) if root else ())
    )
    for prevout, operands in _PREVOUT_OPERANDS.items()
    for tapleaf in (0, 1)
    for root in (0, 1)
}
# An addressed pair's mode packs two commitment values side by side,
# one per participant, each spanning the specifier table, so the
# half width and the packed mode bound derive from the table itself.
SPECIFIER_COMMITMENT_MAX = max(SPECIFIER_OPERANDS)
_SPECIFIER_HALF_BITS = SPECIFIER_COMMITMENT_MAX.bit_length()
_MESSAGE_MODE_MAX = (
    SPECIFIER_COMMITMENT_MAX << _SPECIFIER_HALF_BITS
) | SPECIFIER_COMMITMENT_MAX

# A locktime below the threshold counts blocks, at or above it counts
# Unix seconds. Operand domains exclude the wrong-typed range, so a
# mistyped operand is malformed here at parse rather than
# unsatisfiable later against the field.
LOCKTIME_THRESHOLD = 500_000_000
LOCKTIME_MAX = 0xFFFFFFFF
SEQUENCE_VALUE_MAX = 0xFFFF

# Each assigned opcode's flat cost, charged once per occurrence as
# the condition parses, after its encoding checks. The two taproot
# entries sum their claim or assert constant with the tweak
# constant and charge it as one amount before their point
# derivation runs. Reserved opcodes are absent on purpose: a
# reserved condition charges exactly its declared cost.
CONDITION_COSTS = {
    CREATE_OUTPUT: CREATE_OUTPUT_COST,
    CREATE_OUTPUT_TAPROOT: CREATE_OUTPUT_COST + TAPROOT_TWEAK_COST,
    **{opcode: CONDITION_SIG_ASSERT_COST for opcode in SIG_BINDINGS},
    ASSERT_LOCKTIME_HEIGHT: CONDITION_GENERIC_COST,
    ASSERT_LOCKTIME_TIME: CONDITION_GENERIC_COST,
    ASSERT_SEQUENCE_HEIGHT: CONDITION_GENERIC_COST,
    ASSERT_SEQUENCE_TIME: CONDITION_GENERIC_COST,
    ASSERT_MY_OUTPOINT: CONDITION_GENERIC_COST,
    ASSERT_MY_TXID: CONDITION_GENERIC_COST,
    ASSERT_MY_SCRIPTPUBKEY: CONDITION_GENERIC_COST,
    ASSERT_MY_AMOUNT: CONDITION_GENERIC_COST,
    ASSERT_MY_TAPROOT: CONDITION_GENERIC_COST + TAPROOT_TWEAK_COST,
    ASSERT_MY_TAPTREE: CONDITION_GENERIC_COST,
    ANNOUNCE: CONDITION_MESSAGE_COST,
    ASSERT_ANNOUNCEMENT: CONDITION_MESSAGE_COST,
    ASSURE: CONDITION_MESSAGE_COST,
    REQUIRE: CONDITION_MESSAGE_COST,
    RESERVE_FEE: CONDITION_GENERIC_COST,
    SEAL: CONDITION_GENERIC_COST,
    SEAL_OUTPUTS: CONDITION_GENERIC_COST,
}


@dataclass(frozen=True)
class CreateOutput:
    """Claims one output slot with exactly this content."""

    script_pubkey: bytes
    amount: int

    opcode = CREATE_OUTPUT


@dataclass(frozen=True)
class CreateOutputTaproot:
    """Claims one output slot with derived taproot content.

    script_pubkey is computed from internal_key and merkle_root at
    parse time. The claimed slot content is (script_pubkey, amount),
    exactly as for CreateOutput.
    """

    internal_key: bytes
    merkle_root: bytes
    amount: int
    script_pubkey: bytes

    opcode = CREATE_OUTPUT_TAPROOT


@dataclass(frozen=True)
class AssertLocktimeHeight:
    """Asserts a non-final own sequence and a height-typed locktime
    at or above height."""

    height: int

    opcode = ASSERT_LOCKTIME_HEIGHT


@dataclass(frozen=True)
class AssertLocktimeTime:
    """Asserts a non-final own sequence and a time-typed locktime at
    or above time."""

    time: int

    opcode = ASSERT_LOCKTIME_TIME


@dataclass(frozen=True)
class AssertSequenceHeight:
    """Asserts version 2, an enabled height-typed own sequence whose
    value is at least blocks."""

    blocks: int

    opcode = ASSERT_SEQUENCE_HEIGHT


@dataclass(frozen=True)
class AssertSequenceTime:
    """Asserts version 2, an enabled time-typed own sequence whose
    value, in 512-second units, is at least units."""

    units: int

    opcode = ASSERT_SEQUENCE_TIME


@dataclass(frozen=True)
class AssertMyOutpoint:
    """Asserts the input's consumed outpoint, in wire serialization:
    32 txid bytes then the 32-bit index little-endian."""

    outpoint: bytes

    opcode = ASSERT_MY_OUTPOINT


@dataclass(frozen=True)
class AssertMyTxid:
    """Asserts the input's creating txid, the txid half of its
    outpoint. A strict subset of AssertMyOutpoint: the index is
    left unconstrained."""

    txid: bytes

    opcode = ASSERT_MY_TXID


@dataclass(frozen=True)
class AssertMyScriptPubKey:
    """Asserts the spent output's scriptPubKey byte-exact."""

    script_pubkey: bytes

    opcode = ASSERT_MY_SCRIPTPUBKEY


@dataclass(frozen=True)
class AssertMyAmount:
    """Asserts the spent output's amount numerically."""

    amount: int

    opcode = ASSERT_MY_AMOUNT


@dataclass(frozen=True)
class AssertMyTaproot:
    """Asserts the spent output is the taproot output of these
    components.

    script_pubkey is computed from internal_key and merkle_root at
    parse time, the same derivation CreateOutputTaproot claims
    with, then compared byte-exact against the spent scriptPubKey.
    """

    internal_key: bytes
    merkle_root: bytes
    script_pubkey: bytes

    opcode = ASSERT_MY_TAPROOT


@dataclass(frozen=True)
class AssertMyTaptree:
    """Asserts the input's execution identity: the internal key and
    merkle root its control block carries, each compared byte-exact.

    Proves what AssertMyTaproot proves without the derivation: base
    consensus has already tweaked this key by this root and checked
    the result against the spent scriptPubKey. The internal key is
    width-checked only. The field it is compared against always
    lifts to a curve point, so an operand that does not lift never
    matches and fails as unsatisfied.
    """

    internal_key: bytes
    merkle_root: bytes

    opcode = ASSERT_MY_TAPTREE


@dataclass(frozen=True)
class AssertSig:
    """Asserts that signature is a valid BIP340 signature by pubkey
    over the digest of this opcode's tag, binding fields, and
    message. The binding fields are read from the carrying input at
    validation, so the parsed condition holds operands only."""

    opcode: int
    pubkey: bytes
    message: bytes
    signature: bytes

    @property
    def name(self):
        return SIG_BINDINGS[self.opcode][0]


@dataclass(frozen=True)
class Specifier:
    """A participant specifier: a commitment value and the fields it
    commits to, in SPECIFIER_OPERANDS order. Equality is the rule 3
    definition: equal commitment value and equal fields, so a
    36-byte outpoint specifier never equals a txid-and-script one,
    whatever coin each names."""

    commitment: int
    fields: tuple


@dataclass(frozen=True)
class Announce:
    """Creates the announcement (this input, namespace, payload).
    Constrains nothing by itself."""

    namespace: bytes
    payload: bytes

    opcode = ANNOUNCE


@dataclass(frozen=True)
class AssertAnnouncement:
    """Asserts some input announced (namespace, payload) and matches
    the announcer specifier."""

    announcer: Specifier
    namespace: bytes
    payload: bytes

    opcode = ASSERT_ANNOUNCEMENT


@dataclass(frozen=True)
class Assure:
    """Weight +1 in the message ledger. The assurer half describes the
    emitting input itself, so only its commitment value is stored
    here. The requirer is the argument specifier."""

    assurer_commitment: int
    requirer: Specifier
    message: bytes

    opcode = ASSURE


@dataclass(frozen=True)
class Require:
    """Weight -1 in the message ledger. The requirer half describes
    the emitting input itself, the assurer is the argument
    specifier."""

    assurer: Specifier
    requirer_commitment: int
    message: bytes

    opcode = REQUIRE


@dataclass(frozen=True)
class ReserveFee:
    """A fee reserve: a counted demand of reserve satoshis against
    the transaction's fee. Occurrences sum, and the fee must reach
    the total."""

    reserve: int

    opcode = RESERVE_FEE


@dataclass(frozen=True)
class Seal:
    """Asserts the spending transaction's own txid, fixing every
    non-witness byte of the transaction that carries it."""

    txid: bytes

    opcode = SEAL


@dataclass(frozen=True)
class SealOutputs:
    """Asserts the spending transaction's outputs hash, fixing every
    output slot's content and order and nothing else."""

    outputs_hash: bytes

    opcode = SEAL_OUTPUTS


@dataclass(frozen=True)
class Reserved:
    """No enforced semantics, only the declared cost. args holds the
    raw argument nodes after the cost, unconstrained by design."""

    opcode: int
    cost: int
    args: tuple


class _Meter:
    """Accrued cost against an optional inclusive budget.

    A max_cost of None applies no budget, a reference-tool
    convenience: the consensus interface always supplies one."""

    def __init__(self, max_cost, cost):
        self.max_cost = max_cost
        self.cost = cost

    def charge(self, amount):
        self.cost += amount
        if self.max_cost is not None and self.cost > self.max_cost:
            raise BitLispError("cost_exceeded", "cost exceeded")


def _iter_conditions(node, what):
    """Yields the elements of a proper list, else bad_condition_list."""
    while node != NIL:
        if not is_pair(node):
            raise BitLispError("bad_condition_list", f"{what} is an improper list")
        yield node[0]
        node = node[1]


def _parse_int(atom, what):
    if not is_atom(atom):
        raise BitLispError("bad_condition_arg", f"{what} must be an atom")
    value = atom_to_int(atom)
    if int_to_atom(value) != atom:
        raise BitLispError("bad_condition_arg", f"{what} not minimally encoded")
    return value


def _parse_create_output(args):
    if len(args) != 2:
        raise BitLispError(
            "bad_condition_arity", f"CREATE_OUTPUT takes 2 arguments, got {len(args)}"
        )
    script_pubkey, amount_atom = args
    if not is_atom(script_pubkey):
        raise BitLispError("bad_condition_arg", "scriptPubKey must be an atom")
    if not 1 <= len(script_pubkey) <= MAX_SCRIPT_PUBKEY_SIZE:
        raise BitLispError(
            "bad_condition_arg",
            f"scriptPubKey must be 1 to {MAX_SCRIPT_PUBKEY_SIZE} bytes, "
            f"got {len(script_pubkey)}",
        )
    amount = _parse_int(amount_atom, "CREATE_OUTPUT amount")
    if not 0 <= amount <= MAX_MONEY:
        raise BitLispError("bad_condition_arg", f"amount out of range: {amount}")
    return CreateOutput(script_pubkey, amount)


def _fixed_width_atom(atom, what, size):
    """An atom operand of exactly size bytes, else bad_condition_arg.
    The one rule behind every 32-byte identity operand (txids, keys,
    leaf hashes, roots, seal digests), the 36-byte outpoint, and the
    64-byte signature, so the operands that share a domain share it
    in code."""
    if not is_atom(atom):
        raise BitLispError("bad_condition_arg", f"{what} must be an atom")
    if len(atom) != size:
        raise BitLispError(
            "bad_condition_arg", f"{what} must be {size} bytes, got {len(atom)}"
        )
    return atom


def _check_taproot_components(internal_key, merkle_root):
    """The width checks of the two taproot component atoms. Cheap
    work only, run before the condition's charge: the point work
    lives in _derive_taproot_spk, run after it."""
    _fixed_width_atom(internal_key, "internal key", 32)
    if not is_atom(merkle_root):
        raise BitLispError("bad_condition_arg", "merkle root must be an atom")
    if len(merkle_root) not in (0, 32):
        raise BitLispError(
            "bad_condition_arg",
            f"merkle root must be 0 or 32 bytes, got {len(merkle_root)}",
        )


def _derive_taproot_spk(internal_key, merkle_root):
    """The 34-byte taproot scriptPubKey of two width-checked
    component atoms. Point work: the caller has already charged the
    condition's cost, so a budget too small for the charge never
    reaches this derivation and a derivation defect is reported
    only when the charge is covered."""
    output_key = secp256k1.taproot_output_key(internal_key, merkle_root)
    if output_key is None:
        raise BitLispError(
            "bad_condition_arg", "internal key and merkle root derive no output key"
        )
    return b"\x51\x20" + output_key


def _parse_create_output_taproot(args, meter):
    if len(args) != 3:
        raise BitLispError(
            "bad_condition_arity",
            f"CREATE_OUTPUT_TAPROOT takes 3 arguments, got {len(args)}",
        )
    internal_key, merkle_root, amount_atom = args
    _check_taproot_components(internal_key, merkle_root)
    amount = _parse_int(amount_atom, "CREATE_OUTPUT_TAPROOT amount")
    if not 0 <= amount <= MAX_MONEY:
        raise BitLispError("bad_condition_arg", f"amount out of range: {amount}")
    meter.charge(CONDITION_COSTS[CREATE_OUTPUT_TAPROOT])
    script_pubkey = _derive_taproot_spk(internal_key, merkle_root)
    return CreateOutputTaproot(internal_key, merkle_root, amount, script_pubkey)


def _parse_time_assert(args, name, cls, low, high):
    """One plain-quantity operand whose domain is [low, high]."""
    if len(args) != 1:
        raise BitLispError(
            "bad_condition_arity", f"{name} takes 1 argument, got {len(args)}"
        )
    value = _parse_int(args[0], f"{name} operand")
    if not low <= value <= high:
        raise BitLispError(
            "bad_condition_arg",
            f"{name} operand must be {low} to {high}, got {value}",
        )
    return cls(value)


def _parse_fixed_bytes(args, name, cls, size):
    """One atom operand of exactly size bytes."""
    if len(args) != 1:
        raise BitLispError(
            "bad_condition_arity", f"{name} takes 1 argument, got {len(args)}"
        )
    return cls(_fixed_width_atom(args[0], f"{name} operand", size))


def _parse_assert_my_scriptpubkey(args):
    if len(args) != 1:
        raise BitLispError(
            "bad_condition_arity",
            f"ASSERT_MY_SCRIPTPUBKEY takes 1 argument, got {len(args)}",
        )
    atom = args[0]
    if not is_atom(atom):
        raise BitLispError(
            "bad_condition_arg", "ASSERT_MY_SCRIPTPUBKEY operand must be an atom"
        )
    if len(atom) > MAX_SCRIPT_PUBKEY_SIZE:
        raise BitLispError(
            "bad_condition_arg",
            f"ASSERT_MY_SCRIPTPUBKEY operand must be at most "
            f"{MAX_SCRIPT_PUBKEY_SIZE} bytes, got {len(atom)}",
        )
    return AssertMyScriptPubKey(atom)


def _parse_assert_my_amount(args):
    if len(args) != 1:
        raise BitLispError(
            "bad_condition_arity",
            f"ASSERT_MY_AMOUNT takes 1 argument, got {len(args)}",
        )
    amount = _parse_int(args[0], "ASSERT_MY_AMOUNT operand")
    if not 0 <= amount <= MAX_MONEY:
        raise BitLispError("bad_condition_arg", f"amount out of range: {amount}")
    return AssertMyAmount(amount)


def _parse_assert_my_taproot(args, meter):
    if len(args) != 2:
        raise BitLispError(
            "bad_condition_arity",
            f"ASSERT_MY_TAPROOT takes 2 arguments, got {len(args)}",
        )
    internal_key, merkle_root = args
    _check_taproot_components(internal_key, merkle_root)
    meter.charge(CONDITION_COSTS[ASSERT_MY_TAPROOT])
    script_pubkey = _derive_taproot_spk(internal_key, merkle_root)
    return AssertMyTaproot(internal_key, merkle_root, script_pubkey)


def _parse_assert_my_taptree(args):
    """Two atom operands of exactly 32 bytes each, the internal key
    then the merkle root. The root is never empty here, unlike the
    taproot assert's: a BitLisp spend always executes a leaf of some
    tree."""
    if len(args) != 2:
        raise BitLispError(
            "bad_condition_arity",
            f"ASSERT_MY_TAPTREE takes 2 arguments, got {len(args)}",
        )
    return AssertMyTaptree(
        _fixed_width_atom(args[0], "ASSERT_MY_TAPTREE internal key", 32),
        _fixed_width_atom(args[1], "ASSERT_MY_TAPTREE merkle root", 32),
    )


def _parse_assert_sig(opcode, args):
    name = SIG_BINDINGS[opcode][0]
    if len(args) != 3:
        raise BitLispError(
            "bad_condition_arity", f"{name} takes 3 arguments, got {len(args)}"
        )
    pubkey, message, signature = args
    pubkey = _fixed_width_atom(pubkey, f"{name} pubkey", SIG_PUBKEY_SIZE)
    message = _parse_payload_atom(message, f"{name} message")
    signature = _fixed_width_atom(signature, f"{name} signature", SIG_SIGNATURE_SIZE)
    return AssertSig(opcode, pubkey, message, signature)


def _parse_payload_atom(atom, what):
    """A message, namespace, or payload: an atom of 0 to 1024 bytes."""
    if not is_atom(atom):
        raise BitLispError("bad_condition_arg", f"{what} must be an atom")
    if len(atom) > MAX_MESSAGE_SIZE:
        raise BitLispError(
            "bad_condition_arg",
            f"{what} must be at most {MAX_MESSAGE_SIZE} bytes, got {len(atom)}",
        )
    return atom


def _parse_specifier(commitment, args, name):
    """Parses the specifier operands for a commitment value. The
    caller has already checked the argument count."""
    fields = []
    for kind, atom in zip(SPECIFIER_OPERANDS[commitment], args, strict=True):
        if kind == "amount":
            value = _parse_int(atom, f"{name} specifier amount")
            if not 0 <= value <= MAX_MONEY:
                raise BitLispError(
                    "bad_condition_arg", f"specifier amount out of range: {value}"
                )
            fields.append(value)
            continue
        if kind == "outpoint":
            fields.append(_fixed_width_atom(atom, f"{name} outpoint", OUTPOINT_SIZE))
            continue
        if kind in ("txid", "tapleaf", "merkle_root"):
            fields.append(_fixed_width_atom(atom, f"{name} {kind}", 32))
            continue
        if kind == "script_pubkey":
            if not is_atom(atom):
                raise BitLispError(
                    "bad_condition_arg", f"{name} {kind} must be an atom"
                )
            if len(atom) > MAX_SCRIPT_PUBKEY_SIZE:
                raise BitLispError(
                    "bad_condition_arg",
                    f"{name} scriptPubKey must be at most "
                    f"{MAX_SCRIPT_PUBKEY_SIZE} bytes, got {len(atom)}",
                )
            fields.append(atom)
            continue
        raise AssertionError(f"unhandled specifier operand kind: {kind}")
    return Specifier(commitment, tuple(fields))


def _parse_mode(atom, name, high):
    value = _parse_int(atom, f"{name} mode")
    if not 0 <= value <= high:
        raise BitLispError(
            "bad_condition_arg", f"{name} mode must be 0 to {high}, got {value}"
        )
    return value


def _parse_message_pair(args, name, self_half_high):
    """Shared parse for the addressed pair: mode, message, then the
    specifier operands for the argument half. self_half_high says
    whether the emitting input's own half is the mode's high bits
    (ASSURE) or its low bits (REQUIRE)."""
    if len(args) < 2:
        raise BitLispError(
            "bad_condition_arity",
            f"{name} takes at least 2 arguments, got {len(args)}",
        )
    mode = _parse_mode(args[0], name, _MESSAGE_MODE_MAX)
    high, low = mode >> _SPECIFIER_HALF_BITS, mode & SPECIFIER_COMMITMENT_MAX
    self_half, arg_half = (high, low) if self_half_high else (low, high)
    expected = 2 + len(SPECIFIER_OPERANDS[arg_half])
    if len(args) != expected:
        raise BitLispError(
            "bad_condition_arity",
            f"{name} with mode {mode} takes {expected} arguments, got {len(args)}",
        )
    message = _parse_payload_atom(args[1], f"{name} message")
    specifier = _parse_specifier(arg_half, args[2:], name)
    return mode, self_half, specifier, message


def _parse_assure(args):
    _, self_half, requirer, message = _parse_message_pair(
        args, "ASSURE", self_half_high=True
    )
    return Assure(self_half, requirer, message)


def _parse_require(args):
    _, self_half, assurer, message = _parse_message_pair(
        args, "REQUIRE", self_half_high=False
    )
    return Require(assurer, self_half, message)


def _parse_announce(args):
    if len(args) != 2:
        raise BitLispError(
            "bad_condition_arity", f"ANNOUNCE takes 2 arguments, got {len(args)}"
        )
    namespace = _parse_payload_atom(args[0], "ANNOUNCE namespace")
    payload = _parse_payload_atom(args[1], "ANNOUNCE payload")
    return Announce(namespace, payload)


def _parse_assert_announcement(args):
    if len(args) < 3:
        raise BitLispError(
            "bad_condition_arity",
            f"ASSERT_ANNOUNCEMENT takes at least 3 arguments, got {len(args)}",
        )
    mode = _parse_mode(args[0], "ASSERT_ANNOUNCEMENT", SPECIFIER_COMMITMENT_MAX)
    expected = 3 + len(SPECIFIER_OPERANDS[mode])
    if len(args) != expected:
        raise BitLispError(
            "bad_condition_arity",
            f"ASSERT_ANNOUNCEMENT with mode {mode} takes {expected} "
            f"arguments, got {len(args)}",
        )
    namespace = _parse_payload_atom(args[1], "ASSERT_ANNOUNCEMENT namespace")
    payload = _parse_payload_atom(args[2], "ASSERT_ANNOUNCEMENT payload")
    announcer = _parse_specifier(mode, args[3:], "ASSERT_ANNOUNCEMENT")
    return AssertAnnouncement(announcer, namespace, payload)


def _parse_reserve_fee(args):
    if len(args) != 1:
        raise BitLispError(
            "bad_condition_arity",
            f"RESERVE_FEE takes 1 argument, got {len(args)}",
        )
    reserve = _parse_int(args[0], "RESERVE_FEE operand")
    if not 0 <= reserve <= MAX_MONEY:
        raise BitLispError("bad_condition_arg", f"reserve out of range: {reserve}")
    return ReserveFee(reserve)


def _parse_reserved(opcode, args):
    if not args:
        raise BitLispError(
            "bad_condition_arity", "reserved condition missing its declared cost"
        )
    cost = _parse_int(args[0], "declared cost")
    if cost < 0:
        raise BitLispError("bad_condition_arg", f"declared cost negative: {cost}")
    if cost < RESERVED_COST_FLOOR:
        raise BitLispError(
            "reserved_cost_too_low",
            f"declared cost {cost} below floor {RESERVED_COST_FLOOR}",
        )
    return Reserved(opcode, cost, tuple(args[1:]))


def _parse_condition(node, meter):
    if not is_pair(node):
        raise BitLispError("bad_condition_list", "condition is not a list")
    items = list(_iter_conditions(node, "condition"))
    opcode_atom = items[0]
    if not is_atom(opcode_atom) or len(opcode_atom) != 1:
        raise BitLispError(
            "bad_condition_opcode", "opcode must be an atom of exactly one byte"
        )
    opcode = opcode_atom[0]
    args = items[1:]
    if opcode >= _RESERVED_START:
        condition = _parse_reserved(opcode, args)
        meter.charge(condition.cost)
        return condition
    if opcode == CREATE_OUTPUT_TAPROOT:
        return _parse_create_output_taproot(args, meter)
    if opcode == ASSERT_MY_TAPROOT:
        return _parse_assert_my_taproot(args, meter)
    condition = _parse_assigned(opcode, args)
    meter.charge(CONDITION_COSTS[opcode])
    return condition


def _parse_assigned(opcode, args):
    """Parses an assigned non-derivation opcode: every check runs
    here, and the caller charges the opcode's flat cost after the
    whole parse, so each encoding defect wins over cost_exceeded."""
    if opcode == CREATE_OUTPUT:
        return _parse_create_output(args)
    if opcode in SIG_BINDINGS:
        return _parse_assert_sig(opcode, args)
    if opcode == ASSERT_LOCKTIME_HEIGHT:
        return _parse_time_assert(
            args,
            "ASSERT_LOCKTIME_HEIGHT",
            AssertLocktimeHeight,
            0,
            LOCKTIME_THRESHOLD - 1,
        )
    if opcode == ASSERT_LOCKTIME_TIME:
        return _parse_time_assert(
            args,
            "ASSERT_LOCKTIME_TIME",
            AssertLocktimeTime,
            LOCKTIME_THRESHOLD,
            LOCKTIME_MAX,
        )
    if opcode == ASSERT_SEQUENCE_HEIGHT:
        return _parse_time_assert(
            args,
            "ASSERT_SEQUENCE_HEIGHT",
            AssertSequenceHeight,
            0,
            SEQUENCE_VALUE_MAX,
        )
    if opcode == ASSERT_SEQUENCE_TIME:
        return _parse_time_assert(
            args,
            "ASSERT_SEQUENCE_TIME",
            AssertSequenceTime,
            0,
            SEQUENCE_VALUE_MAX,
        )
    if opcode == ASSERT_MY_OUTPOINT:
        return _parse_fixed_bytes(
            args, "ASSERT_MY_OUTPOINT", AssertMyOutpoint, OUTPOINT_SIZE
        )
    if opcode == ASSERT_MY_TXID:
        return _parse_fixed_bytes(args, "ASSERT_MY_TXID", AssertMyTxid, 32)
    if opcode == ASSERT_MY_SCRIPTPUBKEY:
        return _parse_assert_my_scriptpubkey(args)
    if opcode == ASSERT_MY_AMOUNT:
        return _parse_assert_my_amount(args)
    if opcode == ASSERT_MY_TAPTREE:
        return _parse_assert_my_taptree(args)
    if opcode == ANNOUNCE:
        return _parse_announce(args)
    if opcode == ASSERT_ANNOUNCEMENT:
        return _parse_assert_announcement(args)
    if opcode == ASSURE:
        return _parse_assure(args)
    if opcode == REQUIRE:
        return _parse_require(args)
    if opcode == RESERVE_FEE:
        return _parse_reserve_fee(args)
    if opcode == SEAL:
        return _parse_fixed_bytes(args, "SEAL", Seal, 32)
    if opcode == SEAL_OUTPUTS:
        return _parse_fixed_bytes(args, "SEAL_OUTPUTS", SealOutputs, 32)
    raise BitLispError("bad_condition_opcode", f"invalid opcode {opcode:#04x}")


def parse_conditions(node, max_cost, cost=0):
    """Parses an evaluation result into (cost, tuple of conditions).

    Conditions charge in list order as they parse, each after its
    own encoding checks, against the inclusive budget max_cost.
    cost is the already-accrued total the same budget covers, the
    VM run's own cost in the consensus pipeline, and the returned
    total includes it. max_cost is required, like run's: the
    consensus interface always supplies a budget, and a reference
    tool that wants none must say so with an explicit None.

    Raises BitLispError on any encoding violation or on the first
    charge the budget cannot cover. Condition order is the emitted
    order.
    """
    meter = _Meter(max_cost, cost)
    conditions = tuple(
        _parse_condition(element, meter)
        for element in _iter_conditions(node, "condition list")
    )
    return meter.cost, conditions


def condition_cost(condition):
    """The flat cost a parsed condition charged: its opcode's table
    entry, or the declared cost for a reserved condition."""
    if isinstance(condition, Reserved):
        return condition.cost
    return CONDITION_COSTS[condition.opcode]
