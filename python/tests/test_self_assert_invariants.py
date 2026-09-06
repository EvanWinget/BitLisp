"""Property-based invariants for the self assert family.

Each self assert is an equality against its own input's prevout
data, so the family's defining property is environment independence:
the outcome is a pure function of (conditions, own prevout data) and
nothing else in the transaction can change it. The other properties
pin the txid-outpoint subset relation and the taptree assert's
indifference to the scriptPubKey plus its agreement, on an honest
input, with a plain script assert over the scriptPubKey its
operands derive. The annex assert adds the admission rule: an
input carrying an annex is valid only under the assert. Field
values and operands are drawn from small colliding pools so
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
    AssertMyAnnex,
    AssertMyOutpoint,
    AssertMyScriptPubKey,
    AssertMyTaptree,
    AssertMyTxid,
)
from bitlisp.secp256k1 import taproot_output_key
from hypothesis import given
from hypothesis import strategies as st
from support import (
    FILLER_INTERNAL_KEY,
    FILLER_MERKLE_ROOT,
    FILLER_TAPLEAF,
    NUMS,
)

TXID_A = b"\xaa" * 32
TXID_B = b"\xbb" * 32
IK = bytes.fromhex("187791b6f712a8ea41c8ecdd0ee77fab3e85263b37e1ec18a3651926b3a6cf27")
ROOT = b"\x77" * 32
ROOT_B = b"\x78" * 32
# The execution identity every transaction carries unless a property
# draws one: the shared corpus filler no assert in the pools names.
FILLER_IDENTITY = (FILLER_INTERNAL_KEY, FILLER_MERKLE_ROOT)
# Annex hashes, drawn both as the input's own (or None, no annex) and
# as annex assert operands.
ANNEX_A = b"\xa1" * 32
ANNEX_B = b"\xa2" * 32

# (internal key, merkle root) pairs, drawn both as the input's own
# identity and as taptree operands, so the two collide often.
IDENTITIES = ((IK, ROOT), (IK, ROOT_B), (NUMS, ROOT))
# Derived once: the tweak is the one expensive step in this module,
# and the pools are fixed, so nothing recomputes it per example.
HONEST_SPKS = {pair: b"\x51\x20" + taproot_output_key(*pair) for pair in IDENTITIES}
SPK_IK_ROOT = HONEST_SPKS[(IK, ROOT)]
SPK_IK_PLAIN = b"\x51\x20" + taproot_output_key(IK, b"")
SPK_NUMS_ROOT = HONEST_SPKS[(NUMS, ROOT)]
SPK_P2WSH_TWIN = b"\x00\x20" + SPK_IK_ROOT[2:]

txids = st.sampled_from((TXID_A, TXID_B))
indexes = st.sampled_from((0, 1, 7, 256))
scripts = st.sampled_from(
    (b"", b"\x51", SPK_IK_ROOT, SPK_IK_PLAIN, SPK_NUMS_ROOT, SPK_P2WSH_TWIN)
)
amounts = st.sampled_from((0, 1, 50_000, 50_000 + 2**32, 2_100_000_000_000_000))
identities = st.sampled_from(IDENTITIES)
annex_hashes = st.sampled_from((None, ANNEX_A, ANNEX_B))


def _outpoint(txid, index):
    return txid + index.to_bytes(4, "little")


self_asserts = st.one_of(
    st.tuples(txids, indexes).map(lambda t: AssertMyOutpoint(_outpoint(*t))),
    txids.map(AssertMyTxid),
    scripts.map(AssertMyScriptPubKey),
    amounts.map(AssertMyAmount),
    identities.map(lambda t: AssertMyTaptree(*t)),
    st.sampled_from((ANNEX_A, ANNEX_B)).map(AssertMyAnnex),
)
cond_lists = st.lists(self_asserts, max_size=4)

environments = st.tuples(
    st.sampled_from((0, 1, 2, 0xFFFFFFFF)),
    st.sampled_from((0, 700, 500_000_600)),
    st.sampled_from((0xFFFFFFFF, 0xFFFFFFFE, 144)),
    st.sampled_from(("none", "after", "before")),
)


def build_tx(
    txid, index, script, amount, conds, env, identity=FILLER_IDENTITY, annex=None
):
    """One BitLisp input carrying only self asserts, an unclaimed
    zero output, and an environment the family must never read. The
    unrelated input can sit before the carrying input, so an
    implementation reading a fixed input position dies here. annex
    is the input's own annex hash, None for a witness without one."""
    version, locktime, sequence, extra_position = env
    internal_key, merkle_root = identity
    inputs = [
        TxInput(
            txid=txid,
            index=index,
            script_pubkey=script,
            amount=amount,
            sequence=sequence,
            conditions=tuple(conds),
            tapleaf=FILLER_TAPLEAF,
            merkle_root=merkle_root,
            internal_key=internal_key,
            annex_hash=annex,
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


@given(
    txids,
    indexes,
    scripts,
    amounts,
    identities,
    annex_hashes,
    cond_lists,
    environments,
    environments,
)
def test_outcome_is_environment_independent(
    txid, index, script, amount, identity, annex, conds, env_a, env_b
):
    """The family outcome depends only on the conditions and the
    input's own prevout data, identity, and annex. Version,
    locktime, sequence, and unrelated inputs never change it, the
    stage 2 property that makes every self assert
    recombination-invariant."""
    tx_a = build_tx(txid, index, script, amount, conds, env_a, identity, annex)
    tx_b = build_tx(txid, index, script, amount, conds, env_b, identity, annex)
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


@given(
    txids,
    indexes,
    scripts,
    amounts,
    identities,
    annex_hashes,
    self_asserts,
    environments,
)
def test_single_assert_outcome_matches_field_equality(
    txid, index, script, amount, identity, annex, cond, env
):
    """A lone self assert is satisfied exactly when each operand
    equals the field it reads, and fails with its field's error
    otherwise. An input carrying an annex under any other lone
    assert fails the admission rule instead, whatever that assert
    would have said."""
    if isinstance(cond, AssertMyOutpoint):
        satisfied = cond.outpoint == _outpoint(txid, index)
        error = "unsatisfied_outpoint_assert"
    elif isinstance(cond, AssertMyTxid):
        satisfied = cond.txid == txid
        error = "unsatisfied_outpoint_assert"
    elif isinstance(cond, AssertMyScriptPubKey):
        satisfied = cond.script_pubkey == script
        error = "unsatisfied_scriptpubkey_assert"
    elif isinstance(cond, AssertMyTaptree):
        satisfied = (cond.internal_key, cond.merkle_root) == identity
        error = "unsatisfied_taptree_assert"
    elif isinstance(cond, AssertMyAnnex):
        satisfied = cond.annex_hash == annex
        error = "unsatisfied_annex_assert"
    else:
        satisfied = cond.amount == amount
        error = "unsatisfied_amount_assert"
    got = outcome(build_tx(txid, index, script, amount, [cond], env, identity, annex))
    if annex is not None and not isinstance(cond, AssertMyAnnex):
        assert got == "unasserted_annex"
    else:
        assert got == (None if satisfied else error)


@given(
    txids, indexes, scripts, amounts, identities, annex_hashes, cond_lists, environments
)
def test_annex_admitted_exactly_under_its_assert(
    txid, index, script, amount, identity, annex, conds, env
):
    """An input carrying an annex fails as unasserted_annex exactly
    when its list holds no ASSERT_MY_ANNEX, before any assert is
    checked. Without an annex the admission rule never fires, and
    every annex assert in the list is unsatisfied, so the spend is
    invalid."""
    got = outcome(build_tx(txid, index, script, amount, conds, env, identity, annex))
    asserted = any(isinstance(cond, AssertMyAnnex) for cond in conds)
    assert (got == "unasserted_annex") == (annex is not None and not asserted)
    if annex is None and asserted:
        assert got is not None


@given(txids, indexes, scripts, scripts, amounts, identities, identities, environments)
def test_taptree_assert_ignores_scriptpubkey(
    txid, index, script_a, script_b, amount, identity, operands, env
):
    """ASSERT_MY_TAPTREE reads the execution identity and nothing
    else: the spent scriptPubKey never changes its outcome. The
    model takes the identity as authenticated and derives nothing
    from it."""
    cond = AssertMyTaptree(*operands)
    got_a = outcome(build_tx(txid, index, script_a, amount, [cond], env, identity))
    got_b = outcome(build_tx(txid, index, script_b, amount, [cond], env, identity))
    assert got_a == got_b


@given(txids, indexes, amounts, identities, identities, environments)
def test_taptree_assert_agrees_with_derived_script_assert_on_honest_input(
    txid, index, amount, identity, operands, env
):
    """On an input whose scriptPubKey is the taproot output of its
    own identity, the shape every input base consensus admits has,
    ASSERT_MY_TAPTREE over an operand pair and ASSERT_MY_SCRIPTPUBKEY
    over the scriptPubKey that pair derives are satisfied together:
    the BIP341 tweak derivation is the taptree assert's oracle. The
    pools hold no two pairs deriving one output key, so the
    collision exemption never fires here."""
    honest = HONEST_SPKS[identity]
    taptree = AssertMyTaptree(*operands)
    plain = AssertMyScriptPubKey(HONEST_SPKS[operands])
    got_taptree = outcome(
        build_tx(txid, index, honest, amount, [taptree], env, identity)
    )
    got_plain = outcome(build_tx(txid, index, honest, amount, [plain], env, identity))
    assert (got_taptree is None) == (got_plain is None)
    assert (got_taptree is None) == (operands == identity)
