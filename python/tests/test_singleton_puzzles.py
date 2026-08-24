"""Compile-and-run coverage for the singleton wrapper benchmark puzzle.

The wrapper and the owner inner program compile from source here, so
these tests hold the source-to-bytes link: the mod tree hashes are
pinned as literals, the serialization library is checked against the
transaction model's own txid at every compact-size boundary the
model reaches, the lifecycle runs through the single-spend runner
over transactions whose ids are real (each spend consumes an outpoint
the previous model transaction created), every failure mode asserts
its exact error code live, and the pinned vector files are recomputed
from source so puzzle source and corpus cannot drift apart silently.
Signatures come from the vendored Bitcoin Core framework signer with
fixed aux bytes, so every derived value is deterministic.
"""

import hashlib
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
from bitlisp.sexp import NIL, int_to_atom, iter_proper_list  # noqa: E402
from bitlisp_tools.compiler import compile_program, tree_hash  # noqa: E402
from bitlisp_tools.curry import curry, uncurry  # noqa: E402
from bitlisp_tools.runner import run_spend  # noqa: E402
from support import (  # noqa: E402
    NUMS,
    assert_corpus_identities,
    condition_inputs,
    load_vector,
)
from test_framework.key import compute_xonly_pubkey, sign_schnorr  # noqa: E402

PUZZLES = REPO_ROOT / "puzzles"
INCLUDES = (PUZZLES / "lib", PUZZLES / "singleton")
BUDGET = 11_000_000_000
SEQ_FINAL = 0xFFFFFFFF

OWNER_SK = (0xC0 << 248 | 11).to_bytes(32, "big")
OWNER_PK = compute_xonly_pubkey(OWNER_SK)[0]
OWNER2_SK = (0xC1 << 248 | 12).to_bytes(32, "big")
OWNER2_PK = compute_xonly_pubkey(OWNER2_SK)[0]
FEE_SPK = bytes.fromhex("0014") + b"\x11" * 20
PAY_SPK = bytes.fromhex("0014") + b"\x22" * 20
AUX = b"\x00" * 32
END_AMOUNT = -113
END_PAYLOAD = b"\x00" * 32

# Drift guards: recompiling the sources must reproduce these hashes,
# so any source change is a deliberate re-pin of both literals and
# the vector files.
SINGLETON_MOD_HASH = bytes.fromhex(
    "15d44b7d58dfa717679dfdeb583bb42a749bf9188dc5d7661171fdf89e8c3714"
)
OWNER_INNER_MOD_HASH = bytes.fromhex(
    "40977e84db61eef5f52c9ac9b46dd2e2fbd6439674f50dd7a00ced5daf523bf0"
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


def state_payload(inner_hash, amount, index):
    return tree_hash(proper_list(inner_hash, int_to_atom(amount), int_to_atom(index)))


def state_script(launcher, payload):
    """OP_RETURN then a 68-byte push of the lineage tag and the state
    payload."""
    return bytes.fromhex("6a44") + launcher + payload


def state_output(launcher, inner_hash, amount, index):
    return TxOutput(state_script(launcher, state_payload(inner_hash, amount, index)), 0)


def lineage(launcher):
    """A lineage's curried wrapper, its merkle root, and its
    scriptPubKey."""
    inst = curry(SINGLETON_NODE, [SINGLETON_MOD_HASH, launcher])
    root = tree_hash(inst)
    return inst, root, b"\x51\x20" + secp256k1.taproot_output_key(NUMS, root)


def sig_my_outpoint(sk, txid, index, message_node):
    tag = hashlib.sha256(b"BitLisp/sig/my_outpoint").digest()
    digest = hashlib.sha256(
        tag + tag + outpoint(txid, index) + tree_hash(message_node)
    ).digest()
    return sign_schnorr(sk, digest, AUX)


def inner_solution(sk, txid, index, next_hash, next_amount, tx, extra=NIL, sig=None):
    """The owner inner program's solution, signed over the next state,
    the extra conditions, and the spending transaction's outputs."""
    message = proper_list(next_hash, int_to_atom(next_amount), extra, tx.outputs_hash)
    if sig is None:
        sig = sig_my_outpoint(sk, txid, index, message)
    return proper_list(next_hash, int_to_atom(next_amount), extra, tx.outputs_hash, sig)


def solution(
    amount,
    index,
    child_index,
    parent_tx,
    parent_input,
    parent_vout,
    grandparent,
    inner,
    args,
):
    return proper_list(
        int_to_atom(amount),
        int_to_atom(index),
        int_to_atom(child_index),
        tx_fields(parent_tx),
        int_to_atom(parent_input),
        NIL if parent_vout is None else int_to_atom(parent_vout),
        NIL if grandparent is None else tx_fields(grandparent),
        inner,
        args,
    )


def fee_input(txid=b"\xbb" * 32, amount=50_000, index=0):
    return TxInput(txid, index, FEE_SPK, amount, sequence=SEQ_FINAL)


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
        internal_key=NUMS,
    )


