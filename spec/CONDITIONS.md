# BitLisp Conditions

Status: in progress. Section 1, the CREATE_OUTPUT and
CREATE_OUTPUT_TAPROOT entries, the time assert family, and the
message family are normative. The remaining vocabulary v0 entries
land across Phase 2, each with semantics, arguments, cost,
validation rule reference, and a curation note per design
obligation 4.

A successful program evaluation yields a condition list. This document
specifies the encoding of that list and the meaning of each condition.
How conditions are matched against the transaction is specified in
[VALIDATION.md](VALIDATION.md).

## 1. Condition list encoding

A successful program evaluation yields a value that must satisfy every
rule in this section. Any violation invalidates the spend with the
error code named in parentheses. Every condition-layer error code is
named in this document or in VALIDATION.md at the rule that raises it.

The result must be a proper nil-terminated list (`bad_condition_list`).
Each element is one condition and must itself be a proper list with at
least one element (`bad_condition_list`).

The first element of a condition is its opcode. The opcode must be an
atom of exactly one byte (`bad_condition_opcode`). The opcode's value
selects one of three tiers:

| value | tier |
| --- | --- |
| `0x00` | invalid |
| `0x01` to `0x7f`, listed in the vocabulary table (section 2) | assigned |
| `0x01` to `0x7f`, not listed in the vocabulary table | invalid |
| `0x80` to `0xff` | reserved |

An invalid opcode invalidates the spend (`bad_condition_opcode`).

An assigned condition must have exactly the argument count its
vocabulary entry states (`bad_condition_arity`), and every argument
must satisfy its entry's type, encoding, and range rules
(`bad_condition_arg`). Arguments are atoms unless the entry states
otherwise. Integer arguments use the minimal integer encoding of
VM.md section 1 and are rejected if non-minimal (`bad_condition_arg`).

A reserved condition is accepted without enforcing any semantics,
under the shape rules of VALIDATION.md rule 6.

The vocabulary is laid out in family blocks. Codes inside a family
block without a vocabulary entry are invalid, not reserved:

| range | family |
| --- | --- |
| `0x01` to `0x0f` | output creation |
| `0x10` to `0x1f` | signatures |
| `0x20` to `0x2f` | time asserts |
| `0x30` to `0x3f` | self asserts |
| `0x40` to `0x4f` | messages |
| `0x50` to `0x5f` | fees and universal asserts |
| `0x60` to `0x7f` | unallocated, invalid |

## 2. Vocabulary v0

| opcode | condition |
| --- | --- |
| `0x01` | `CREATE_OUTPUT` |
| `0x02` | `CREATE_OUTPUT_TAPROOT` |
| `0x20` | `ASSERT_LOCKTIME_HEIGHT` |
| `0x21` | `ASSERT_LOCKTIME_TIME` |
| `0x22` | `ASSERT_SEQUENCE_HEIGHT` |
| `0x23` | `ASSERT_SEQUENCE_TIME` |
| `0x40` | `ANNOUNCE` |
| `0x41` | `ASSERT_ANNOUNCEMENT` |
| `0x42` | `SEND_MESSAGE` |
| `0x43` | `RECEIVE_MESSAGE` |

Planned entries, unassigned and invalid until their sections land:
the secp `AGG_SIG` family with program-composed messages, the
`ASSERT_MY_*` family, `RESERVE_FEE`, `ASSERT_OUTPUT_COUNT`, and
`ASSERT_FEE_LE`.

Every planned entry lands only in a shape the composition
guarantee in `spec/VALIDATION.md` permits. In their listed shapes,
`ASSERT_OUTPUT_COUNT` (an exact count) and `ASSERT_FEE_LE` (an
upper bound on a quantity that concatenation sums) are forbidden
by that guarantee, so each lands re-shaped or not at all, decided
at its design session.

### CREATE_OUTPUT (`0x01`)

`(0x01 scriptPubKey amount)`

**Semantics.** Claims one output slot of the containing transaction
whose content is exactly (`scriptPubKey`, `amount`). Asserts nothing.
Claims are matched injectively across the whole transaction
under VALIDATION.md rule 1: k conditions carrying identical content
require k distinct output slots. Two identical CREATE_OUTPUT conditions
from one input are two claims.

The `amount` is part of the demanded content, not a debit from the
spending input. Validation never tracks which input's value funds which
slot. Value conservation is enforced transaction-wide by Bitcoin's
base rules, and an input's own value is unrelated to the amounts its
conditions claim.

