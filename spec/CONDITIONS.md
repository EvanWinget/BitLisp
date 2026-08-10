# BitLisp Conditions

Status: normative and complete for v0. Every entry carries its
semantics, arguments, cost line, and validation rule reference.
Costs are charged under the accounting and charge order of
VALIDATION.md rule 5, with the constants in COSTS.md section 10.

A successful program evaluation yields a condition list. This document
specifies the encoding of that list and the per-condition rules: each
condition's arguments, their domains, and the claims, asserts,
message records, or fee reserves it produces. Everything that combines conditions
across inputs, checking them against the containing transaction, is
specified in [VALIDATION.md](VALIDATION.md).

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
| `0x10` to `0x1f` | signature asserts |
| `0x20` to `0x2f` | time asserts |
| `0x30` to `0x3f` | self asserts |
| `0x40` to `0x4f` | messages |
| `0x50` to `0x5f` | fees |
| `0x60` to `0x6f` | seals |
| `0x70` to `0x7f` | unallocated, invalid |

## 2. Vocabulary v0

| opcode | condition |
| --- | --- |
| `0x01` | `CREATE_OUTPUT` |
| `0x02` | `CREATE_OUTPUT_TAPROOT` |
| `0x10` | `ASSERT_SIG_MY_TXID` |
| `0x11` | `ASSERT_SIG_MY_SCRIPTPUBKEY` |
| `0x12` | `ASSERT_SIG_MY_AMOUNT` |
| `0x13` | `ASSERT_SIG_MY_SCRIPTPUBKEY_AMOUNT` |
| `0x14` | `ASSERT_SIG_MY_TXID_AMOUNT` |
| `0x15` | `ASSERT_SIG_MY_TXID_SCRIPTPUBKEY` |
| `0x16` | `ASSERT_SIG_RAW` |
| `0x17` | `ASSERT_SIG_MY_OUTPOINT` |
| `0x20` | `ASSERT_LOCKTIME_HEIGHT` |
| `0x21` | `ASSERT_LOCKTIME_TIME` |
| `0x22` | `ASSERT_SEQUENCE_HEIGHT` |
| `0x23` | `ASSERT_SEQUENCE_TIME` |
| `0x30` | `ASSERT_MY_OUTPOINT` |
| `0x31` | `ASSERT_MY_TXID` |
| `0x32` | `ASSERT_MY_SCRIPTPUBKEY` |
| `0x33` | `ASSERT_MY_AMOUNT` |
| `0x37` | `ASSERT_MY_TAPROOT` |
| `0x40` | `ANNOUNCE` |
| `0x41` | `ASSERT_ANNOUNCEMENT` |
| `0x42` | `SEND_MESSAGE` |
| `0x43` | `RECEIVE_MESSAGE` |
| `0x50` | `RESERVE_FEE` |
| `0x60` | `SEAL` |
| `0x61` | `SEAL_OUTPUTS` |

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

**Cost.** `CREATE_OUTPUT_COST` = 1,350,000 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** VALIDATION.md rule 1.

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

**Cost.** `CREATE_OUTPUT_COST + TAPROOT_TWEAK_COST` = 2,650,000
(COSTS.md section 10), charged after every argument check and
before the point derivation.

**Validation rule.** VALIDATION.md rule 1, after the derivation above.

### Signature asserts (`0x10` to `0x17`)

The eight conditions of this family assert that a BIP340 Schnorr
signature over secp256k1 accompanies the spend. Each carries three
operands, a public key, a message, and a signature, and is
satisfied exactly when the signature verifies for the public key
over the digest its entry defines. Verification is BIP340's
Verify algorithm, the relation VM.md's `secp_verify` entry pins
for a non-empty signature.
Every condition of this family is an assert: it claims nothing,
consumes nothing, and reads only its own operands and the carrying
input's own prevout data in the transaction view.

The digest of the variant with tag `tag` and binding data
`binding` is

