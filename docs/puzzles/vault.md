# The vault benchmark puzzle

The first of the four Phase 3 benchmark puzzles: coins held so that
sends pass through a public delay with an always-available recovery
path, plus a keyless consolidation path that lets anyone merge the
vault's coins back into one. The core semantics reproduce BIP-345
(OP_VAULT and OP_VAULT_RECOVER) with the condition vocabulary
instead of new opcodes. This is tooling and vectors only: nothing
here changes `spec/` or the consensus implementation.

Sources live in `puzzles/vault/`, shared helpers in `puzzles/lib/`.
Both programs compile with the two include directories on the
search path:

```
bitlisp-compile puzzles/vault/vault.bl -I puzzles/lib -I puzzles/vault
bitlisp-compile puzzles/vault/triggered.bl -I puzzles/lib -I puzzles/vault
```

## Instance identity

A vault instance is the vault program curried with its seven fixed
values. Its coin's scriptPubKey is the taproot output of a fixed
internal key tweaked with the curried program's tree hash as the
merkle root, the derivation CREATE_OUTPUT_TAPROOT performs in
the validator. The internal key is the
BIP341 nothing-up-my-sleeve point, so no key-path spend exists and
the program is the whole spending policy.

No VM operator performs the taproot tweak, so a program cannot
derive its own 34-byte scriptPubKey. What it can do is recompute
its own curried tree hash: the curried shape
`(a (q . F) (c (q . v1) ... 1))` is fixed, so the hash follows from
the uncurried program's tree hash and the tree hashes of the fixed
values. The helpers in `puzzles/lib/curry-hash.blib` compute
exactly the digest `bitlisp-curry -T` prints. Every path emits
`ASSERT_MY_TAPTREE` over the fixed internal key and the
reconstructed root, the execution identity base consensus
authenticated from the control block, binding the
program run to the coin it claims to govern: one instance's
program can never spend another instance's coin, and a program
installed against a coin at any other scriptPubKey fails its own
assert.

That binding is exactly program-to-coin and nothing stronger. The
assert recomputes the root from the same curried values the coin's
scriptPubKey was derived from, so it cannot detect that those
values differ from the author's intent: a coin funded from a curry
with transposed or wrong values is live and governed by that wrong
curry. Verifying a curry before funding it is the wallet's job,
and `bitlisp-uncurry` plus the `-T` flag exist for it.

What the programs do check, on every path of both states, is that
each fixed value sits inside its domain: the authorization key is
32 bytes, the recovery key is nil or 32 bytes, the recovery
scriptPubKey is 1 to 10000 bytes, the delay is 0 to 65535 and
minimally encoded, and the triggered state's target hash is 32
bytes. Without these guards a value outside its domain would break
a single path at spend time while the others kept working, a
quietly lost recovery path being the worst case, and the recovery
scriptPubKey is exactly the value whose failure is that worst
case: nil is the legitimate spelling for the adjacent recovery
key, and an instance curried with a nil recovery scriptPubKey
would trigger, revault, and consolidate perfectly while the panic
button alone was dead. The minimality clause exists because a
padded delay encoding reads as the same number in these guards but
is rejected by the sequence assert it feeds, which would brick
withdrawal alone. With the guards a malformed instance fails on
its first spend of any kind, before it has a history.

This identity convention is a recorded stand-in. The commitment
scheme of `spec/SPEC.md` commits a program in a leaf whose script
is the curried program's tree hash, so a coin's merkle root is the
tagged leaf hash over that tree hash, or a tagged branch fold when
the paths sit in leaves of their own. The sources here still use
the bare tree hash as the root, confined to the `curry-hash.blib`
call sites, until the vault is re-pinned under the scheme in its
own unit, where each path becomes a leaf and only the trigger path
keeps reconstruction (commitment-record decisions 7 and 8).

## The two programs

`vault.bl` is the resting state. Curried values, in order:

| value | width | meaning |
| --- | --- | --- |
| `VAULT_MOD_HASH` | 32 | tree hash of the uncurried vault program |
| `TRIG_MOD_HASH` | 32 | tree hash of the uncurried triggered program |
| `AUTH_KEY` | 32 | x-only key authorizing triggers |
| `INTERNAL_KEY` | 32 | the taproot internal key, the BIP341 NUMS point |
| `RECOVERY_SPK` | script | the recovery destination, literal scriptPubKey bytes |
| `RECOVERY_KEY` | 0 or 32 | nil for keyless recovery, an x-only key to require a recovery signature |
| `DELAY` | int | the withdrawal delay in blocks, 0 to 65535 |

`triggered.bl` is the delayed state a trigger creates. Curried
values: `TRIG_MOD_HASH`, `INTERNAL_KEY`, `RECOVERY_SPK`,
`RECOVERY_KEY`, `DELAY`, `TARGET_HASH`. The first five carry over
from the vault unchanged, and `TARGET_HASH` is chosen at trigger
time.

