# BitLisp Conditions

Status: in progress. Section 1 and the CREATE_OUTPUT and
CREATE_OUTPUT_TAPROOT entries are normative. The remaining vocabulary v0 entries land across Phase 2,
each with semantics, arguments, cost, matching rule reference, and a
curation note per design obligation 4.

A successful puzzle evaluation yields a condition list. This document
specifies the encoding of that list and the meaning of each condition.
How conditions are matched against the transaction is specified in
[MATCHING.md](MATCHING.md).

## 1. Condition list encoding

A successful puzzle evaluation yields a value that must satisfy every
rule in this section. Any violation invalidates the spend with the
error code named in parentheses. Every condition-layer error code is
named in this document or in MATCHING.md at the rule that raises it.

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
under the shape rules of MATCHING.md rule 6.

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

Planned entries, unassigned and invalid until their sections land:
the secp `AGG_SIG` family with program-composed
messages, `ASSERT_HEIGHT_ABSOLUTE`, `ASSERT_HEIGHT_RELATIVE`,
`ASSERT_SECONDS_ABSOLUTE`, `ASSERT_SECONDS_RELATIVE`, the `ASSERT_MY_*`
family, `SEND_MESSAGE` and `RECV_MESSAGE` (transaction-scoped),
`RESERVE_FEE`, `ASSERT_OUTPUT_COUNT`, and `ASSERT_FEE_LE`.

### CREATE_OUTPUT (`0x01`)

`(0x01 scriptPubKey amount)`

**Semantics.** Asserts that the containing transaction has one output
slot whose content is exactly (`scriptPubKey`, `amount`), and claims
that slot. Claims are matched injectively across the whole transaction
under MATCHING.md rule 1: k conditions carrying identical content
require k distinct output slots. Two identical CREATE_OUTPUT conditions
from one input are two claims.

The `amount` is part of the demanded content, not a debit from the
spending input. Matching never tracks which input's value funds which
slot. Value conservation is enforced transaction-wide by Bitcoin's
base rules, and an input's own value is unrelated to the amounts its
conditions claim.

**Arguments.** `scriptPubKey` is an atom of 1 to 10,000 bytes. The
empty atom is rejected (`bad_condition_arg`). `amount` is a minimally
encoded integer with 0 <= amount <= 2,100,000,000,000,000 (MAX_MONEY,
in satoshis). Exactly two arguments, both atoms.

**Cost.** Assigned when MATCHING.md rule 5 lands.

**Matching rule.** MATCHING.md rule 1.

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

**Semantics.** Asserts that the containing transaction has one output
slot whose content is exactly (`spk`, `amount`) and claims that slot,
where `spk` is derived as follows:

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
claims require k distinct output slots under MATCHING.md rule 1,
regardless of which opcode produced each claim.

**Arguments.** `internal_key` is an atom of exactly 32 bytes and must
satisfy the point derivation above (`bad_condition_arg`).
`merkle_root` is an atom of exactly 0 or exactly 32 bytes
(`bad_condition_arg`). The empty atom means the output commits to no
script tree. `amount` is a minimally encoded integer with
0 <= amount <= 2,100,000,000,000,000 (MAX_MONEY, in satoshis).
Exactly three arguments, all atoms.

**Cost.** Assigned when MATCHING.md rule 5 lands.

**Matching rule.** MATCHING.md rule 1, after the derivation above.

**Curation note.** Neither output-creation condition is an output
type. Both produce the identical claim, and a taproot output with a
statically known key is created with plain CREATE_OUTPUT. This
condition exists so covenant recursion can construct a successor
taproot output when the puzzle computes the internal key or tree
root dynamically, without giving the VM elliptic-curve arithmetic.
Two alternatives were declined, a general `secp256k1_muladd`
operator and a narrow `taptweak` operator, recorded as decision
D-CC2 in the condition record (`docs/condition-record.md`). The
derivation matches BIP341 output-key construction exactly,
including the key-only tweak when no script tree is committed.
