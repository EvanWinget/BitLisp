"""The witness layer against its oracles and its invariants.

The commitment scheme's hashing has real oracles: the official BIP341
wallet vectors for the leaf hash, the path fold, and the output key
under arbitrary leaf versions, and the vendored Bitcoin Core test
framework for the tagged hash and the annex digest's serialization.
The tree hash is checked against the VM's own sha256tree operator,
which the differential harness pins to the consensus wheel. The
digest-domain table of the spec is recomputed from the tag strings
the package hashes under. The spend entry's invariants cover what no
vector enumerates: any well-formed spend gains an annex only under
its assert, the element bound is exact, and the identity read is a
pure function of the control block and leaf.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "oracle" / "bitcoincore"))

from bitlisp import (  # noqa: E402
    NIL,
    BaseConsensusError,
    BitLispError,
    TxInput,
    evaluate_spend,
    serialize,
)
from bitlisp.commitment import (  # noqa: E402
    BITLISP_LEAF_VERSION,
    ControlBlock,
    merkle_root,
    sha_annex,
    tagged_hash,
    tapleaf_hash,
    taproot_script_pubkey,
    tree_hash,
)
from bitlisp.operators import op_sha256tree  # noqa: E402
from bitlisp.spend import MAX_WITNESS_ELEMENT_SIZE, split_annex  # noqa: E402
from support import NUMS  # noqa: E402
from test_framework.key import TaggedHash  # noqa: E402
from test_framework.messages import ser_string  # noqa: E402

EXAMPLES = settings(max_examples=50, deadline=None)
VECTORS_JSON = (
    REPO_ROOT / "vectors" / "upstream" / "bip341" / "wallet-test-vectors.json"
)


# --- the official BIP341 vectors: leaf hash, path fold, output key ----------


def _leaves(tree):
    """The leaves of a wallet-vector script tree in id order."""
    if isinstance(tree, dict):
        return [tree]
    return [leaf for branch in tree for leaf in _leaves(branch)]


def bip341_leaf_cases():
    with open(VECTORS_JSON) as fh:
        entries = json.load(fh)["scriptPubKey"]
    cases = []
    for n, entry in enumerate(entries):
        tree = entry["given"]["scriptTree"]
        if tree is None:
            continue
        leaves = sorted(_leaves(tree), key=lambda leaf: leaf["id"])
        blocks = entry["expected"]["scriptPathControlBlocks"]
        for leaf, block in zip(leaves, blocks, strict=True):
            cases.append(
                pytest.param(
                    bytes.fromhex(entry["given"]["internalPubkey"]),
                    leaf["leafVersion"],
                    bytes.fromhex(leaf["script"]),
                    bytes.fromhex(block),
                    bytes.fromhex(entry["intermediary"]["leafHashes"][leaf["id"]]),
                    bytes.fromhex(entry["intermediary"]["merkleRoot"]),
                    bytes.fromhex(entry["expected"]["scriptPubKey"]),
                    id=f"bip341_{n}_leaf_{leaf['id']}",
                )
            )
    assert len(cases) == 12
    return cases


@pytest.mark.parametrize(
    "key,version,script,block,leaf_hash,root,spk", bip341_leaf_cases()
)
def test_official_control_blocks_read_to_the_published_identity(
    key, version, script, block, leaf_hash, root, spk
):
    control = ControlBlock.parse(block)
    assert control.leaf_version == version
    assert control.internal_key == key
    assert control.identity(script) == (leaf_hash, root)
    assert control.check(script, spk) == (leaf_hash, root)
    assert taproot_script_pubkey(key, root) == spk


@pytest.mark.parametrize(
    "key,version,script,block,leaf_hash,root,spk", bip341_leaf_cases()
)
def test_official_control_blocks_reject_a_foreign_output(
    key, version, script, block, leaf_hash, root, spk
):
    control = ControlBlock.parse(block)
    other = spk[:-1] + bytes([spk[-1] ^ 1])
    with pytest.raises(BaseConsensusError, match="not the taproot output"):
        control.check(script, other)
    flipped = bytes([block[0] ^ 1]) + block[1:]
    with pytest.raises(BaseConsensusError, match="parity"):
        ControlBlock.parse(flipped).check(script, spk)
    with pytest.raises(BaseConsensusError, match="not the taproot output"):
        control.check(script + b"\x00", spk)


def test_official_key_path_outputs():
    with open(VECTORS_JSON) as fh:
        entries = json.load(fh)["scriptPubKey"]
    checked = 0
    for entry in entries:
        if entry["given"]["scriptTree"] is None:
            key = bytes.fromhex(entry["given"]["internalPubkey"])
            assert (
                taproot_script_pubkey(key, b"").hex()
                == entry["expected"]["scriptPubKey"]
            )
            checked += 1
    assert checked == 1


@pytest.mark.parametrize("size", [0, 32, 34, 66, 33 + 32 * 129])
def test_control_block_lengths_rejected(size):
    with pytest.raises(BaseConsensusError, match="33 plus 32m"):
        ControlBlock.parse(b"\x00" * size)


def test_control_block_length_bounds_accepted():
    ControlBlock.parse(bytes([BITLISP_LEAF_VERSION]) + NUMS)
    ControlBlock.parse(bytes([BITLISP_LEAF_VERSION]) + NUMS + b"\x00" * (32 * 128))


def test_off_curve_internal_key_rejected():
    control = ControlBlock.parse(bytes([BITLISP_LEAF_VERSION]) + b"\xff" * 32)
    with pytest.raises(BaseConsensusError, match="no curve point"):
        control.check(b"\x00" * 32, b"\x51\x20" + b"\x00" * 32)


# --- the Core framework: tagged hash and annex serialization ---------------

tags = st.sampled_from(("TapLeaf", "TapBranch", "TapTweak", "BIP0340/challenge"))
payloads = st.binary(max_size=200)


@EXAMPLES
@given(tags, payloads)
def test_tagged_hash_matches_core(tag, data):
    assert tagged_hash(tag, data) == TaggedHash(tag, data)


@EXAMPLES
@given(st.integers(0, 0xFF), st.binary(max_size=300))
def test_tapleaf_hash_matches_core_under_any_version(version, script):
    version &= 0xFE
    expected = TaggedHash("TapLeaf", bytes([version]) + ser_string(script))
    assert tapleaf_hash(version, script) == expected


@EXAMPLES
@given(st.binary(min_size=0, max_size=300))
def test_sha_annex_matches_core_serialization(annex):
    assert sha_annex(annex) == hashlib.sha256(ser_string(annex)).digest()


def test_sha_annex_covers_a_bound_sized_annex():
    annex = b"\x50" + b"\x00" * (MAX_WITNESS_ELEMENT_SIZE - 1)
    # The compact-size prefix turns three bytes wide at 253.
    assert sha_annex(annex) == hashlib.sha256(ser_string(annex)).digest()


# --- the tree hash against the VM operator ---------------------------------

atoms = st.binary(max_size=8)
nodes = st.recursive(
    atoms, lambda children: st.tuples(children, children), max_leaves=12
)


@EXAMPLES
@given(nodes)
def test_tree_hash_matches_the_operator(node):
    assert tree_hash(node) == op_sha256tree([node], lambda amount: None)


def test_tree_hash_of_named_programs():
    # The two programs the spec names, and the leaf script they give.
    assert tree_hash(b"\x01") == hashlib.sha256(b"\x01\x01").digest()
    assert tree_hash(NIL) == hashlib.sha256(b"\x01").digest()


# --- the digest-domain table -----------------------------------------------

# Every tag a BitLisp validator hashes under, and the first byte of
# each tag's digest, as the spec's table states them.
DIGEST_DOMAIN_TABLE = {
    "TapLeaf": 0xAE,
    "TapBranch": 0x19,
    "TapTweak": 0xE8,
    "BIP0340/challenge": 0x7B,
    "BitLisp/sig/my_txid": 0x54,
    "BitLisp/sig/my_scriptpubkey": 0xE3,
    "BitLisp/sig/my_amount": 0xDF,
    "BitLisp/sig/my_scriptpubkey_amount": 0xEC,
    "BitLisp/sig/my_txid_amount": 0xFF,
    "BitLisp/sig/my_txid_scriptpubkey": 0xE5,
    "BitLisp/sig/raw": 0x56,
    "BitLisp/sig/my_outpoint": 0xDA,
}


def test_digest_domain_table_first_bytes():
    for tag, first in DIGEST_DOMAIN_TABLE.items():
        assert hashlib.sha256(tag.encode("ascii")).digest()[0] == first, tag
    # No tagged-hash preimage begins like a tree-hash preimage.
    assert not {0x01, 0x02} & set(DIGEST_DOMAIN_TABLE.values())


def test_digest_domain_table_is_every_tag_the_package_hashes_under():
    """Every tagged digest goes through secp256k1.tagged_hash, so the
    tags in use are its literal arguments plus the signature bindings'
    tags, and the table must be exactly that set."""
    from bitlisp.conditions import SIG_BINDINGS

    package = REPO_ROOT / "python" / "bitlisp"
    literal = re.compile(r'tagged_hash\(\s*"([^"]+)"')
    tags = {binding[1] for binding in SIG_BINDINGS.values()}
    for path in package.glob("*.py"):
        tags.update(literal.findall(path.read_text()))
    assert tags == set(DIGEST_DOMAIN_TABLE)
    # One tagged hash, in one place, so the scan above sees every tag.
    definitions = [
        path.name
        for path in package.glob("*.py")
        if "def tagged_hash(" in path.read_text()
    ]
    assert definitions == ["secp256k1.py"]


# --- the spend entry's invariants ------------------------------------------


def _clist(*items):
    node = NIL
    for item in reversed(items):
        node = (item, node)
    return node


def _spend(program, solution, annex=None, path=b"", max_cost=10_000_000):
    """Evaluates a program over a solution as a spend of a leaf under
    NUMS with the given path, returning (cost, input) or the error
    code."""
    leaf = tree_hash(program)
    block = ControlBlock.build(NUMS, leaf, path)
    witness = [serialize(solution), serialize(program), leaf, block.serialize()]
    if annex is not None:
        witness.append(annex)
    root = merkle_root(tapleaf_hash(BITLISP_LEAF_VERSION, leaf), path)
    tx_input = TxInput(b"\x00" * 32, 0, taproot_script_pubkey(NUMS, root), 1, 0)
    try:
        return evaluate_spend(tx_input, witness, max_cost)
    except BitLispError as exc:
        return exc.code


def _annex_assert(annex_hash):
    return _clist(b"\x39", annex_hash)


amount_asserts = st.integers(0, 3).map(
    lambda n: _clist(b"\x33", bytes([n]) if n else NIL)
)
solutions = st.lists(amount_asserts, max_size=3).map(lambda conds: _clist(*conds))
annexes = st.one_of(st.none(), st.binary(max_size=40).map(lambda tail: b"\x50" + tail))


@EXAMPLES
@given(solutions, annexes, st.booleans())
def test_annex_admitted_exactly_under_its_assert(solution, annex, asserted):
    """Under the anyone-can-spend program, a spend with an annex passes
    the input stages exactly when its solution asserts that annex's
    hash, and a spend without one always does."""
    if asserted and annex is not None:
        solution = (_annex_assert(sha_annex(annex)), solution)
    outcome = _spend(b"\x01", solution, annex)
    if annex is None or asserted:
        cost, spent = outcome
        assert spent.annex_hash == (None if annex is None else sha_annex(annex))
    else:
        assert outcome == "unasserted_annex"


@EXAMPLES
@given(st.integers(-3, 3))
def test_element_bound_is_exact(delta):
    """A solution element of exactly MAX_WITNESS_ELEMENT_SIZE bytes
    passes stage 1 and one more byte fails it, under the program that
    ignores its solution."""
    size = MAX_WITNESS_ELEMENT_SIZE + delta
    atom = next(
        b"\x00" * n
        for n in range(size - 3, size + 1)
        if len(serialize(b"\x00" * n)) == size
    )
    outcome = _spend((b"\x01", NIL), atom)
    if delta <= 0:
        assert outcome[1].conditions == ()
    else:
        assert outcome == "bad_witness"


@EXAMPLES
@given(st.lists(st.binary(min_size=32, max_size=32), max_size=4))
def test_identity_is_read_from_the_control_block(siblings):
    """The identity the spend carries is the leaf hash of the revealed
    leaf script and the fold of the control block's path, whatever
    the path."""
    path = b"".join(siblings)
    cost, spent = _spend((b"\x01", NIL), NIL, path=path)
    leaf = tree_hash((b"\x01", NIL))
    tapleaf = tapleaf_hash(BITLISP_LEAF_VERSION, leaf)
    assert spent.tapleaf == tapleaf
    assert spent.merkle_root == merkle_root(tapleaf, path)
    assert spent.internal_key == NUMS
    assert (spent.merkle_root == tapleaf) == (path == b"")


def test_split_annex_follows_bip341():
    assert split_annex([b"\x50"]) == ([b"\x50"], None)
    assert split_annex([b"\x01", b"\x50"]) == ([b"\x01"], b"\x50")
    assert split_annex([b"\x50", b"\x01"]) == ([b"\x50", b"\x01"], None)
    assert split_annex([b"\x01", b""]) == ([b"\x01", b""], None)
    assert split_annex([]) == ([], None)


def test_key_path_and_foreign_leaf_versions_are_outside_bitlisp():
    leaf = tree_hash(b"\x01")
    block = ControlBlock.build(NUMS, leaf, leaf_version=0xC0).serialize()
    root = merkle_root(tapleaf_hash(0xC0, leaf), b"")
    tx_input = TxInput(b"\x00" * 32, 0, taproot_script_pubkey(NUMS, root), 1, 0)
    with pytest.raises(BaseConsensusError, match="leaf version"):
        evaluate_spend(tx_input, [b"\x80", b"\x01", leaf, block], 1000)
    with pytest.raises(BaseConsensusError, match="not a script-path spend"):
        evaluate_spend(tx_input, [b"\x00" * 64], 1000)
    carrying = TxInput(
        b"\x00" * 32,
        0,
        b"\x51",
        1,
        0,
        conditions=(),
        tapleaf=leaf,
        merkle_root=leaf,
        internal_key=NUMS,
    )
    with pytest.raises(ValueError, match="already carries"):
        evaluate_spend(carrying, [b"\x80", b"\x01", leaf, block], 1000)


@EXAMPLES
@given(
    st.integers(0, 127).map(lambda v: v * 2),
    st.lists(st.binary(min_size=32, max_size=32), max_size=5),
    st.binary(max_size=40),
)
def test_control_block_round_trips(leaf_version, siblings, leaf_script):
    """build then serialize then parse gives the block back, its
    parity the output key's, and build reports None exactly when the
    key does not lift."""
    path = b"".join(siblings)
    block = ControlBlock.build(NUMS, leaf_script, path, leaf_version)
    assert ControlBlock.parse(block.serialize()) == block
    assert block.check(
        leaf_script, taproot_script_pubkey(NUMS, block.identity(leaf_script)[1])
    )
    assert ControlBlock.build(b"\xff" * 32, leaf_script, path, leaf_version) is None
