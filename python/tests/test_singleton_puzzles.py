"""Compile-and-run coverage for the singleton wrapper benchmark puzzle.

The wrapper and the owner inner program compile from source here, so
these tests hold the source-to-bytes link: the mod tree hashes are
pinned as literals, the serialization library is checked against the
transaction model's own txid, the lifecycle runs through the
single-spend runner over transactions whose ids are real (each spend
consumes an outpoint the previous model transaction created), every
failure mode asserts its exact error code live, and the pinned
vector files are recomputed from source so puzzle source and corpus
cannot drift apart silently. Signatures come from the vendored
Bitcoin Core framework signer with fixed aux bytes, so every derived
value is deterministic.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "oracle" / "bitcoincore"))

from bitlisp import (  # noqa: E402
    BitLispError,
    Transaction,
    TxInput,
    TxOutput,
    run,
    secp256k1,
    serialize,
)
from bitlisp.conditions import CreateOutput, parse_conditions  # noqa: E402
from bitlisp.sexp import NIL, int_to_atom  # noqa: E402
from bitlisp_tools.compiler import compile_program, tree_hash  # noqa: E402
from bitlisp_tools.curry import curry, uncurry  # noqa: E402
from bitlisp_tools.runner import run_spend  # noqa: E402
from test_framework.key import compute_xonly_pubkey, sign_schnorr  # noqa: E402

PUZZLES = REPO_ROOT / "puzzles"
INCLUDES = (PUZZLES / "lib", PUZZLES / "singleton")
BUDGET = 11_000_000_000
SEQ_FINAL = 0xFFFFFFFF

# The BIP341 nothing-up-my-sleeve point: no key-path spend exists.
NUMS = bytes.fromhex("50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0")
OWNER_SK = (0xC0 << 248 | 11).to_bytes(32, "big")
OWNER_PK = compute_xonly_pubkey(OWNER_SK)[0]
OWNER2_SK = (0xC1 << 248 | 12).to_bytes(32, "big")
OWNER2_PK = compute_xonly_pubkey(OWNER2_SK)[0]
FEE_SPK = bytes.fromhex("0014") + b"\x11" * 20
PAY_SPK = bytes.fromhex("0014") + b"\x22" * 20
AUX = b"\x00" * 32
END_AMOUNT = -113

# Drift guards: recompiling the sources must reproduce these hashes,
# so any source change is a deliberate re-pin of both literals and
# the vector files.
SINGLETON_MOD_HASH = bytes.fromhex(
    "5f9b069d8c33d55360ee8ac42a97ff64680b28a40195daf8c3851cf0ebeb3849"
)
OWNER_INNER_MOD_HASH = bytes.fromhex(
    "b8bdd33e430a797065babc3ea3adcf15c9c0f62b1c7ae78f92ef9a6b1e61f9f0"
)

SINGLETON_NODE, _ = compile_program(
    (PUZZLES / "singleton" / "singleton.bl").read_text(), INCLUDES
)
INNER_NODE, _ = compile_program(
    (PUZZLES / "singleton" / "owner-inner.bl").read_text(), INCLUDES
)


def proper_list(*items):
    node = NIL
    for item in reversed(items):
        node = (item, node)
    return node


def outpoint(txid, index):
    return txid + index.to_bytes(4, "little")


def tx_fields(tx):
    """The transaction in the field shape tx-wire.blib serializes."""
    return proper_list(
        tx.version.to_bytes(4, "little"),
        proper_list(
            *[
                proper_list(
                    outpoint(i.txid, i.index),
                    i.script_sig,
                    i.sequence.to_bytes(4, "little"),
                )
                for i in tx.inputs
            ]
        ),
        proper_list(
            *[
                proper_list(o.amount.to_bytes(8, "little"), o.script_pubkey)
                for o in tx.outputs
            ]
        ),
        tx.locktime.to_bytes(4, "little"),
    )


def state_script(launcher, inner_hash):
    """OP_RETURN then a 68-byte push of the lineage tag and the inner
    program's tree hash."""
    return bytes.fromhex("6a44") + launcher + inner_hash


