# BitLisp Transaction Matching

Status: in progress. The transaction view, rule 1, and rule 6 are
normative. Rules 2 to 5 are designed in architecture sessions, land
here as prose first, and only then get implemented. Ground rule 4:
this layer gets invariants and adversarial vectors before any feature
work.

This document specifies how a validated spend's condition list is checked
against the containing Bitcoin transaction.

Target property: a reviewer who has read only this document can predict
the outcome of every vector in `vectors/matching/`.

## Transaction view

Matching is a pure function of the transaction below. No other data
influences any rule in this document. Contextual asserts (height,
time) compare against fields of this view and the validation context
in which the transaction is evaluated, in the manner of Bitcoin's
locktime rules, and are specified with their conditions.

A transaction is:

- `version`, a 32-bit integer
- `locktime`, a 32-bit unsigned integer
- `inputs`, an ordered list. Each input carries the outpoint it
  consumes (a 32-byte txid and a 32-bit index), the consumed output's
  `scriptPubKey` and `amount`, and a 32-bit `sequence`. A BitLisp
  input additionally carries the condition list its evaluation
  produced.
- `outputs`, an ordered list of slots. Each slot's content is the
  pair (`scriptPubKey`, `amount`). Slots are addressed by index.

Matching is defined only over transactions that satisfy Bitcoin's
base consensus rules. The reference transaction model enforces the
subset it represents: at least one input and one output, no outpoint
consumed by two inputs, every amount within 0 to MAX_MONEY, and the
sum of outputs not exceeding the sum of inputs. It enforces nothing
base consensus does not: in particular, an output slot's
scriptPubKey has no size bound, and a slot larger than any claimable
script is simply an unmatched slot.

## Rules (in landing order)

### 1. Injective multiset output matching

An **output claim** is a pair (`scriptPubKey`, `amount`) demanded of
the transaction's outputs. Each vocabulary entry states whether it
produces a claim. CREATE_OUTPUT produces exactly one claim, its own
argument pair.

Let C be the multiset of all output claims produced by all BitLisp
inputs of the transaction, and let O be the multiset of all output
slot contents. The transaction is valid under this rule if and only
if C is contained in O as a multiset: for every distinct pair p, the
number of claims equal to p is at most the number of slots whose
content equals p. Violation is the error `unsatisfied_output_claim`.

Equivalently: there must exist an assignment of claims to output
slots such that every claim maps to a slot with equal content and no
slot is assigned twice. Multiset containment and the existence of
such an injective assignment are the same condition here because a
claim matches a slot only by equality.

A claim matches a slot only by byte-exact equality of `scriptPubKey`
and numeric equality of `amount`. No rule in this document may
introduce a claim that matches by range, prefix, or any predicate
other than equality. Relaxing this sentence is a change to the
validator's algorithmic class and requires a recorded design
decision.

Slots not consumed by any claim are unconstrained by this rule.
Rule 2 states the coexistence consequences.

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

TODO. Including the superlinear `CREATE_OUTPUT` pricing stub (design
obligation 2). Tuning is data-driven in Phase 4.

### 6. Reserved conditions

Opcodes `0x80` to `0xff` are reserved. A reserved condition is
`(opcode cost arg...)`: the opcode, a declared cost, then zero or
more further arguments. A reserved condition with no arguments is
rejected (`bad_condition_arity`).

The declared cost must be an atom carrying a minimally encoded
non-negative integer (`bad_condition_arg`) with
cost >= RESERVED_COST_FLOOR, where RESERVED_COST_FLOOR is 500
(`reserved_cost_too_low`). The declared cost counts against the
spend's cost total under the accounting rule 5 defines, and vectors
pin the charge when that rule lands. Arguments after the cost are
unconstrained: any count, any shapes, including pairs.

No semantics are enforced. A reserved condition constrains nothing
about the transaction.

A future assignment of a reserved opcode must only tighten validity,
must keep charging exactly the declared cost, and must require the
declared cost to be at least the assigned operation's cost-table
entry. These constraints are what keep validators that predate the
assignment in consensus with validators that enforce it.

**Policy note (not consensus).** Implementations should treat
transactions containing unassigned reserved conditions as
non-standard for relay and mining, in the manner of Bitcoin's
upgradable NOPs, so that future assignments do not confiscate
in-flight spends.

## Invariants

The `hypothesis` suite in `python/tests/` must enforce the following
over generated transactions. Each invariant names the rule that makes
it enforceable, and lands with that rule:

- Value conservation on every accepted transaction (transaction view,
  enforced as a model precondition).
- No output satisfies two conditions, k identical claims require k
  distinct slots (rule 1).
- Validation is invariant under input reordering, output reordering,
  and condition-list reordering (rule 1).
- Removing a condition from a valid transaction never turns it
  invalid, and adding a condition to an invalid transaction never
  turns it valid: constraints only tighten (rule 1).
- Removing a claimed output from a transaction whose claims exactly
  cover that output's content turns it invalid (rule 1).
- Metamorphic: mutating the content of any exactly-claimed output
  (amount off by one, script byte flip) causes rejection (rule 1).
