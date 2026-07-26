# BitLisp Conditions

Status: stub. Vocabulary v0 lands in Phase 2. Curation rationale per
design obligation 4 accompanies every entry.

A successful puzzle evaluation yields a condition list. This document
specifies the encoding of that list and the meaning of each condition.
How conditions are matched against the transaction is specified in
[MATCHING.md](MATCHING.md).

## 1. Condition list encoding

TODO: list shape, opcode encoding, argument arity and range rules,
unknown-opcode policy.

## 2. Vocabulary v0 (planned)

Ported set:

- `CREATE_COIN`
- `AGG_SIG` family (secp, program-composed messages)
- `ASSERT_HEIGHT_ABSOLUTE`, `ASSERT_HEIGHT_RELATIVE`
- `ASSERT_SECONDS_ABSOLUTE`, `ASSERT_SECONDS_RELATIVE`
- `ASSERT_MY_*` family
- `SEND_MESSAGE`, `RECV_MESSAGE` (transaction-scoped)
- `RESERVE_FEE`

Universal asserts:

- `ASSERT_OUTPUT_COUNT`
- `ASSERT_FEE_LE`

Each entry gets: semantics, arguments, cost, matching rule reference,
curation note (why it is in v0, what was declined and why).
