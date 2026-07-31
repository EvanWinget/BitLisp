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
| claim | no direct equivalent | none | a demanded (scriptPubKey, amount) pair, MATCHING.md rule 1 |
| spend | input plus its witness | coin spend | one input's evaluation and conditions |
| reserved condition | upgradable NOP | unknown condition | priced forward-compatibility hatch, invalid-by-default outside it |
| internal key, merkle root, tweak | BIP341 terms, used as defined there | none | see the CREATE_OUTPUT_TAPROOT entry |
| SEND_MESSAGE, RECV_MESSAGE | no direct equivalent | SEND_MESSAGE, RECEIVE_MESSAGE (CHIP-0025) | planned, strictly transaction-scoped |