Both take the solution `(PATH . ARGS)`.

```
                 trigger (AUTH_KEY signs target)
   +-------+  ------------------------------------>  +-----------+
   | vault |          revault remainder              | triggered |
   |       |  <------------------------------------  |           |
   +-------+                                         +-----------+
     |   ^  \                                         /    |
     |   |   \  recovery (anyone, or RECOVERY_KEY)   /     |  withdrawal
     |   |    v                                     v      |  (DELAY blocks,
     |   |    +------------- RECOVERY_SPK ----------+      |   exact TARGET
     |   |                                                 v   outputs)
     |   +--- consolidation (anyone, leader + followers,  outputs named
     +------- merges coins back into one vault coin)      by TARGET_HASH
```

## Vault paths

**Path 1, trigger.** ARGS is
`(TARGET TRIG_AMT REVAULT_AMT MY_AMT SIG)`. The program rejects a
`TARGET` that is not 32 bytes, a non-positive `TRIG_AMT`, a
negative `REVAULT_AMT`, and `MY_AMT > TRIG_AMT + REVAULT_AMT`, the
BIP-345 value rule over the coin's own pinned amount. The amount
guards hold even against a misbehaving signer: no signed solution
can mint an oversized triggered coin through a negative revault or
a worthless zero-value one. Emitted conditions:

1. `ASSERT_MY_TAPTREE INTERNAL_KEY <vault root>`
2. `ASSERT_MY_AMOUNT MY_AMT`
3. `ASSERT_SIG_MY_OUTPOINT AUTH_KEY <digest message> SIG` where the
   message is the tree hash of `(1 TARGET TRIG_AMT REVAULT_AMT)`,
   the leading 1 the trigger's signing-domain tag. The digest binds
   the consumed outpoint, so an authorization cannot be replayed
   onto a sibling coin of the same instance, and it binds the
   target and both amounts, so a captured signature authorizes
   exactly one trigger shape. The tag keeps trigger and recovery
   authorizations in disjoint domains even for an operator who
   curries one key into both roles, instead of resting on the two
   message lists' shapes happening to differ.
4. `CREATE_OUTPUT_TAPROOT INTERNAL_KEY <triggered root> TRIG_AMT`,
   the triggered root computed over the carried-over values plus
   `TARGET`.
5. When `REVAULT_AMT > 0`, `CREATE_OUTPUT_TAPROOT INTERNAL_KEY
   <vault root> REVAULT_AMT`, re-encumbering the remainder under
   the byte-exact original scriptPubKey.

**Path 2, recovery.** ARGS is `(MY_AMT RECOVER_AMT)` keyless, with
a trailing signature when `RECOVERY_KEY` is set. The program
rejects `MY_AMT > RECOVER_AMT`. Emitted conditions: the taproot
assert, `ASSERT_MY_AMOUNT MY_AMT`, and
`CREATE_OUTPUT RECOVERY_SPK RECOVER_AMT`, plus
`ASSERT_SIG_MY_OUTPOINT RECOVERY_KEY <tree hash of (2 MY_AMT
RECOVER_AMT)> SIG` in the keyed posture, the leading 2 the
recovery signing-domain tag. A recovery moves at least
the coin's full value to the fixed recovery destination and
nowhere else. Keyless recovery lets any watcher sweep a coin under
attack without holding a key, at the cost of value-preserving
griefing. The keyed posture closes the griefing and costs key
management. The choice is per instance.

**Path 3, consolidation follower.** ARGS is `(MY_SPK)`. Emitted
conditions: the taptree assert, `ASSERT_MY_SCRIPTPUBKEY MY_SPK`,
and `ASSURE 98 () MY_SPK`. The scriptPubKey arrives in the
solution because no operator derives it, and the assert proves it
is the coin's own. Mode 98 puts the assurer half at commitment 3,
the assuring input's own scriptPubKey and amount filled by the
validator from real prevout data, and the requirer half at
commitment 2, addressing the shared scriptPubKey.

**Path 4, consolidation leader.** ARGS is
`(MY_SPK MY_AMT OUT_AMT FOLLOWER_AMOUNTS)`. The program rejects an
empty follower list and `MY_AMT + sum(FOLLOWER_AMOUNTS) > OUT_AMT`.
Emitted conditions: the taptree assert,
`ASSERT_MY_SCRIPTPUBKEY MY_SPK`, `ASSERT_MY_AMOUNT MY_AMT`, one
`REQUIRE 98 () MY_SPK <amount>` per listed follower
amount, and `CREATE_OUTPUT MY_SPK OUT_AMT`.

