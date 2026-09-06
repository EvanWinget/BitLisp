"""Property-based invariants for the validation layer.

The validation rules have no external oracle, so property-based
invariants and the adversarial vector corpus stand in for one.

Transactions are generated over a small content pool (three scripts,
four amounts, plus taproot-derived scripts) so claim and slot
collisions are dense, which is where injective matching earns its
keep. Contents with a taproot derivation are claimed alternately by
CreateOutputTaproot and by a plain CreateOutput carrying the derived
script, so every property here also pins that the producing class is
irrelevant to validation.
"""

from collections import Counter
from dataclasses import replace

import pytest
from bitlisp import (
    BitLispError,
    CreateOutput,
    CreateOutputTaproot,
    Transaction,
    TxInput,
    TxOutput,
    validate_transaction,
)
from bitlisp.secp256k1 import G, point_mul, taproot_output_key
from hypothesis import given
from hypothesis import strategies as st
from support import filler_identity

SCRIPTS = (b"\x51", b"\x52", b"\x53")
AMOUNTS = (0, 1, 2, 3)
UNMATCHABLE = b"\xff"  # never appears in generated outputs


def _taproot_pool():
    """(script_pubkey, amount) -> CreateOutputTaproot, derived from
    two on-curve internal keys, one with and one without a script
    tree."""
    pool = {}
    for k, root in ((1, b""), (2, b"\xab" * 32)):
        internal_key = point_mul(k, G)[0].to_bytes(32, "big")
        script = b"\x51\x20" + taproot_output_key(internal_key, root)
        for amount in (1, 2):
            pool[(script, amount)] = CreateOutputTaproot(
                internal_key, root, amount, script
            )
    return pool


TAPROOT_BY_CONTENT = _taproot_pool()
TAPROOT_CONTENTS = tuple(sorted(TAPROOT_BY_CONTENT))

contents = st.one_of(
    st.tuples(st.sampled_from(SCRIPTS), st.sampled_from(AMOUNTS)),
    st.sampled_from(TAPROOT_CONTENTS),
)
claim_lists = st.lists(contents, max_size=3)
output_lists = st.lists(contents, min_size=1, max_size=6)
# None is a non-BitLisp input, a list is a BitLisp input's claims.
input_specs = st.lists(st.one_of(st.none(), claim_lists), min_size=1, max_size=3)


def _condition_for(script, amount, position):
    """The claim's producing condition. Taproot-derivable contents
    alternate producers by list position, so reorderings exercise
    both classes over identical content."""
    taproot = TAPROOT_BY_CONTENT.get((script, amount))
    if taproot is not None and position % 2 == 0:
        return taproot
    return CreateOutput(script, amount)


def build_tx(input_claims, outputs):
    """A transaction whose first input funds all outputs."""
    out_total = sum(amount for _, amount in outputs)
    inputs = []
    for n, claims in enumerate(input_claims):
        conditions = (
            None
            if claims is None
            else tuple(
                _condition_for(script, amount, i)
                for i, (script, amount) in enumerate(claims)
            )
        )
        inputs.append(
            TxInput(
                txid=bytes([n + 1]) * 32,
                index=0,
                script_pubkey=b"\x51",
                amount=out_total if n == 0 else 0,
                sequence=0xFFFFFFFF,
                conditions=conditions,
                **filler_identity(),
            )
        )
    return Transaction(
        version=2,
        locktime=0,
        inputs=tuple(inputs),
        outputs=tuple(TxOutput(script, amount) for script, amount in outputs),
    )


def is_valid(tx):
    try:
        validate_transaction(tx)
        return True
    except BitLispError as exc:
        assert exc.code == "unsatisfied_output_claim"
        return False


def all_claims(input_claims):
    return [c for claims in input_claims if claims is not None for c in claims]


@given(input_specs, output_lists)
def test_validity_is_multiset_containment(input_claims, outputs):
    """Rule 1's counting formulation, restated. This restates the
    matcher's own algorithm, so it pins the implementation against
    drift but cannot judge the algorithm. The assignment-search test
    below is the independent judge."""
    tx = build_tx(input_claims, outputs)
    claimed = Counter(all_claims(input_claims))
    slots = Counter(outputs)
    expected = all(count <= slots[content] for content, count in claimed.items())
    assert is_valid(tx) == expected


def _injective_assignment_exists(claims, slots):
    """Literal backtracking search for an injective claim-to-slot
    assignment, trying assignments one at a time. Deliberately naive
    and deliberately sharing no code or idea with the matcher's
    counting: this is the other formulation of rule 1, implemented as
    written."""
    if not claims:
        return True
    first, rest = claims[0], claims[1:]
    for i, slot in enumerate(slots):
        if slot == first:
            if _injective_assignment_exists(rest, slots[:i] + slots[i + 1 :]):
                return True
    return False


