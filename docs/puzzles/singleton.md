# The singleton wrapper benchmark puzzle

The fourth of the Phase 3 benchmark puzzles: a coin that exists
exactly once. A singleton is a lineage of coins, one live at a time,
carrying an identity fixed at launch and a state its owner or its
rules replace on every spend. Chia's `singleton_top_layer` is the
reference: it wraps an arbitrary inner program, rewrites the inner
program's output-creation conditions so the child coin is wrapped
the same way, and proves on every spend that the coin descends from
its launcher. Everything in Chia that needs a unique on-chain
identity sits on it: NFTs, decentralized identifiers, pool state,
DataLayer roots, name registries. The wrapper pattern it embodies,
a program that runs another program and morphs its conditions, is
the userspace covenant engine the evaluation document names, and
this puzzle is its acceptance test. This is tooling and vectors
only: nothing here changes `spec/` or the consensus implementation.

Sources live in `puzzles/singleton/`, shared helpers in
`puzzles/lib/`. Both programs compile with the two include
directories on the search path:

```
bitlisp-compile puzzles/singleton/singleton.bl -I puzzles/lib -I puzzles/singleton
bitlisp-compile puzzles/singleton/owner-inner.bl -I puzzles/lib -I puzzles/singleton
```

## Why the Chia construction does not port directly

Chia identifies a coin by the hash of three things: its parent
coin's id, its own puzzle hash, and its amount. A singleton proves
its descent in one step. The spend supplies the parent's inner
puzzle hash, the wrapper recomputes what the parent's full puzzle
hash must have been, hashes that into the parent coin id, hashes
that into its own coin id, and asserts the result with
ASSERT_MY_COIN_ID. One hash chain, one fixed-size proof, and the
parent's program is part of the child's identity.

Bitcoin identifies a coin by its outpoint: the txid of the creating
transaction and an output index. The txid commits to the creating
transaction's non-witness serialization, which names the outpoints
it spent and the scriptPubKeys it created, but never the
scriptPubKeys it spent. So a coin can prove which outpoint its
creating transaction consumed by supplying that transaction's
serialization, but to learn what script that outpoint carried it
must supply the grandparent's serialization as well. Two preimages
where Chia needs one, and the cost of the proof scales with the
size of the two transactions rather than being fixed.

A second obstacle is sharper. Chia's wrapper recognizes its
parent's puzzle hash by recomputing it, and can, because a puzzle
hash is a tree hash. Here the parent's scriptPubKey is a taproot
output key, the internal key tweaked by the merkle root, and no VM
operator performs that tweak. `secp_verify` is BIP340 Schnorr only,
and a Schnorr verification cannot be bent into a point addition the
way an ECDSA verification could. The validator derives the tweak
for the spending input's own scriptPubKey through ASSERT_MY_TAPROOT
and for claimed outputs through CREATE_OUTPUT_TAPROOT, and for
nothing else. A program can therefore recognize exactly one
scriptPubKey as a member of its own family: its own.

That constraint decides the construction. Every coin of a lineage
sits at one scriptPubKey, fixed at launch, so "the parent sat at a
lineage scriptPubKey" becomes a byte comparison against the coin's
own, which the validator has already proven. The state, the inner
program the spend must run, cannot then live in the scriptPubKey.
It lives in the creating transaction instead: a zero-value
OP_RETURN output tagged with the lineage commits the inner
program's tree hash, and the child reads it back through the same
serialization it already supplies for the lineage proof.

The alternative is the Chia shape with the inner program curried
into the wrapper, a scriptPubKey that changes with every state, and
a new VM operator computing the taproot tweak so the parent's
scriptPubKey can be recognized. Both sides, for the decision this
document records as open:

- For the constant scriptPubKey: it needs nothing the v0 vocabulary
  lacks, it costs no point multiplication beyond the one
  ASSERT_MY_TAPROOT already charges, a wallet watches one address
  for the whole lineage, and a counterparty paying to the singleton
  addresses it by that one scriptPubKey rather than by a hash that
  moves with the state. The state output costs about 80 bytes per
  spend.
- For the Chia shape: the scriptPubKey commits the state, so any
  construction that addresses a singleton by its current state
  (Chia's `p2_singleton` pattern, offers against a specific NFT
  state) works by computing one hash, and the inner program is part
  of the coin rather than a witness the spend reveals. It needs the
  tweak operator, a consensus change priced at one point
  multiplication, and the lineage proof still needs both
  serializations, since the grandparent reveals the parent's
  scriptPubKey either way.

The constant scriptPubKey is built here because it is buildable
inside the phase, and the tweak operator is recorded as a Phase 4
candidate with this puzzle as its first consumer. Ratifying the
deviation from the Chia shape, or reversing it once the operator
exists, is Evan's call.

