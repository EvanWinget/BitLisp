"""Transaction matching, rule by rule.

Rule 1, injective multiset output matching: every output claim maps
to a distinct output slot with byte-exact content. Because a claim
matches a slot only by exact equality, the injective-assignment
question collapses to multiset containment and the check is counting.
That equality-only restriction is what keeps this a counting problem
rather than bipartite matching. Relaxing it is a recorded design
decision, never an implementation choice.
"""

from collections import Counter

from .conditions import CreateOutput
from .errors import BitLispError


def output_claims(conditions):
    """The (scriptPubKey, amount) claims a condition list produces."""
    return [
        (c.script_pubkey, c.amount) for c in conditions if isinstance(c, CreateOutput)
    ]


def check_output_claims(tx):
    """Rule 1. Raises unsatisfied_output_claim unless every claim in
    the transaction can consume its own distinct output slot."""
    claims = Counter()
    for tx_input in tx.inputs:
        if tx_input.conditions is not None:
            claims.update(output_claims(tx_input.conditions))
    slots = Counter(output.content for output in tx.outputs)
    for content, count in claims.items():
        script_pubkey, amount = content
        if count > slots[content]:
            raise BitLispError(
                "unsatisfied_output_claim",
                f"{count} claim(s) on ({script_pubkey.hex()}, {amount}) but "
                f"{slots[content]} matching output slot(s)",
            )


def validate_transaction(tx):
    """Every matching rule that has landed so far."""
    check_output_claims(tx)