`digest = tagged_hash(tag, binding || message)`

where `tagged_hash` is as defined in the CREATE_OUTPUT_TAPROOT
entry, `tag` is the ASCII bytes of the tag string, and `||` is
byte concatenation. Every binding field is fixed-length and
precedes the variable-length message, so equal digests imply
equal binding fields and equal messages.

| opcode | condition | tag | binding data |
| --- | --- | --- | --- |
| `0x10` | `ASSERT_SIG_MY_TXID` | `BitLisp/sig/my_txid` | `txid` |
| `0x11` | `ASSERT_SIG_MY_SCRIPTPUBKEY` | `BitLisp/sig/my_scriptpubkey` | `spk_hash` |
| `0x12` | `ASSERT_SIG_MY_AMOUNT` | `BitLisp/sig/my_amount` | `amount8` |
| `0x13` | `ASSERT_SIG_MY_SCRIPTPUBKEY_AMOUNT` | `BitLisp/sig/my_scriptpubkey_amount` | `spk_hash \|\| amount8` |
| `0x14` | `ASSERT_SIG_MY_TXID_AMOUNT` | `BitLisp/sig/my_txid_amount` | `txid \|\| amount8` |
| `0x15` | `ASSERT_SIG_MY_TXID_SCRIPTPUBKEY` | `BitLisp/sig/my_txid_scriptpubkey` | `txid \|\| spk_hash` |
| `0x16` | `ASSERT_SIG_RAW` | `BitLisp/sig/raw` | empty |
| `0x17` | `ASSERT_SIG_MY_OUTPOINT` | `BitLisp/sig/my_outpoint` | `outpoint` |

Binding fields, each read from the carrying input's own prevout
data in the transaction view:

- `txid` is the 32 txid bytes of the consumed outpoint, the
  creating txid as the ASSERT_MY_TXID entry defines it.
- `spk_hash` is the sha256 of the spent output's scriptPubKey,
  32 bytes.
- `amount8` is the spent output's amount as 8 bytes in
  little-endian byte order.
- `outpoint` is the consumed outpoint's 36 wire-serialization
  bytes: the 32 txid bytes followed by the 32-bit index in
  little-endian byte order.

ASSERT_SIG_RAW's binding data is empty: its digest commits to the
message alone, under its own tag.

The binding fields commit to the same prevout data as the
participant specifiers of VALIDATION.md rule 3 and carry the
recombination-stability classes stated there: amount and
scriptPubKey are knowable when a program is written, the creating
txid and the outpoint exist only once the creating transaction is
final.

**Arguments, all eight entries.** `pubkey` is an atom of exactly
32 bytes, an x-only public key. `message` is an atom of 0 to 1024
bytes. `signature` is an atom of exactly 64 bytes. Any violation
is `bad_condition_arg`. Exactly three arguments, in the order
`pubkey`, `message`, `signature`, all atoms. Argument checks run
in a fixed order, pinned by vectors: the argument count rejects
first (`bad_condition_arity`), then each operand in the order
above.

Failure of verification is the error `unsatisfied_sig_assert`. A
`pubkey` whose x coordinate lifts to no curve point fails
verification with that error, as the `secp_verify` relation
defines: it is not an operand shape defect.

**Cost, all eight entries.** `CONDITION_SIG_ASSERT_COST` =
1,300,000 (COSTS.md section 10), charged after every argument
check. Verification runs in stage 5, after the charge.

**Validation rule, all eight entries.** The assert clause of
VALIDATION.md (claims and asserts, rule 2), checked under
VALIDATION.md rule 8. Stage 5.

### ASSERT_SIG_MY_TXID (`0x10`)

`(0x10 pubkey message signature)`

**Semantics.** Claims nothing. Asserts that `signature` is a
valid signature by `pubkey` over the family digest at tag
`BitLisp/sig/my_txid` with binding data the carrying input's
creating txid (`unsatisfied_sig_assert`). Arguments, cost, and
validation rule as the family preamble states.