def lineage(launcher):
    """A lineage's curried wrapper, its merkle root, and its
    scriptPubKey."""
    inst = curry(SINGLETON_NODE, [SINGLETON_MOD_HASH, NUMS, launcher])
    root = tree_hash(inst)
    return inst, root, b"\x51\x20" + secp256k1.taproot_output_key(NUMS, root)


def sig_my_outpoint(sk, txid, index, message_node):
    tag = hashlib.sha256(b"BitLisp/sig/my_outpoint").digest()
    digest = hashlib.sha256(
        tag + tag + outpoint(txid, index) + tree_hash(message_node)
    ).digest()
    return sign_schnorr(sk, digest, AUX)


def inner_solution(sk, txid, index, next_hash, next_amount, extra=NIL, sig=None):
    message = proper_list(next_hash, int_to_atom(next_amount), extra)
    if sig is None:
        sig = sig_my_outpoint(sk, txid, index, message)
    return proper_list(next_hash, int_to_atom(next_amount), extra, sig)


def solution(spk, amount, index, parent_tx, parent_vout, grandparent_tx, inner, args):
    return proper_list(
        spk,
        int_to_atom(amount),
        int_to_atom(index),
        tx_fields(parent_tx),
        NIL if parent_vout is None else int_to_atom(parent_vout),
        NIL if grandparent_tx is None else tx_fields(grandparent_tx),
        inner,
        args,
    )


def fee_input(txid=b"\xbb" * 32, amount=50_000):
    return TxInput(txid, 0, FEE_SPK, amount, sequence=SEQ_FINAL)


def singleton_input(spk, root, txid, index, amount, conditions=None):
    """A BitLisp input of a single-leaf taproot tree, where the
    executing leaf's hash is also the spending path's merkle root."""
    return TxInput(
        txid,
        index,
        spk,
        amount,
        sequence=SEQ_FINAL,
        conditions=conditions,
        tapleaf=root,
        merkle_root=root,
    )


LAUNCHER_TXID = b"\xaa" * 32
LAUNCHER = outpoint(LAUNCHER_TXID, 0)
SINGLETON, ROOT, SPK = lineage(LAUNCHER)
INNER1 = curry(INNER_NODE, [OWNER_PK])
H1 = tree_hash(INNER1)
INNER2 = curry(INNER_NODE, [OWNER2_PK])
H2 = tree_hash(INNER2)
AMOUNT = 10_001

# The launch: a plain wallet transaction spends the launcher coin at
# input 0 and places the first singleton coin at output 0, beside the
# state output committing the first inner program.
LAUNCH = Transaction(
    version=2,
    locktime=0,
    inputs=(TxInput(LAUNCHER_TXID, 0, FEE_SPK, 100_000, sequence=SEQ_FINAL),),
    outputs=(
        TxOutput(SPK, AMOUNT),
        TxOutput(state_script(LAUNCHER, H1), 0),
        TxOutput(FEE_SPK, 80_000),
    ),
)

# Generation 1: the first coin hands the lineage to the second owner.
TX1 = Transaction(
    version=2,
    locktime=0,
    inputs=(singleton_input(SPK, ROOT, LAUNCH.txid, 0, AMOUNT), fee_input()),
    outputs=(
        TxOutput(SPK, AMOUNT),
        TxOutput(state_script(LAUNCHER, H2), 0),
        TxOutput(FEE_SPK, 40_000),
    ),
)
SOL1 = solution(
    SPK,
    AMOUNT,
    0,
    LAUNCH,
    None,
    None,
    INNER1,
    inner_solution(OWNER_SK, LAUNCH.txid, 0, H2, AMOUNT),
)