def tx(inputs, outputs):
    return Transaction(
        version=2, locktime=0, inputs=tuple(inputs), outputs=tuple(outputs)
    )


LAUNCHER_TXID = b"\xaa" * 32
LAUNCHER = outpoint(LAUNCHER_TXID, 0)
SINGLETON, ROOT, SPK = lineage(LAUNCHER)
INNER1 = curry(INNER_NODE, [OWNER_PK])
H1 = tree_hash(INNER1)
INNER2 = curry(INNER_NODE, [OWNER2_PK])
H2 = tree_hash(INNER2)
AMOUNT = 10_001

# The launch: a plain wallet transaction spends the launcher coin and
# places the first singleton coin at output 0, beside the state output
# committing the first inner program, the amount, and that index.
LAUNCH = tx(
    [TxInput(LAUNCHER_TXID, 0, FEE_SPK, 100_000, sequence=SEQ_FINAL)],
    [
        TxOutput(SPK, AMOUNT),
        state_output(LAUNCHER, H1, AMOUNT, 0),
        TxOutput(FEE_SPK, 80_000),
    ],
)

# Generation 1: the first coin hands the lineage to the second owner,
# child at output 0 again.
TX1 = tx(
    [singleton_input(SPK, ROOT, LAUNCH.txid, 0, AMOUNT), fee_input()],
    [
        TxOutput(SPK, AMOUNT),
        state_output(LAUNCHER, H2, AMOUNT, 0),
        TxOutput(FEE_SPK, 40_000),
    ],
)
SOL1 = solution(
    AMOUNT, 0, 0, LAUNCH, 0, None, None, INNER1,
    inner_solution(OWNER_SK, LAUNCH.txid, 0, H2, AMOUNT, TX1),
)  # fmt: skip

# Generation 2: the singleton sits at input 1 and its child at output
# 1, and the second owner hands the lineage back.
TX2 = tx(
    [fee_input(b"\xcc" * 32), singleton_input(SPK, ROOT, TX1.txid, 0, AMOUNT)],
    [
        TxOutput(FEE_SPK, 40_000),
        TxOutput(SPK, AMOUNT),
        state_output(LAUNCHER, H1, AMOUNT, 1),
    ],
)
SOL2 = solution(
    AMOUNT, 0, 1, TX1, 0, 0, LAUNCH, INNER2,
    inner_solution(OWNER2_SK, TX1.txid, 0, H1, AMOUNT, TX2),
)  # fmt: skip

# Generation 3 ends the lineage, paying the coin's value out beside
# the ending state output.
PAYOUT = proper_list(proper_list(b"\x01", PAY_SPK, int_to_atom(10_000)))
TX3 = tx(
    [singleton_input(SPK, ROOT, TX2.txid, 1, AMOUNT)],
    [TxOutput(PAY_SPK, 10_000), TxOutput(state_script(LAUNCHER, END_PAYLOAD), 0)],
)
SOL3 = solution(
    AMOUNT, 1, 0, TX2, 1, 0, TX1, INNER1,
    inner_solution(OWNER_SK, TX2.txid, 1, NIL, END_AMOUNT, TX3, PAYOUT),
)  # fmt: skip