### ASSERT_SIG_MY_SCRIPTPUBKEY (`0x11`)

`(0x11 pubkey message signature)`

**Semantics.** Claims nothing. Asserts that `signature` is a
valid signature by `pubkey` over the family digest at tag
`BitLisp/sig/my_scriptpubkey` with binding data the sha256 of the
spent output's scriptPubKey (`unsatisfied_sig_assert`).
Arguments, cost, and validation rule as the family preamble
states.

### ASSERT_SIG_MY_AMOUNT (`0x12`)

`(0x12 pubkey message signature)`

**Semantics.** Claims nothing. Asserts that `signature` is a
valid signature by `pubkey` over the family digest at tag
`BitLisp/sig/my_amount` with binding data the spent output's
amount as 8 little-endian bytes (`unsatisfied_sig_assert`).
Arguments, cost, and validation rule as the family preamble
states.

### ASSERT_SIG_MY_SCRIPTPUBKEY_AMOUNT (`0x13`)

`(0x13 pubkey message signature)`

**Semantics.** Claims nothing. Asserts that `signature` is a
valid signature by `pubkey` over the family digest at tag
`BitLisp/sig/my_scriptpubkey_amount` with binding data `spk_hash`
then `amount8` of the carrying input (`unsatisfied_sig_assert`).
Arguments, cost, and validation rule as the family preamble
states.

### ASSERT_SIG_MY_TXID_AMOUNT (`0x14`)

`(0x14 pubkey message signature)`

**Semantics.** Claims nothing. Asserts that `signature` is a
valid signature by `pubkey` over the family digest at tag
`BitLisp/sig/my_txid_amount` with binding data `txid` then
`amount8` of the carrying input (`unsatisfied_sig_assert`).
Arguments, cost, and validation rule as the family preamble
states.

### ASSERT_SIG_MY_TXID_SCRIPTPUBKEY (`0x15`)

`(0x15 pubkey message signature)`

**Semantics.** Claims nothing. Asserts that `signature` is a
valid signature by `pubkey` over the family digest at tag
`BitLisp/sig/my_txid_scriptpubkey` with binding data `txid` then
`spk_hash` of the carrying input (`unsatisfied_sig_assert`).
Arguments, cost, and validation rule as the family preamble
states.

### ASSERT_SIG_RAW (`0x16`)

`(0x16 pubkey message signature)`

**Semantics.** Claims nothing. Asserts that `signature` is a
valid signature by `pubkey` over the family digest at tag
`BitLisp/sig/raw` with empty binding data
(`unsatisfied_sig_assert`). The digest commits to no prevout
data: the same satisfied triple satisfies this assert on any
input of any transaction. Arguments, cost, and validation rule as
the family preamble states.

### ASSERT_SIG_MY_OUTPOINT (`0x17`)

`(0x17 pubkey message signature)`

**Semantics.** Claims nothing. Asserts that `signature` is a
valid signature by `pubkey` over the family digest at tag
`BitLisp/sig/my_outpoint` with binding data the consumed
outpoint's 36 wire-serialization bytes
(`unsatisfied_sig_assert`). Arguments, cost, and validation rule
as the family preamble states.

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

**Cost.** `CONDITION_GENERIC_COST` = 200 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 4.

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

**Cost.** `CONDITION_GENERIC_COST` = 200 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 4.

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

**Cost.** `CONDITION_GENERIC_COST` = 200 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 4.

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

**Cost.** `CONDITION_GENERIC_COST` = 200 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 4.

### Self asserts (`0x30` to `0x33`, `0x37`)

The five conditions of this family assert facts of the spending
input's own prevout data: the outpoint it consumes, the creating
txid, the spent scriptPubKey, and the amount. Every assert is an
equality against that input's own data in the transaction view.
Nothing in this family reads another input, an output slot, or a
transaction-level field.