**Arguments.** `scriptPubKey` is an atom of 1 to 10,000 bytes. The
empty atom is rejected (`bad_condition_arg`). `amount` is a minimally
encoded integer with 0 <= amount <= 2,100,000,000,000,000 (MAX_MONEY,
in satoshis). Exactly two arguments, both atoms.

**Cost.** Assigned when VALIDATION.md rule 5 lands.

**Validation rule.** VALIDATION.md rule 1.

**Curation note.** Ported from Chia's CREATE_COIN, renamed because
the condition claims a transaction output slot and names no coin
type (decision recorded in the condition record), with two
deliberate changes,
recorded as divergences C1 and C2 in the condition record
(`docs/condition-record.md`). First, the argument is full script bytes
rather than a puzzle hash, because a Bitcoin output may carry any
scriptPubKey and exits to non-BitLisp outputs are ordinary. Second,
Chia's optional memo argument is declined in v0: its wallet-discovery
job does not exist under output-script scanning, and consensus-carried
bytes with no consensus meaning are a deliberate non-affordance
(design obligation 4). A memo-bearing variant remains reachable
through the reserved tier if evidence of need emerges.

### CREATE_OUTPUT_TAPROOT (`0x02`)

`(0x02 internal_key merkle_root amount)`

**Semantics.** Claims one output slot of the containing transaction
whose content is exactly (`spk`, `amount`). Asserts nothing. `spk` is
derived as follows:

- Let `P` be the secp256k1 point whose x coordinate is `internal_key`
  interpreted as a 32-byte big-endian integer and whose y coordinate
  is even. If no such point exists, the spend is invalid
  (`bad_condition_arg`).
- Let `t` be `tagged_hash("TapTweak", internal_key || merkle_root)`,
  where `tagged_hash(tag, m)` is `sha256(sha256(tag) || sha256(tag)
  || m)` with `tag` the ASCII bytes of the tag name. When
  `merkle_root` is the empty atom, the concatenation leaves
  `internal_key` alone and the tweak commits to no script tree.
- If `t`, interpreted as a 32-byte big-endian integer, is greater
  than or equal to the secp256k1 group order, the spend is invalid
  (`bad_condition_arg`).
- Let `Q = P + t*G`, where `G` is the secp256k1 generator. If `Q` is
  the point at infinity, the spend is invalid (`bad_condition_arg`).
- `spk` is the 34 bytes `0x51 0x20` followed by the x coordinate of
  `Q` as 32 big-endian bytes.

After derivation, the claim is indistinguishable from a
`CREATE_OUTPUT` claim of the same content. In particular, a
`CREATE_OUTPUT_TAPROOT` claim and a `CREATE_OUTPUT` claim whose
`scriptPubKey` bytes equal `spk` carry equal content, and k such
claims require k distinct output slots under VALIDATION.md rule 1,
regardless of which opcode produced each claim.

**Arguments.** `internal_key` is an atom of exactly 32 bytes and must
satisfy the point derivation above (`bad_condition_arg`).
`merkle_root` is an atom of exactly 0 or exactly 32 bytes
(`bad_condition_arg`). The empty atom means the output commits to no
script tree. `amount` is a minimally encoded integer with
0 <= amount <= 2,100,000,000,000,000 (MAX_MONEY, in satoshis).
Exactly three arguments, all atoms.

**Cost.** Assigned when VALIDATION.md rule 5 lands.

**Validation rule.** VALIDATION.md rule 1, after the derivation above.

**Curation note.** Neither output-creation condition is an output
type. Both produce the identical claim, and a taproot output with a
statically known key is created with plain CREATE_OUTPUT. This
condition exists so covenant recursion can construct a successor
taproot output when the program computes the internal key or tree
root dynamically, without giving the VM elliptic-curve arithmetic.
Two alternatives were declined, a general `secp256k1_muladd`
operator and a narrow `taptweak` operator, recorded as decision
D-CC2 in the condition record (`docs/condition-record.md`). The
derivation matches BIP341 output-key construction exactly,
including the key-only tweak when no script tree is committed.

### Time asserts (`0x20` to `0x23`)

The four conditions of this family assert facts about the
transaction's locktime machinery: the transaction-level `locktime`
field, the spending input's own `sequence` field, and the
transaction's `version`. Base consensus already enforces these
fields against the chain, so a satisfied assert means the chain
rules themselves prevent early confirmation. No condition in this
family reads the chain, and validation remains a pure function of
the transaction.

Shared definitions, matching base consensus exactly:

- The `locktime` field is **height-typed** if its value is below
  500,000,000 and **time-typed** (Unix seconds) otherwise.
- The spending input's sequence is **final** if it equals
  `0xffffffff`. Base consensus ignores `locktime` when every input
  is final, so each locktime assert requires its own input to be
  non-final, which alone guarantees enforcement.
- A sequence encodes a relative lock in three parts: bit 31 is the
  **disable flag** (set means no relative lock), bit 22 is the
  **type flag** (clear means the value counts blocks, set means it
  counts 512-second units), and the low 16 bits are the **value**.
  Base consensus enforces relative locks only when the disable
  flag is clear and the transaction's version is at least 2.

Failure of a locktime assert is the error
`unsatisfied_locktime_assert`. Failure of a sequence assert is the
error `unsatisfied_sequence_assert`.

This family is stage 4 work: every assert reads a
transaction-level field (`locktime` or `version`), so its outcome
can change when spends are recombined into a different
transaction. The composition guarantee states the discipline under
which recombination preserves it.

**Family curation note.** The family ports Chia's four timelock
asserts in the enforcement shape of Bitcoin's own locktime
machinery rather than Chia's direct chain reads: conditions
constrain the transaction's fields and deployed consensus enforces
the fields, so this layer adds no chain-reading surface (decision
15 in the condition record, with the declined direct-read shape
and its reversibility argument). The type lives in the condition
code and the operand is a plain quantity, so the field bit layouts
appear only in the definitions above, never in arguments. Chia's
ASSERT_BEFORE family is declined: this shape cannot express
expiring validity, and that is deliberate (decision 15). The
before-threshold operand domains make a mistyped operand
malformed at stage 1 rather than unsatisfiable at stage 4.

### ASSERT_LOCKTIME_HEIGHT (`0x20`)

`(0x20 height)`

**Semantics.** Claims nothing. Asserts all of the following, with
`unsatisfied_locktime_assert` on violation:

- the spending input's own sequence is not final,
- the transaction's `locktime` is height-typed,
- `locktime` >= `height`.

**Arguments.** `height` is a minimally encoded integer with
0 <= height < 500,000,000 (`bad_condition_arg`). Exactly one
argument, an atom.

**Cost.** Assigned when VALIDATION.md rule 5 lands.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 4.

**Curation note.** Ported from Chia's ASSERT_HEIGHT_ABSOLUTE,
re-based from a chain read to the `locktime` field that
OP_CHECKLOCKTIMEVERIFY constrains, including its non-final
sequence requirement and its same-type rule. Divergence rows in
the condition record.

### ASSERT_LOCKTIME_TIME (`0x21`)

`(0x21 time)`

**Semantics.** Claims nothing. Asserts all of the following, with
`unsatisfied_locktime_assert` on violation:

- the spending input's own sequence is not final,
- the transaction's `locktime` is time-typed,
- `locktime` >= `time`.

**Arguments.** `time` is a minimally encoded integer with
500,000,000 <= time <= 4,294,967,295 (`bad_condition_arg`).
Exactly one argument, an atom.

**Cost.** Assigned when VALIDATION.md rule 5 lands.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 4.

**Curation note.** Ported from Chia's ASSERT_SECONDS_ABSOLUTE.
The wall-clock semantics are whatever base consensus gives
`locktime`, median time past under current rules, so this layer
neither defines nor reads a clock. Kept despite the height-first
design stance: the field is part of Bitcoin's spend schema and
scripts constrain it today, so declining it removes no surface
and opens a calendar-deadline expressiveness hole (decision 15).

### ASSERT_SEQUENCE_HEIGHT (`0x22`)

`(0x22 blocks)`

**Semantics.** Claims nothing. Asserts all of the following, with
`unsatisfied_sequence_assert` on violation:

- the transaction's `version` is at least 2, compared unsigned as
  the transaction view defines the field,
- the spending input's own sequence has the disable flag clear,
- that sequence's type flag is clear (the value counts blocks),
- that sequence's value is at least `blocks`.

**Arguments.** `blocks` is a minimally encoded integer with
0 <= blocks <= 65,535 (`bad_condition_arg`). Exactly one
argument, an atom.

**Cost.** Assigned when VALIDATION.md rule 5 lands.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 4.

**Curation note.** Ported from Chia's ASSERT_HEIGHT_RELATIVE,
re-based to the sequence field that OP_CHECKSEQUENCEVERIFY
constrains, anchored at prevout confirmation by those deployed
rules. The 16-bit range is inherited and recorded as a
divergence. The operand cannot express OP_CSV's disabled no-op
form: a program wanting no relative lock omits the condition.