# A second lineage, for composition.
OTHER_LAUNCHER = outpoint(b"\xa1" * 32, 1)
OTHER, OTHER_ROOT, OTHER_SPK = lineage(OTHER_LAUNCHER)
OTHER_LAUNCH = tx(
    [TxInput(b"\xa1" * 32, 1, FEE_SPK, 100_000, sequence=SEQ_FINAL)],
    [
        TxOutput(OTHER_SPK, AMOUNT),
        state_output(OTHER_LAUNCHER, H1, AMOUNT, 0),
        TxOutput(FEE_SPK, 80_000),
    ],
)
# Two lineages spent in one transaction, each finding its own child
# and its own tagged state output, both owners sealing the same
# output set.
COMPOSED = tx(
    [
        singleton_input(SPK, ROOT, LAUNCH.txid, 0, AMOUNT),
        singleton_input(OTHER_SPK, OTHER_ROOT, OTHER_LAUNCH.txid, 0, AMOUNT),
        fee_input(),
    ],
    [
        TxOutput(SPK, AMOUNT),
        TxOutput(OTHER_SPK, AMOUNT),
        state_output(LAUNCHER, H2, AMOUNT, 0),
        state_output(OTHER_LAUNCHER, H2, AMOUNT, 1),
        TxOutput(FEE_SPK, 40_000),
    ],
)
COMPOSED_SOL = solution(
    AMOUNT, 0, 0, LAUNCH, 0, None, None, INNER1,
    inner_solution(OWNER_SK, LAUNCH.txid, 0, H2, AMOUNT, COMPOSED),
)  # fmt: skip
OTHER_SOL = solution(
    AMOUNT, 0, 1, OTHER_LAUNCH, 0, None, None, INNER1,
    inner_solution(OWNER_SK, OTHER_LAUNCH.txid, 0, H2, AMOUNT, COMPOSED),
)  # fmt: skip

# Hostile creating transactions. FUNDED pays to the lineage
# scriptPubKey from an ordinary coin with a perfect state output
# beside it. CHAINED does the same from a coin whose own creating
# transaction is real, so only the grandparent's script clause can
# reject it.
FUNDED = tx(
    [TxInput(b"\xee" * 32, 3, FEE_SPK, 100_000, sequence=SEQ_FINAL)],
    [TxOutput(SPK, AMOUNT), state_output(LAUNCHER, H1, AMOUNT, 0)],
)
UNRELATED = tx([fee_input(b"\xed" * 32, 400_000)], [TxOutput(FEE_SPK, 100_000)] * 4)
GRANDPARENT_OF_FEE = tx([fee_input(b"\xdd" * 32, 60_000)], [TxOutput(FEE_SPK, 60_000)])
CHAINED = tx(
    [TxInput(GRANDPARENT_OF_FEE.txid, 0, FEE_SPK, 60_000, sequence=SEQ_FINAL)],
    [TxOutput(SPK, AMOUNT), state_output(LAUNCHER, H1, AMOUNT, 0)],
)
TWO_STATES = tx(
    LAUNCH.inputs, LAUNCH.outputs + (state_output(LAUNCHER, H2, AMOUNT, 0),)
)
# The generation 1 spend re-assembled by an observer: a 1-satoshi
# coin of the observer's own at the committed index, the authorized
# child moved to index 3.
SUBSTITUTED = tx(
    [singleton_input(SPK, ROOT, LAUNCH.txid, 0, AMOUNT), fee_input()],
    [
        TxOutput(SPK, 1),
        state_output(LAUNCHER, H2, AMOUNT, 0),
        TxOutput(FEE_SPK, 40_000),
        TxOutput(SPK, AMOUNT),
    ],
)
# The ending spend re-assembled with a refill: a 1-satoshi coin and a
# second tagged output naming the observer's inner program.
REFILLED = tx(
    [singleton_input(SPK, ROOT, TX2.txid, 1, AMOUNT), fee_input()],
    TX3.outputs + (TxOutput(SPK, 1), state_output(LAUNCHER, H2, 1, 2)),
)