This family is stage 2 work: each assert reads only the spent
output's own data, which travels with the spend, so recombining
spends into a different transaction never changes an outcome, and
the composition guarantee stated in VALIDATION.md's claims and
asserts preamble holds for this family with no discipline
required. The operands commit to the
same fields as the participant specifiers of VALIDATION.md rule 3
and carry the recombination-stability classes stated there:
amount and scriptPubKey are knowable when a program is written,
the creating txid and the outpoint exist only once the creating
transaction is final.

Failure of an assert reading the outpoint is the error
`unsatisfied_outpoint_assert`. Failure of an assert reading the
spent scriptPubKey is the error `unsatisfied_scriptpubkey_assert`.
Failure of an assert reading the amount is the error
`unsatisfied_amount_assert`.

### ASSERT_MY_OUTPOINT (`0x30`)

`(0x30 outpoint)`

**Semantics.** Claims nothing. Asserts that the outpoint the
spending input consumes equals `outpoint` byte-exact
(`unsatisfied_outpoint_assert`).

**Arguments.** `outpoint` is an atom of exactly 36 bytes: the
consumed outpoint's 32 txid bytes followed by its 32-bit index in
little-endian byte order, the wire serialization
(`bad_condition_arg`). Exactly one argument, an atom.

**Cost.** `CONDITION_GENERIC_COST` = 200 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 2.

### ASSERT_MY_TXID (`0x31`)

`(0x31 txid)`

**Semantics.** Claims nothing. Asserts that the spending input's
creating txid, the txid half of the outpoint it consumes, equals
`txid` byte-exact (`unsatisfied_outpoint_assert`). This asserts
strictly less than ASSERT_MY_OUTPOINT: the output index is left
unconstrained.

**Arguments.** `txid` is an atom of exactly 32 bytes
(`bad_condition_arg`). Exactly one argument, an atom.

**Cost.** `CONDITION_GENERIC_COST` = 200 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 2.

### ASSERT_MY_SCRIPTPUBKEY (`0x32`)

`(0x32 scriptPubKey)`

**Semantics.** Claims nothing. Asserts that the spent output's
scriptPubKey equals `scriptPubKey` byte-exact
(`unsatisfied_scriptpubkey_assert`).

**Arguments.** `scriptPubKey` is an atom of 0 to 10,000 bytes
(`bad_condition_arg`). A prevout may carry any script base
consensus accepts, including the empty script, so the empty atom
is a valid operand here even though CREATE_OUTPUT rejects it as
claim content. Exactly one argument, an atom.

**Cost.** `CONDITION_GENERIC_COST` = 200 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 2.

### ASSERT_MY_AMOUNT (`0x33`)

`(0x33 amount)`

**Semantics.** Claims nothing. Asserts that the spent output's
amount equals `amount` numerically
(`unsatisfied_amount_assert`).

**Arguments.** `amount` is a minimally encoded integer with
0 <= amount <= 2,100,000,000,000,000 (MAX_MONEY, in satoshis)
(`bad_condition_arg`). Exactly one argument, an atom.

**Cost.** `CONDITION_GENERIC_COST` = 200 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 2.

### ASSERT_MY_TAPROOT (`0x37`)

`(0x37 internal_key merkle_root)`

**Semantics.** Claims nothing. Derives `spk` from `internal_key`
and `merkle_root` by the derivation stated in the
CREATE_OUTPUT_TAPROOT entry, including its `bad_condition_arg`
failures, then asserts that the spent output's scriptPubKey
equals `spk` byte-exact (`unsatisfied_scriptpubkey_assert`).

A satisfied assert proves the spent output is the taproot output
of `internal_key` tweaked with `merkle_root`.

**Arguments.** `internal_key` is an atom of exactly 32 bytes and
must satisfy the point derivation (`bad_condition_arg`).
`merkle_root` is an atom of exactly 0 or exactly 32 bytes
(`bad_condition_arg`). The empty atom means the output commits to
no script tree. Exactly two arguments, both atoms.