## Instance identity

A singleton lineage is the wrapper program curried with three fixed
values. Its coins' scriptPubKey is the taproot output of the
internal key tweaked with the curried program's tree hash as the
merkle root, the same identity convention as the vault, with the
BIP341 nothing-up-my-sleeve point as the internal key so the
program is the whole spending policy.

| value | width | meaning |
| --- | --- | --- |
| `SINGLETON_MOD_HASH` | 32 | tree hash of the uncurried wrapper program |
| `INTERNAL_KEY` | 32 | the taproot internal key, the BIP341 NUMS point |
| `LAUNCHER_OUTPOINT` | 36 | the lineage's identity: the outpoint of the coin whose spend created the first singleton coin |

The launcher is any coin at all. Its outpoint exists before the
launch transaction does, so the identity is known, and the lineage
scriptPubKey computable, before the first singleton coin exists.
Base consensus spends the launcher once, and that is the whole
launch mechanism: no launcher program, no launch announcement.

Every spend asserts ASSERT_MY_TAPROOT over the recomputed root and
ASSERT_MY_SCRIPTPUBKEY over the scriptPubKey the solution supplies,
which together prove the supplied scriptPubKey is the lineage's. The
binding is program-to-coin only, as for the vault: the wallet checks
a curry before funding it. The wrapper checks the three values'
widths on every spend so a malformed instance fails on its first
spend of any kind.

## The lineage proof

```
   launcher L            coin 1 (first)           coin 2              coin 3
   any script     +----> spk_L, odd amt    +----> spk_L, odd     +--> spk_L, odd
   outpoint L     |      state: h1         |      state: h2      |    state: h3
        |         |          |             |         |           |
        v         |          v             |         v           |
   +----------+   |    +----------+        |   +----------+      |
   | launch   |---+    | spend 1  |--------+   | spend 2  |------+
   | spends L |        | spends   |            | spends   |
   | at in 0  |        | coin 1   |            | coin 2   |
   | out 0 -->|        | at in k  |            | at in j  |
   | OP_RETURN|        | out k -->|            | out j -->|
   |  L || h1 |        | OP_RETURN|            | OP_RETURN|
   +----------+        |  L || h2 |            |  L || h3 |
                       +----------+            +----------+

   coin 3 proves: spend 2 hashes to my txid, its input j is coin 2,
                  spend 1 hashes to coin 2's txid and created it at
                  spk_L, and spend 2 has one state output for L.
```

A spend supplies its creating transaction in full, as the field
list `puzzles/lib/tx-wire.blib` serializes, and the wrapper hashes
the serialization twice and asserts ASSERT_MY_OUTPOINT over that
txid and the coin's own output index. The serialization library
emits every length prefix in Bitcoin's canonical compact-size
encoding and width-checks every fixed field, so the byte string it
builds parses back, under Bitcoin's own parser, to exactly the
fields it was built from: a supplied field list proves the creating
transaction's structure, not merely its hash.

**The output-index rule.** The coin's parent is the creating
transaction's input at the coin's own output index. A singleton at
input k of its spending transaction must place its child at output
k. That is the wallet's only placement rule, and two singletons of
different lineages compose in one transaction by taking distinct
indices. The rule is what makes the lineage a chain rather than a
tree: the parent's outpoint is spent by exactly one transaction,
and within that transaction exactly one output index is the child.
A second output at the lineage scriptPubKey, added by whoever
assembled the transaction, is dust: its program reads the input at
its own index, finds a coin that never sat at the lineage
scriptPubKey, and fails.

**The parent check.** If the parent's outpoint equals
`LAUNCHER_OUTPOINT`, the coin is the first of its lineage and the
check ends. Otherwise the spend supplies the parent's creating
transaction too, the grandparent, with the parent's output index in
it. The grandparent must hash to the txid half of the parent's
outpoint, the index must match the index half, and the output at
that index must carry the lineage scriptPubKey byte-exact. That is
the induction step: a coin at the lineage scriptPubKey is spendable
only by running this program, so a transaction that spent one
spent a genuine singleton, and the genuine singleton's spend
created exactly one child. A coin at the lineage scriptPubKey that
no singleton spend created, however it was funded, has no proof and
never moves.

## The state output

The state is the inner program, supplied in full by the spend. The
creating transaction commits it through one output whose script is

```
OP_RETURN <68 bytes: LAUNCHER_OUTPOINT || inner program tree hash>
```

spelled `0x6a 0x44` then the 68 bytes, 70 bytes in all, amount
zero. The wrapper scans the creating transaction's outputs for
scripts opening with `0x6a44` and the lineage's outpoint, requires
exactly one, and requires it to end in the supplied inner program's
tree hash. The tag carries the lineage so that two singletons spent
in one transaction each find their own state output. Exactly one is
required because whoever assembles a transaction may add outputs
the claims never asked for: two tagged outputs would let the
assembler offer two states and let whoever can satisfy either
inner program take the singleton, so the child refuses both.