### ASSERT_SEQUENCE_TIME (`0x23`)

`(0x23 units)`

**Semantics.** Claims nothing. Asserts all of the following, with
`unsatisfied_sequence_assert` on violation:

- the transaction's `version` is at least 2, compared unsigned as
  the transaction view defines the field,
- the spending input's own sequence has the disable flag clear,
- that sequence's type flag is set (the value counts 512-second
  units),
- that sequence's value is at least `units`.

**Arguments.** `units` is a minimally encoded integer with
0 <= units <= 65,535, counting 512-second units
(`bad_condition_arg`). Exactly one argument, an atom.

**Cost.** Assigned when VALIDATION.md rule 5 lands.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 4.

**Curation note.** Ported from Chia's ASSERT_SECONDS_RELATIVE.
The operand counts the field's own 512-second units, compared
unit for unit with no arithmetic in the validator. Conversion
from seconds is tooling's job.

### Message family (`0x40` to `0x43`)

The four conditions of this family coordinate the inputs of a
single transaction. The addressed pair produces the message
records of VALIDATION.md rule 3, a demand that a matching
counterpart condition exist in the same transaction. The broadcast
pair produces and reads announcements, ordinary asserts over facts
other inputs create. Nothing in this family outlives the
transaction. This family is the first vocabulary that constrains
the transaction outside the claim and assert sorts, and the first
whose conditions' removal from a valid transaction can invalidate
it: a lone half of a pair, or the only announcement an assert
reads.

Descriptor operands, consumed in the order VALIDATION.md rule 3's
descriptor table states for the commitment value:

- `txid` is an atom of exactly 32 bytes (`bad_condition_arg`).
- `scriptPubKey` is an atom of 0 to 10,000 bytes
  (`bad_condition_arg`). A prevout may carry any script base
  consensus accepts, including the empty script, so the empty
  atom is a valid descriptor operand here even though
  CREATE_OUTPUT rejects it as claim content. A prevout whose
  script exceeds the bound is addressable by its other fields.
- `amount` is a minimally encoded integer with
  0 <= amount <= 2,100,000,000,000,000 (MAX_MONEY, in satoshis)
  (`bad_condition_arg`).
- `outpoint` is an atom of exactly 36 bytes: the consumed
  outpoint's 32 txid bytes followed by its 32-bit index in
  little-endian byte order, the wire serialization
  (`bad_condition_arg`).

`message`, `namespace`, and `payload` are atoms of 0 to 1024 bytes
(`bad_condition_arg`).

Argument checks run in a fixed order, pinned by vectors: an
argument count below the entry's minimum (two for the addressed
pair, three for the assert) rejects first, then the mode, then the
mode-dependent exact count, then each operand in the order the
entry states.

**Family curation note.** The addressed pair ports Chia's
SEND_MESSAGE and RECEIVE_MESSAGE with their opcodes numerically
intact (66 and 67 are `0x42` and `0x43`), their full mode
geometry, and their counted balance, re-addressed to Bitcoin
prevout data: parent coin id becomes the creating txid, puzzle
hash becomes the spent scriptPubKey carried as raw bytes, coin id
becomes the outpoint. Scope narrows from Chia's block to the
transaction, because a Bitcoin transaction must be valid on its
own. Arity is strict everywhere, where deployed Chia enforces
arity only in its mempool. The broadcast pair replaces Chia's four
announcement conditions with two: the announcer carries its full
prevout data and the assert side picks its precision through the
descriptor grammar, so the coin and puzzle flavors are commitment
values 7 and 2 of one condition, and the namespace is a
first-class operand rather than a payload prefix convention. Both
pairs are kept because they solve different jobs: a message is a
handshake whose sender must know its audience exactly, an
announcement is posted once and read by any number of asserts,
including zero. All divergence rows and the full rationale are in
the condition record (decision 16).

### ANNOUNCE (`0x40`)

`(0x40 namespace payload)`

**Semantics.** Claims nothing, asserts nothing, and contributes no
message record. Creates the announcement (announcing input,
`namespace`, `payload`) that ASSERT_ANNOUNCEMENT reads under
VALIDATION.md rule 3. The announcing input is carried with its
full prevout data, so an assert at any commitment value can match
it. An announcement no assert reads constrains nothing.

**Arguments.** `namespace` and `payload` are atoms of 0 to 1024
bytes (`bad_condition_arg`). Exactly two arguments, both atoms.

**Cost.** Assigned when VALIDATION.md rule 5 lands.

