# BitLisp Condition Validation

Status: in progress. The transaction view, the claims-and-asserts
principle, the validation stages, and rules 1, 2, 3, 4, 6, and 7
are normative. Rule 5 is designed in architecture sessions, lands
here as prose first, and only then gets implemented. Ground rule 4:
this layer gets invariants and adversarial vectors before any feature
work.

This document specifies how a validated spend's condition list is checked
against the containing Bitcoin transaction. The per-condition rules,
each condition's arguments, their domains, and what it produces, are
specified in [CONDITIONS.md](CONDITIONS.md).

Target property: a reviewer who has read only this document can predict
the outcome of every vector in `vectors/validation/`.

Every rule names the error code its violation raises. A
transaction that violates exactly one rule of the condition layer
is rejected with that rule's code, and vectors pin the code. A
transaction that violates more than one rule is invalid under
each of them, and an implementation conforms by rejecting it with
any violated rule's code. Rejection is the consensus outcome, the
code is diagnostic, and no vector pins the code of a transaction
violating more than one rule.

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

A condition constrains the transaction through claims, asserts,
message records, and fee reserves, and in no other way. Each
vocabulary entry in `spec/CONDITIONS.md` states which of these it
produces. An entry may produce none: rule 6's reserved conditions
constrain nothing.

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
- A **message record** is a weighted entry, +1 or -1, in a
  per-transaction ledger that rule 3 defines and requires to
  balance exactly. Its counterpart is another condition, not a
  transaction resource, so it is neither a claim nor an assert.
  Satisfaction is consumed one for one as with a claim, but both
  directions demand: an unmatched send and an unmatched receive
  are equally invalid.
- A **fee reserve** demands that the transaction's fee reach a
  quantity. Reserves are counted, not idempotent: rule 7 sums
  every reserve of every BitLisp input and compares the fee
  against the total once. A reserve consumes no resource and is
  assigned no satisfier: the same fee covers every reserve
  jointly by covering their sum.

The implication runs one way only. No rule in this document
constrains a part of the transaction that no condition claims,
reads, records, or reserves against. An input that is not a
BitLisp input, a fact no assert reads, and the content of an
output slot no claim consumes are all unconstrained. When a
reserve is present, rule 7 reads every input's and every slot's
amount through the fee. Rule 2 states the consequences.

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
today. The message ledger of rule 3 preserves this guarantee
arithmetically: concatenation adds the two ledgers, and sums of
zeros are zero. The fee reserve of rule 7 preserves it the same
way: fees are non-negative and sum under concatenation, reserves
sum, so two covered reserves concatenate into a covered reserve.
Relaxing this paragraph changes what wallets may
safely batch and requires a recorded design decision.

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
   facts of the assembled transaction's fields (version,
   locktime, and the spending inputs' sequences), and quantities
   derived from the assembled transaction (the fee).
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
every claim is assigned a satisfier, every assert holds, the
message ledger of rule 3 balances, and the fee covers rule 7's
reserve. No other property of the transaction's inputs and output
slots affects validity under this document.

### 3. Message scoping

This rule defines the message ledger, the one structure in this
document where two conditions satisfy each other, and the
announcement facts that ASSERT_ANNOUNCEMENT reads. Everything in
this rule is scoped to the containing transaction. No message or
announcement exists outside it.

**Participant specifiers.** A specifier identifies an input's
prevout data at a chosen precision. It is a commitment value from
0 to 7 together with the fields that value commits to:

| commitment value | committed fields | operands, in order |
| --- | --- | --- |
| 0 | none | none |
| 1 | `amount` | `amount` |
| 2 | `scriptPubKey` | `scriptPubKey` |
| 3 | `scriptPubKey` and `amount` | `scriptPubKey`, `amount` |
| 4 | creating txid | `txid` |
| 5 | creating txid and `amount` | `txid`, `amount` |
| 6 | creating txid and `scriptPubKey` | `txid`, `scriptPubKey` |
| 7 | the outpoint | `outpoint` |

The creating txid of an input is the txid half of the outpoint it
consumes: the transaction that created a coin is the transaction
its outpoint names. Commitment value 7 commits to the whole
outpoint as a single 36-byte value and is a distinct specifier,
not the union of the other bits.

Two specifiers are equal if and only if their commitment values
are equal and their committed fields are equal, byte-exact for
scripts, txids, and outpoints, numeric for amounts.

The **self specifier** of an input at commitment value m fills
the committed fields from that input's own prevout data in the
transaction view. The **argument specifier** fills them from
condition operands, in the operand order the table states.