## The spend

The solution is `(MY_SPK MY_AMOUNT MY_INDEX PARENT_TX PARENT_VOUT
GRANDPARENT_TX INNER INNER_SOLUTION)`: the lineage scriptPubKey
(no operator derives it, so it arrives and is asserted), the coin's
amount and output index, the creating transaction, the parent's
output index in the grandparent and the grandparent itself (both
nil for the first coin), the inner program, and its solution.

Checks, in order: the curried values' widths, the index domain, the
coin's amount odd, the parent proven, the state proven. Then the
wrapper runs the inner program over the cons of its truths onto the
inner solution, the truths being
`(LAUNCHER_OUTPOINT MY_OUTPOINT MY_SPK MY_AMOUNT INNER_HASH)`, and
rewrites the conditions it yields. Emitted conditions:

1. `ASSERT_MY_TAPROOT INTERNAL_KEY <lineage root>`
2. `ASSERT_MY_SCRIPTPUBKEY MY_SPK`
3. `ASSERT_MY_AMOUNT MY_AMOUNT`
4. `ASSERT_MY_OUTPOINT <creating txid || MY_INDEX>`
5. The inner program's conditions, morphed.

**The morph.** Exactly one of the inner program's conditions must
be a CREATE_OUTPUT whose amount is odd, and the wrapper raises at
the second one or at the end of a list with none. Its scriptPubKey
operand is read as the next inner program's tree hash, 32 bytes,
and the condition becomes two: `CREATE_OUTPUT MY_SPK <amount>`, the
child at the lineage scriptPubKey, and
`CREATE_OUTPUT <state script for that hash> 0`. An odd amount of
exactly -113 instead ends the lineage: the condition is dropped and
no child is created, Chia's own escape value for a singleton's last
spend, kept here so a lineage ends only on an explicit signal and
never because an inner program forgot to create its child. Every
other condition passes through unchanged, so an inner program
creates ordinary outputs with even amounts and asserts whatever it
likes. Only the CREATE_OUTPUT opcode is inspected: an odd-amount
CREATE_OUTPUT_TAPROOT passes through as an ordinary output.

A singleton coin's amount is always odd, the child marker, and the
wrapper refuses to run on an even one.

## The owner inner program

