"""Property-based invariants for the self assert family.

Each self assert is an equality against its own input's prevout
data, so the family's defining property is environment independence:
the outcome is a pure function of (conditions, own prevout data) and
nothing else in the transaction can change it. The other properties
pin the txid-outpoint subset relation and the taproot assert's
equivalence to a plain script assert over the derived scriptPubKey.
Field values and operands are drawn from small colliding pools so
satisfied and unsatisfied asserts are both dense.
"""

from bitlisp import (
    BitLispError,
    Transaction,
    TxInput,
    TxOutput,
    validate_transaction,
)
from bitlisp.conditions import (
    AssertMyAmount,
    AssertMyOutpoint,
    AssertMyScriptPubKey,
    AssertMyTaproot,
    AssertMyTxid,
)
from bitlisp.secp256k1 import taproot_output_key
from hypothesis import given
from hypothesis import strategies as st

TXID_A = b"\xaa" * 32
TXID_B = b"\xbb" * 32
IK = bytes.fromhex("187791b6f712a8ea41c8ecdd0ee77fab3e85263b37e1ec18a3651926b3a6cf27")
NUMS = bytes.fromhex("50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0")
ROOT = b"\x77" * 32

SPK_IK_ROOT = b"\x51\x20" + taproot_output_key(IK, ROOT)
SPK_IK_PLAIN = b"\x51\x20" + taproot_output_key(IK, b"")
SPK_NUMS_ROOT = b"\x51\x20" + taproot_output_key(NUMS, ROOT)
SPK_P2WSH_TWIN = b"\x00\x20" + SPK_IK_ROOT[2:]

txids = st.sampled_from((TXID_A, TXID_B))
indexes = st.sampled_from((0, 1, 7, 256))
scripts = st.sampled_from(
    (b"", b"\x51", SPK_IK_ROOT, SPK_IK_PLAIN, SPK_NUMS_ROOT, SPK_P2WSH_TWIN)
)
amounts = st.sampled_from((0, 1, 50_000, 50_000 + 2**32, 2_100_000_000_000_000))


def _outpoint(txid, index):
    return txid + index.to_bytes(4, "little")


def _taproot(internal_key, merkle_root):
    spk = b"\x51\x20" + taproot_output_key(internal_key, merkle_root)
    return AssertMyTaproot(internal_key, merkle_root, spk)


self_asserts = st.one_of(
    st.tuples(txids, indexes).map(lambda t: AssertMyOutpoint(_outpoint(*t))),
    txids.map(AssertMyTxid),
    scripts.map(AssertMyScriptPubKey),
    amounts.map(AssertMyAmount),
    st.sampled_from(((IK, ROOT), (IK, b""), (NUMS, ROOT))).map(lambda t: _taproot(*t)),
)
cond_lists = st.lists(self_asserts, max_size=4)

environments = st.tuples(
    st.sampled_from((0, 1, 2, 0xFFFFFFFF)),
    st.sampled_from((0, 700, 500_000_600)),
    st.sampled_from((0xFFFFFFFF, 0xFFFFFFFE, 144)),
    st.sampled_from(("none", "after", "before")),
)


def build_tx(txid, index, script, amount, conds, env):
    """One BitLisp input carrying only self asserts, an unclaimed
    zero output, and an environment the family must never read. The
    unrelated input can sit before the carrying input, so an
    implementation reading a fixed input position dies here."""
    version, locktime, sequence, extra_position = env
    inputs = [
        TxInput(
            txid=txid,
            index=index,
            script_pubkey=script,
            amount=amount,
            sequence=sequence,
            conditions=tuple(conds),
            tapleaf=b"\x0a" * 32,
            merkle_root=b"\x0b" * 32,
        )
    ]
    if extra_position != "none":
        extra = TxInput(
            txid=b"\xcc" * 32,
            index=0,
            script_pubkey=b"\x52",
            amount=7,
            sequence=0xFFFFFFFF,
            conditions=None,
        )
        if extra_position == "before":
            inputs.insert(0, extra)
        else:
            inputs.append(extra)
    return Transaction(version, locktime, tuple(inputs), (TxOutput(b"\x51", 0),))


def outcome(tx):
    try:
        validate_transaction(tx)
        return None
    except BitLispError as exc:
        return exc.code


@given(txids, indexes, scripts, amounts, cond_lists, environments, environments)
def test_outcome_is_environment_independent(
    txid, index, script, amount, conds, env_a, env_b
):
    """The family outcome depends only on the conditions and the
    input's own prevout data. Version, locktime, sequence, and
    unrelated inputs never change it, the stage 2 property that
    makes every self assert recombination-invariant."""
    tx_a = build_tx(txid, index, script, amount, conds, env_a)
    tx_b = build_tx(txid, index, script, amount, conds, env_b)
    assert outcome(tx_a) == outcome(tx_b)


@given(txids, indexes, txids, indexes, environments)
def test_satisfied_outpoint_assert_implies_txid_assert(
    txid, index, operand_txid, operand_index, env
):
    """ASSERT_MY_TXID asserts a strict subset of ASSERT_MY_OUTPOINT:
    whenever an outpoint assert is satisfied, the txid assert built
    from its first 32 bytes is satisfied too."""
    operand = _outpoint(operand_txid, operand_index)
    with_outpoint = build_tx(txid, index, b"\x51", 1, [AssertMyOutpoint(operand)], env)
    with_txid = build_tx(txid, index, b"\x51", 1, [AssertMyTxid(operand[:32])], env)
    if outcome(with_outpoint) is None:
        assert outcome(with_txid) is None


@given(txids, indexes, scripts, amounts, self_asserts, environments)
def test_single_assert_outcome_matches_field_equality(
    txid, index, script, amount, cond, env
):
    """A lone self assert is satisfied exactly when its operand
    equals the field it reads, and fails with its field's error
    otherwise."""
    if isinstance(cond, AssertMyOutpoint):
        satisfied = cond.outpoint == _outpoint(txid, index)
        error = "unsatisfied_outpoint_assert"
    elif isinstance(cond, AssertMyTxid):
        satisfied = cond.txid == txid
        error = "unsatisfied_outpoint_assert"
    elif isinstance(cond, (AssertMyScriptPubKey, AssertMyTaproot)):
        satisfied = cond.script_pubkey == script
        error = "unsatisfied_scriptpubkey_assert"
    else:
        satisfied = cond.amount == amount
        error = "unsatisfied_amount_assert"
    got = outcome(build_tx(txid, index, script, amount, [cond], env))
    assert got == (None if satisfied else error)


@given(
    txids,
    indexes,
    scripts,
    amounts,
    st.sampled_from(((IK, ROOT), (IK, b""), (NUMS, ROOT))),
    environments,
)
def test_taproot_assert_equals_script_assert_on_derived_spk(
    txid, index, script, amount, components, env
):
    """ASSERT_MY_TAPROOT behaves exactly like ASSERT_MY_SCRIPTPUBKEY
    over the scriptPubKey its components derive."""
    taproot = _taproot(*components)
    plain = AssertMyScriptPubKey(taproot.script_pubkey)
    got_taproot = outcome(build_tx(txid, index, script, amount, [taproot], env))
    got_plain = outcome(build_tx(txid, index, script, amount, [plain], env))
    assert got_taproot == got_plain