**The message ledger.** Each SEND_MESSAGE condition of an input
contributes weight +1 to the record (self specifier of that input
at the mode's sender half, argument specifier at the receiver
half, `message`). Each RECEIVE_MESSAGE condition of an input
contributes weight -1 to the record (argument specifier at the
sender half, self specifier of that input at the receiver half,
`message`). The sender half of the six-bit mode is its high three
bits and the receiver half its low three bits.

The message ledger balances if and only if the
weights of every distinct record sum to zero, and a transaction
whose ledger does not balance is invalid, with the error
`unbalanced_message`. The announcements below are asserts and are
checked as asserts, not through the ledger.

Consequences, each pinned by vectors:

- k identical sends require exactly k identical receives, and the
  reverse. One send cannot satisfy two receives.
- A send and a receive may come from the same input, including one
  input carrying both halves of its own pair.
- The ledger is a sum, so input order and condition order never
  affect the outcome.
- A send whose receiver specifier matches no input's self
  specifier can never balance, because only a receive from a
  matching input produces the equal record.
- Two independently balanced groups of inputs stay balanced when
  spent together, even when their records collide.

**Binding stability.** Every committed field carries a
recombination-stability class:

| committed field | knowable before the creating transaction exists | survives reassembly of an unconfirmed creator |
| --- | --- | --- |
| `amount` | yes | yes |
| `scriptPubKey` | yes | yes |
| creating txid | no | no |
| `outpoint` | no | no |

For an input whose creating transaction is confirmed, every field
is fixed and any mode is safe. The classes separate content, which
a program written before its counterpart exists can commit to,
from location, which exists only once the creating transaction is
final.

**Guidance for program authors (not consensus).** A loose
commitment is a loose lock. A specifier at commitment value 0, or
one committing only to content fields, is matched by any input
whose prevout data fits, including an input an adversary supplies:
the argument specifier is chosen by the emitting program, and
every self specifier is honest by construction, so nothing stops
a third party from spending an input of their own that fits a
loose description. A program using the addressed pair or an
announcement assert to authenticate a specific counterpart can
rely on it only by committing to that counterpart's identity
fields, txid or outpoint, once the counterpart is confirmed. A
program embedded in a coin whose counterpart may still be
reassembled can only safely address by content fields, and it
accepts the substitution exposure that choice implies.

**Announcements.** Each ANNOUNCE condition of an input creates the
announcement (that input, `namespace`, `payload`). An
ASSERT_ANNOUNCEMENT condition asserts that some single input
carries an ANNOUNCE condition whose `namespace` and `payload`
equal the assert's operands byte-exact, and that the same input's
self specifier at the assert's commitment value equals the
argument specifier. This is an ordinary assert:
it reads a fact of the transaction view, consumes nothing, and any
number of asserts may read the same announcement. An announcement
no assert reads constrains nothing. Violation is the error
`unsatisfied_announcement_assert`.

This rule is stage 4 work: records and announcements combine data
across inputs, so outcomes change when spends are recombined into
a different transaction.

### 4. Duplicates and multiplicity

Two conditions are identical when their opcodes are equal and
their operands are equal, operand by operand, equal as trees with
corresponding atoms byte-exact. Identity is a property of the
condition alone. What a condition contributes may still depend on
the input that carries it: rule 3's self specifiers make
identical SEND_MESSAGE conditions of different inputs contribute
distinct records, and an assert's fact may read the carrying
input's own fields.

The validator never merges, deduplicates, or collapses
conditions: every occurrence, identical or not, within one input
or across inputs, is checked by the rules of this document
individually.

What duplication means follows from what the condition produces,
as its entry in `spec/CONDITIONS.md` states:

- **Claims are counted.** Each occurrence, in one input or many,
  produces its own claim, and validation assigns every claim its
  own satisfier: k identical CREATE_OUTPUT conditions demand k
  output slots of the claimed content under rule 1.
- **Message records are counted.** Each occurrence contributes
  its own weight to rule 3's ledger: duplicating one half of a
  balanced pair unbalances it.
- **Fee reserves are counted.** Each occurrence adds its operand
  to rule 7's total: duplicating a reserve doubles the demand.
- **Asserts are idempotent within their input.** An assert reads
  a fact and consumes nothing, so identical occurrences in one
  input's condition list hold or fail together. Identical
  occurrences in different inputs each read their own carrying
  input's fields, and diverge where those fields do: an assert
  reading the carrying input's sequence can hold in one input
  and fail in another. Occurrences with differing operands are
  checked independently, and the transaction is valid only if
  every one holds.
- **A condition producing no claim, assert, record, or reserve
  constrains nothing.** Identical ANNOUNCE occurrences within one input
  create one fact, so duplicating an ANNOUNCE within its input
  never changes any assert's outcome. ANNOUNCE conditions of
  different inputs create distinct facts under rule 3, whatever
  their operands. A reserved condition's occurrences each charge
  their declared cost under rule 6.