def own_args(sk, parent, index, next_hash, amount, spending, extra=NIL):
    return inner_solution(sk, parent.txid, index, next_hash, amount, spending, extra)


# Spends the owner sealed without the output the wrapper claims, so
# the claim alone fails validation.
CHILD_MISSING = tx(TX1.inputs, (TX1.outputs[1], TxOutput(FEE_SPK, 50_000)))
STATE_MISSING = tx(TX1.inputs, (TX1.outputs[0], TX1.outputs[2]))
END_STATE_MISSING = tx(TX3.inputs, (TX3.outputs[0],))


def first_spend_sealing(spending):
    return solution(
        AMOUNT, 0, 0, LAUNCH, 0, None, None, INNER1,
        own_args(OWNER_SK, LAUNCH, 0, H2, AMOUNT, spending),
    )  # fmt: skip


def ending_spend_sealing(spending):
    return solution(
        AMOUNT, 1, 0, TX2, 1, 0, TX1, INNER1,
        own_args(OWNER_SK, TX2, 1, NIL, END_AMOUNT, spending, PAYOUT),
    )  # fmt: skip


def spend_error(program, sol, spending, input_index=0):
    with pytest.raises(BitLispError) as info:
        run_spend(program, sol, spending, input_index)
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
    # The program's own root reconstruction, read off the taptree
    # assert it emits, must agree with the tooling's tree hash over
    # the curried node, and uncurry must read the values back.
    inner, values = uncurry(SINGLETON)
    assert inner == SINGLETON_NODE
    assert values == [SINGLETON_MOD_HASH, LAUNCHER]
    conds = conditions_of(SINGLETON, SOL1)
    assert conds[0].internal_key == NUMS
    assert conds[0].merkle_root == ROOT


def test_wire_serialization_matches_model():
    # The library's txid over the field shape equals the model's txid
    # at every compact-size boundary the model can reach: script
    # lengths 252, 253, 65535, and 65536, a 253-input list, and a
    # non-empty legacy scriptSig.
    txid_program, _ = compile_program(
        '(program (TX) (include "tx-wire.blib") (txid TX))', INCLUDES
    )
    legacy = TxInput(
        b"\xdd" * 32, 7, FEE_SPK, 9_000, sequence=0x12345678, script_sig=b"\x00" * 5
    )
    samples = [LAUNCH, TX2]
    for width in (252, 253, 65_535, 65_536):
        samples.append(
            Transaction(
                version=1,
                locktime=500_000,
                inputs=(legacy, fee_input()),
                outputs=(
                    TxOutput(b"\x6a" + b"\x55" * (width - 1), 0),
                    TxOutput(FEE_SPK, 59_000),
                ),
            )
        )
    samples.append(
        tx(
            [fee_input(bytes([i]) * 32, 1_000) for i in range(253)],
            [TxOutput(FEE_SPK, 1_000)],
        )
    )
    for sample in samples:
        _, result = run(txid_program, proper_list(tx_fields(sample)), BUDGET)
        assert result == sample.txid


def test_wire_serialization_rejects_empty_lists():
    txid_program, _ = compile_program(
        '(program (TX) (include "tx-wire.blib") (txid TX))', INCLUDES
    )
    fields = tx_fields(LAUNCH)
    no_inputs = proper_list(fields[0], NIL, fields[1][1][0], b"\x00" * 4)
    no_outputs = proper_list(fields[0], fields[1][0], NIL, b"\x00" * 4)
    for bad in (no_inputs, no_outputs):
        assert run_error(txid_program, proper_list(bad)) == "user_raise"


