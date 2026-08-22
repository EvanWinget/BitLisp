"""Minimal Bitcoin transaction view for condition validation.

Just enough structure to validate condition lists against: inputs
carrying their consumed output's content, outputs as (scriptPubKey,
amount) slots addressed by index. Construction enforces the base-rule
subset the model represents, so validation only ever sees transactions
that conserve value. Violations here raise ValueError: a malformed
model is a harness bug, never a spend failure.
"""

import hashlib
from dataclasses import dataclass

from .conditions import MAX_MONEY

_UINT32_MAX = 0xFFFFFFFF


def _compact_size(n):
    """Bitcoin's variable-length count prefix, the wire encoding of
    list lengths and byte-string lengths."""
    if n < 0xFD:
        return n.to_bytes(1, "little")
    if n <= 0xFFFF:
        return b"\xfd" + n.to_bytes(2, "little")
    if n <= 0xFFFFFFFF:
        return b"\xfe" + n.to_bytes(4, "little")
    return b"\xff" + n.to_bytes(8, "little")


def _check_amount(amount, what):
    if not isinstance(amount, int) or not 0 <= amount <= MAX_MONEY:
        raise ValueError(f"{what} amount out of range: {amount!r}")


def _check_script(script, what):
    # No size bound on purpose: Bitcoin base consensus places none on
    # a created output's scriptPubKey, and the model must represent
    # every transaction base consensus accepts. The 10,000-byte bound
    # is conditions.MAX_SCRIPT_PUBKEY_SIZE, a claim-argument rule, not
    # a slot rule.
    if not isinstance(script, bytes):
        raise ValueError(f"{what} scriptPubKey must be bytes")


@dataclass(frozen=True)
class TxInput:
    """One input: the outpoint it consumes, that output's content, the
    sequence, and the legacy scriptSig, empty for every segwit input.
    conditions is None for a non-BitLisp input, else the parsed
    condition list its program evaluation produced. A BitLisp input
    also carries its execution identity, the triple base consensus
    authenticates against the spent scriptPubKey through the control
    block: tapleaf, the executing leaf's leaf hash, merkle_root, the
    spending path's root, and internal_key, the x-only key the
    control block carries. The model takes the triple as
    authenticated and never re-derives the scriptPubKey from it."""

    txid: bytes
    index: int
    script_pubkey: bytes
    amount: int
    sequence: int
    conditions: tuple | None = None
    script_sig: bytes = b""
    tapleaf: bytes | None = None
    merkle_root: bytes | None = None
    internal_key: bytes | None = None

    def __post_init__(self):
        if not isinstance(self.txid, bytes) or len(self.txid) != 32:
            raise ValueError("txid must be 32 bytes")
        if not isinstance(self.index, int) or not 0 <= self.index <= _UINT32_MAX:
            raise ValueError(f"input index out of range: {self.index!r}")
        if not isinstance(self.sequence, int) or not 0 <= self.sequence <= _UINT32_MAX:
            raise ValueError(f"sequence out of range: {self.sequence!r}")
        _check_script(self.script_pubkey, "input")
        _check_amount(self.amount, "input")
        if self.conditions is not None and not isinstance(self.conditions, tuple):
            raise ValueError("conditions must be a tuple or None")
        if not isinstance(self.script_sig, bytes):
            raise ValueError("scriptSig must be bytes")
        if self.tapleaf is not None and (
            not isinstance(self.tapleaf, bytes) or len(self.tapleaf) != 32
        ):
            raise ValueError("tapleaf must be 32 bytes")
        if self.merkle_root is not None and (
            not isinstance(self.merkle_root, bytes) or len(self.merkle_root) != 32
        ):
            raise ValueError("merkle_root must be 32 bytes")
        if self.internal_key is not None and (
            not isinstance(self.internal_key, bytes) or len(self.internal_key) != 32
        ):
            raise ValueError("internal_key must be 32 bytes")
        if self.conditions is not None and (
            self.tapleaf is None
            or self.merkle_root is None
            or self.internal_key is None
        ):
            raise ValueError(
                "a condition-carrying input must carry tapleaf, merkle_root, "
                "and internal_key"
            )

    @property
    def outpoint(self):
        return (self.txid, self.index)


@dataclass(frozen=True)
class TxOutput:
    """One output slot. Content is the (scriptPubKey, amount) pair."""

    script_pubkey: bytes
    amount: int

    def __post_init__(self):
        _check_script(self.script_pubkey, "output")
        _check_amount(self.amount, "output")

    @property
    def content(self):
        return (self.script_pubkey, self.amount)

    @property
    def wire(self):
        """The slot's wire serialization: the 8-byte little-endian
        amount, then the length-prefixed scriptPubKey."""
        return (
            self.amount.to_bytes(8, "little")
            + _compact_size(len(self.script_pubkey))
            + self.script_pubkey
        )


@dataclass(frozen=True)
class Transaction:
    version: int
    locktime: int
    inputs: tuple
    outputs: tuple

    def __post_init__(self):
        # Unsigned like the locktime field: base consensus compares
        # the version unsigned in its locktime rules (Core casts
        # nVersion to uint32), so a top-bit wire version is a large
        # value here, never a negative one.
        if not isinstance(self.version, int) or not (0 <= self.version <= _UINT32_MAX):
            raise ValueError(f"version out of range: {self.version!r}")
        if not isinstance(self.locktime, int) or not (
            0 <= self.locktime <= _UINT32_MAX
        ):
            raise ValueError(f"locktime out of range: {self.locktime!r}")
        if not isinstance(self.inputs, tuple) or not self.inputs:
            raise ValueError("inputs must be a non-empty tuple")
        if not isinstance(self.outputs, tuple) or not self.outputs:
            raise ValueError("outputs must be a non-empty tuple")
        if not all(isinstance(i, TxInput) for i in self.inputs):
            raise ValueError("inputs must all be TxInput")
        if not all(isinstance(o, TxOutput) for o in self.outputs):
            raise ValueError("outputs must all be TxOutput")
        outpoints = [i.outpoint for i in self.inputs]
        if len(set(outpoints)) != len(outpoints):
            raise ValueError("duplicate input outpoint")
        in_total = sum(i.amount for i in self.inputs)
        out_total = sum(o.amount for o in self.outputs)
        if out_total > in_total:
            raise ValueError(
                f"outputs {out_total} exceed inputs {in_total}, value not conserved"
            )

    @property
    def txid(self):
        """The transaction's own id: the double-SHA256 of its
        serialization without witness data. Condition lists, programs,
        and solutions are witness data, so nothing a BitLisp input
        carries changes this value. Distinct from an input's txid,
        which names the past transaction that created its prevout."""
        data = bytearray(self.version.to_bytes(4, "little"))
        data += _compact_size(len(self.inputs))
        for tx_input in self.inputs:
            data += tx_input.txid
            data += tx_input.index.to_bytes(4, "little")
            data += _compact_size(len(tx_input.script_sig)) + tx_input.script_sig
            data += tx_input.sequence.to_bytes(4, "little")
        data += _compact_size(len(self.outputs))
        for output in self.outputs:
            data += output.wire
        data += self.locktime.to_bytes(4, "little")
        return hashlib.sha256(hashlib.sha256(bytes(data)).digest()).digest()

    @property
    def outputs_hash(self):
        """The single SHA256 of every output slot's wire serialization
        in order, the value a taproot sighash commits to as its
        outputs commitment."""
        return hashlib.sha256(b"".join(o.wire for o in self.outputs)).digest()