This classification binds future rules. An entry whose
occurrences must accumulate is defined to produce claims,
records, or reserves, never asserts. An entry defined as an assert commits to
idempotence within its input: no meaning may attach to how many
times it occurs in one condition list.

Every occurrence enters the spend's cost accounting individually,
under the accounting rule 5 defines, and a condition's charge may
never depend on whether the condition is identical to another.
This rule constrains pricing in no other way.

Like rule 2, this rule performs no computation and defines no
error. Every check a duplicate triggers, and every error it can
produce, belongs to the rule governing what the condition
produces.

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

### 7. The fee reserve

The transaction's **fee** is the sum of every input's amount
minus the sum of every output slot's amount. Every input and
every slot contributes, BitLisp or not, claimed or not. The
transaction view's preconditions make the fee well-defined and
non-negative.

Each RESERVE_FEE condition of a BitLisp input produces a **fee
reserve** of its operand's value. The transaction is valid under
this rule if and only if the fee is at least the sum of all fee
reserves (`insufficient_fee`). The sum and the comparison are
exact integer arithmetic: no width bounds them, and a sum no fee
can reach fails the comparison like any other. A transaction with
no fee reserve satisfies this rule: the fee is at least the empty
sum.

This rule is stage 4 work: the fee reads every input's amount and
every output slot's amount, so the outcome changes when spends
are recombined into a different transaction.

## Invariants

The `hypothesis` suite in `python/tests/` must enforce the following
over generated transactions. Each invariant names the rule that makes
it enforceable, and lands with that rule:

- Value conservation on every accepted transaction (transaction view,
  enforced as a model precondition).
- No output satisfies two conditions, k identical claims require k
  distinct slots (rule 1).
- Validation is invariant under input reordering, output reordering,
  and condition-list reordering (rules 1 and 3).
- Removing a condition from a valid transaction never turns it
  invalid, and adding a condition to an invalid transaction never
  turns it valid: constraints only tighten (rule 1, scoped to claim
  and assert conditions: rule 3's family is the recorded exemption,
  a lone message half invalidates, a removed announcement can
  invalidate, an added one can validate, with its own invariants
  below).
- Removing a claimed output from a transaction whose claims exactly
  cover that output's content turns it invalid (rule 1).
- Metamorphic: mutating the content of any exactly-claimed output
  (amount off by one, script byte flip) causes rejection (rule 1).
- Adding an output slot to a valid transaction carrying no fee
  reserve never turns it invalid, and adding a non-BitLisp input
  never turns it invalid: an added slot never raises the fee,
  an added input never lowers it (rules 2 and 7, the merge
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
- A self assert's outcome is unchanged by the transaction's
  version, locktime, its input's sequence, and the presence of
  unrelated inputs: the outcome is a function of the condition and
  its input's own prevout data alone (self asserts).
- Whenever an ASSERT_MY_OUTPOINT is satisfied, the ASSERT_MY_TXID
  built from its operand's first 32 bytes is satisfied on the same
  input (self asserts).
- A lone self assert is satisfied exactly when its operand equals
  the field it reads, failing otherwise with its field's error
  (self asserts).
- ASSERT_MY_TAPROOT and an ASSERT_MY_SCRIPTPUBKEY carrying its
  derived scriptPubKey produce identical outcomes on every input
  (self asserts).
- Adding a balanced send and receive pair to a valid transaction
  keeps it valid, and adding either half alone invalidates it
  (rule 3).
- Adding an ANNOUNCE to a valid transaction never invalidates it,
  and removing the only announcement an assert reads invalidates
  it (rule 3).
- Metamorphic: flipping any byte of a message payload, a
  namespace, or a committed specifier field of the only balancing
  pair causes rejection (rule 3).
- Duplicating any assert, ANNOUNCE, or reserved condition within
  its input's condition list never changes the outcome: valid
  stays valid, invalid stays invalid (rule 4, over the costless
  v0: rule 5's budget re-scopes this to outcomes below the cost
  ceiling when it lands). Copying a condition to a different
  input is not duplication in this sense: the copy reads its own
  input's fields and creates its own facts.
- Increasing a fee reserve's operand never turns an invalid
  transaction valid, and decreasing it never turns a valid
  transaction invalid (rule 7).
- Replacing a fee reserve with two whose operands sum to it,
  within one input or split across two BitLisp inputs, never
  changes the outcome (rule 7).
- Metamorphic: on a valid transaction whose fee equals its
  summed reserve, raising any reserve operand by one causes
  rejection (rule 7).
- Metamorphic: on a valid transaction whose fee equals its
  summed reserve, appending an output slot of positive amount
  causes rejection (rule 7).