**Cost.** `CONDITION_GENERIC_COST + TAPROOT_TWEAK_COST` =
1,300,200 (COSTS.md section 10), charged after every argument
check and before the point derivation.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2), after the derivation above. Stage 2.

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

Specifier operands, consumed in the order VALIDATION.md rule 3's
specifier table states for the commitment value:

- `txid` is an atom of exactly 32 bytes (`bad_condition_arg`).
- `scriptPubKey` is an atom of 0 to 10,000 bytes
  (`bad_condition_arg`). A prevout may carry any script base
  consensus accepts, including the empty script, so the empty
  atom is a valid specifier operand here even though
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

**Cost.** `CONDITION_MESSAGE_COST` = 700 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** VALIDATION.md rule 3 (announcements). Stage 4.

### ASSERT_ANNOUNCEMENT (`0x41`)

`(0x41 mode namespace payload announcer...)`

**Semantics.** Claims nothing. Asserts that some input of the
transaction carries an ANNOUNCE condition whose `namespace` and
`payload` equal this condition's operands byte-exact, and whose
self specifier at `mode` equals the argument specifier built
from `announcer...`. Any number of asserts, from one input or
many, may read the same announcement. Violation is
`unsatisfied_announcement_assert`.

**Arguments.** `mode` is a minimally encoded integer with
0 <= mode <= 7, a commitment value (`bad_condition_arg`).
`namespace` and `payload` are atoms of 0 to 1024 bytes. Then the
specifier operands the table in VALIDATION.md rule 3 states for
`mode`, in table order. Exactly 3 + n arguments, where n is the
mode's operand count (`bad_condition_arity`).

**Cost.** `CONDITION_MESSAGE_COST` = 700 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** VALIDATION.md rule 3 (announcements). Stage 4.

### SEND_MESSAGE (`0x42`)

`(0x42 mode message receiver...)`