def test_lifecycle():
    _, conds = run_spend(SINGLETON, SOL1, TX1)
    created = [c for c in conds if isinstance(c, CreateOutput)]
    assert [c.script_pubkey for c in created] == [SPK, TX1.outputs[1].script_pubkey]
    assert created[0].amount == AMOUNT
    run_spend(SINGLETON, SOL2, TX2, 1)
    _, conds = run_spend(SINGLETON, SOL3, TX3)
    # The ending spend creates no child: the ending state output in
    # the marker's place, then the payout the inner program asked for.
    created = [c for c in conds if isinstance(c, CreateOutput)]
    assert [c.script_pubkey for c in created] == [TX3.outputs[1].script_pubkey, PAY_SPK]


def test_fee_input_prepended_keeps_spend_valid():
    # Placement is committed by the state output and the owner's
    # seal, never by the input index, so anyone may prepend a fee
    # input to the broadcast spend with the owner's witness unchanged.
    bumped = tx([fee_input(b"\xc9" * 32)] + list(TX1.inputs), TX1.outputs)
    run_spend(SINGLETON, SOL1, bumped, 1)


def test_reordered_outputs_fail_the_owner_seal():
    reordered = tx(TX1.inputs, (TX1.outputs[1], TX1.outputs[0], TX1.outputs[2]))
    assert spend_error(SINGLETON, SOL1, reordered) == "unsatisfied_seal_assert"


def test_funded_coin_without_lineage_is_unspendable():
    # An ordinary payment to the lineage scriptPubKey, with a perfect
    # state output beside it, cannot prove descent: its creating
    # transaction's input is neither the launcher nor a coin at this
    # scriptPubKey, whatever grandparent is offered, including none.
    args = own_args(OWNER_SK, FUNDED, 0, H2, AMOUNT, TX1)
    for vout, grandparent in ((None, None), (3, UNRELATED)):
        sol = solution(AMOUNT, 0, 0, FUNDED, 0, vout, grandparent, INNER1, args)
        assert run_error(SINGLETON, sol) == "user_raise"


def test_grandparent_script_and_index_clauses():
    # A real chain whose grandparent hashes correctly but shows an
    # ordinary script at the parent's index fails on the script
    # clause alone, and a correct grandparent with the wrong output
    # index fails on the index clause alone.
    args = own_args(OWNER_SK, CHAINED, 0, H2, AMOUNT, TX1)
    chained = solution(AMOUNT, 0, 0, CHAINED, 0, 0, GRANDPARENT_OF_FEE, INNER1, args)
    assert run_error(SINGLETON, chained) == "user_raise"
    wrong_vout = solution(
        AMOUNT, 0, 1, TX1, 0, 2, LAUNCH, INNER2,
        own_args(OWNER2_SK, TX1, 0, H1, AMOUNT, TX2),
    )  # fmt: skip
    assert run_error(SINGLETON, wrong_vout) == "user_raise"


def test_parent_must_be_a_lineage_coin():
    # Naming the fee input as the parent fails: its own creating
    # transaction shows no lineage scriptPubKey.
    args = own_args(OWNER2_SK, TX1, 0, H1, AMOUNT, TX2)
    sol = solution(AMOUNT, 0, 1, TX1, 1, 0, LAUNCH, INNER2, args)
    assert run_error(SINGLETON, sol) == "user_raise"


def test_substituted_child_is_dead_and_so_is_the_displaced_one():
    # The state output commits amount and index, so the observer's
    # 1-satoshi coin at the committed index fails on amount, and the
    # authorized coin moved to index 3 fails on index. The owner's
    # seal rejects the re-assembly outright as well.
    assert spend_error(SINGLETON, SOL1, SUBSTITUTED) == "unsatisfied_seal_assert"
    for index, amount in ((0, 1), (3, AMOUNT)):
        sol = solution(
            amount, index, 0, SUBSTITUTED, 0, 0, LAUNCH, INNER2,
            own_args(OWNER2_SK, SUBSTITUTED, index, H1, amount, TX2),
        )  # fmt: skip
        assert run_error(SINGLETON, sol) == "user_raise"


