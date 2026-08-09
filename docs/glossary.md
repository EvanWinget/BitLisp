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
| self asserts | nearest relative is the sighash, which commits prevout data through a signature | the ASSERT_MY_* family | the family asserting the spending input's own prevout data, landed 2026-08-08 (condition-record decision 20) |
| ASSERT_MY_OUTPOINT | asserts the input's own outpoint | ASSERT_MY_COIN_ID | the outpoint in wire serialization, txid then little-endian index |
| ASSERT_MY_TXID | asserts the txid half of the input's outpoint | ASSERT_MY_PARENT_ID | a deliberate strict subset of ASSERT_MY_OUTPOINT, the index left unconstrained |
| ASSERT_MY_SCRIPTPUBKEY | asserts the spent output's scriptPubKey | ASSERT_MY_PUZZLEHASH | raw script bytes per divergence C1, empty script allowed as prevout content |
| ASSERT_MY_AMOUNT | asserts the spent output's amount | ASSERT_MY_AMOUNT | numeric equality in satoshis |
| ASSERT_MY_TAPROOT | verifies the spent scriptPubKey against the BIP341 tweak of its components | none | the assert-side mirror of CREATE_OUTPUT_TAPROOT, the self-propagation covenant primitive |
| satisfier | compare miniscript satisfactions, which are spender-side | none | the transaction resource assigned to a claim, one per claim. A miniscript satisfaction is what the spender gives a script, a satisfier is what the transaction gives a claim |
| composition guarantee | batching and coinjoin practice, no consensus equivalent | spend bundle aggregation, offers | two valid transactions with disjoint outpoints concatenate into a valid transaction (VALIDATION.md preamble, condition-record decision 14) |
| spend | input plus its witness | coin spend | one input's evaluation and conditions |
| reserved condition | upgradable NOP | unknown condition | priced forward-compatibility hatch, invalid-by-default outside it |
| internal key, merkle root, tweak | BIP341 terms, used as defined there | none | see the CREATE_OUTPUT_TAPROOT entry |
| SEND_MESSAGE, RECEIVE_MESSAGE | no direct equivalent | SEND_MESSAGE, RECEIVE_MESSAGE (CHIP-0025) | landed 2026-08-07, opcodes numerically Chia's, transaction-scoped counted balance (condition-record decision 16) |
| ANNOUNCE, ASSERT_ANNOUNCEMENT | no direct equivalent | the four announcement conditions (coin and puzzle, create and assert) | landed 2026-08-07, the unaddressed pair, namespace first-class, announcer precision chosen by the assert (condition-record decisions 10 and 16) |
| message record | no direct equivalent | send and receive balancing in chia_rs | the third condition sort beside claims and asserts, a weighted ledger entry (+1 or -1) whose record must net to zero (VALIDATION.md rule 3, condition-record decision 16) |
| RESERVE_FEE | no direct opcode, the fee itself is implicit (inputs minus outputs) | RESERVE_FEE 52 | landed 2026-08-09 at 0x50, demands the transaction's fee reach the summed reservations (VALIDATION.md rule 7, condition-record decision 21) |
| fee reserve | no direct equivalent | reserve_fee accumulation in chia_rs | the fourth condition sort: a counted demand against the transaction's fee, occurrences summing rather than sharing (VALIDATION.md rule 7, condition-record decision 21) |
| participant specifier | no direct equivalent | mode bits with SpendId | the commitment-value grammar naming an input's prevout data at a chosen precision (VALIDATION.md rule 3, condition-record decision 18) |
| creating txid | the txid half of an outpoint | parent coin id | the creator handle the validator holds, substituting for Chia's coin-parent lineage (divergence C9) |
| validator | no direct equivalent, the script interpreter checks one input at a time | condition parsing and checking | the single consensus component that checks every spend's conditions against the transaction |
| condition validation | nearest relative is the contextual transaction checks in Core's validation.cpp | condition parsing and checking in chia_rs | the layer the validator implements, checking every spend's condition list against the containing transaction, renamed from matching 2026-08-07 (condition-record decision 13) |
| validation stage | nearest relative is Core's split between context-free and contextual checks | condition parsing and checking stages in chia_rs | the validator spec's organizing frame, five stages, context strictly increasing through stage 4 with stage 5 the signature pass over own-input data (condition-record decision 11, renamed from wave 2026-08-07, stage 5 restated with decision 23) |
| recombination-stable | no direct equivalent | fast-forward eligible | a binding mode whose claims survive aggregation of the spend into a different transaction (condition-record decision 12) |
| injective matching | no direct equivalent | cross-spend checks, send and receive pairing rules | VALIDATION.md rule 1's claim-to-slot assignment, equality-only, multiset counting |
| guess and assert | no direct equivalent | truths | re-deriving a transaction fact in-program and asserting it, the pattern the assert vocabulary exists to bound |
| signature assert family | nearest relative is OP_CHECKSIG, but the digest is a program-composed message plus a prevout binding, not a sighash | AGG_SIG_ME 50, AGG_SIG_PARENT 43, AGG_SIG_PUZZLE 44, AGG_SIG_AMOUNT 45, and the three combinations 46 to 48 | landed 2026-08-09 at 0x10 to 0x17, eight per-condition BIP340 triples, the seven ASSERT_SIG_MY_* bound variants over the input's own prevout data plus ASSERT_SIG_RAW below, MY per the self-assert convention (VALIDATION.md rule 8, condition-record decision 23) |
| ASSERT_SIG_RAW | no equivalent, script verifies no arbitrary-message signatures | AGG_SIG_UNSAFE 49 | binds nothing about its input, imports external attestations, replayable by design, the eager in-VM counterpart is secp_verify (condition-record decision 23) |
| seal family (SEAL, SEAL_OUTPUTS) | nearest relatives are SIGHASH_ALL's whole-transaction commitment and BIP341's sha_outputs | no equivalent, Chia identity is content-derived so bundles need no seal | landed 2026-08-09 at 0x60 and 0x61, asserts pinning the spending transaction's own txid and its outputs hash respectively, stage 4, excluded from the composition guarantee by its second scoping (condition-record decision 24, divergence C20) |
| delegated-program idiom | nearest relative is signing a sighash: committing the signature to the spend's effects | the delegated puzzle of the standard wallet | signing the hash of a program whose output is the intended condition list, the authoring pattern that closes the fixed-message rewrite footgun (VALIDATION.md rule 8 guidance, condition-record decision 23) |