**Semantics.** Contributes weight +1 to the message record (self
specifier at the sender half of `mode`, argument specifier at
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
the specifier operands the table in VALIDATION.md rule 3 states
for the receiver half, in table order. Exactly 2 + n arguments,
where n is the receiver half's operand count
(`bad_condition_arity`).

**Cost.** `CONDITION_MESSAGE_COST` = 700 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** VALIDATION.md rule 3 (the message ledger).
Stage 4.

### RECEIVE_MESSAGE (`0x43`)

`(0x43 mode message sender...)`

**Semantics.** Contributes weight -1 to the message record
(argument specifier at the sender half of `mode`, self specifier
at the receiver half, `message`) in the ledger of VALIDATION.md
rule 3. Claims nothing and asserts nothing. The receiver half
always describes the emitting input, filled from its own prevout
data, never from operands. The ledger must balance exactly, so a
receive without its send invalidates the transaction
(`unbalanced_message`).

**Arguments.** As for SEND_MESSAGE with the halves' roles
exchanged: `mode` 0 to 63, `message` an atom of 0 to 1024 bytes,
then the specifier operands for the sender half, in table order.
Exactly 2 + n arguments, where n is the sender half's operand
count (`bad_condition_arity`).

**Cost.** `CONDITION_MESSAGE_COST` = 700 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** VALIDATION.md rule 3 (the message ledger).
Stage 4.

### RESERVE_FEE (`0x50`)

`(0x50 reserve)`

**Semantics.** Claims nothing, asserts nothing. Produces a fee
reserve of `reserve` satoshis. The transaction's fee must be at
least the sum of every fee reserve of every BitLisp input
(VALIDATION.md rule 7, `insufficient_fee`).

**Arguments.** `reserve` is a minimally encoded integer with
0 <= reserve <= 2,100,000,000,000,000 (MAX_MONEY, in satoshis)
(`bad_condition_arg`). Exactly one argument, an atom.

**Cost.** `CONDITION_GENERIC_COST` = 200 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** VALIDATION.md rule 7 (the fee reserve).
Stage 4.

### Seals (`0x60` and `0x61`)

The two conditions of this family assert facts of the assembled
spending transaction itself: SEAL its txid, SEAL_OUTPUTS its
outputs hash, both quantities as the transaction view of
VALIDATION.md derives them. The txid excludes witness data, and a
BitLisp input's program, solution, and seal operand all live in
the witness, so the equality is well-defined and signatures added
to satisfy the signature asserts never change what a seal reads.

A seal exists to make a broadcast transaction immutable in the
mempool. Every other condition constrains only what it names, so
a spend whose input carries surplus value beyond its claims can
be rebuilt in flight with a grafted output capturing the surplus,
every original condition still holding. A satisfied seal makes
any such rebuild fail: altering the transaction changes the
quantity the seal reads.

A transaction carrying any condition of this family is excluded
from the composition guarantee of VALIDATION.md by that
guarantee's own hypothesis: sealing is a declared demand for
unbatchability, and concatenation changes every txid and every
outputs hash.

Both conditions are asserts under VALIDATION.md rule 4: identical
occurrences hold or fail together wherever they appear, since the
facts read are transaction-wide. Occurrences with differing
operands are checked independently, and two SEAL conditions with
differing operands can never both hold. Failure of either assert
is the error `unsatisfied_seal_assert`.

This family is stage 4 work: both quantities are derived from the
assembled transaction, so recombining spends into a different
transaction changes them by construction.

**Guidance for program authors (not consensus).** A seal operand
arrives in the solution, and the solution is witness data no rule
protects from rewriting. A seal whose operand no signature
commits to therefore seals nothing: whoever rebuilds the
transaction substitutes the matching operand in the same motion.
Compose the seal into a signed message, such as the hash of a
delegated program that emits it. One binding signature anywhere
in the transaction suffices, whichever input carries the seal,
because the facts read are transaction-wide. A transaction
spendable with no signature at all is re-solvable by anyone in
full and has no immutability for any condition to provide. Choose
the variant by posture: SEAL_OUTPUTS holds the outputs fixed and
leaves the input side open, so a later-added input can only raise
the fee, while SEAL forbids every alteration including that one.

### SEAL (`0x60`)

`(0x60 txid)`

**Semantics.** Claims nothing. Asserts that the spending
transaction's own txid equals `txid` byte-exact
(`unsatisfied_seal_assert`). The operand names the containing
transaction, where ASSERT_MY_TXID names the past one that created
the spent output. A satisfied SEAL fixes every non-witness byte
of the transaction: the version, every input's outpoint,
scriptSig, and sequence, every output slot's content and order,
and the locktime. SEAL asserts strictly more than SEAL_OUTPUTS:
the txid commits to the outputs hash's preimage.

**Arguments.** `txid` is an atom of exactly 32 bytes, the txid in
the byte order outpoints carry (`bad_condition_arg`). Exactly one
argument, an atom.

**Cost.** `CONDITION_GENERIC_COST` = 200 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 4.

### SEAL_OUTPUTS (`0x61`)

`(0x61 outputs_hash)`

**Semantics.** Claims nothing. Asserts that the spending
transaction's outputs hash equals `outputs_hash` byte-exact
(`unsatisfied_seal_assert`). A satisfied SEAL_OUTPUTS fixes every
output slot's content and order and nothing else: the version,
the locktime, and the input list, including which inputs exist,
stay unconstrained.

**Arguments.** `outputs_hash` is an atom of exactly 32 bytes
(`bad_condition_arg`). Exactly one argument, an atom.

**Cost.** `CONDITION_GENERIC_COST` = 200 (COSTS.md section 10),
charged after every argument check.

**Validation rule.** The assert clause of VALIDATION.md
(claims and asserts, rule 2). Stage 4.
