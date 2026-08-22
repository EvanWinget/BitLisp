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
from bitlisp.sexp import int_to_atom, iter_proper_list  # noqa: E402
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
NUMS = bytes.fromhex("50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0")
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
    "2fc2096c3167018bc0210e061d4add87f081360a77ec352bcfb1456243ca34a2"
)
TRIG_MOD_HASH = bytes.fromhex(
    "214b0347c7df10d8d7c95769dd4cc3e0fdcee183b281b3d96ebda71bb739ec1b"
)

VAULT_NODE, _ = compile_program((PUZZLES / "vault" / "vault.bl").read_text(), INCLUDES)
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
    msg = assemble(f"(1 0x{target.hex()} {trig_amt} {revault_amt})")
    sig = sig_my_outpoint(sk, txid, index, msg)
    return assemble(
        f"(1 0x{target.hex()} {trig_amt} {revault_amt} {my_amt} 0x{sig.hex()})"
    )


def fee_input(amount=20_000):
    return TxInput(FEE_TXID, 0, FEE_SPK, amount, sequence=SEQ_FINAL)


def bl_input(txid, index, spk, amount, root, sequence=SEQ_FINAL, conditions=None):
    """A BitLisp input of a single-leaf taproot tree, where the
    executing leaf's hash is also the spending path's merkle root."""
    return TxInput(
        txid,
        index,
        spk,
        amount,
        sequence=sequence,
        conditions=conditions,
        tapleaf=root,
        merkle_root=root,
        internal_key=NUMS,
    )


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


def _h_atom(data):
    return hashlib.sha256(b"\x01" + data).digest()


def _h_pair(left, right):
    return hashlib.sha256(b"\x02" + left + right).digest()


def spec_curried_root(mod_hash, values):
    """The curried instance's tree hash from the spec's two hash
    rules alone, independent of tree_hash and of the puzzle helpers:
    the curried shape is (a (q . F) (c (q . v1) ... 1)) with apply
    the atom 2, quote and the chain terminator the atom 1, and cons
    the atom 4. All curried values here are atoms."""
    chain = _h_atom(b"\x01")
    for value in reversed(values):
        quoted = _h_pair(_h_atom(b"\x01"), _h_atom(value))
        chain = _h_pair(_h_atom(b"\x04"), _h_pair(quoted, _h_pair(chain, _h_atom(b""))))
    program = _h_pair(_h_atom(b"\x01"), mod_hash)
    return _h_pair(_h_atom(b"\x02"), _h_pair(program, _h_pair(chain, _h_atom(b""))))


def test_curried_identity_matches_tooling():
    # Three independent computations of each instance's identity
    # must agree: the tooling's tree_hash over the curried node, the
    # spec-rule reimplementation above, and the program's own
    # reconstruction read off the taproot assert it emits. uncurry
    # must also read back the inner program and the fixed values.
    for node, inst, root, values in (
        (VAULT_NODE, VAULT, VROOT, vault_values(b"")),
        (TRIG_NODE, TRIG, TROOT, trig_values(b"", TARGET)),
    ):
        mod_hash = values[0]
        assert spec_curried_root(mod_hash, values) == root
        inner, read_back = uncurry(inst)
        assert inner == node
        assert read_back == values
    conds = conditions_of(VAULT, f"(3 0x{VSPK.hex()})")
    assert conds[0].merkle_root == VROOT
    assert conds[0].script_pubkey == VSPK


