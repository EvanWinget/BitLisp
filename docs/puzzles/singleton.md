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
this puzzle is its acceptance test. Whether the singleton itself
earns a place on Bitcoin is a separate question, answered honestly
in the next section: for the constructions Bitcoin cares about
first it does not, and what it built is the foundation the asset
token benchmark needs. This is tooling and vectors only: nothing
here changes `spec/` or the consensus implementation.

Sources live in `puzzles/singleton/`, shared helpers in
`puzzles/lib/`. Both programs compile with the two include
directories on the search path:

```
bitlisp-compile puzzles/singleton/singleton.bl -I puzzles/lib -I puzzles/singleton
bitlisp-compile puzzles/singleton/owner-inner.bl -I puzzles/lib -I puzzles/singleton
```

## Is a singleton worth having on Bitcoin

The singleton entered the plan with the repository's first commit
as one of four puzzles to write, with no recorded rationale, and
the evaluation document's benchmark suite never lists it. The suite
lists a fungible asset token, and mentions singletons once, as the
example of the wrapper pattern. So the question of value was owed
before review, and it was answered two ways on 2026-08-22: a census
of what the vendored Chia code actually uses singletons for, and a
pass over the constructions Bitcoin cares about first.

The test that decides it is the **funded imitation**: anyone can
pay to a construction's scriptPubKey and then try to spend that coin
as if it were the real one. A singleton exists to make that coin
unspendable. The question for each construction is who loses if it
were spendable.

| construction | identity comes from | state advanced by | a funded imitation hurts | singleton needed |
| --- | --- | --- | --- | --- |
| Lightning channel, LN-Symmetry | the funding outpoint | 2-of-2 signatures | the faker only | no |
| channel factory | the factory outpoint | n-of-n signatures | the faker only | no |
| Ark round | the round outpoint | the coordinator and the users, timelocks | the faker only | no |
| vault | the curried policy | the owner's key, then keyless paths | nobody, a funded "fake" vault coin is a deposit | no |
| payment pool | the pool outpoint | n-of-n, unilateral exit under rules | the faker only, an exit from a fake balance tree returns the faker's own sats | no |
| oracle or DLC with a fixed key | the key | the key | nobody, ASSERT_SIG_RAW suffices, no co-spend needed | no |
| fungible asset token | the issuance lineage | anyone holding tokens | everyone, a fake mints value from nothing | yes, this lineage proof |
| name registry, identity with a changing policy | the lineage | a program, not one key | whoever relied on the name or identity | yes |

Every value-carrying construction gets identity from its root
outpoint, which base consensus spends exactly once, and authority
from its parties' signatures, and an imitation is someone buying
their own coin. The singleton earns its keep only where the coin's
meaning is external to its own satoshis: a token's provenance, a
name, an identity whose policy changes over time.

The Chia census says the same. Every dependent in the vendored
corpora names a singleton by its launcher id: the NFT layers (one
NFT, one history), the DID inner puzzle (identity across key
recovery, and a forked DID could cast a recovery vote twice), the
pool member (a reward absorbed once, keyless), and the tibetswap
pair, whose reserve coins hold real value claimable only by the one
live descendant. chia-gaming, a real state channel with off-chain
state and preemption, never applies the wrapper at all: two keys
and per-coin curried commitments carry it, the Lightning shape.
Every Chia use is a token, an identity, or a coin governing other
coins, and none is a two-party value-carrying state machine.

The census also settled the design question this document records
as open below. No dependent needs the puzzle hash to move with the
inner puzzle. The only thing any of them reconstructs from the
current hash is an announcement target, and each such site
(`p2_singleton`, the liquidity TAIL, DID recovery) must be handed
the current inner hash at runtime to do it. Under a constant
scriptPubKey that overhead disappears, and Chia's singleton
fast-forward, today usable only for singletons whose inner puzzle
never changes, would apply to every singleton. The constant
scriptPubKey is the better shape on Chia's own evidence, not a
compromise.

Verdict, recorded for the plan: the singleton as a standalone
identity primitive has thin demand on Bitcoin, and Ark, Lightning,
vaults, and pools will not import it. What this puzzle built, the
serialization library, the two-preimage lineage proof, the
output-index rule, and the condition morph, is exactly what the
fungible asset token needs, the one construction on the list where
a funded imitation steals, and the suite's own entry. That is the
value this work delivered, and the remaining benchmark effort on
lineage belongs there.