# Generation 2: the singleton sits at input 1, so its child sits at
# output 1, and the second owner hands the lineage back.
TX2 = Transaction(
    version=2,
    locktime=0,
    inputs=(fee_input(b"\xcc" * 32), singleton_input(SPK, ROOT, TX1.txid, 0, AMOUNT)),
    outputs=(
        TxOutput(FEE_SPK, 40_000),
        TxOutput(SPK, AMOUNT),
        TxOutput(state_script(LAUNCHER, H1), 0),
    ),
)
SOL2 = solution(
    SPK,
    AMOUNT,
    0,
    TX1,
    0,
    LAUNCH,
    INNER2,
    inner_solution(OWNER2_SK, TX1.txid, 0, H1, AMOUNT),
)

# Generation 3 ends the lineage, paying the coin's value out.
PAYOUT = proper_list(proper_list(b"\x01", PAY_SPK, int_to_atom(10_000)))
TX3 = Transaction(
    version=2,
    locktime=0,
    inputs=(singleton_input(SPK, ROOT, TX2.txid, 1, AMOUNT),),
    outputs=(TxOutput(PAY_SPK, 10_000),),
)
SOL3 = solution(
    SPK,
    AMOUNT,
    1,
    TX2,
    0,
    TX1,
    INNER1,
    inner_solution(OWNER_SK, TX2.txid, 1, NIL, END_AMOUNT, PAYOUT),
)


def spend_error(program, sol, tx, input_index=0):
    with pytest.raises(BitLispError) as info:
        run_spend(program, sol, tx, input_index)
    return info.value.code


def run_error(program, sol):
    with pytest.raises(BitLispError) as info:
        run(program, sol, BUDGET)
    return info.value.code


def conditions_of(program, sol):
    _, result = run(program, sol, BUDGET)
    _, conds = parse_conditions(result, None)
    return conds


def test_mod_hashes_pinned():
    assert tree_hash(SINGLETON_NODE) == SINGLETON_MOD_HASH
    assert tree_hash(INNER_NODE) == OWNER_INNER_MOD_HASH


def test_curried_identity_matches_tooling():
    # The program's own root reconstruction, read off the taproot
    # assert it emits, must agree with the tooling's tree hash over
    # the curried node, and uncurry must read the values back.
    inner, values = uncurry(SINGLETON)
    assert inner == SINGLETON_NODE
    assert values == [SINGLETON_MOD_HASH, NUMS, LAUNCHER]
    conds = conditions_of(SINGLETON, SOL1)
    assert conds[0].merkle_root == ROOT
    assert conds[0].script_pubkey == SPK
    assert conds[1].script_pubkey == SPK


def test_wire_serialization_matches_model():
    # The library's txid over the field shape equals the model's
    # txid for transactions exercising every compact-size width the
    # model can reach: a one-byte count, a script past 252 bytes, and
    # a non-empty legacy scriptSig.
    txid_program, _ = compile_program(
        '(program (TX) (include "tx-wire.blib") (txid TX))', INCLUDES
    )
    long_script = b"\x6a\x4d\x20\x01" + b"\x55" * 288
    legacy = TxInput(
        b"\xdd" * 32, 7, FEE_SPK, 9_000, sequence=0x12345678, script_sig=b"\x00" * 5
    )
    samples = (
        LAUNCH,
        TX2,
        Transaction(
            version=1,
            locktime=500_000,
            inputs=(legacy, fee_input()),
            outputs=(TxOutput(long_script, 0), TxOutput(FEE_SPK, 59_000)),
        ),
    )
    for tx in samples:
        _, result = run(txid_program, proper_list(tx_fields(tx)), BUDGET)
        assert result == tx.txid


def test_lifecycle():
    _, conds = run_spend(SINGLETON, SOL1, TX1)
    assert [c.script_pubkey for c in conds[-2:]] == [SPK, state_script(LAUNCHER, H2)]
    assert conds[-2].amount == AMOUNT
    run_spend(SINGLETON, SOL2, TX2, 1)
    _, conds = run_spend(SINGLETON, SOL3, TX3)
    # The ending spend creates no child and no state output, only
    # the payout the inner program asked for.
    assert [c.script_pubkey for c in conds if isinstance(c, CreateOutput)] == [PAY_SPK]