def test_trigger_spend_with_revault():
    solution = trigger_solution(AUTH_SK, TXID, 0, TARGET, 40_000, 20_000, 60_000)
    tx = Transaction(
        version=2,
        locktime=0,
        inputs=(bl_input(TXID, 0, VSPK, 60_000, VROOT), fee_input()),
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


def path_raises(program, solution):
    if isinstance(solution, str):
        solution = assemble(solution)
    with pytest.raises(BitLispError) as info:
        run(program, solution, BUDGET)
    return info.value.code


def test_trigger_amount_guards():
    # A misbehaving signer still cannot mint an oversized triggered
    # coin through a negative revault amount or a worthless one
    # through a zero trigger amount, and a malformed target is
    # rejected before it becomes an unwithdrawable coin.
    for trig_amt, revault_amt in ((60_001, -1), (0, 60_000)):
        solution = trigger_solution(
            AUTH_SK, TXID, 0, TARGET, trig_amt, revault_amt, 60_000
        )
        assert path_raises(VAULT, solution) == "user_raise"
    short_target = trigger_solution(AUTH_SK, TXID, 0, b"\x77" * 31, 60_000, 0, 60_000)
    assert path_raises(VAULT, short_target) == "user_raise"


def test_malformed_instance_fails_every_path():
    # A fixed value outside its domain would break one path at spend
    # time while the others kept working, so every path rejects the
    # instance up front, on whichever spend is tried first.
    bad_instances = (
        instance(VAULT_NODE, vault_values(b"\x02" + RKEY_PK))[0],
        instance(
            VAULT_NODE,
            [
                VAULT_MOD_HASH,
                TRIG_MOD_HASH,
                b"\x02" + AUTH_PK,
                NUMS,
                RECOVERY_SPK,
                b"",
                int_to_atom(DELAY),
            ],
        )[0],
    )
    solutions = (
        f"(3 0x{VSPK.hex()})",
        "(2 60000 60000)",
        f"(4 0x{VSPK.hex()} 60000 120000 (60000))",
    )
    for bad in bad_instances:
        for solution in solutions:
            assert path_raises(bad, solution) == "user_raise"
    overlong_delay = instance(
        VAULT_NODE,
        [
            VAULT_MOD_HASH,
            TRIG_MOD_HASH,
            AUTH_PK,
            NUMS,
            RECOVERY_SPK,
            b"",
            int_to_atom(65_536),
        ],
    )[0]
    assert path_raises(overlong_delay, f"(3 0x{VSPK.hex()})") == "user_raise"
    nil_recovery_spk = instance(
        VAULT_NODE,
        [
            VAULT_MOD_HASH,
            TRIG_MOD_HASH,
            AUTH_PK,
            NUMS,
            b"",
            b"",
            int_to_atom(DELAY),
        ],
    )[0]
    for solution in solutions:
        assert path_raises(nil_recovery_spk, solution) == "user_raise"
    padded_delay = instance(
        VAULT_NODE,
        [
            VAULT_MOD_HASH,
            TRIG_MOD_HASH,
            AUTH_PK,
            NUMS,
            RECOVERY_SPK,
            b"",
            b"\x00\x00\x90",
        ],
    )[0]
    assert path_raises(padded_delay, f"(3 0x{VSPK.hex()})") == "user_raise"
    bad_triggered = instance(
        TRIG_NODE,
        [
            TRIG_MOD_HASH,
            NUMS,
            RECOVERY_SPK,
            b"\x02" + RKEY_PK,
            int_to_atom(DELAY),
            TARGET,
        ],
    )[0]
    assert path_raises(bad_triggered, "(1)") == "user_raise"


def test_trigger_signature_binds_target():
    # An attacker redirects the trigger to a different target and
    # supplies the matching output, so the output claim passes and
    # only the signature's message binding stops the redirect.
    solution = trigger_solution(AUTH_SK, TXID, 0, TARGET, 60_000, 0, 60_000)
    other_target = b"\x66" * 32
    _, _, other_tspk = instance(TRIG_NODE, trig_values(b"", other_target))
    items = list(iter_proper_list(solution))
    redirected = assemble(
        f"(1 0x{other_target.hex()} 60000 0 60000 0x{items[5].hex()})"
    )
    tx = Transaction(
        version=2,
        locktime=0,
        inputs=(bl_input(TXID, 0, VSPK, 60_000, VROOT), fee_input()),
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
        inputs=(bl_input(b"\xcd" * 32, 0, VSPK, 60_000, VROOT), fee_input()),
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
    trig_inst, trig_root, trig_spk = instance(TRIG_NODE, trig_values(b"", real_target))

    solution = trigger_solution(
        AUTH_SK, vault_outpoint[0], 0, real_target, 100_000, 0, 100_000
    )
    trigger_tx = Transaction(
        version=2,
        locktime=0,
        inputs=(bl_input(*vault_outpoint, VSPK, 100_000, VROOT), fee_input()),
        outputs=(TxOutput(trig_spk, 100_000),),
    )
    run_spend(VAULT, solution, trigger_tx)

    def withdrawal(sequence):
        return Transaction(
            version=2,
            locktime=0,
            inputs=(
                bl_input(
                    trigger_tx.txid, 0, trig_spk, 100_000, trig_root, sequence=sequence
                ),
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
    assert spend_error(trig_inst, assemble("(1)"), grafted) == "unsatisfied_seal_assert"

    # Recovery works from both states at any time.
    recovery_from_vault = Transaction(
        version=2,
        locktime=0,
        inputs=(bl_input(*vault_outpoint, VSPK, 100_000, VROOT), fee_input()),
        outputs=(TxOutput(RECOVERY_SPK, 100_000),),
    )
    run_spend(VAULT, assemble("(2 100000 100000)"), recovery_from_vault)
    recovery_from_triggered = Transaction(
        version=2,
        locktime=0,
        inputs=(
            bl_input(trigger_tx.txid, 0, trig_spk, 100_000, trig_root),
            fee_input(),
        ),
        outputs=(TxOutput(RECOVERY_SPK, 100_000),),
    )
    run_spend(trig_inst, assemble("(2 100000 100000)"), recovery_from_triggered)


def keyed_recovery_solution(txid, my_amt, recover_amt, sig=None):
    if sig is None:
        msg = assemble(f"(2 {my_amt} {recover_amt})")
        sig = sig_my_outpoint(RKEY_SK, txid, 0, msg)
    return assemble(f"(2 {my_amt} {recover_amt} 0x{sig.hex()})")


def keyed_recovery_tx():
    return Transaction(
        version=2,
        locktime=0,
        inputs=(bl_input(TXID, 0, KVSPK, 60_000, KVROOT), fee_input()),
        outputs=(TxOutput(RECOVERY_SPK, 60_000),),
    )


def test_keyed_recovery():
    run_spend(
        KVAULT, keyed_recovery_solution(TXID, 60_000, 60_000), keyed_recovery_tx()
    )
    # A wrong key's signature fails, and a solution missing the
    # signature dies in the VM reaching for it.
    wrong = sig_my_outpoint(AUTH_SK, TXID, 0, assemble("(2 60000 60000)"))
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
        inputs=(bl_input(TXID, 0, VSPK, 60_000, VROOT), fee_input()),
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
    inputs = [bl_input(b"\xd0" * 32, 0, VSPK, 60_000, VROOT)]
    for i, amount in enumerate(followers):
        inputs.append(
            bl_input(
                bytes([0xD1 + i]) * 32,
                0,
                VSPK,
                amount,
                VROOT,
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


def test_same_target_withdrawals_merge_and_burn():
    # Two matured triggered coins carrying the same target satisfy
    # one committed output set together, and the second coin's value
    # goes entirely to fees: the recorded consequence of SEAL_OUTPUTS
    # leaving the input side open, which is why wallets must make
    # every target unique.
    wd_out = TxOutput(bytes.fromhex("0014") + b"\x22" * 20, 39_000)
    real_target = hashlib.sha256(wd_out.wire).digest()
    trig_inst, trig_root, trig_spk = instance(TRIG_NODE, trig_values(b"", real_target))
    other = bl_input(
        b"\xce" * 32,
        0,
        trig_spk,
        40_000,
        trig_root,
        sequence=DELAY,
        conditions=conditions_of(trig_inst, "(1)"),
    )
    merged = Transaction(
        version=2,
        locktime=0,
        inputs=(
            bl_input(b"\xcc" * 32, 1, trig_spk, 40_000, trig_root, sequence=DELAY),
            other,
        ),
        outputs=(wd_out,),
    )
    run_spend(trig_inst, assemble("(1)"), merged)


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
    malformed_rkey = instance(VAULT_NODE, vault_values(b"\x02" + RKEY_PK))[0]
    overlong_delay = instance(
        VAULT_NODE,
        [
            VAULT_MOD_HASH,
            TRIG_MOD_HASH,
            AUTH_PK,
            NUMS,
            RECOVERY_SPK,
            b"",
            int_to_atom(65_536),
        ],
    )[0]
    nil_recovery_spk = instance(
        VAULT_NODE,
        [VAULT_MOD_HASH, TRIG_MOD_HASH, AUTH_PK, NUMS, b"", b"", int_to_atom(DELAY)],
    )[0]
    padded_delay = instance(
        VAULT_NODE,
        [
            VAULT_MOD_HASH,
            TRIG_MOD_HASH,
            AUTH_PK,
            NUMS,
            RECOVERY_SPK,
            b"",
            b"\x00\x00\x90",
        ],
    )[0]
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
        "vault_trigger_negative_revault": VAULT,
        "vault_trigger_zero_amount": VAULT,
        "vault_malformed_recovery_key_unspendable": malformed_rkey,
        "vault_overlong_delay_unspendable": overlong_delay,
        "vault_nil_recovery_spk_unspendable": nil_recovery_spk,
        "vault_padded_delay_unspendable": padded_delay,
        "vault_lead_no_followers": VAULT,
        "vault_unknown_path": VAULT,
    }
    assert set(cases) == set(by_program)
    for name, node in by_program.items():
        assert cases[name]["program"] == serialize(node).hex(), name


def emitted_hex(program, solution):
    if isinstance(solution, str):
        solution = assemble(solution)
    return serialize(run(program, solution, BUDGET)[1]).hex()


def lead_hex(listed, out_amt):
    listed_text = " ".join(str(a) for a in listed)
    return emitted_hex(VAULT, f"(4 0x{VSPK.hex()} 60000 {out_amt} ({listed_text}))")


def test_validation_vectors_match_source():
    # The complete closure: every conditions field in both validation
    # vector files is recomputed here, from compiled source for the
    # program-derived lists and from its documented construction for
    # the hand-built hostile and encoding variants. Set equality in
    # both directions, so a drifted payload fails and so does a
    # vector case this table does not account for.
    trig_nr = emitted_hex(
        VAULT, trigger_solution(AUTH_SK, TXID, 0, TARGET, 60_000, 0, 60_000)
    )
    nr_sig = sig_my_outpoint(
        AUTH_SK, TXID, 0, assemble(f"(1 0x{TARGET.hex()} 60000 0)")
    )
    flipped = bytes([nr_sig[0] ^ 0x01]) + nr_sig[1:]
    wd_out = TxOutput(bytes.fromhex("0014") + b"\x22" * 20, 39_000)
    real_target = hashlib.sha256(wd_out.wire).digest()
    trig_w = instance(TRIG_NODE, trig_values(b"", real_target))[0]
    one_follower_lead = lead_hex((50_000,), 110_000)
    assert one_follower_lead.count("8300c350") == 1
    expected = {
        trig_nr,
        trig_nr.replace(nr_sig.hex(), flipped.hex()),
        emitted_hex(
            VAULT,
            trigger_solution(AUTH_SK, TXID, 0, TARGET, 40_000, 20_000, 60_000),
        ),
        emitted_hex(
            VAULT,
            f"(1 0x{'66' * 32} 60000 0 60000 0x{nr_sig.hex()})",
        ),
        emitted_hex(trig_w, "(1)"),
        emitted_hex(VAULT, "(2 60000 60000)"),
        emitted_hex(KVAULT, keyed_recovery_solution(TXID, 60_000, 60_000)),
        emitted_hex(TRIG, "(2 40000 40000)"),
        emitted_hex(VAULT, f"(3 0x{VSPK.hex()})"),
        lead_hex((50_000, 30_000), 140_000),
        lead_hex((50_000, 50_000), 160_000),
        lead_hex((50_000,), 110_000),
        lead_hex((30_000,), 90_000),
        lead_hex((40_000, 30_000), 130_000),
        lead_hex((60_000, 30_000), 150_000),
        emitted_hex(VAULT, f"(4 0x{VSPK.hex()} 60000 110000 (50000 -1))"),
        one_follower_lead.replace("8300c350", "840000c350"),
        serialize(
            assemble(
                f"((0x43 98 () 0x{VSPK.hex()} 50000)"
                f" (0x43 98 () 0x{VSPK.hex()} 30000)"
                f" (0x01 0x{'5120' + '42' * 32} 85000))"
            )
        ).hex(),
        serialize(assemble(f"((0x42 98 () 0x{VSPK.hex()}))")).hex(),
    }
    observed = set()
    for name in ("validation/vault-core.json", "validation/vault-consolidation.json"):
        for case in load_vector(name).values():
            for entry in case["tx"]["inputs"]:
                if "conditions" in entry:
                    observed.add(entry["conditions"])
    assert observed == expected


def test_validation_vector_identities_derive_their_scripts():
    # The corpus carries each instance input's execution identity as
    # data the model takes on trust, so this is where the trust is
    # checked: every instance input's scriptPubKey must be the tweak
    # of its internal key by its merkle root, with the single-leaf
    # tree's root equal to its leaf hash. The hostile foreign-script
    # inputs carry the corpus filler triple, counted so the exemption
    # cannot widen unnoticed.
    filler = ("0a" * 32, "0b" * 32, "0c" * 32)
    filler_seen = 0
    for name in ("validation/vault-core.json", "validation/vault-consolidation.json"):
        for case in load_vector(name).values():
            for entry in case["tx"]["inputs"]:
                if "conditions" not in entry:
                    continue
                identity = (
                    entry["tapleaf"],
                    entry["merkle_root"],
                    entry["internal_key"],
                )
                if identity == filler:
                    filler_seen += 1
                    continue
                root = bytes.fromhex(entry["merkle_root"])
                assert entry["tapleaf"] == entry["merkle_root"]
                assert entry["internal_key"] == NUMS.hex()
                expected = b"\x51\x20" + secp256k1.taproot_output_key(NUMS, root)
                assert entry["script_pubkey"] == expected.hex(), case["name"]
    assert filler_seen == 2
