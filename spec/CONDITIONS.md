# BitLisp Conditions

Status: in progress. Section 1 and the CREATE_COIN entry are
normative. The remaining vocabulary v0 entries land across Phase 2,
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
| `0x01` | `CREATE_COIN` |

Planned entries, unassigned and invalid until their sections land:
`CREATE_COIN_TAPROOT`, the secp `AGG_SIG` family with program-composed
messages, `ASSERT_HEIGHT_ABSOLUTE`, `ASSERT_HEIGHT_RELATIVE`,
`ASSERT_SECONDS_ABSOLUTE`, `ASSERT_SECONDS_RELATIVE`, the `ASSERT_MY_*`
family, `SEND_MESSAGE` and `RECV_MESSAGE` (transaction-scoped),
`RESERVE_FEE`, `ASSERT_OUTPUT_COUNT`, and `ASSERT_FEE_LE`.

### CREATE_COIN (`0x01`)

`(0x01 scriptPubKey amount)`

**Semantics.** Asserts that the containing transaction has one output
slot whose content is exactly (`scriptPubKey`, `amount`), and claims
that slot. Claims are matched injectively across the whole transaction
under MATCHING.md rule 1: k conditions carrying identical content
require k distinct output slots. Two identical CREATE_COIN conditions
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

**Curation note.** Ported from Chia with two deliberate changes,
recorded as divergences C1 and C2 in the condition record
(`docs/condition-record.md`). First, the argument is full script bytes
rather than a puzzle hash, because a Bitcoin output may carry any
scriptPubKey and exits to non-BitLisp outputs are ordinary. Second,
Chia's optional memo argument is declined in v0: its wallet-discovery
job does not exist under output-script scanning, and consensus-carried
bytes with no consensus meaning are a deliberate non-affordance
(design obligation 4). A memo-bearing variant remains reachable
through the reserved tier if evidence of need emerges.