@given(input_specs, output_lists)
def test_counting_agrees_with_assignment_search(input_claims, outputs):
    """Rule 1 states two formulations and calls them equivalent:
    multiset containment (what the matcher computes) and the
    existence of an injective assignment (what this search computes).
    They must never disagree."""
    tx = build_tx(input_claims, outputs)
    assert is_valid(tx) == _injective_assignment_exists(
        all_claims(input_claims), list(outputs)
    )


@given(input_specs, output_lists, st.randoms(use_true_random=False))
def test_reordering_never_changes_the_outcome(input_claims, outputs, rng):
    tx = build_tx(input_claims, outputs)
    shuffled_inputs = list(input_claims)
    rng.shuffle(shuffled_inputs)
    shuffled_inputs = [
        (None if claims is None else rng.sample(claims, len(claims)))
        for claims in shuffled_inputs
    ]
    shuffled_outputs = rng.sample(outputs, len(outputs))
    shuffled = build_tx(shuffled_inputs, shuffled_outputs)
    assert is_valid(tx) == is_valid(shuffled)


@given(input_specs, output_lists)
def test_removing_a_condition_never_invalidates(input_claims, outputs):
    """Constraints only tighten. Dropping any one claim from a valid
    transaction leaves it valid."""
    tx = build_tx(input_claims, outputs)
    if not is_valid(tx):
        return
    for i, claims in enumerate(input_claims):
        if not claims:
            continue
        for j in range(len(claims)):
            reduced = list(input_claims)
            reduced[i] = claims[:j] + claims[j + 1 :]
            assert is_valid(build_tx(reduced, outputs))


@given(input_specs, output_lists)
def test_adding_an_unmatchable_claim_always_invalidates(input_claims, outputs):
    augmented = list(input_claims)
    augmented.append([(UNMATCHABLE, 1)])
    assert not is_valid(build_tx(augmented, outputs))


@given(input_specs, output_lists, contents)
def test_adding_a_condition_never_validates(input_claims, outputs, extra_claim):
    """The other half of monotonicity: an invalid transaction stays
    invalid under any added claim."""
    if is_valid(build_tx(input_claims, outputs)):
        return
    augmented = list(input_claims)
    augmented.append([extra_claim])
    assert not is_valid(build_tx(augmented, outputs))


@given(input_specs, output_lists)
def test_removing_an_exactly_claimed_output_invalidates(input_claims, outputs):
    tx = build_tx(input_claims, outputs)
    if not is_valid(tx) or len(outputs) < 2:
        return
    claimed = Counter(all_claims(input_claims))
    slots = Counter(outputs)
    for content, count in claimed.items():
        if count == slots[content]:
            reduced = list(outputs)
            reduced.remove(content)
            assert not is_valid(build_tx(input_claims, reduced))
            break


@given(input_specs, output_lists, st.sampled_from(["amount", "script"]))
def test_mutating_an_exactly_claimed_output_invalidates(
    input_claims, outputs, mutation
):
    """Metamorphic: bump the amount or flip a script byte on a slot
    whose content is exactly covered by claims."""
    tx = build_tx(input_claims, outputs)
    if not is_valid(tx):
        return
    claimed = Counter(all_claims(input_claims))
    slots = Counter(outputs)
    for content, count in claimed.items():
        if count == slots[content] and count > 0:
            script, amount = content
            if mutation == "amount":
                mutated_content = (script, amount + 1)
            else:
                mutated_content = (script[:-1] + bytes([script[-1] ^ 0x01]), amount)
            mutated = list(outputs)
            mutated[mutated.index(content)] = mutated_content
            assert not is_valid(build_tx(input_claims, mutated))
            break


@given(st.sampled_from(TAPROOT_CONTENTS))
def test_cross_opcode_equal_content_competes_for_slots(content):
    """A taproot-derived claim and a plain CreateOutput claim
    carrying the same content are one multiset: two claims need two
    slots. build_tx's alternation guarantees the pair mixes both
    classes."""
    input_claims = [[content, content]]
    tx = build_tx(input_claims, [content])
    produced = {type(c) for c in tx.inputs[0].conditions}
    assert produced == {CreateOutput, CreateOutputTaproot}
    assert not is_valid(tx)
    assert is_valid(build_tx(input_claims, [content, content]))


@given(st.integers(min_value=2, max_value=5), contents)
def test_k_claims_never_fit_k_minus_1_slots(k, content):
    """The theft property, generalized: k identical claims are never
    satisfied by k - 1 identical slots."""
    input_claims = [[content] for _ in range(k)]
    outputs = [content] * (k - 1)
    assert not is_valid(build_tx(input_claims, outputs))
    assert is_valid(build_tx(input_claims, outputs + [content]))


# --- rule 2 and the composition guarantee -----------------------------------


@given(input_specs, output_lists, contents)
def test_adding_an_output_slot_never_invalidates(input_claims, outputs, extra):
    """Rule 2 over the landed vocabulary: no landed condition reads
    a fact that adding a slot changes, so growing the output side
    of a valid transaction never rejects. An entry that reads an
    addition-sensitive fact (a fee floor) re-scopes this property
    when it lands. The merge property below is the permanent one."""
    if not is_valid(build_tx(input_claims, outputs)):
        return
    assert is_valid(build_tx(input_claims, outputs + [extra]))