**Validation rule.** VALIDATION.md rule 3 (announcements). Stage 4.

**Curation note.** Replaces Chia's CREATE_COIN_ANNOUNCEMENT and
CREATE_PUZZLE_ANNOUNCEMENT with one condition: the announcer
carries its full prevout data and the assert side picks the
precision, so the create side needs no flavors. The namespace is a
first-class operand, replacing the payload prefix convention, a
ratified safety decision upheld against the match-by-default
policy (decision 16). Kept beside the addressed pair on deployed
evidence: Chia's offer settlement, singleton launcher, and
post-message custody puzzles all still build on announcements.

### ASSERT_ANNOUNCEMENT (`0x41`)

`(0x41 mode namespace payload announcer...)`

**Semantics.** Claims nothing. Asserts that some input of the
transaction carries an ANNOUNCE condition whose `namespace` and
`payload` equal this condition's operands byte-exact, and whose
self descriptor at `mode` equals the argument descriptor built
from `announcer...`. Any number of asserts, from one input or
many, may read the same announcement. Violation is
`unsatisfied_announcement_assert`.

**Arguments.** `mode` is a minimally encoded integer with
0 <= mode <= 7, a commitment value (`bad_condition_arg`).
`namespace` and `payload` are atoms of 0 to 1024 bytes. Then the
descriptor operands rule 3's table states for `mode`, in table
order. Exactly 3 + n arguments, where n is the mode's operand
count (`bad_condition_arity`).

**Cost.** Assigned when VALIDATION.md rule 5 lands.

**Validation rule.** VALIDATION.md rule 3 (announcements). Stage 4.

**Curation note.** Replaces Chia's ASSERT_COIN_ANNOUNCEMENT and
ASSERT_PUZZLE_ANNOUNCEMENT, whose flavors survive as commitment
values 7 and 2 of one condition, generalized to the remaining
precisions by the shared descriptor grammar. Commitment value 0 is
the fully unaddressed read.

### SEND_MESSAGE (`0x42`)

`(0x42 mode message receiver...)`

**Semantics.** Contributes weight +1 to the message record (self
descriptor at the sender half of `mode`, argument descriptor at
the receiver half, `message`) in the ledger of VALIDATION.md rule
3. Claims nothing and asserts nothing. The sender half always
describes the emitting input, filled from its own prevout data,
never from operands. The ledger must balance exactly, so a send
without its receive invalidates the transaction
(`unbalanced_message`): this condition demands as much as it
offers.

**Arguments.** `mode` is a minimally encoded integer with
0 <= mode <= 63 (`bad_condition_arg`). Its high three bits are the
sender half and its low three bits the receiver half, both
commitment values. `message` is an atom of 0 to 1024 bytes. Then
the descriptor operands rule 3's table states for the receiver
half, in table order. Exactly 2 + n arguments, where n is the
receiver half's operand count (`bad_condition_arity`).

**Cost.** Assigned when VALIDATION.md rule 5 lands.

**Validation rule.** VALIDATION.md rule 3 (the message ledger).
Stage 4.

**Curation note.** Ported from Chia's SEND_MESSAGE with the opcode
numerically intact (66 is `0x42`), the full mode geometry, and the
counted balance. The re-addressing, the transaction scope, and the
strict arity are the family's recorded divergences (decision 16).

### RECEIVE_MESSAGE (`0x43`)

`(0x43 mode message sender...)`

**Semantics.** Contributes weight -1 to the message record
(argument descriptor at the sender half of `mode`, self descriptor
at the receiver half, `message`) in the ledger of VALIDATION.md
rule 3. Claims nothing and asserts nothing. The receiver half
always describes the emitting input, filled from its own prevout
data, never from operands. The ledger must balance exactly, so a
receive without its send invalidates the transaction
(`unbalanced_message`).

**Arguments.** As for SEND_MESSAGE with the halves' roles
exchanged: `mode` 0 to 63, `message` an atom of 0 to 1024 bytes,
then the descriptor operands for the sender half, in table order.
Exactly 2 + n arguments, where n is the sender half's operand
count (`bad_condition_arity`).

**Cost.** Assigned when VALIDATION.md rule 5 lands.

**Validation rule.** VALIDATION.md rule 3 (the message ledger).
Stage 4.

**Curation note.** Ported from Chia's RECEIVE_MESSAGE with the
opcode numerically intact (67 is `0x43`). The pair shares the
family's divergence rows: every divergence of SEND_MESSAGE is a
divergence of this condition too.
