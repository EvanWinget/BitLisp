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
and the control block, with an annex after them only when the
program commits to one. Base consensus authenticates the leaf
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

When `m` is 0 the merkle root is the tapleaf hash itself, so a
BitLisp spend's `merkleRoot` is never empty: the empty root the
CREATE_OUTPUT_TAPROOT entry admits names an output with no script
tree, which has no leaf to execute.

Base consensus accepts the spend only when the spent scriptPubKey
is `0x51 0x20` followed by the x coordinate of `P + t*G`, where `P`
is the point with x coordinate `internalKey` and even y, `t` is
`tagged_hash("TapTweak", internalKey || merkleRoot)`, and the low
bit of `c[0]` equals the parity of that point's y coordinate. This
document takes the triple as authenticated by that check and
derives nothing further from it.

### 2.4 Digest domains

A tree hash never enters a script tree as a node. The leaf script
is the tree hash as data, and the tree's nodes are BIP341's tagged
hashes over it: the tapleaf hash wraps the leaf script under
`BITLISP_LEAF_VERSION`, and every branch and the tweak wrap tagged
hashes again. The two kinds of digest a BitLisp validator computes
are further disjoint by preimage, and no preimage is valid under
both:

- A tree hash. Its preimage begins with the byte `0x01` (an atom)
  or `0x02` (a pair).
- A tagged hash. Its preimage begins with the 64-byte prefix
  `sha256(tag) || sha256(tag)`, whose first byte is the first byte
  of `sha256(tag)`.

Every tag a BitLisp validator hashes under, and the first byte of
each tag digest:

| tag | first byte |
| --- | --- |
| `TapLeaf` | `0xae` |
| `TapBranch` | `0x19` |
| `TapTweak` | `0xe8` |
| `BIP340/challenge` | `0x07` |
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

`BIP340/challenge` is the challenge tag of BIP340's Verify, which
`secp_verify` and the signature asserts compute. The three other
digests the companion documents read, the txid and the outputs
hash of VALIDATION.md's transaction view and the annex hash of
section 3.4, are Bitcoin's own untagged constructions. None
enters a script tree, no rule compares any of them against a
digest of the two kinds above, and each reaches a rule only as a
value compared against a condition operand or bound as data into
a tagged signature digest.

## 3. Witness structure

### 3.1 Elements

The witness of a BitLisp spend is exactly four elements, in BIP341's
stack order with the control block last, followed by an annex only
when section 3.4 admits one:

| position | element | content |
| --- | --- | --- |
| 1 | solution | the serialization of the solution node |
| 2 | program | the serialization of the program node |
| 3 | leaf script | the 32-byte tree hash of section 2.2 |
| 4 | control block | `33 + 32m` bytes, as base consensus defines it |

Position 1 is the first element of the input's witness as the
transaction serializes it, and the control block is the last.

Base consensus checks the control block before any rule below
runs: its length, the lift of the internal key, and the tweak
check of section 2.3. This document adds no rule over its bytes.
The rules over the witness, in order:

1. **The annex.** In the witness as the transaction serializes
   it, if there are at least two elements and the last begins with
   the byte `0x50`, that element is the annex, as BIP341 defines
   it. It is set aside before the rules below count elements, and
   section 3.4 governs it.
2. **Exactly four elements** remain, else `bad_witness`.
3. **The leaf script** is exactly 32 bytes, else `bad_witness`.
4. **Element sizes.** The solution, the program, and the annex
   when present are each at most `MAX_WITNESS_ELEMENT_SIZE =
   10,000` bytes, else `bad_witness`.
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

The leaf script's width and the element bound of rule 4 are the
only sizes this document fixes, and the control block's length is
base consensus's. Every witness byte is priced by the weight
mapping of COSTS.md section 9, and within the bound the budget of
section 3.2 is the only limit evaluation places on a spend.

### 3.2 Budget

The cost budget of a BitLisp spend is a function of the weight of
its own input's witness alone, the function fixed in COSTS.md
section 9. The witness carries no budget declaration, and no other
input's witness changes the budget. Deserializing the two node
elements and hashing the program tree are not charged against the
budget: the weight mapping prices those bytes.

PROVISIONAL until COSTS.md section 9 fixes the function. Until it
does, a vector under this document states the budget it runs
under explicitly.

### 3.3 Evaluation and the condition list

The spend evaluates `run(program, solution, budget)` under VM.md
section 3. An error is a spend failure under the error's own name.
The returned value is parsed as a condition list under CONDITIONS.md,
and the conditions are costed against the remaining budget under
VALIDATION.md rule 5. The input then enters the transaction view
carrying its condition list and its execution identity, and
VALIDATION.md's rules run over the assembled transaction.

Two programs follow from these rules and are named so they are
pinned. The program that is the atom `1` returns its solution, so
a leaf committing to it accepts any condition list the spender
supplies: the anyone-can-spend leaf. The program nil returns nil,
the empty list, which CONDITIONS.md rejects as
`bad_condition_list`, so a leaf committing to nil has no valid
script-path spend.

### 3.4 The annex

An annex is admitted on a BitLisp spend exactly when the input's
condition list carries `ASSERT_MY_ANNEX` over its hash. The annex
hash is

`annexHash = sha256(compact_size(len(annex)) || annex)`

over the annex element's bytes including its leading `0x50`, the
`sha_annex` value of BIP341. The transaction view's BitLisp input
carries `annexHash` when the witness carries an annex and nothing
otherwise. No rule reads the annex's content.

- An input whose witness carries an annex and whose condition list
  holds no `ASSERT_MY_ANNEX` is invalid, `unasserted_annex`.
- An `ASSERT_MY_ANNEX` on an input without an annex, or whose
  annex hashes to a different value, is unsatisfied,
  `unsatisfied_annex_assert`, the CONDITIONS.md entry.

Together the two rules make an input's annex committed data the
spender chose: no third party can attach, remove, or alter one
without invalidating the spend.

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
| 1 | witness shape: the annex set aside, four elements, a 32-byte leaf script, element sizes | `bad_witness` |
| 2 | program decode and the leaf check | `bad_encoding`, `leaf_mismatch` |
| 3 | solution decode | `bad_encoding` |
| 4 | evaluation under the budget | the VM.md section 5 taxonomy, `cost_exceeded` among them |
| 5 | condition-list parsing and costing, then the annex rule of section 3.4 | the CONDITIONS.md parse errors, `cost_exceeded`, `unasserted_annex` |
| 6 | transaction validation | the VALIDATION.md rule errors |

Stages 1 to 3 precede VALIDATION.md's stage 1, stages 4 and 5 are
that stage, the stateless per-spend work, and stage 6 is its
stages 2 to 5. The control block's own
checks, base consensus's, precede stage 1: a spend that fails them
never reaches this document.
