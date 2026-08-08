# BitLisp Condition Validation

Status: in progress. The transaction view, the claims-and-asserts
principle, the validation stages, and rules 1, 2, and 6 are
normative. Rules 3 to 5 are designed in architecture sessions, land
here as prose first, and only then get implemented. Ground rule 4:
this layer gets invariants and adversarial vectors before any feature
work.

This document specifies how a validated spend's condition list is checked
against the containing Bitcoin transaction.

Target property: a reviewer who has read only this document can predict
the outcome of every vector in `vectors/validation/`.

## Transaction view

Validation is a pure function of the transaction below. No other
data influences any rule in this document. The time asserts of
`spec/CONDITIONS.md` compare against the transaction's own
locktime, sequence, and version fields, which base consensus
enforces against the chain. No rule reads the chain.

A transaction is:

- `version`, a 32-bit unsigned integer. Base consensus compares
  the field unsigned in its locktime rules, and this document
  follows it, so wire versions with the top bit set are large
  values, never negative ones.
- `locktime`, a 32-bit unsigned integer
- `inputs`, an ordered list. Each input carries the outpoint it
  consumes (a 32-byte txid and a 32-bit index), the consumed output's
  `scriptPubKey` and `amount`, and a 32-bit `sequence`. A BitLisp
  input additionally carries the condition list its evaluation
  produced.
- `outputs`, an ordered list of slots. Each slot's content is the
  pair (`scriptPubKey`, `amount`). Slots are addressed by index.

Validation is defined only over transactions that satisfy Bitcoin's
base consensus rules. The reference transaction model enforces the
subset it represents: at least one input and one output, no outpoint
consumed by two inputs, every amount within 0 to MAX_MONEY, and the
sum of outputs not exceeding the sum of inputs. It enforces nothing
base consensus does not: in particular, an output slot's
scriptPubKey has no size bound, and a slot larger than any claimable
script is simply an unmatched slot.

## Claims and asserts

A condition constrains the transaction through claims and asserts,
and in no other way. Each vocabulary entry in `spec/CONDITIONS.md`
states what it claims and what it asserts. An entry may produce
neither: rule 6's reserved conditions constrain nothing.

- A **claim** requires a resource of the transaction and consumes
  it. The output claims of rule 1 are the only claim kind defined
  so far. Validation assigns resources to claims injectively: each
  claim is assigned its own resource, called its **satisfier**,
  and no resource is assigned to two claims.
- An **assert** requires a fact to hold. A fact is a predicate
  over the transaction view and nothing else. Checking
  an assert assigns and consumes nothing. Any number of asserts,
  from one input or many, may read the same fact. The transaction
  is checked against every assert of every BitLisp input.

The implication runs one way only. No rule in this document
constrains a part of the transaction that no condition claims or
reads. An output slot no claim consumes, an input that is not a
BitLisp input, and a fact no assert reads are all unconstrained.
Rule 2 states the consequences.

**Composition guarantee.** Let two transactions each be valid
under this document, with no outpoint consumed in both, and with
locktime fields of the same type: both height-typed or both
time-typed. Their concatenation is the inputs of both followed by
the outputs of both, carrying the greater of the two version
fields and the greater of the two locktime fields. If the
concatenation satisfies the transaction view's preconditions,
then no rule in this document rejects it. Every rule and every
vocabulary entry must preserve this property. A vocabulary entry
whose assert reads a fact that a concatenation satisfying these
hypotheses can falsify, such as an upper bound on a quantity that
concatenation sums or an exact count, must not be defined. The
same-type hypothesis is Bitcoin's own constraint, not a new one:
a transaction has a single locktime field, so height-locked and
time-locked spends cannot share any transaction on the network
today. Relaxing this paragraph changes what wallets may safely
batch and requires a recorded design decision.

## Validation stages

Rules are organized into stages of strictly increasing context. A
rule's stage states exactly what context can invalidate its work,
and no check reads more context than its stage provides.

1. Stateless per-spend work: the VM run and condition
   well-formedness.
2. Facts of the spent output's own data: outpoint, spent
   scriptPubKey, amount.
3. Chain-context facts: height and median time past. Deliberately
   empty in v0: no rule in this document reads them, and the time
   asserts read the transaction's own fields instead.
4. Whole-transaction work: claim assignment, cross-input pairing,
   and facts of the assembled transaction's fields (version,
   locktime, and the spending inputs' sequences).
5. Batch signature verification over the collected
   (public key, message) pairs.

## Rules (in landing order)

### 1. Injective multiset output matching

An **output claim** is a pair (`scriptPubKey`, `amount`) demanded of
the transaction's outputs. Each vocabulary entry states whether it
produces a claim. CREATE_OUTPUT produces exactly one claim, its own
argument pair. CREATE_OUTPUT_TAPROOT produces exactly one claim, the
pair (`spk`, `amount`) its entry derives. Nothing in this document
distinguishes which entry produced a claim.

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

This rule is stage 4 work: its outcome depends on every BitLisp
input's claims and every output slot, so it is re-checked when
spends are recombined into a different transaction.

### 2. Mixed-transaction rule

This rule performs no computation and defines no error. It states
what the rest of this document must leave unconstrained, and it
binds future rules exactly as it binds the current ones.

A transaction may contain inputs that are not BitLisp inputs. They
produce no conditions, and no rule examines them beyond their
contribution to the transaction view. A transaction may contain
output slots that no claim consumes. Unconsumed slots are
unconstrained. Rule 1 states this for output claims, and this rule
extends it to every claim kind a future rule may define.

A transaction with no BitLisp inputs is subject to no rule in this
document.

A transaction is valid under this document if and only if every
condition of every BitLisp input is well-formed (the encoding
rules of `spec/CONDITIONS.md` and rule 6, the stage 1 checks),
every claim is assigned a satisfier, and every assert holds. No
other property of the transaction's inputs and output slots
affects validity under this document.

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

This rule is stage 1 work: it reads nothing beyond the condition
itself.

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
- Adding an output slot to a valid transaction never turns it
  invalid, and adding a non-BitLisp input never turns it invalid
  (rule 2, over the landed vocabulary: an entry whose assert reads
  a fact that additions change, such as a fee floor, re-scopes the
  slot half of this invariant when it lands, while the merge
  invariant below is permanent).
- Merge: two valid transactions consuming disjoint outpoints, with
  same-typed locktime fields, whose concatenation under the greater
  version and greater locktime the transaction view admits,
  concatenate into a valid transaction (composition guarantee).
- A transaction with no BitLisp inputs validates regardless of its
  shape (rule 2).
- Increasing any time assert's operand never turns an invalid
  transaction valid, and decreasing it never turns a valid
  transaction invalid: asserts are monotone in their operand
  (time asserts).
- Metamorphic: on a valid transaction with a time assert, flipping
  the read field across the relevant boundary causes rejection,
  with locktime moved across the type threshold, the sequence
  disable flag set, or version dropped below 2 (time asserts).
