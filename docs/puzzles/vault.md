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
merkle root, the derivation CREATE_OUTPUT_TAPROOT and
ASSERT_MY_TAPROOT perform in the validator. The internal key is the
BIP341 nothing-up-my-sleeve point, so no key-path spend exists and
the program is the whole spending policy.

No VM operator performs the taproot tweak, so a program cannot
derive its own 34-byte scriptPubKey. What it can do is recompute
its own curried tree hash: the curried shape
`(a (q . F) (c (q . v1) ... 1))` is fixed, so the hash follows from
the uncurried program's tree hash and the tree hashes of the fixed
values. The helpers in `puzzles/lib/curry-hash.blib` compute
exactly the digest `bitlisp-curry -T` prints. Every path emits
`ASSERT_MY_TAPROOT` over the reconstructed root, binding execution
to the coin the program claims to govern. A wrongly curried
instance fails that assert on every path, so the failure mode is
an unspendable coin, never theft.

This identity convention is a recorded stand-in: the Phase 4
commitment scheme decides how programs are really committed under
the new tapleaf version, and it may replace the bare curried tree
hash with a tagged leaf construction. The convention is confined
to the `curry-hash.blib` call sites.

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
`(TARGET TRIG_AMT REVAULT_AMT MY_AMT SIG)`. The program rejects
`MY_AMT > TRIG_AMT + REVAULT_AMT`, the BIP-345 value rule over the
coin's own pinned amount. Emitted conditions:

1. `ASSERT_MY_TAPROOT INTERNAL_KEY <vault root>`
2. `ASSERT_MY_AMOUNT MY_AMT`
3. `ASSERT_SIG_MY_OUTPOINT AUTH_KEY <digest message> SIG` where the
   message is the tree hash of `(TARGET TRIG_AMT REVAULT_AMT)`. The
   digest binds the consumed outpoint, so an authorization cannot
   be replayed onto a sibling coin of the same instance, and it
   binds the target and both amounts, so a captured signature
   authorizes exactly one trigger shape.
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
`ASSERT_SIG_MY_OUTPOINT RECOVERY_KEY <tree hash of (MY_AMT
RECOVER_AMT)> SIG` in the keyed posture. A recovery moves at least
the coin's full value to the fixed recovery destination and
nowhere else. Keyless recovery lets any watcher sweep a coin under
attack without holding a key, at the cost of value-preserving
griefing. The keyed posture closes the griefing and costs key
management. The choice is per instance.

**Path 3, consolidation follower.** ARGS is `(MY_SPK)`. Emitted
conditions: the taproot assert, `ASSERT_MY_SCRIPTPUBKEY MY_SPK`,
and `SEND_MESSAGE 26 () MY_SPK`. The scriptPubKey arrives in the
solution because no operator derives it, and the assert proves it
is the coin's own. Mode 26 puts the sender half at commitment 3,
the sending input's own scriptPubKey and amount filled by the
validator from real prevout data, and the receiver half at
commitment 2, addressing the shared scriptPubKey.

**Path 4, consolidation leader.** ARGS is
`(MY_SPK MY_AMT OUT_AMT FOLLOWER_AMOUNTS)`. The program rejects an
empty follower list and `MY_AMT + sum(FOLLOWER_AMOUNTS) > OUT_AMT`.
Emitted conditions: the taproot assert,
`ASSERT_MY_SCRIPTPUBKEY MY_SPK`, `ASSERT_MY_AMOUNT MY_AMT`, one
`RECEIVE_MESSAGE 26 () MY_SPK <amount>` per listed follower
amount, and `CREATE_OUTPUT MY_SPK OUT_AMT`.

An unknown path raises.

## Triggered paths

