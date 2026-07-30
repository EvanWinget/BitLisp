"""Minimal Bitcoin transaction view for matching.

Just enough structure to validate condition lists against: inputs
carrying their consumed output's content, outputs as (scriptPubKey,
amount) slots addressed by index. Construction enforces the base-rule
subset the model represents, so matching only ever sees transactions
that conserve value. Violations here raise ValueError: a malformed
model is a harness bug, never a spend failure.
"""

from dataclasses import dataclass

from .conditions import MAX_MONEY

_UINT32_MAX = 0xFFFFFFFF
_INT32_MIN, _INT32_MAX = -(2**31), 2**31 - 1


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
    """One input: the outpoint it consumes, that output's content, and
    the sequence. conditions is None for a non-BitLisp input, else the
    parsed condition list its puzzle evaluation produced."""

    txid: bytes
    index: int
    script_pubkey: bytes
    amount: int
    sequence: int
    conditions: tuple | None = None

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


@dataclass(frozen=True)
class Transaction:
    version: int
    locktime: int
    inputs: tuple
    outputs: tuple

    def __post_init__(self):
        if not isinstance(self.version, int) or not (
            _INT32_MIN <= self.version <= _INT32_MAX
        ):
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