def test_funded_coin_without_lineage_is_unspendable():
    # An ordinary payment to the lineage scriptPubKey, with a perfect
    # state output beside it, cannot prove descent: the input at its
    # index is neither the launcher nor a coin at this scriptPubKey,
    # whatever grandparent is offered.
    funder_txid = b"\xee" * 32
    funding = Transaction(
        version=2,
        locktime=0,
        inputs=(TxInput(funder_txid, 3, FEE_SPK, 100_000, sequence=SEQ_FINAL),),
        outputs=(TxOutput(SPK, AMOUNT), TxOutput(state_script(LAUNCHER, H1), 0)),
    )
    args = inner_solution(OWNER_SK, funding.txid, 0, H2, AMOUNT)
    assert (
        run_error(
            SINGLETON, solution(SPK, AMOUNT, 0, funding, None, None, INNER1, args)
        )
        == "path_into_atom"
    )
    grandparent = Transaction(
        version=2,
        locktime=0,
        inputs=(fee_input(b"\xed" * 32, 400_000),),
        outputs=(TxOutput(FEE_SPK, 100_000),) * 4,
    )
    assert (
        run_error(
            SINGLETON, solution(SPK, AMOUNT, 0, funding, 3, grandparent, INNER1, args)
        )
        == "user_raise"
    )


def test_extra_output_at_lineage_spk_is_dust():
    # A second output at the lineage scriptPubKey in a genuine spend
    # names, through its index, a fee input or no input at all.
    for index, code in ((1, "user_raise"), (2, "arg_not_pair")):
        args = inner_solution(OWNER2_SK, TX1.txid, index, H1, AMOUNT)
        assert (
            run_error(
                SINGLETON, solution(SPK, AMOUNT, index, TX1, 0, LAUNCH, INNER2, args)
            )
            == code
        )


def test_wrong_outpoint_fails_in_validator():
    wrong = Transaction(
        version=2,
        locktime=0,
        inputs=(singleton_input(SPK, ROOT, TX1.txid, 2, AMOUNT), fee_input()),
        outputs=TX2.outputs,
    )
    assert spend_error(SINGLETON, SOL2, wrong) == "unsatisfied_outpoint_assert"


def test_state_must_match_committed_inner():
    # Supplying an inner program the state output does not commit
    # raises, and so does a creating transaction with two tagged
    # state outputs, which would let its assembler offer two states.
    uncommitted = inner_solution(OWNER2_SK, LAUNCH.txid, 0, H2, AMOUNT)
    assert (
        run_error(
            SINGLETON, solution(SPK, AMOUNT, 0, LAUNCH, None, None, INNER2, uncommitted)
        )
        == "user_raise"
    )
    two_states = Transaction(
        version=2,
        locktime=0,
        inputs=LAUNCH.inputs,
        outputs=LAUNCH.outputs + (TxOutput(state_script(LAUNCHER, H2), 0),),
    )
    args = inner_solution(OWNER_SK, two_states.txid, 0, H2, AMOUNT)
    assert (
        run_error(
            SINGLETON, solution(SPK, AMOUNT, 0, two_states, None, None, INNER1, args)
        )
        == "user_raise"
    )


def test_morph_requires_exactly_one_odd_output():
    even_child = inner_solution(OWNER_SK, LAUNCH.txid, 0, H2, 10_000)
    assert (
        run_error(
            SINGLETON, solution(SPK, AMOUNT, 0, LAUNCH, None, None, INNER1, even_child)
        )
        == "user_raise"
    )
    second_odd = proper_list(proper_list(b"\x01", FEE_SPK, int_to_atom(3)))
    two_children = inner_solution(OWNER_SK, LAUNCH.txid, 0, H2, AMOUNT, second_odd)
    assert (
        run_error(
            SINGLETON,
            solution(SPK, AMOUNT, 0, LAUNCH, None, None, INNER1, two_children),
        )
        == "user_raise"
    )


