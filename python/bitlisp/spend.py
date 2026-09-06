"""The witness layer: one BitLisp input's spend, from its witness
elements to the condition list it contributes to the transaction.

A BitLisp spend is a BIP341 script-path spend whose witness carries
four elements in stack order: the solution, the program, the leaf
script, and the control block, with an annex after them only when
the program commits to one. Base consensus authenticates the leaf
against the spent output through the control block before anything
here runs. The stages below then check the witness's shape, decode
the two node elements, check the program against the leaf, evaluate
it over the solution under the budget, and parse the value it
returns as a condition list. The result is the input as the
transaction view carries it, ready for validate_transaction.
"""

from dataclasses import replace

from .commitment import (
    ANNEX_TAG,
    BITLISP_LEAF_VERSION,
    ControlBlock,
    sha_annex,
    tree_hash,
)
from .conditions import AssertMyAnnex, parse_conditions
from .errors import BaseConsensusError, BitLispError
from .machine import run
from .serialize import deserialize

# The solution, the program, the leaf script, and the control block.
WITNESS_ELEMENT_COUNT = 4
LEAF_SCRIPT_SIZE = 32
# Every element the spender chooses freely (the solution, the program,
# the annex) is bounded here. Bitcoin's legacy script cap, the bound
# the condition layer already places on a scriptPubKey operand.
MAX_WITNESS_ELEMENT_SIZE = 10_000


def split_annex(witness):
    """BIP341's annex rule over the witness as the transaction
    serializes it: with at least two elements and the last beginning
    0x50, that element is the annex. Returns (elements, annex), the
    annex None when there is none."""
    if len(witness) >= 2 and witness[-1][:1] == bytes([ANNEX_TAG]):
        return witness[:-1], witness[-1]
    return witness, None


def read_identity(elements, script_pubkey):
    """Base consensus's view of a script-path spend, run before any
    rule of this layer: at least two elements, the last a well-formed
    control block naming BitLisp's leaf version, whose internal key
    tweaked by the revealed leaf's root gives the spent scriptPubKey.
    Returns (tapleaf, merkle root, internal key), else
    BaseConsensusError. A witness of fewer than two elements is a
    key-path spend, not a script-path spend, and a leaf version other
    than BitLisp's is a spend this layer never sees."""
    if len(elements) < 2:
        raise BaseConsensusError(
            f"{len(elements)} witness element(s) is not a script-path spend"
        )
    control_block = ControlBlock.parse(elements[-1])
    if control_block.leaf_version != BITLISP_LEAF_VERSION:
        raise BaseConsensusError(
            f"leaf version {control_block.leaf_version:#04x} is not BitLisp's "
            f"{BITLISP_LEAF_VERSION:#04x}"
        )
    tapleaf, root = control_block.check(elements[-2], script_pubkey)
    return tapleaf, root, control_block.internal_key


def check_annex_admission(tx_input):
    """The annex rule: an input whose witness carries an annex is
    valid only when its condition list holds an ASSERT_MY_ANNEX, so
    the annex is data the spender committed to and no third party
    can attach one. The rule reads the input alone, so it runs here
    right after the input's conditions parse, and validate_transaction
    runs it again over every assembled input, because a transaction
    view built without evaluate_spend must satisfy the same invariant.
    An input without a condition list is not a BitLisp input and
    carries no annex the rule reads."""
    if tx_input.annex_hash is None or tx_input.conditions is None:
        return
    if not any(isinstance(cond, AssertMyAnnex) for cond in tx_input.conditions):
        raise BitLispError(
            "unasserted_annex",
            f"the witness carries an annex hashing to {tx_input.annex_hash.hex()} "
            "and the condition list holds no ASSERT_MY_ANNEX",
        )


def evaluate_spend(tx_input, witness, max_cost):
    """Runs one input's spend through every per-input stage.

    tx_input is the input as the transaction carries it before
    evaluation: outpoint, spent scriptPubKey and amount, sequence,
    and no condition list. witness is the input's witness elements
    as the transaction serializes them, the control block last and
    an annex after it when present. max_cost is the inclusive budget
    evaluation and condition parsing share.

    Returns (cost, input): the accrued total and the same input
    carrying its condition list, its execution identity, and its
    annex hash when the witness carried an annex. Raises
    BitLispError when the spend is invalid, under the first failing
    stage's code, and BaseConsensusError when base consensus would
    reject the spend or it is not a BitLisp spend.
    """
    if tx_input.conditions is not None:
        raise ValueError("the input already carries a condition list")
    elements, annex = split_annex(witness)
    tapleaf, root, internal_key = read_identity(elements, tx_input.script_pubkey)

    # Stage 1: the witness shape. Every check here is a width.
    if len(elements) != WITNESS_ELEMENT_COUNT:
        raise BitLispError(
            "bad_witness",
            f"a BitLisp witness is {WITNESS_ELEMENT_COUNT} elements beside the "
            f"annex, got {len(elements)}",
        )
    solution_bytes, program_bytes, leaf_script, _ = elements
    if len(leaf_script) != LEAF_SCRIPT_SIZE:
        raise BitLispError(
            "bad_witness",
            f"the leaf script is {LEAF_SCRIPT_SIZE} bytes, got {len(leaf_script)}",
        )
    for name, element in (
        ("solution", solution_bytes),
        ("program", program_bytes),
        ("annex", annex),
    ):
        if element is not None and len(element) > MAX_WITNESS_ELEMENT_SIZE:
            raise BitLispError(
                "bad_witness",
                f"the {name} element is {len(element)} bytes, above "
                f"{MAX_WITNESS_ELEMENT_SIZE}",
            )

    # Stage 2: the program decodes and is the one the leaf commits to.
    program = deserialize(program_bytes)
    program_hash = tree_hash(program)
    if program_hash != leaf_script:
        raise BitLispError(
            "leaf_mismatch",
            f"the program's tree hash {program_hash.hex()} is not the leaf "
            f"script {leaf_script.hex()}",
        )

    # Stage 3: the solution decodes. Its content is the program's
    # business, so there is nothing else to check.
    solution = deserialize(solution_bytes)

    # Stage 4: evaluation under the budget.
    vm_cost, result = run(program, solution, max_cost)

    # Stage 5: the value is a condition list charged against the same
    # budget, and an annex is admitted only under its assert.
    cost, conditions = parse_conditions(result, max_cost, cost=vm_cost)
    spent = replace(
        tx_input,
        conditions=conditions,
        tapleaf=tapleaf,
        merkle_root=root,
        internal_key=internal_key,
        annex_hash=None if annex is None else sha_annex(annex),
    )
    check_annex_admission(spent)
    return cost, spent