One thing the token benchmark is not: a goal. BitLisp does not set
out to put fungible asset tokens on Bitcoin. The benchmark exists
because a covenant vocabulary that can express a vault can
probably express a token layer too, and the project's obligation is
to know that, to know what it costs, and to state the risks, rather
than to discover them after deployment. The token is built to
understand the capability and its exposure, not to ship it. Should
a standard ever be written, its name is BAT1, the Bitcoin asset
token standard (decision by Evan, 2026-08-22).

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

## Authoring observations across the vault and the singleton

Two puzzles in the v0 language, about 500 source lines between
them, are enough to see repeated shapes. Each is recorded here with
a concrete candidate, for the typed v1 ledger and for the language
itself. None is implemented by this change.

1. **Naming a value once is the dominant cost.** The vault's
   `dispatch` exists to name a reconstructed root, and the
   singleton's `spend` and `emit` exist to name a txid and an inner
   hash, each threading nine to eleven parameters through a helper
   whose only purpose is a binding. The pre-registered `assign`
   trigger has now fired in both puzzles. Candidate: a `let` form
   with several bindings, compiled exactly as those helpers are
   written by hand, a synthetic function taking the bound names as
   parameters and called once, so it costs one apply and no new
   compiled shape. Chialisp's modern compiler has `let` and
   `assign`, and the census that deferred them found two test-only
   uses. The puzzles are the production evidence that was missing.
2. **Every curried value gets a domain guard.** Both puzzles open
   with an `assert` block checking widths and ranges of every fixed
   value, because a malformed instance must fail on its first
   spend rather than on the one path that reads the bad value. This
   is the evidence the typed v1 gate asked for: the curried
   parameter domains are the main thing a type would check, and a
   compiler that emitted these guards from declared widths would
   remove the block and the risk of omitting one entry from it.
3. **List helpers are rewritten per puzzle.** `sum-amounts`,
   `require-conditions`, `state-scripts`, `length`, `nth`, and the
   serializers are all the same recursion skeleton. Without
   function values or macros there is no `map`, and that is
   Chialisp's position too, but `length` and `nth` now live in
   `tx-wire.blib` and take those names for every program that
   includes it, under the one-namespace rule. Candidate: a standard
   `puzzles/lib/list.blib` owning the generic names, so a library
   never claims them incidentally.
4. **Consing conditions onto a tail.** Condition lists are built as
   `(c A (c B (c C TAIL)))` in both puzzles because `list` cannot
   end in a tail. Candidate: a `list*` form consing its arguments
   onto its last one, a purely syntactic compiler form with an
   obvious expansion. Chialisp lacks it, so it would be a recorded
   tooling divergence, and a small one.
5. **Identity reconstruction is the same call three times.**
   `vault-root`, `triggered-root`, and `singleton-root` each spell
   `curried-tree-hash` over a hand-written list of `sha256tree`
   calls. A `map` would fold them, and its absence is item 3.
   Until then a helper taking the raw values, one arity per
   length, is the honest option, and the Phase 4 commitment scheme
   may replace the whole convention.
6. **Self data arrives in the solution and is asserted.** The
   scriptPubKey, amount, and outpoint are supplied and then pinned
   with the self asserts in every path of both puzzles, because no
   operator reads the spending input's prevout. That is Chia's
   shape as well and costs one condition each. A library helper
   emitting the three asserts together would remove the repetition
   without touching the vocabulary.
7. **Byte-level encoding is clumsy at the VM layer.** Little-endian
   widths are built one byte at a time through
   `(substr (+ 256 B) 1 2)`, and the serialization library spends
   most of its lines on compact-size and field widths. A Bitcoin
   program that reads transactions will do this often. This is a
   Phase 4 cost question, not a language one: a fixed-width
   integer encoding operator, or a transaction-field family in the
   spirit of the "opcodes special to parsing Bitcoin transactions"
   Bram Cohen suggested for a UTXO-model Lisp, would shrink both the
   witness and the cost line.
8. **Test harnesses repeat.** `test_vault_puzzles.py` and
   `test_singleton_puzzles.py` each define proper-list building,
   outpoint-bound signing, BitLisp input construction, and the
   instance helper. A shared puzzle test module is due before the
   third puzzle.

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