def test_even_amount_raises():
    args = inner_solution(OWNER_SK, LAUNCH.txid, 0, H2, 10_000)
    assert (
        run_error(SINGLETON, solution(SPK, 10_000, 0, LAUNCH, None, None, INNER1, args))
        == "user_raise"
    )


def test_malformed_instance_and_fields_raise():
    short_launcher = curry(SINGLETON_NODE, [SINGLETON_MOD_HASH, NUMS, LAUNCHER[:35]])
    assert run_error(short_launcher, SOL1) == "user_raise"
    fields = tx_fields(LAUNCH)
    truncated_version = proper_list(
        b"\x02\x00\x00", fields[1][0], fields[1][1][0], b"\x00" * 4
    )
    args = inner_solution(OWNER_SK, LAUNCH.txid, 0, H2, AMOUNT)
    bad = proper_list(
        SPK, int_to_atom(AMOUNT), NIL, truncated_version, NIL, NIL, INNER1, args
    )
    assert run_error(SINGLETON, bad) == "user_raise"


def test_owner_signature_binds_outpoint_and_state():
    # The generation 1 authorization, signed over the first coin's
    # outpoint, replayed on a later coin of the same lineage whose
    # committed state is the same inner program, fails on the outpoint
    # binding alone. The captured signature rewritten to a different
    # next state fails on the message binding alone.
    args1 = list(iter_items(SOL1))[7]
    committed = Transaction(
        version=2,
        locktime=0,
        inputs=TX1.inputs,
        outputs=(
            TX1.outputs[0],
            TxOutput(state_script(LAUNCHER, H1), 0),
            TX1.outputs[2],
        ),
    )
    later = Transaction(
        version=2,
        locktime=0,
        inputs=(singleton_input(SPK, ROOT, committed.txid, 0, AMOUNT), fee_input()),
        outputs=TX1.outputs,
    )
    replayed = solution(SPK, AMOUNT, 0, committed, 0, LAUNCH, INNER1, args1)
    assert spend_error(SINGLETON, replayed, later) == "unsatisfied_sig_assert"
    captured = list(iter_items(args1))[3]
    rewritten = inner_solution(OWNER_SK, LAUNCH.txid, 0, H1, AMOUNT, sig=captured)
    assert (
        spend_error(
            SINGLETON,
            solution(SPK, AMOUNT, 0, LAUNCH, None, None, INNER1, rewritten),
            committed,
        )
        == "unsatisfied_sig_assert"
    )


def iter_items(node):
    while node != NIL:
        yield node[0]
        node = node[1]


OTHER_LAUNCHER = outpoint(b"\xa1" * 32, 1)
OTHER, OTHER_ROOT, OTHER_SPK = lineage(OTHER_LAUNCHER)
OTHER_LAUNCH = Transaction(
    version=2,
    locktime=0,
    inputs=(TxInput(b"\xa1" * 32, 1, FEE_SPK, 100_000, sequence=SEQ_FINAL),),
    outputs=(
        TxOutput(OTHER_SPK, AMOUNT),
        TxOutput(state_script(OTHER_LAUNCHER, H1), 0),
        TxOutput(FEE_SPK, 80_000),
    ),
)


def composed_tx():
    """Two lineages spent in one transaction at indices 0 and 1, each
    finding its own child and its own tagged state output."""
    return Transaction(
        version=2,
        locktime=0,
        inputs=(
            singleton_input(SPK, ROOT, LAUNCH.txid, 0, AMOUNT),
            singleton_input(OTHER_SPK, OTHER_ROOT, OTHER_LAUNCH.txid, 0, AMOUNT),
            fee_input(),
        ),
        outputs=(
            TxOutput(SPK, AMOUNT),
            TxOutput(OTHER_SPK, AMOUNT),
            TxOutput(state_script(LAUNCHER, H2), 0),
            TxOutput(state_script(OTHER_LAUNCHER, H2), 0),
            TxOutput(FEE_SPK, 40_000),
        ),
    )