def test_ended_lineage_cannot_be_refilled():
    # An ending spend claims a state output nothing hashes to. An
    # observer's refill adds a coin and a second tagged output, which
    # the owner's seal rejects, and the refilled coin itself finds two
    # tagged outputs and dies.
    assert spend_error(SINGLETON, SOL3, REFILLED) == "unsatisfied_seal_assert"
    refill = solution(
        1, 2, 0, REFILLED, 0, 0, TX1, INNER2,
        own_args(OWNER2_SK, REFILLED, 2, H1, 1, TX2),
    )  # fmt: skip
    assert run_error(SINGLETON, refill) == "user_raise"


def test_wrong_outpoint_fails_in_validator():
    wrong = tx(
        [singleton_input(SPK, ROOT, TX1.txid, 2, AMOUNT), fee_input()], TX2.outputs
    )
    assert spend_error(SINGLETON, SOL2, wrong) == "unsatisfied_outpoint_assert"


def test_state_must_match_committed_inner():
    # Supplying an inner program the state output does not commit
    # raises, and so does a creating transaction with two tagged
    # state outputs, which would let its assembler offer two states.
    uncommitted = solution(
        AMOUNT, 0, 0, LAUNCH, 0, None, None, INNER2,
        own_args(OWNER2_SK, LAUNCH, 0, H2, AMOUNT, TX1),
    )  # fmt: skip
    assert run_error(SINGLETON, uncommitted) == "user_raise"
    two_states = solution(
        AMOUNT, 0, 0, TWO_STATES, 0, None, None, INNER1,
        own_args(OWNER_SK, TWO_STATES, 0, H2, AMOUNT, TX1),
    )  # fmt: skip
    assert run_error(SINGLETON, two_states) == "user_raise"


def first_spend_with(extra, next_amount=AMOUNT):
    return solution(
        AMOUNT, 0, 0, LAUNCH, 0, None, None, INNER1,
        own_args(OWNER_SK, LAUNCH, 0, H2, next_amount, TX1, extra),
    )  # fmt: skip


SECOND_ODD = proper_list(proper_list(b"\x01", FEE_SPK, int_to_atom(3)))
ODD_TAPROOT = proper_list(proper_list(b"\x02", NUMS, ROOT, int_to_atom(3)))


def test_morph_requires_exactly_one_odd_output():
    # No odd output, a second odd CREATE_OUTPUT, and an odd
    # CREATE_OUTPUT_TAPROOT at the lineage root all raise: a spend
    # creates one odd coin and no more.
    assert run_error(SINGLETON, first_spend_with(NIL, 10_000)) == "user_raise"
    assert run_error(SINGLETON, first_spend_with(SECOND_ODD)) == "user_raise"
    assert run_error(SINGLETON, first_spend_with(ODD_TAPROOT)) == "user_raise"


def test_even_amount_raises():
    sol = solution(
        10_000, 0, 0, LAUNCH, 0, None, None, INNER1,
        own_args(OWNER_SK, LAUNCH, 0, H2, 10_000, TX1),
    )  # fmt: skip
    assert run_error(SINGLETON, sol) == "user_raise"


TRUNCATED_VERSION = proper_list(
    b"\x02\x00\x00", tx_fields(LAUNCH)[1][0], tx_fields(LAUNCH)[1][1][0], b"\x00" * 4
)
MALFORMED = curry(SINGLETON_NODE, [SINGLETON_MOD_HASH, LAUNCHER[:35]])


def truncated_solution():
    items = list(iter_proper_list(SOL1))
    items[3] = TRUNCATED_VERSION
    return proper_list(*items)


