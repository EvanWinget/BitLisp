# BitLisp Architecture

This document specifies how a BitLisp program is committed to on
chain and how a spend supplies it: the taproot leaf version, the
commitment scheme, the witness structure, and the validation
pipeline that runs over them. Evaluator semantics live in
[VM.md](VM.md), the condition vocabulary in
[CONDITIONS.md](CONDITIONS.md), transaction condition validation in
[VALIDATION.md](VALIDATION.md), and the cost model in
[COSTS.md](COSTS.md).

## 1. Overview

A BitLisp program is committed in a taproot output as one leaf of
the output's script tree, under the leaf version section 2 assigns.
The leaf commits to the program by its tree hash. A spend of that
leaf is a BIP341 script-path spend whose witness carries four
elements: the solution, the serialized program, the leaf script,
and the control block. Base consensus authenticates the leaf
against the spent output exactly as it does for every script-path
spend, and the rules of this document then run: the program must
match the leaf, the program evaluates over the solution under a
cost budget derived from the witness weight, the value it returns
is parsed as a condition list, and the condition list is validated
against the spending transaction together with every other input's.

```
  witness    [solution]  [program]  [leaf script]  [control block]
                 |           |            |               |
                 |           |            +-------+-------+
                 |           |                    |
                 |           |          base consensus (BIP341):
                 |           |          tapleaf hash, path fold,
                 |           |          tweak check against the
                 |           |          spent scriptPubKey
                 |           |                    |
                 |     tree hash of the           +--> execution identity
                 |     program equals the              (tapleaf, merkleRoot,
                 |     leaf script?                     internalKey)
                 |           |                                |
                 +-----+-----+                                |
                       |                                      |
              run(program, solution, budget)                  |
                       |                                      |
                     value ---- parse as a condition list     |
                                          |                   |
                                          +---------+---------+
                                                    |
                              VALIDATION.md over the whole transaction
```

The key path of a BitLisp output is base consensus's key path,
unchanged: a spend by signature under the output key runs no
program and this document places no rule on it. A program learns
that no key path exists only by asserting the internal key it was
committed under, the `ASSERT_MY_TAPTREE` entry of CONDITIONS.md.

## 2. Leaf version and commitment

### 2.1 Leaf version

`BITLISP_LEAF_VERSION = 0xd0`. PROVISIONAL: the value is fixed at
deployment and nothing else in this document depends on which
compliant byte it is.

A script-path spend is a BitLisp spend exactly when the leaf
version of its control block, the first byte with the low bit
cleared, equals `BITLISP_LEAF_VERSION`. Every BitLisp spend is
subject to this document. Spends under every other leaf version
are unaffected by it.

### 2.2 The leaf

The leaf script `s` of a BitLisp leaf is exactly 32 bytes: the tree
hash of the committed program, the `sha256tree` digest VM.md
section 4 defines over the program's node. The leaf script is never
executed. Its tapleaf hash is

`tapleaf = tagged_hash("TapLeaf", BITLISP_LEAF_VERSION || 0x20 || s)`

where `tagged_hash(tag, m)` is `sha256(sha256(tag) || sha256(tag) ||
m)` with `tag` the ASCII bytes of the tag name, as the
CREATE_OUTPUT_TAPROOT entry of CONDITIONS.md defines it, and `0x20`
is the compact-size encoding of the 32-byte script length.

A program is identified by its tree hash and by nothing else. The
tree hash is a function of the program's node, and VM.md section 2
gives every node exactly one serialization, so a program has one
identity however it is written down. A curried program is one
program: a leaf commits to the curried program's tree hash, fixed
values included, and the uncurried program has no separate
standing in the commitment.

### 2.3 The tree

A BitLisp leaf is an ordinary BIP341 leaf. A script tree holds any
number of leaves in any arrangement BIP341 admits, BitLisp leaves
and leaves of other versions alike, and a spend reveals exactly one
leaf. Two BitLisp leaves of one tree are two independently
spendable programs of the same output.

A BitLisp spend's execution identity, the triple VALIDATION.md's
transaction view carries, is read from the control block `c` of
`33 + 32m` bytes, `m` from 0 to 128 inclusive, as base consensus
reads it:

- `internalKey` is `c[1..33]`, the 32-byte x-only internal key.
- `tapleaf` is the tapleaf hash of section 2.2 over the revealed
  leaf script.
- `merkleRoot` is the fold of the path: `k_0 = tapleaf`, and for
  each `j` from 0 to `m - 1`, with `e_j` the `j`th 32-byte element
  of `c[33..]`, `k_(j+1) = tagged_hash("TapBranch", k_j || e_j)` when
  `k_j` sorts before `e_j` lexicographically and
  `tagged_hash("TapBranch", e_j || k_j)` otherwise. `merkleRoot` is
  `k_m`.

Base consensus accepts the spend only when the spent scriptPubKey
is `0x51 0x20` followed by the x coordinate of `P + t*G`, where `P`
is the point with x coordinate `internalKey` and even y, `t` is
`tagged_hash("TapTweak", internalKey || merkleRoot)`, and the low
bit of `c[0]` equals the parity of that point's y coordinate. This
document takes the triple as authenticated by that check and
derives nothing further from it.