OTHER_SOL = solution(
    OTHER_SPK,
    AMOUNT,
    0,
    OTHER_LAUNCH,
    None,
    None,
    INNER1,
    inner_solution(OWNER_SK, OTHER_LAUNCH.txid, 0, H2, AMOUNT),
)


def test_two_lineages_compose():
    tx = composed_tx()
    run_spend(SINGLETON, SOL1, tx, 0)
    other_conds = conditions_of(OTHER, OTHER_SOL)
    with_other = Transaction(
        version=2,
        locktime=0,
        inputs=(
            tx.inputs[0],
            singleton_input(
                OTHER_SPK, OTHER_ROOT, OTHER_LAUNCH.txid, 0, AMOUNT, other_conds
            ),
            tx.inputs[2],
        ),
        outputs=tx.outputs,
    )
    run_spend(SINGLETON, SOL1, with_other, 0)
    # Each child, once spent, reads its own index: lineage one at
    # output 0, the other at output 1.
    next_sol = solution(
        OTHER_SPK,
        AMOUNT,
        1,
        with_other,
        0,
        OTHER_LAUNCH,
        INNER2,
        inner_solution(OWNER2_SK, with_other.txid, 1, H1, AMOUNT),
    )
    conds = conditions_of(OTHER, next_sol)
    assert conds[3].outpoint == outpoint(with_other.txid, 1)


def load_vector(name):
    path = REPO_ROOT / "vectors" / name
    return {case["name"]: case for case in json.loads(path.read_text())["cases"]}


