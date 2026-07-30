# BitLisp Transaction Matching

Status: stub. This is the novel consensus layer with no external
reference. Rules are designed in architecture sessions, land here as
prose first, and only then get implemented. Ground rule 4: this layer
gets invariants and adversarial vectors before any feature work.

This document specifies how a validated spend's condition list is checked
against the containing Bitcoin transaction.

Target property: a reviewer who has read only this document can predict
the outcome of every vector in `vectors/matching/`.

## Rules (in landing order)

### 1. Injective multiset output matching

TODO. k identical `CREATE_COIN` conditions must consume k distinct output
slots. No output satisfies two conditions. The duplicate-output theft
case is regression vector #1 in `vectors/matching/`.

### 2. Mixed-transaction rule

TODO. Every condition finds a distinct satisfier. Unmatched outputs are
permitted, so plain-taproot inputs and outputs coexist in the same
transaction.

### 3. Message scoping

TODO. Messages are strictly within-transaction. Sender and receiver
binding modes, multiplicity rules for duplicate sends and receives.

### 4. Dedup and multiplicity

TODO. Within-input and cross-input deduplication, with the cost
interaction documented.

### 5. Per-condition costing

TODO. Including the superlinear `CREATE_COIN` pricing stub (design
obligation 2). Tuning is data-driven in Phase 3.

### 6. Reserved conditions

TODO. Condition codes outside the assigned vocabulary. This rule is
the designated forward-compatibility mechanism for already-deployed
coins (the D3 ratification in
[docs/vm-record.md](../docs/vm-record.md)): a reserved code is
accepted unenforced at a fixed cost so a later soft fork can assign
it real semantics, the OP_NOP path. The rule must fix which code
ranges are reserved versus invalid, the cost old and new validators
agree on forever, the unconstrained argument shape, and the policy
stance toward reserved conditions before assignment.

## Invariants

The `hypothesis` suite in `python/tests/` must enforce, over generated
transactions:

- Value conservation on every accepted transaction.
- No output satisfies two conditions (matching injectivity).
- Validation is invariant under input reordering and condition-list
  reordering.
- Removing a condition from a spend never turns an invalid transaction
  valid. Removing an output never leaves a matched condition matched.
- Metamorphic: mutating any matched output (amount off by one, script
  byte flip) causes rejection.