@given(input_specs, output_lists)
def test_adding_a_plain_input_never_invalidates(input_claims, outputs):
    """Rule 2: a non-BitLisp input contributes no conditions, so it
    can never turn a valid transaction invalid."""
    if not is_valid(build_tx(input_claims, outputs)):
        return
    assert is_valid(build_tx(input_claims + [None], outputs))


@given(st.integers(min_value=1, max_value=3), output_lists)
def test_plain_only_transaction_always_valid(input_count, outputs):
    """Rule 2: a transaction with no BitLisp inputs is subject to no
    validation rule, whatever its shape."""
    assert is_valid(build_tx([None] * input_count, outputs))


def _with_fresh_outpoints(tx_inputs, offset):
    """The same inputs on outpoints from a disjoint txid range."""
    return tuple(
        replace(tx_input, txid=bytes([offset + n]) * 32)
        for n, tx_input in enumerate(tx_inputs, start=1)
    )


@given(input_specs, output_lists, input_specs, output_lists)
def test_merge_of_valid_transactions_is_valid(claims_a, outputs_a, claims_b, outputs_b):
    """The composition guarantee: two valid transactions consuming
    disjoint outpoints concatenate into a valid transaction."""
    tx_a = build_tx(claims_a, outputs_a)
    tx_b = build_tx(claims_b, outputs_b)
    if not (is_valid(tx_a) and is_valid(tx_b)):
        return
    merged = Transaction(
        version=2,
        locktime=0,
        inputs=_with_fresh_outpoints(tx_a.inputs, 0x10)
        + _with_fresh_outpoints(tx_b.inputs, 0x40),
        outputs=tx_a.outputs + tx_b.outputs,
    )
    assert is_valid(merged)


# --- transaction-model preconditions ---------------------------------------
# Value conservation is enforced at construction, so validation never
# sees a transaction that creates value out of nothing.


def test_model_rejects_value_creation():
    tx_input = TxInput(b"\x01" * 32, 0, b"\x51", 4, 0)
    with pytest.raises(ValueError, match="value not conserved"):
        Transaction(2, 0, (tx_input,), (TxOutput(b"\x51", 5),))


def test_model_rejects_duplicate_outpoints():
    tx_input = TxInput(b"\x01" * 32, 0, b"\x51", 1, 0)
    with pytest.raises(ValueError, match="duplicate input outpoint"):
        Transaction(2, 0, (tx_input, tx_input), (TxOutput(b"\x51", 1),))


def test_model_rejects_empty_sides():
    tx_input = TxInput(b"\x01" * 32, 0, b"\x51", 1, 0)
    with pytest.raises(ValueError, match="non-empty"):
        Transaction(2, 0, (), (TxOutput(b"\x51", 1),))
    with pytest.raises(ValueError, match="non-empty"):
        Transaction(2, 0, (tx_input,), ())


def test_model_requires_identity_with_conditions():
    # A condition-carrying input is a BitLisp input, and a BitLisp
    # input always executes a leaf of some tree, so the model refuses
    # the impossible shape.
    identity = filler_identity()
    with pytest.raises(ValueError, match="tapleaf, merkle_root, and internal_key"):
        TxInput(b"\x01" * 32, 0, b"\x51", 1, 0, conditions=())
    for missing in identity:
        partial = {k: v for k, v in identity.items() if k != missing}
        with pytest.raises(ValueError, match="tapleaf, merkle_root, and internal_key"):
            TxInput(b"\x01" * 32, 0, b"\x51", 1, 0, conditions=(), **partial)
    TxInput(b"\x01" * 32, 0, b"\x51", 1, 0, conditions=(), **identity)
    with pytest.raises(ValueError, match="tapleaf must be 32 bytes"):
        TxInput(b"\x01" * 32, 0, b"\x51", 1, 0, tapleaf=b"\x0a" * 31)
    with pytest.raises(ValueError, match="merkle_root must be 32 bytes"):
        TxInput(b"\x01" * 32, 0, b"\x51", 1, 0, merkle_root=b"\x0b" * 33)
    with pytest.raises(ValueError, match="internal_key must be 32 bytes"):
        TxInput(b"\x01" * 32, 0, b"\x51", 1, 0, internal_key=b"\x0c" * 31)
    with pytest.raises(ValueError, match="annex_hash must be 32 bytes"):
        TxInput(b"\x01" * 32, 0, b"\x51", 1, 0, annex_hash=b"\x0d" * 33)


def test_model_rejects_out_of_range_amounts():
    with pytest.raises(ValueError, match="amount out of range"):
        TxOutput(b"\x51", -1)
    with pytest.raises(ValueError, match="amount out of range"):
        TxOutput(b"\x51", 2_100_000_000_000_001)