**Path 1, withdrawal.** ARGS is `()`. Emitted conditions: the
taproot assert over the triggered root,
`ASSERT_SEQUENCE_HEIGHT DELAY`, and `SEAL_OUTPUTS TARGET_HASH`.
The sequence assert makes the coin `DELAY` blocks old before it
moves. The seal fixes every output slot of the spending
transaction to the committed set and nothing else, so the
withdrawal pays exactly the outputs `TARGET_HASH` names while
anyone may add a fee input to a stuck withdrawal. The seal operand
is curried, committed in the scriptPubKey, so the unsigned-seal
footgun of solution-supplied seals does not apply.

**Path 2, recovery.** Identical to the vault's recovery path with
the triggered root in the taproot assert, available at any time
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
- Withdrawal batching is what `SEAL_OUTPUTS` allows: spends
  committing to the same target can share a transaction, and
  nothing else can add an output to it.
- The BIP's fee posture survives: vault value never pays fees, and
  fee inputs attach freely because the seal and the claims
  constrain outputs, not inputs.

## The consolidation construction

Consolidation answers the benchmark case recorded in the
evaluation document: an input authorized only if some output pays
the input's own scriptPubKey at least the summed value of every
input sharing that scriptPubKey, with the validator doing linear
work.

The spender, who needs no key, picks one coin as leader. Every
other coin spends its follower path and sends one message
addressed to the shared scriptPubKey, the sender half carrying its
own scriptPubKey and amount from prevout data the validator fills.
The leader lists the follower amounts in its solution, receives
one matching message per listed amount, and claims one output
paying the shared scriptPubKey at least its own amount plus the
listed sum.

The message ledger makes the sum honest. Message records balance
only when k identical sends meet exactly k identical receives, so:

- An omitted follower leaves an unmatched send. Its coin cannot be
  silently absorbed.
- A phantom or misstated listed amount creates an unmatched
  receive. The sum cannot be inflated or deflated against the
  coins actually present.
- Two followers of equal amount produce one record at weight two,
  and the leader must list the amount twice.
- A hostile input at a foreign scriptPubKey cannot forge a
  follower record, because the sender half is filled from its real
  prevout data, and cannot intercept the followers as a fake
  leader, because its receive records carry its own scriptPubKey
  in the receiver half while the followers addressed the vault's.
- A negative or non-minimal listed amount dies at condition
  parsing, before the ledger runs.
- Two independently balanced consolidations at the same
  scriptPubKey compose in one transaction.

The leader path rejects an empty follower list, so every
consolidation merges at least two coins. No keyless path splits
coins, a revault needs the trigger signature, so any conflicting
consolidation an adversary substitutes still strictly reduces the
number of coins at the vault's scriptPubKey. Consolidation
progress is monotone. What remains to an adversary is
value-preserving griefing, spending their own fees to delay a
pending merge or to choose which coins merge, the same griefing
posture as keyless recovery, and a vault that objects chooses the
keyed recovery posture and accepts the key management.

The theft cases above are pinned in
`vectors/validation/vault-consolidation.json`, one vector per
attack shape.

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
c5c5c72807c36371c15fc58c34d2a5181db8856bd5045dc44d91ba0e6db4be63
$ bitlisp-compile -T puzzles/vault/triggered.bl -I puzzles/lib -I puzzles/vault
250cdfb910709b360f5ebb37102a2fe42fb42287edc66eff7dffe7f5a183f6cc
```

An instance's merkle root is the curried tree hash, printable
without running anything:

```
$ bitlisp-compile puzzles/vault/vault.bl -I puzzles/lib -I puzzles/vault \
  | bitlisp-curry -a 0x<vault mod hash> -a 0x<trig mod hash> \
      -a 0x<auth key> -a 0x<internal key> -a 0x<recovery spk> \
      -a 0x -a 144 -T
```

The compiled representatives, one per spend path with the
in-program guard failures, are pinned in
`vectors/vm/vault-programs.json`, and the condition-level lifecycle
in `vectors/validation/vault-core.json`. The test suite recompiles
both programs and byte-compares them against the pinned vectors,
so source and corpus move together or not at all.