An unknown path raises.

## Triggered paths

**Path 1, withdrawal.** ARGS is `()`. Emitted conditions: the
taptree assert over the triggered root,
`ASSERT_SEQUENCE_HEIGHT DELAY`, and `SEAL_OUTPUTS TARGET_HASH`.
The sequence assert makes the coin `DELAY` blocks old before it
moves. The seal fixes every output slot of the spending
transaction to the committed set and nothing else, so the
withdrawal pays exactly the outputs `TARGET_HASH` names while
anyone may add a fee input to a stuck withdrawal. The seal operand
is curried, committed in the scriptPubKey, so the unsigned-seal
footgun of solution-supplied seals does not apply. The open input
side cuts the other way too: two triggered coins carrying the same
target hash satisfy one output set together and the second coin's
value burns to fees, the recorded divergence below, so a wallet
never reuses a target.

**Path 2, recovery.** Identical to the vault's recovery path with
the triggered root in the taptree assert, available at any time
before a withdrawal confirms, before or after the delay matures.

## BIP-345 correspondence

| BIP-345 | here |
| --- | --- |
| vault taptree, trigger leaf plus recovery leaf | the vault program's path dispatch |
| OP_VAULT leaf-update: trigger output carries the taptree with the leaf substituted | the trigger claims a `CREATE_OUTPUT_TAPROOT` whose merkle root is the triggered program curried with `TARGET_HASH` |
| leaf-update script, CSV plus CTV | the triggered program's withdrawal path, `ASSERT_SEQUENCE_HEIGHT` plus `SEAL_OUTPUTS` |
| CTV hash chosen at trigger time in witness data | `TARGET` in the trigger solution, signed by `AUTH_KEY` |
| revault output at the input's own scriptPubKey | the `REVAULT_AMT` claim at the byte-exact vault scriptPubKey |
| trigger amount rule, deferred checks | the in-program value guard plus exact output claims under validation rule 1 |
| OP_VAULT_RECOVER, recovery scriptPubKey pinned by hash | the recovery path, `RECOVERY_SPK` curried as literal bytes |
| unauthorized or authorized recovery | `RECOVERY_KEY` nil or set, per instance |
| recovery output value at least the input value | the `MY_AMT <= RECOVER_AMT` guard over the pinned own amount |

Recorded divergences from BIP-345:

- `RECOVERY_SPK` is curried as literal bytes where the BIP pins a
  tagged hash of it. Curried data is already committed data, and
  `CREATE_OUTPUT` needs the literal bytes, so the hash indirection
  buys nothing here.
- Batched triggers merging several vault inputs into one summed
  trigger output are declined scope. Validation rule 1 matches
  claims to output slots by exact content and counts them, it
  never sums, so per-input triggers compose in one transaction
  with one triggered output each, and the summing instrument in
  this vocabulary is the consolidation message ledger below.
- `SEAL_OUTPUTS` drops the input-side commitment BIP-345 inherits
  from CTV's template hash, and that loss has a consequence, not
  just a flexibility gain. The gain: fee inputs attach freely to a
  stuck withdrawal. The consequence: the withdrawal path is
  keyless, and the seal explicitly leaves which inputs exist
  unconstrained, so two matured triggered coins carrying the same
  target hash can be spent in one transaction where the single
  committed output set satisfies both seals and the second coin's
  entire value becomes fee. Anyone may build that transaction, and
  a miner profits from building it. CTV's input-count commitment
  is exactly the known half-spend protection, and this construction
  does not have it. Wallets must therefore never produce two
  triggered coins with the same target hash: make every target
  unique, by perturbing an output amount, adding a per-trigger salt
  output, or simply never re-triggering an unspent target. The
  merge-and-burn transaction is pinned as the vector
  `same_target_withdrawals_merge_second_burns`, expected valid,
  because the validator accepts it and the defense is the wallet
  rule. A seal variant that also commits the input count would
  close this at the vocabulary level and is flagged for a spec
  decision outside this unit.
- The BIP's fee posture otherwise survives: no vault path can pay
  vault value out as fees on its own, and fee inputs attach freely
  because the seal and the claims constrain outputs, not inputs.
  The same-target merge above is the recorded exception.

## The consolidation construction

Consolidation answers the benchmark case recorded in the
evaluation document: an input authorized only if some output pays
the input's own scriptPubKey at least the summed value of every
input sharing that scriptPubKey, with the validator doing linear
work.

The spender, who needs no key, picks one coin as leader. Every
other coin spends its follower path and sends one message
addressed to the shared scriptPubKey, the assurer half carrying its
own scriptPubKey and amount from prevout data the validator fills.
The leader lists the follower amounts in its solution, requires
one matching message per listed amount, and claims one output
paying the shared scriptPubKey at least its own amount plus the
listed sum.