def test_malformed_instance_and_fields_raise():
    assert run_error(MALFORMED, SOL1) == "user_raise"
    assert run_error(SINGLETON, truncated_solution()) == "user_raise"


def test_owner_signature_binds_outpoint_and_message():
    # The generation 1 authorization replayed on a later coin whose
    # committed state is the same inner program fails on the outpoint
    # binding, and the captured signature under a rewritten next state
    # fails on the message binding.
    args1 = list(iter_proper_list(SOL1))[8]
    committed = tx(
        TX1.inputs,
        (TX1.outputs[0], state_output(LAUNCHER, H1, AMOUNT, 0), TX1.outputs[2]),
    )
    later = tx(
        [singleton_input(SPK, ROOT, committed.txid, 0, AMOUNT), fee_input()],
        TX1.outputs,
    )
    replayed = solution(AMOUNT, 0, 0, committed, 0, 0, LAUNCH, INNER1, args1)
    assert spend_error(SINGLETON, replayed, later) == "unsatisfied_sig_assert"
    captured = list(iter_proper_list(args1))[4]
    rewritten = inner_solution(
        OWNER_SK, LAUNCH.txid, 0, H1, AMOUNT, committed, sig=captured
    )
    sol = solution(AMOUNT, 0, 0, LAUNCH, 0, None, None, INNER1, rewritten)
    assert spend_error(SINGLETON, sol, committed) == "unsatisfied_sig_assert"


def test_two_lineages_compose():
    other_conds = conditions_of(OTHER, OTHER_SOL)
    with_other = tx(
        [
            COMPOSED.inputs[0],
            singleton_input(
                OTHER_SPK, OTHER_ROOT, OTHER_LAUNCH.txid, 0, AMOUNT, other_conds
            ),
            COMPOSED.inputs[2],
        ],
        COMPOSED.outputs,
    )
    run_spend(SINGLETON, COMPOSED_SOL, with_other, 0)
    # Each child reads its own committed index: the other lineage's
    # at output 1, with its parent at input 1.
    next_sol = solution(
        AMOUNT, 1, 0, with_other, 1, 0, OTHER_LAUNCH, INNER2,
        own_args(OWNER2_SK, with_other, 1, H1, AMOUNT, TX2),
    )  # fmt: skip
    conds = conditions_of(OTHER, next_sol)
    assert conds[2].outpoint == outpoint(with_other.txid, 1)