### 2.4 Digest domains

Two kinds of digest meet in a BitLisp coin's script tree and its
tweak, and no preimage is valid under both:

- A tree hash. Its preimage begins with the byte `0x01` (an atom)
  or `0x02` (a pair).
- A tagged hash. Its preimage begins with the 64-byte prefix
  `sha256(tag) || sha256(tag)`, whose first byte is the first byte
  of `sha256(tag)`.

The tags in use and the first byte of each tag digest:

| tag | first byte |
| --- | --- |
| `TapLeaf` | `0xae` |
| `TapBranch` | `0x19` |
| `TapTweak` | `0xe8` |
| `BitLisp/sig/my_txid` | `0x54` |
| `BitLisp/sig/my_scriptpubkey` | `0xe3` |
| `BitLisp/sig/my_amount` | `0xdf` |
| `BitLisp/sig/my_scriptpubkey_amount` | `0xec` |
| `BitLisp/sig/my_txid_amount` | `0xff` |
| `BitLisp/sig/my_txid_scriptpubkey` | `0xe5` |
| `BitLisp/sig/raw` | `0x56` |
| `BitLisp/sig/my_outpoint` | `0xda` |

None is `0x01` or `0x02`, so no tree-hash preimage is a tagged-hash
preimage and no tagged-hash preimage is a tree-hash preimage. A
tag added to any companion document adds a row here.

The two other digests the companion documents read, the txid and
the outputs hash of VALIDATION.md's transaction view, are Bitcoin's
own untagged constructions. Neither enters a script tree, and no
rule compares either against a digest of the two kinds above: each
is compared only against a condition operand.

## 3. Witness structure

### 3.1 Elements

The witness of a BitLisp spend is exactly four elements, in BIP341's
stack order with the control block last:

| position | element | content |
| --- | --- | --- |
| 1 | solution | the serialization of the solution node |
| 2 | program | the serialization of the program node |
| 3 | leaf script | the 32-byte tree hash of section 2.2 |
| 4 | control block | `33 + 32m` bytes, as base consensus defines it |

The rules over them, in order:

1. **No annex.** A witness whose last element begins with the
   byte `0x50`, the element BIP341 would remove as the annex, makes
   the spend invalid, `bad_witness`.
2. **Exactly four elements**, else `bad_witness`.
3. **The control block** is checked by base consensus: its length,
   the lift of the internal key, and the tweak check of section
   2.3. This document adds no rule over its bytes.
4. **The leaf script** is exactly 32 bytes, else `bad_witness`.
5. **The program element** deserializes under VM.md section 2 to
   a node, else `bad_encoding`, and that node's tree hash equals
   the leaf script, else `leaf_mismatch`. The node is the program:
   an atom or a pair, with no further constraint on its shape.
6. **The solution element** deserializes under VM.md section 2 to
   a node, else `bad_encoding`. That node is the environment the
   program evaluates over. Its content is otherwise unconstrained:
   the program reads what it reads, and solution data the program
   never reads does not invalidate the spend.

An empty element is not the serialization of any node. Nil is the
one-byte element `0x80`.

No element has a size bound beyond the ones base consensus places
on the transaction. Every witness byte is priced by the weight
mapping of COSTS.md section 9, and the budget of section 3.2 is
the only bound evaluation places on a spend.

### 3.2 Budget

The cost budget of a BitLisp spend is a function of the weight of
its own input's witness alone, the function fixed in COSTS.md
section 9. The witness carries no budget declaration, and no other
input's witness changes the budget. Deserializing the two node
elements and hashing the program tree are not charged against the
budget: the weight mapping prices those bytes.

### 3.3 Evaluation and the condition list

The spend evaluates `run(program, solution, budget)` under VM.md
section 3. An error is a spend failure under the error's own name.
The returned value is parsed as a condition list under CONDITIONS.md,
and the conditions are costed against the remaining budget under
VALIDATION.md rule 5. The input then enters the transaction view
carrying its condition list and its execution identity, and
VALIDATION.md's rules run over the assembled transaction.

## 4. Validation pipeline

A BitLisp spend passes through six stages. The first five are
per-input work that reads the input's own witness and prevout, and
run independently for every BitLisp input of a transaction. The
sixth reads the assembled transaction. A failure at any stage
invalidates the transaction, and the error named is diagnostic:
the consensus fact is invalidity, and the names distinguish the
failure modes so each has its own vector.

| stage | work | failure modes |
| --- | --- | --- |
| 1 | witness shape: no annex, four elements, a 32-byte leaf script | `bad_witness` |
| 2 | program decode and the leaf check | `bad_encoding`, `leaf_mismatch` |
| 3 | solution decode | `bad_encoding` |
| 4 | evaluation under the budget | the VM.md section 5 taxonomy, `cost_exceeded` among them |
| 5 | condition-list parsing and costing | the CONDITIONS.md parse errors, `cost_exceeded` |
| 6 | transaction validation | the VALIDATION.md rule errors |

Stages 1 to 5 are VALIDATION.md's stage 1, the stateless per-spend
work, and stage 6 is its stages 2 to 5. The control block's own
checks, base consensus's, precede stage 1: a spend that fails them
never reaches this document.