The message ledger makes the sum honest. Message records balance
only when k identical ASSURE records meet exactly k identical
REQUIRE records, so:

- An omitted follower leaves an unmatched ASSURE. Its coin cannot
  be silently absorbed.
- A phantom or misstated listed amount creates an unmatched
  REQUIRE. The sum cannot be inflated or deflated against the
  coins actually present.
- Two followers of equal amount produce one record at weight two,
  and the leader must list the amount twice.
- A hostile input at a foreign scriptPubKey cannot forge a
  follower record, because the assurer half is filled from its
  real prevout data, and cannot intercept the followers as a fake
  leader, because its REQUIRE records carry its own scriptPubKey
  in the requirer half while the followers addressed the vault's.
- A negative or non-minimal listed amount dies at condition
  parsing, before the ledger runs.
- Two independently balanced consolidations at the same
  scriptPubKey compose in one transaction.

The leader path rejects an empty follower list, so every
consolidation merges at least two coins, and no keyless path can
split a coin's value, a revault needing the trigger signature. Any
conflicting consolidation an adversary substitutes therefore still
merges the coins it consumes. That is deliberately not a claim
that the coin count at the scriptPubKey only falls: validation
rule 1 leaves unclaimed output slots unconstrained, so a
transaction can carry additional funded outputs at the vault's
scriptPubKey. Creating such a coin costs its full value, and
anyone can dust any scriptPubKey with an ordinary payment at any
time, so this adds nothing to the consolidation attack surface.
What remains to an adversary is value-preserving griefing,
spending their own fees to delay a pending merge or to choose
which coins merge, the same griefing posture as keyless recovery,
and a vault that objects chooses the keyed recovery posture and
accepts the key management.

One reading note against the benchmark as the evaluation document
records it: the recorded predicate sums every input at the shared
scriptPubKey, while this construction enforces it per group, the
leader plus its listed followers, and independently balanced
groups compose in one transaction. The single-output global form
is the one-group case. Per group is the only reading compatible
with the validation layer's composition guarantee, under which two
valid spend sets must stay valid when combined, so the
construction takes it deliberately.

The theft cases above are pinned in
`vectors/validation/vault-consolidation.json`, one vector per
attack shape, the negative and non-minimal listed amounts and the
two-leaders double-claim included.

## Fees

The transaction model requires outputs not to exceed inputs, and
every value rule here is a floor on an output claim, so each
example transaction carries an ordinary fee input beside the vault
coins. Withdrawal transactions additionally accept fee inputs
added by anyone after the fact, because `SEAL_OUTPUTS` leaves the
input side open.

## Worked instance

The mod hashes, pinned in `python/tests/test_vault_puzzles.py`:

```
$ bitlisp-compile -T puzzles/vault/vault.bl -I puzzles/lib -I puzzles/vault
802e8fda9a74a0fdf0170b2e974ae3d9b91805c4f7640997f05b1b0d0268dc13
$ bitlisp-compile -T puzzles/vault/triggered.bl -I puzzles/lib -I puzzles/vault
8c7afe4710a59fc8dfa7534f0fef404b45acb8dc494b681e17f1b08f4609b461
```

An instance's merkle root is the curried tree hash, printable
without running anything:

```
$ bitlisp-compile puzzles/vault/vault.bl -I puzzles/lib -I puzzles/vault \
  | bitlisp-curry -a 0x<vault mod hash> -a 0x<trig mod hash> \
      -a 0x<auth key> -a 0x<internal key> -a 0x<recovery spk> \
      -a 0x -a 144 -T
```

Measured through the single-spend runner at the provisional
constants, evaluation and condition charges together: a trigger
spend with no revault costs 4,054,131 and one with a revault
claim 6,704,696, a keyless recovery 1,407,940, a matured
withdrawal 49,468, a consolidation leader with two followers
1,418,898, and a follower 57,496. Each is exactly 1,300,000 below
the same spend under ASSERT_MY_TAPROOT, the derivation assert decision 29
has since removed, the point multiplication
the taptree assert does not run because base consensus already
authenticated the identity it reads. The condition charge itself
is 200 against 1,300,200, and a minimal spend emitting one
identity assert and nothing else runs at 220 against 1,300,220
through evaluation and parsing together.

The compiled representatives, one per spend path with the
in-program guard failures and the malformed instances, are pinned
in `vectors/vm/vault-programs.json`, and the condition-level
lifecycle in `vectors/validation/vault-core.json`. The test suite
recompiles both programs, byte-compares every pinned program
against a fresh compile and curry, and recomputes every conditions
field in both validation vector files, program-derived lists from
compiled source and the hand-built hostile variants from their
documented constructions, with set equality in both directions.
Source and corpus move together or not at all.
