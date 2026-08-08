# Glossary

BitLisp favors Bitcoin-native vocabulary in every artifact
(decision by Evan, 2026-07-31, recorded in the condition record).
This table maps BitLisp terms to their Bitcoin and Chia
counterparts so a reader from either ecosystem can orient quickly.
A term enters this table in the same PR that introduces it.

| BitLisp | Bitcoin | Chia | notes |
| --- | --- | --- | --- |
| coin | coin, UTXO (Bitcoin Core's class Coin is a UTXO entry) | coin | the thing a spend consumes, kept because it is Core's own term |
| program | locking program in a tapleaf | puzzle | the program committed in the output, renamed 2026-07-31 |
| witness arguments | witness data | solution | spender-supplied arguments to the program, delivered to the VM as its environment value (env), renamed 2026-07-31 |
| condition | no direct equivalent | condition | a declarative demand the transaction must satisfy |
| condition list | no direct equivalent | conditions | the value a successful program evaluation yields |
| CREATE_OUTPUT | creates a transaction output | CREATE_COIN | renamed 2026-07-31, claims one output slot by literal scriptPubKey bytes |
| CREATE_OUTPUT_TAPROOT | creates a taproot output via the BIP341 tweak | none, compare bllsh secp256k1_muladd | same claim as CREATE_OUTPUT with the scriptPubKey validator-derived |
| output slot | transaction output (scriptPubKey, amount) | created coin | identity is positional on Bitcoin, content-derived on Chia |
| claim | no direct equivalent | none | a condition's demand that consumes a transaction resource, assigned injectively. Output claims (VALIDATION.md rule 1) are the first kind (condition-record decision 14) |
| assert | nearest relatives are CLTV and CSV, opcodes reading transaction context | the ASSERT_* condition family | a condition's predicate over the transaction view, freely shared, checked as a conjunction (condition-record decision 14) |
| time asserts | CLTV and CSV, the locktime opcodes | the four timelock ASSERT conditions | the family constraining the transaction's locktime machinery, fields base consensus enforces, landed 2026-08-07 (condition-record decision 15) |
| ASSERT_LOCKTIME_HEIGHT | OP_CHECKLOCKTIMEVERIFY, height type | ASSERT_HEIGHT_ABSOLUTE | requires a non-final own sequence and a height-typed nLockTime at or above the operand |
| ASSERT_LOCKTIME_TIME | OP_CHECKLOCKTIMEVERIFY, time type | ASSERT_SECONDS_ABSOLUTE | the same shape against a time-typed nLockTime, wall-clock meaning is whatever base consensus gives the field |
| ASSERT_SEQUENCE_HEIGHT | OP_CHECKSEQUENCEVERIFY, block count | ASSERT_HEIGHT_RELATIVE | requires an unsigned version of at least 2 and an enabled height-typed sequence value at or above the operand |
| ASSERT_SEQUENCE_TIME | OP_CHECKSEQUENCEVERIFY, 512-second units | ASSERT_SECONDS_RELATIVE | the same shape with the time type flag, the operand counts the field's own 512-second units |
| satisfier | compare miniscript satisfactions, which are spender-side | none | the transaction resource assigned to a claim, one per claim. A miniscript satisfaction is what the spender gives a script, a satisfier is what the transaction gives a claim |
| composition guarantee | batching and coinjoin practice, no consensus equivalent | spend bundle aggregation, offers | two valid transactions with disjoint outpoints concatenate into a valid transaction (VALIDATION.md preamble, condition-record decision 14) |
| spend | input plus its witness | coin spend | one input's evaluation and conditions |
| reserved condition | upgradable NOP | unknown condition | priced forward-compatibility hatch, invalid-by-default outside it |
| internal key, merkle root, tweak | BIP341 terms, used as defined there | none | see the CREATE_OUTPUT_TAPROOT entry |
| SEND_MESSAGE, RECV_MESSAGE | no direct equivalent | SEND_MESSAGE, RECEIVE_MESSAGE (CHIP-0025) | planned, strictly transaction-scoped, addressed exact pairing |
| broadcast conditions | no direct equivalent | announcements (coin and puzzle, create and assert) | planned unaddressed pair, transaction-scoped, names owed by the VALIDATION.md rule 3 design (condition-record decision 10) |
| validator | no direct equivalent, the script interpreter checks one input at a time | condition parsing and checking | the single consensus component that checks every spend's conditions against the transaction |
| condition validation | nearest relative is the contextual transaction checks in Core's validation.cpp | condition parsing and checking in chia_rs | the layer the validator implements, checking every spend's condition list against the containing transaction, renamed from matching 2026-08-07 (condition-record decision 13) |
| validation stage | nearest relative is Core's split between context-free and contextual checks | condition parsing and checking stages in chia_rs | the validator spec's organizing frame, five stages of strictly increasing context (condition-record decision 11, renamed from wave 2026-08-07) |
| recombination-stable | no direct equivalent | fast-forward eligible | a binding mode whose claims survive aggregation of the spend into a different transaction (condition-record decision 12) |
| injective matching | no direct equivalent | cross-spend checks, send and receive pairing rules | VALIDATION.md rule 1's claim-to-slot assignment, equality-only, multiset counting |
| guess and assert | no direct equivalent | truths | re-deriving a transaction fact in-program and asserting it, the pattern the assert vocabulary exists to bound |
