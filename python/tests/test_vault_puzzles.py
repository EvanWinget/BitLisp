"""Compile-and-run coverage for the vault benchmark puzzles.

The two programs compile from source here, so these tests hold the
source-to-bytes link: the mod tree hashes are pinned as literals, the
in-program curried-hash reconstruction is checked against the curry
tooling's own hash, every spend path runs through the single-spend
runner against model transactions, every failure mode asserts its
exact error code live, and the pinned vector files are recomputed
from source so puzzle source and corpus cannot drift apart silently.
Signatures come from the vendored Bitcoin Core framework signer with
fixed aux bytes, so every derived value is deterministic.
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
from bitlisp.conditions import parse_conditions  # noqa: E402
from bitlisp.sexp import int_to_atom  # noqa: E402
from bitlisp_tools import assemble  # noqa: E402
from bitlisp_tools.compiler import compile_program, tree_hash  # noqa: E402
from bitlisp_tools.curry import curry, uncurry  # noqa: E402
from bitlisp_tools.runner import run_spend  # noqa: E402
from test_framework.key import compute_xonly_pubkey, sign_schnorr  # noqa: E402

PUZZLES = REPO_ROOT / "puzzles"
INCLUDES = (PUZZLES / "lib", PUZZLES / "vault")
BUDGET = 11_000_000_000
SEQ_FINAL = 0xFFFFFFFF

# The BIP341 nothing-up-my-sleeve point: no key-path spend exists.
NUMS = bytes.fromhex(
    "50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0"
)
AUTH_SK = (0xA0 << 248 | 7).to_bytes(32, "big")
AUTH_PK = compute_xonly_pubkey(AUTH_SK)[0]
RKEY_SK = (0xB0 << 248 | 9).to_bytes(32, "big")
RKEY_PK = compute_xonly_pubkey(RKEY_SK)[0]
RECOVERY_SPK = bytes.fromhex("0014") + b"\x99" * 20
FEE_SPK = bytes.fromhex("0014") + b"\x11" * 20
DELAY = 144
AUX = b"\x00" * 32

# Drift guards: recompiling the sources must reproduce these hashes,
# so any source change is a deliberate re-pin of both literals and
# the vector files.
VAULT_MOD_HASH = bytes.fromhex(
    "c5c5c72807c36371c15fc58c34d2a5181db8856bd5045dc44d91ba0e6db4be63"
)
TRIG_MOD_HASH = bytes.fromhex(
    "250cdfb910709b360f5ebb37102a2fe42fb42287edc66eff7dffe7f5a183f6cc"
)

VAULT_NODE, _ = compile_program(
    (PUZZLES / "vault" / "vault.bl").read_text(), INCLUDES
)
TRIG_NODE, _ = compile_program(
    (PUZZLES / "vault" / "triggered.bl").read_text(), INCLUDES
)


def instance(node, values):
    """A curried instance, its merkle root, and its scriptPubKey."""
    inst = curry(node, values)
    root = tree_hash(inst)
    return inst, root, b"\x51\x20" + secp256k1.taproot_output_key(NUMS, root)


def vault_values(recovery_key):
    return [
        VAULT_MOD_HASH,
        TRIG_MOD_HASH,
        AUTH_PK,
        NUMS,
        RECOVERY_SPK,
        recovery_key,
        int_to_atom(DELAY),
    ]


def trig_values(recovery_key, target):
    return [
        TRIG_MOD_HASH,
        NUMS,
        RECOVERY_SPK,
        recovery_key,
        int_to_atom(DELAY),
        target,
    ]


VAULT, VROOT, VSPK = instance(VAULT_NODE, vault_values(b""))
KVAULT, KVROOT, KVSPK = instance(VAULT_NODE, vault_values(RKEY_PK))
TARGET = b"\x77" * 32
TRIG, TROOT, TSPK = instance(TRIG_NODE, trig_values(b"", TARGET))

TXID = b"\xaa" * 32
FEE_TXID = b"\xbb" * 32


def sig_my_outpoint(sk, txid, index, message_node):
    tag = hashlib.sha256(b"BitLisp/sig/my_outpoint").digest()
    outpoint = txid + index.to_bytes(4, "little")
    digest = hashlib.sha256(tag + tag + outpoint + tree_hash(message_node)).digest()
    return sign_schnorr(sk, digest, AUX)


def trigger_solution(sk, txid, index, target, trig_amt, revault_amt, my_amt):
    msg = assemble(f"(0x{target.hex()} {trig_amt} {revault_amt})")
    sig = sig_my_outpoint(sk, txid, index, msg)
    return assemble(
        f"(1 0x{target.hex()} {trig_amt} {revault_amt} {my_amt} 0x{sig.hex()})"
    )


def fee_input(amount=20_000):
    return TxInput(FEE_TXID, 0, FEE_SPK, amount, sequence=SEQ_FINAL)


def spend_error(program, solution, tx, input_index=0):
    with pytest.raises(BitLispError) as info:
        run_spend(program, solution, tx, input_index)
    return info.value.code


def conditions_of(program, solution_text):
    _, result = run(program, assemble(solution_text), BUDGET)
    _, conds = parse_conditions(result, None)
    return conds


def test_mod_hashes_pinned():
    assert tree_hash(VAULT_NODE) == VAULT_MOD_HASH
    assert tree_hash(TRIG_NODE) == TRIG_MOD_HASH


def test_curried_identity_matches_tooling():
    # The program's own reconstruction, read off the taproot assert,
    # must equal the hash the curry tooling computes for the same
    # instance, and uncurry must read the fixed values back.
    for inst, root, values in (
        (VAULT, VROOT, vault_values(b"")),
        (TRIG, TROOT, trig_values(b"", TARGET)),
    ):
        assert tree_hash(inst) == root
        inner, read_back = uncurry(inst)
        assert read_back == values
    conds = conditions_of(VAULT, f"(3 0x{VSPK.hex()})")
    assert conds[0].merkle_root == VROOT
    assert conds[0].script_pubkey == VSPK


def test_trigger_spend_with_revault():
    solution = trigger_solution(AUTH_SK, TXID, 0, TARGET, 40_000, 20_000, 60_000)
    tx = Transaction(
        version=2,
        locktime=0,
        inputs=(
            TxInput(TXID, 0, VSPK, 60_000, sequence=SEQ_FINAL),
            fee_input(),
        ),
        outputs=(TxOutput(TSPK, 40_000), TxOutput(VSPK, 20_000)),
    )
    _, conds = run_spend(VAULT, solution, tx)
    # The revault claim re-encumbers under the byte-exact vault
    # scriptPubKey.
    assert conds[-1].script_pubkey == VSPK


def test_trigger_value_shortfall_raises():
    solution = trigger_solution(AUTH_SK, TXID, 0, TARGET, 30_000, 0, 60_000)
    with pytest.raises(BitLispError) as info:
        run(VAULT, solution, BUDGET)
    assert info.value.code == "user_raise"


def solution_items(node):
    while node != b"":
        yield node[0]
        node = node[1]


def test_trigger_signature_binds_target():
    # An attacker redirects the trigger to a different target and
    # supplies the matching output, so the output claim passes and
    # only the signature's message binding stops the redirect.
    solution = trigger_solution(AUTH_SK, TXID, 0, TARGET, 60_000, 0, 60_000)
    other_target = b"\x66" * 32
    _, _, other_tspk = instance(TRIG_NODE, trig_values(b"", other_target))
    items = list(solution_items(solution))
    redirected = assemble(
        f"(1 0x{other_target.hex()} 60000 0 60000 0x{items[5].hex()})"
    )
    tx = Transaction(
        version=2,
        locktime=0,
        inputs=(
            TxInput(TXID, 0, VSPK, 60_000, sequence=SEQ_FINAL),
            fee_input(),
        ),
        outputs=(TxOutput(other_tspk, 60_000),),
    )
    assert spend_error(VAULT, redirected, tx) == "unsatisfied_sig_assert"


def test_trigger_signature_binds_outpoint():
    # The same authorization replayed onto a sibling coin of the
    # same instance fails: the digest binds the consumed outpoint.
    solution = trigger_solution(AUTH_SK, TXID, 0, TARGET, 60_000, 0, 60_000)
    tx = Transaction(
        version=2,
        locktime=0,
        inputs=(
            TxInput(b"\xcd" * 32, 0, VSPK, 60_000, sequence=SEQ_FINAL),
            fee_input(),
        ),
        outputs=(TxOutput(TSPK, 60_000),),
    )
    assert spend_error(VAULT, solution, tx) == "unsatisfied_sig_assert"


def test_full_lifecycle():
    # Vault coin -> trigger -> matured withdrawal, outpoints taken
    # from each real transaction's txid.
    vault_tx = Transaction(
        version=2,
        locktime=0,
        inputs=(fee_input(200_000),),
        outputs=(TxOutput(VSPK, 100_000),),
    )
    vault_outpoint = (vault_tx.txid, 0)

    withdrawal_out = TxOutput(bytes.fromhex("0014") + b"\x22" * 20, 99_000)
    probe = Transaction(
        version=2,
        locktime=0,
        inputs=(fee_input(200_000),),
        outputs=(withdrawal_out,),
    )
    real_target = probe.outputs_hash
    trig_inst, _, trig_spk = instance(TRIG_NODE, trig_values(b"", real_target))

    solution = trigger_solution(
        AUTH_SK, vault_outpoint[0], 0, real_target, 100_000, 0, 100_000
    )
    trigger_tx = Transaction(
        version=2,
        locktime=0,
        inputs=(
            TxInput(*vault_outpoint, VSPK, 100_000, sequence=SEQ_FINAL),
            fee_input(),
        ),
        outputs=(TxOutput(trig_spk, 100_000),),
    )
    run_spend(VAULT, solution, trigger_tx)

    def withdrawal(sequence):
        return Transaction(
            version=2,
            locktime=0,
            inputs=(
                TxInput(trigger_tx.txid, 0, trig_spk, 100_000, sequence=sequence),
            ),
            outputs=(withdrawal_out,),
        )

    run_spend(trig_inst, assemble("(1)"), withdrawal(DELAY))
    assert (
        spend_error(trig_inst, assemble("(1)"), withdrawal(DELAY - 1))
        == "unsatisfied_sequence_assert"
    )

    # The seal leaves the input side open, so a fee input can be
    # added, but any grafted output invalidates the withdrawal.
    matured = withdrawal(DELAY)
    with_fee = Transaction(
        version=2,
        locktime=0,
        inputs=matured.inputs + (fee_input(),),
        outputs=matured.outputs,
    )
    run_spend(trig_inst, assemble("(1)"), with_fee)
    grafted = Transaction(
        version=2,
        locktime=0,
        inputs=with_fee.inputs,
        outputs=matured.outputs + (TxOutput(FEE_SPK, 10_000),),
    )
    assert (
        spend_error(trig_inst, assemble("(1)"), grafted)
        == "unsatisfied_seal_assert"
    )

    # Recovery works from both states at any time.
    recovery_from_vault = Transaction(
        version=2,
        locktime=0,
        inputs=(
            TxInput(*vault_outpoint, VSPK, 100_000, sequence=SEQ_FINAL),
            fee_input(),
        ),
        outputs=(TxOutput(RECOVERY_SPK, 100_000),),
    )
    run_spend(VAULT, assemble("(2 100000 100000)"), recovery_from_vault)
    recovery_from_triggered = Transaction(
        version=2,
        locktime=0,
        inputs=(
            TxInput(trigger_tx.txid, 0, trig_spk, 100_000, sequence=SEQ_FINAL),
            fee_input(),
        ),
        outputs=(TxOutput(RECOVERY_SPK, 100_000),),
    )
    run_spend(trig_inst, assemble("(2 100000 100000)"), recovery_from_triggered)


def keyed_recovery_solution(txid, my_amt, recover_amt, sig=None):
    if sig is None:
        msg = assemble(f"({my_amt} {recover_amt})")
        sig = sig_my_outpoint(RKEY_SK, txid, 0, msg)
    return assemble(f"(2 {my_amt} {recover_amt} 0x{sig.hex()})")


def keyed_recovery_tx():
    return Transaction(
        version=2,
        locktime=0,
        inputs=(
            TxInput(TXID, 0, KVSPK, 60_000, sequence=SEQ_FINAL),
            fee_input(),
        ),
        outputs=(TxOutput(RECOVERY_SPK, 60_000),),
    )


def test_keyed_recovery():
    run_spend(KVAULT, keyed_recovery_solution(TXID, 60_000, 60_000), keyed_recovery_tx())
    # A wrong key's signature fails, and a solution missing the
    # signature dies in the VM reaching for it.
    wrong = sig_my_outpoint(AUTH_SK, TXID, 0, assemble("(60000 60000)"))
    assert (
        spend_error(
            KVAULT,
            keyed_recovery_solution(TXID, 60_000, 60_000, sig=wrong),
            keyed_recovery_tx(),
        )
        == "unsatisfied_sig_assert"
    )
    with pytest.raises(BitLispError) as info:
        run(KVAULT, assemble("(2 60000 60000)"), BUDGET)
    assert info.value.code == "arg_not_pair"


def test_recovery_cannot_underpay():
    with pytest.raises(BitLispError) as info:
        run(VAULT, assemble("(2 60000 59999)"), BUDGET)
    assert info.value.code == "user_raise"
    underfunded = Transaction(
        version=2,
        locktime=0,
        inputs=(
            TxInput(TXID, 0, VSPK, 60_000, sequence=SEQ_FINAL),
            fee_input(),
        ),
        outputs=(TxOutput(RECOVERY_SPK, 59_999),),
    )
    assert (
        spend_error(VAULT, assemble("(2 60000 60000)"), underfunded)
        == "unsatisfied_output_claim"
    )


def follower_conditions():
    return conditions_of(VAULT, f"(3 0x{VSPK.hex()})")


def consolidation_tx(listed, out_amt, followers=(50_000, 30_000)):
    listed_text = " ".join(str(a) for a in listed)
    solution = assemble(f"(4 0x{VSPK.hex()} 60000 {out_amt} ({listed_text}))")
    inputs = [TxInput(b"\xd0" * 32, 0, VSPK, 60_000, sequence=SEQ_FINAL)]
    for i, amount in enumerate(followers):
        inputs.append(
            TxInput(
                bytes([0xD1 + i]) * 32,
                0,
                VSPK,
                amount,
                sequence=SEQ_FINAL,
                conditions=follower_conditions(),
            )
        )
    inputs.append(fee_input(50_000))
    tx = Transaction(
        version=2,
        locktime=0,
        inputs=tuple(inputs),
        outputs=(TxOutput(VSPK, out_amt),),
    )
    return solution, tx


def test_consolidation_three_coins():
    solution, tx = consolidation_tx((50_000, 30_000), 140_000)
    run_spend(VAULT, solution, tx)


def test_consolidation_omitted_follower():
    solution, tx = consolidation_tx((50_000,), 110_000)
    assert spend_error(VAULT, solution, tx) == "unbalanced_message"


def test_consolidation_rejects_empty_follower_list():
    # A leader alone is not a consolidation: every consolidation
    # merges at least two coins, so conflicting consolidations still
    # shrink the coin set at this scriptPubKey.
    with pytest.raises(BitLispError) as info:
        run(VAULT, assemble(f"(4 0x{VSPK.hex()} 60000 60000 ())"), BUDGET)
    assert info.value.code == "user_raise"


def test_consolidation_rejects_negative_listed_amount():
    # A negative listed amount would deflate the in-program sum, so
    # the specifier's amount domain must close the hole at parse
    # time before the ledger runs.
    solution, tx = consolidation_tx((50_000, -1), 110_000)
    assert spend_error(VAULT, solution, tx) == "bad_condition_arg"


def test_consolidation_output_cannot_underpay():
    with pytest.raises(BitLispError) as info:
        run(VAULT, assemble(f"(4 0x{VSPK.hex()} 60000 139999 (50000 30000))"), BUDGET)
    assert info.value.code == "user_raise"


def test_unknown_path_raises():
    with pytest.raises(BitLispError) as info:
        run(VAULT, assemble("(9)"), BUDGET)
    assert info.value.code == "user_raise"


def load_vector(name):
    path = REPO_ROOT / "vectors" / name
    return {case["name"]: case for case in json.loads(path.read_text())["cases"]}


def test_vm_vectors_match_source():
    # Every pinned program is byte-identical to a fresh compile and
    # curry of the sources, so the corpus cannot drift from them.
    cases = load_vector("vm/vault-programs.json")
    by_program = {
        "vault_trigger_no_revault": VAULT,
        "vault_trigger_with_revault": VAULT,
        "vault_recover_keyless": VAULT,
        "vault_recover_keyed": KVAULT,
        "vault_follow": VAULT,
        "vault_lead_two_followers": VAULT,
        "triggered_withdraw": TRIG,
        "triggered_recover": TRIG,
        "vault_trigger_value_shortfall": VAULT,
        "vault_lead_no_followers": VAULT,
        "vault_unknown_path": VAULT,
    }
    assert set(cases) == set(by_program)
    for name, node in by_program.items():
        assert cases[name]["program"] == serialize(node).hex(), name


def test_validation_vectors_match_source():
    # Every condition list that a vector attributes to a vault
    # program run is byte-identical to what the compiled source
    # emits for that case's documented solution.
    core = load_vector("validation/vault-core.json")
    trig_nr = trigger_solution(AUTH_SK, TXID, 0, TARGET, 60_000, 0, 60_000)
    _, result = run(VAULT, trig_nr, BUDGET)
    assert core["trigger_valid"]["tx"]["inputs"][0]["conditions"] == (
        serialize(result).hex()
    )
    _, result = run(VAULT, assemble("(2 60000 60000)"), BUDGET)
    assert core["recover_from_vault_keyless_valid"]["tx"]["inputs"][0][
        "conditions"
    ] == serialize(result).hex()
    consolidation = load_vector("validation/vault-consolidation.json")
    follower_hex = serialize(run(VAULT, assemble(f"(3 0x{VSPK.hex()})"), BUDGET)[1]).hex()
    valid = consolidation["consolidate_two_followers_valid"]["tx"]["inputs"]
    assert valid[1]["conditions"] == follower_hex
    assert valid[2]["conditions"] == follower_hex