def vm_cases():
    """Every pinned program and solution, by case name, built from
    the sources and the lifecycle above."""
    funded = own_args(OWNER_SK, FUNDED, 0, H2, AMOUNT, TX1)
    chained = own_args(OWNER_SK, CHAINED, 0, H2, AMOUNT, TX1)
    second = own_args(OWNER2_SK, TX1, 0, H1, AMOUNT, TX2)
    return {
        "first_spend": (SINGLETON, SOL1),
        "second_generation_at_input_one": (SINGLETON, SOL2),
        "lineage_ends": (SINGLETON, SOL3),
        "second_lineage_composed": (OTHER, OTHER_SOL),
        "funded_coin_no_grandparent": (
            SINGLETON,
            solution(AMOUNT, 0, 0, FUNDED, 0, None, None, INNER1, funded),
        ),
        "funded_coin_wrong_grandparent": (
            SINGLETON,
            solution(AMOUNT, 0, 0, FUNDED, 0, 3, UNRELATED, INNER1, funded),
        ),
        "grandparent_shows_ordinary_script": (
            SINGLETON,
            solution(AMOUNT, 0, 0, CHAINED, 0, 0, GRANDPARENT_OF_FEE, INNER1, chained),
        ),
        "grandparent_index_mismatch": (
            SINGLETON,
            solution(AMOUNT, 0, 1, TX1, 0, 2, LAUNCH, INNER2, second),
        ),
        "parent_is_fee_input": (
            SINGLETON,
            solution(AMOUNT, 0, 1, TX1, 1, 0, LAUNCH, INNER2, second),
        ),
        "substituted_child_amount_mismatch": (
            SINGLETON,
            solution(
                1,
                0,
                0,
                SUBSTITUTED,
                0,
                0,
                LAUNCH,
                INNER2,
                own_args(OWNER2_SK, SUBSTITUTED, 0, H1, 1, TX2),
            ),  # fmt: skip
        ),
        "displaced_child_index_mismatch": (
            SINGLETON,
            solution(
                AMOUNT,
                3,
                0,
                SUBSTITUTED,
                0,
                0,
                LAUNCH,
                INNER2,
                own_args(OWNER2_SK, SUBSTITUTED, 3, H1, AMOUNT, TX2),
            ),  # fmt: skip
        ),
        "ended_lineage_refill": (
            SINGLETON,
            solution(
                1,
                2,
                0,
                REFILLED,
                0,
                0,
                TX1,
                INNER2,
                own_args(OWNER2_SK, REFILLED, 2, H1, 1, TX2),
            ),  # fmt: skip
        ),
        "uncommitted_inner_program": (
            SINGLETON,
            solution(
                AMOUNT,
                0,
                0,
                LAUNCH,
                0,
                None,
                None,
                INNER2,
                own_args(OWNER2_SK, LAUNCH, 0, H2, AMOUNT, TX1),
            ),  # fmt: skip
        ),
        "two_state_outputs": (
            SINGLETON,
            solution(
                AMOUNT,
                0,
                0,
                TWO_STATES,
                0,
                None,
                None,
                INNER1,
                own_args(OWNER_SK, TWO_STATES, 0, H2, AMOUNT, TX1),
            ),  # fmt: skip
        ),
        "inner_creates_no_odd_output": (SINGLETON, first_spend_with(NIL, 10_000)),
        "inner_creates_two_odd_outputs": (SINGLETON, first_spend_with(SECOND_ODD)),
        "inner_creates_odd_taproot_output": (SINGLETON, first_spend_with(ODD_TAPROOT)),
        "even_amount": (
            SINGLETON,
            solution(
                10_000,
                0,
                0,
                LAUNCH,
                0,
                None,
                None,
                INNER1,
                own_args(OWNER_SK, LAUNCH, 0, H2, 10_000, TX1),
            ),  # fmt: skip
        ),
        "malformed_launcher_outpoint_unspendable": (MALFORMED, SOL1),
        "truncated_version_field": (SINGLETON, truncated_solution()),
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
    sig = list(iter_proper_list(list(iter_proper_list(SOL1))[8]))[4]
    flipped = bytes([sig[0] ^ 0x01]) + sig[1:]
    return {
        first,
        first.replace(sig.hex(), flipped.hex()),
        emitted_hex(SINGLETON, SOL2),
        emitted_hex(SINGLETON, SOL3),
        emitted_hex(SINGLETON, COMPOSED_SOL),
        emitted_hex(OTHER, OTHER_SOL),
        emitted_hex(SINGLETON, first_spend_sealing(CHILD_MISSING)),
        emitted_hex(SINGLETON, first_spend_sealing(STATE_MISSING)),
        emitted_hex(SINGLETON, ending_spend_sealing(END_STATE_MISSING)),
    }


def test_validation_vectors_match_source():
    # The complete closure: every conditions field in the validation
    # vector file is recomputed here from compiled source and the
    # documented signature flip, set-equal in both directions.
    files = [load_vector("validation/singleton-lineage.json")]
    observed = {entry["conditions"] for _, entry in condition_inputs(files)}
    assert observed == validation_conditions()


def test_validation_vector_identities_derive_their_scripts():
    # The corpus carries each lineage input's execution identity as
    # data the model takes on trust, so this is where the trust is
    # checked, by the shared audit. No input in this file carries
    # filler.
    assert_corpus_identities(
        [load_vector("validation/singleton-lineage.json")],
        NUMS,
        filler_expected=0,
    )
