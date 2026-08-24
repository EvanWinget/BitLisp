"""Shared harness for the benchmark puzzle test files.

A plain module beside support.py for the same reason support.py is
one: importing helpers by name from conftest works only through
conftest's special loading. It holds the puzzle-agnostic pieces:
the transaction and input builders, the outpoint-bound signer, the
curried-instance derivation, the run wrappers, the spec-rule root
reimplementation, and the vector-agreement audits. Everything a
puzzle owns (sources, mod hashes, lifecycle, case tables) stays in
that puzzle's test file, and the mod-hash drift guards there keep
proving a harness change touches no puzzle bytes.

The vendored Bitcoin Core framework signer joins sys.path here, so
a puzzle file gets it by importing this module first.
"""

import hashlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "oracle" / "bitcoincore"))

from bitlisp import BitLispError, Transaction, TxInput, run, serialize  # noqa: E402
from bitlisp.conditions import parse_conditions  # noqa: E402
from bitlisp.secp256k1 import taproot_output_key  # noqa: E402
from bitlisp.sexp import NIL  # noqa: E402
from bitlisp_tools import assemble  # noqa: E402
from bitlisp_tools.compiler import tree_hash  # noqa: E402
from bitlisp_tools.curry import curry  # noqa: E402
from bitlisp_tools.runner import run_spend  # noqa: E402
from support import NUMS, condition_inputs, load_vector  # noqa: E402
from test_framework.key import sign_schnorr  # noqa: E402

BUDGET = 11_000_000_000
SEQ_FINAL = 0xFFFFFFFF
AUX = b"\x00" * 32
FEE_SPK = bytes.fromhex("0014") + b"\x11" * 20


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


def tx(inputs, outputs):
    return Transaction(
        version=2, locktime=0, inputs=tuple(inputs), outputs=tuple(outputs)
    )


def instance(node, values, internal_key=NUMS):
    """A curried instance, its merkle root, and its scriptPubKey."""
    inst = curry(node, values)
    root = tree_hash(inst)
    return inst, root, b"\x51\x20" + taproot_output_key(internal_key, root)


def sig_my_outpoint(sk, txid, index, message_node):
    """The outpoint-bound Schnorr signature ASSERT_SIG_MY_OUTPOINT
    verifies, over the tagged digest of the consumed outpoint and
    the message's tree hash, with fixed aux bytes so every derived
    signature is deterministic."""
    tag = hashlib.sha256(b"BitLisp/sig/my_outpoint").digest()
    digest = hashlib.sha256(
        tag + tag + outpoint(txid, index) + tree_hash(message_node)
    ).digest()
    return sign_schnorr(sk, digest, AUX)


def fee_input(amount, txid=b"\xbb" * 32, index=0):
    return TxInput(txid, index, FEE_SPK, amount, sequence=SEQ_FINAL)


def taproot_input(
    txid,
    index,
    spk,
    amount,
    root,
    internal_key=NUMS,
    sequence=SEQ_FINAL,
    conditions=None,
):
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
        internal_key=internal_key,
    )


def _node(solution):
    return assemble(solution) if isinstance(solution, str) else solution


def spend_error(program, solution, spending, input_index=0):
    with pytest.raises(BitLispError) as info:
        run_spend(program, _node(solution), spending, input_index)
    return info.value.code


def run_error(program, solution):
    with pytest.raises(BitLispError) as info:
        run(program, _node(solution), BUDGET)
    return info.value.code


def conditions_of(program, solution):
    _, result = run(program, _node(solution), BUDGET)
    _, conds = parse_conditions(result, None)
    return conds


def emitted_hex(program, solution):
    return serialize(run(program, _node(solution), BUDGET)[1]).hex()


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


def assert_vm_vectors_match(name, expected):
    """Every pinned program, and solution where one is given, in the
    named vm vector file must be byte-identical to its fresh
    construction from source, the case sets equal both ways, so the
    corpus cannot drift from the sources."""
    cases = load_vector(name)
    assert set(cases) == set(expected)
    for case_name, (program, solution) in expected.items():
        assert cases[case_name]["program"] == serialize(program).hex(), case_name
        if solution is not None:
            assert cases[case_name]["env"] == serialize(solution).hex(), case_name


def assert_conditions_closure(names, expected):
    """The complete closure over the named validation vector files:
    every conditions field a file carries is recomputed by the
    caller and every recomputed payload appears, set equality in
    both directions, so a drifted payload fails and so does a case
    the caller's table does not account for."""
    files = [load_vector(name) for name in names]
    observed = {entry["conditions"] for _, entry in condition_inputs(files)}
    assert observed == expected