def vm_cases():
    """Every pinned program and solution, by case name, built from
    the sources and the lifecycle above."""
    funding = Transaction(
        version=2,
        locktime=0,
        inputs=(TxInput(b"\xee" * 32, 3, FEE_SPK, 100_000, sequence=SEQ_FINAL),),
        outputs=(TxOutput(SPK, AMOUNT), TxOutput(state_script(LAUNCHER, H1), 0)),
    )
    grandparent = Transaction(
        version=2,
        locktime=0,
        inputs=(fee_input(b"\xed" * 32, 400_000),),
        outputs=(TxOutput(FEE_SPK, 100_000),) * 4,
    )
    two_states = Transaction(
        version=2,
        locktime=0,
        inputs=LAUNCH.inputs,
        outputs=LAUNCH.outputs + (TxOutput(state_script(LAUNCHER, H2), 0),),
    )
    eve_args = inner_solution(OWNER_SK, LAUNCH.txid, 0, H2, AMOUNT)
    fields = tx_fields(LAUNCH)
    truncated_version = proper_list(
        b"\x02\x00\x00", fields[1][0], fields[1][1][0], b"\x00" * 4
    )
    second_odd = proper_list(proper_list(b"\x01", FEE_SPK, int_to_atom(3)))
    return {
        "first_spend": (SINGLETON, SOL1),
        "second_generation_at_input_one": (SINGLETON, SOL2),
        "lineage_ends": (SINGLETON, SOL3),
        "second_lineage_composed": (OTHER, OTHER_SOL),
        "funded_coin_no_grandparent": (
            SINGLETON,
            solution(
                SPK,
                AMOUNT,
                0,
                funding,
                None,
                None,
                INNER1,
                inner_solution(OWNER_SK, funding.txid, 0, H2, AMOUNT),
            ),
        ),
        "funded_coin_wrong_grandparent": (
            SINGLETON,
            solution(
                SPK,
                AMOUNT,
                0,
                funding,
                3,
                grandparent,
                INNER1,
                inner_solution(OWNER_SK, funding.txid, 0, H2, AMOUNT),
            ),
        ),
        "extra_output_indexes_fee_input": (
            SINGLETON,
            solution(
                SPK,
                AMOUNT,
                1,
                TX1,
                0,
                LAUNCH,
                INNER2,
                inner_solution(OWNER2_SK, TX1.txid, 1, H1, AMOUNT),
            ),
        ),
        "extra_output_indexes_no_input": (
            SINGLETON,
            solution(
                SPK,
                AMOUNT,
                2,
                TX1,
                0,
                LAUNCH,
                INNER2,
                inner_solution(OWNER2_SK, TX1.txid, 2, H1, AMOUNT),
            ),
        ),
        "uncommitted_inner_program": (
            SINGLETON,
            solution(
                SPK,
                AMOUNT,
                0,
                LAUNCH,
                None,
                None,
                INNER2,
                inner_solution(OWNER2_SK, LAUNCH.txid, 0, H2, AMOUNT),
            ),
        ),
        "two_state_outputs": (
            SINGLETON,
            solution(
                SPK,
                AMOUNT,
                0,
                two_states,
                None,
                None,
                INNER1,
                inner_solution(OWNER_SK, two_states.txid, 0, H2, AMOUNT),
            ),
        ),
        "inner_creates_no_odd_output": (
            SINGLETON,
            solution(
                SPK,
                AMOUNT,
                0,
                LAUNCH,
                None,
                None,
                INNER1,
                inner_solution(OWNER_SK, LAUNCH.txid, 0, H2, 10_000),
            ),
        ),
        "inner_creates_two_odd_outputs": (
            SINGLETON,
            solution(
                SPK,
                AMOUNT,
                0,
                LAUNCH,
                None,
                None,
                INNER1,
                inner_solution(OWNER_SK, LAUNCH.txid, 0, H2, AMOUNT, second_odd),
            ),
        ),
        "even_amount": (
            SINGLETON,
            solution(
                SPK,
                10_000,
                0,
                LAUNCH,
                None,
                None,
                INNER1,
                inner_solution(OWNER_SK, LAUNCH.txid, 0, H2, 10_000),
            ),
        ),
        "malformed_launcher_outpoint_unspendable": (
            curry(SINGLETON_NODE, [SINGLETON_MOD_HASH, NUMS, LAUNCHER[:35]]),
            SOL1,
        ),
        "truncated_version_field": (
            SINGLETON,
            proper_list(
                SPK,
                int_to_atom(AMOUNT),
                NIL,
                truncated_version,
                NIL,
                NIL,
                INNER1,
                eve_args,
            ),
        ),
    }


def test_vm_vectors_match_source():
    # Every pinned program and solution is byte-identical to a fresh
    # compile, curry, and lifecycle construction, so the corpus
    # cannot drift from the sources.
    cases = load_vector("vm/singleton-programs.json")
    expected = vm_cases()
    assert set(cases) == set(expected)
    for name, (program, sol) in expected.items():
        assert cases[name]["program"] == serialize(program).hex(), name
        assert cases[name]["env"] == serialize(sol).hex(), name


def emitted_hex(program, sol):
    return serialize(run(program, sol, BUDGET)[1]).hex()


def validation_conditions():
    """Every conditions field the validation vector file carries."""
    first = emitted_hex(SINGLETON, SOL1)
    sig = list(iter_items(list(iter_items(SOL1))[7]))[3]
    flipped = bytes([sig[0] ^ 0x01]) + sig[1:]
    return {
        first,
        first.replace(sig.hex(), flipped.hex()),
        emitted_hex(SINGLETON, SOL2),
        emitted_hex(SINGLETON, SOL3),
        emitted_hex(OTHER, OTHER_SOL),
    }


def test_validation_vectors_match_source():
    # The complete closure: every conditions field in the validation
    # vector file is recomputed here from compiled source and the
    # documented signature flip, set-equal in both directions.
    observed = set()
    for case in load_vector("validation/singleton-lineage.json").values():
        for entry in case["tx"]["inputs"]:
            if "conditions" in entry:
                observed.add(entry["conditions"])
    assert observed == validation_conditions()