`owner-inner.bl` is the simplest inner program that makes the
lineage useful: one curried key owns the state. Its solution is
`(NEXT_INNER_HASH NEXT_AMOUNT EXTRA_CONDITIONS SIG)`. It emits
`ASSERT_SIG_MY_OUTPOINT OWNER_KEY <tree hash of (NEXT_INNER_HASH
NEXT_AMOUNT EXTRA_CONDITIONS)> SIG`, binding the authorization to
the singleton coin's own outpoint, then `CREATE_OUTPUT
NEXT_INNER_HASH NEXT_AMOUNT`, the child marker, then the extra
conditions verbatim. Handing the singleton to a new owner is a
spend whose next inner hash is the program curried with the new
key. The signature travels through the wrapper untouched, because
the wrapper passes every condition but the marker through.

## Chia correspondence

| `singleton_top_layer` | here |
| --- | --- |
| `SINGLETON_STRUCT` = (mod hash, launcher id, launcher puzzle hash) | `SINGLETON_MOD_HASH`, `LAUNCHER_OUTPOINT`, no launcher program |
| launcher puzzle creating the eve coin and announcing it | any coin, spent by any transaction that places the first coin at the launcher's input index |
| `INNER_PUZZLE` curried, full puzzle hash moves with the state | inner program supplied in the solution, committed by the state output, one scriptPubKey per lineage |
| lineage proof (parent's parent, parent inner hash, parent amount) and ASSERT_MY_COIN_ID | creating and grandparent transactions, ASSERT_MY_OUTPOINT, the output-index rule |
| eve proof (parent's parent, parent amount) checked against the launcher puzzle hash | parent outpoint equals `LAUNCHER_OUTPOINT` |
| truths prepended to the inner solution | `(LAUNCHER_OUTPOINT MY_OUTPOINT MY_SPK MY_AMOUNT INNER_HASH)` |
| exactly one odd CREATE_COIN, morphed to the wrapped puzzle hash | exactly one odd CREATE_OUTPUT, morphed to the lineage scriptPubKey plus the state output |
| -113 escape value | -113, `END_AMOUNT` |
| my amount odd | same |

Recorded divergences from the Chia construction:

- The scriptPubKey is constant per lineage and the state is
  committed by a tagged OP_RETURN output of the creating
  transaction, for the reason the opening section states. The
  tweak operator that would allow the Chia shape is the recorded
  Phase 4 candidate.
- The lineage proof carries two transaction serializations, and its
  cost is the size of those transactions. A griefer who can assemble
  a singleton's spend, which any party can for an inner program
  with a public path, can bloat that transaction so the next two
  spends carry it in their witnesses. An inner program with a
  public path that cares seals its outputs. Chia's proof is three
  fixed-size fields.
- There is no launcher program. Chia's launcher exists to fix the
  singleton id before the eve coin exists and to create exactly one
  eve coin. Here the launcher's outpoint is the id and base
  consensus spends it once, and the output-index rule makes exactly
  one output of that spend the first coin.
- The child's placement is a rule rather than a consequence. Chia's
  CREATE_COIN creates exactly the coin it names, so an inner
  program's authorization is the child's existence. Here validation
  rule 1 matches claims by content without fixing an index, and
  rule 2 leaves unclaimed outputs free, so the wrapper can claim
  the child but cannot place it, and whoever assembles the
  transaction can. The output-index rule plus the state output's
  uniqueness close the two attacks that freedom opens: a
  substituted child at the singleton's index carries a state hash
  the unique state output does not commit, so it is dead, and the
  authorized child placed elsewhere finds no parent at its index,
  so it is dead too. Either way the assembler gets no singleton.
  What the assembler keeps is the power to end the lineage by
  misplacing the child or doubling the state output, a griefing
  that Chia's exact coin creation does not allow, available only to
  a party who could already refuse to assemble the transaction.
  The inner program's signature covers the marker and the extra
  conditions, so against a signing owner none of this arises.

## Adversarial cases

Each is pinned in `vectors/vm/singleton-programs.json` or
`vectors/validation/singleton-lineage.json`, and reproduced with
its exact error code in `python/tests/test_singleton_puzzles.py`.

- A coin at the lineage scriptPubKey funded by an ordinary payment,
  with a perfect state output beside it, fails the parent check:
  its creating transaction's input at its index is not the launcher
  and sat at no lineage scriptPubKey, whatever grandparent is
  supplied.
- A second output at the lineage scriptPubKey, added to a genuine
  spend at another index, is dust: its index names a fee input, or
  no input at all.
- The authorized conditions presented for a coin at the wrong
  outpoint fail ASSERT_MY_OUTPOINT in the validator.
- An inner program other than the committed one fails the state
  check, and so does a creating transaction carrying two tagged
  state outputs.
- An even amount, an inner program creating no odd output, and one
  creating two, all raise.
- A malformed instance and a serialization with a wrong field
  width raise before any condition is emitted.

## Fees and composition

The wrapper claims the child and the state output and asserts its
own data. It seals nothing, so fee inputs attach freely and two
lineages compose in one transaction at distinct indices, pinned by
a vector. The transaction model requires outputs not to exceed
inputs, so every example transaction carries an ordinary fee input
beside the singleton coin, and the launch transaction is a plain
wallet transaction whose only BitLisp content is the two outputs it
creates.

## Worked instance

The mod hashes, pinned in `python/tests/test_singleton_puzzles.py`:

```
$ bitlisp-compile -T puzzles/singleton/singleton.bl -I puzzles/lib -I puzzles/singleton
5f9b069d8c33d55360ee8ac42a97ff64680b28a40195daf8c3851cf0ebeb3849
$ bitlisp-compile -T puzzles/singleton/owner-inner.bl -I puzzles/lib -I puzzles/singleton
b8bdd33e430a797065babc3ea3adcf15c9c0f62b1c7ae78f92ef9a6b1e61f9f0
```

A lineage's merkle root and scriptPubKey follow from the launcher's
outpoint alone:

```
$ bitlisp-compile puzzles/singleton/singleton.bl -I puzzles/lib -I puzzles/singleton \
  | bitlisp-curry -a 0x<singleton mod hash> -a 0x<internal key> -a 0x<launcher outpoint> -T
```

Measured on the test lifecycle: the curried wrapper serializes to
3416 bytes, the first spend's solution to 522 bytes and a later
generation's to 804, the two serialized transactions being most of
it. Evaluation costs 197071 for the first spend and 274191 for a
later generation before the conditions charge, which add about 5.3
million for the taproot assert, the signature assert, and the two
output claims.

The compiled representatives, one per lifecycle step with the
in-program failures, are pinned in
`vectors/vm/singleton-programs.json`, and the condition-level
lifecycle in `vectors/validation/singleton-lineage.json`. The test
suite recompiles both programs, byte-compares every pinned program
against a fresh compile and curry, builds the lifecycle from real
transaction ids through the transaction model, and recomputes every
conditions field in the validation vector file. Source and corpus
move together or not at all.
