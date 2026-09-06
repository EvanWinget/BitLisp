# Commitment record

The rationale, reference provenance, and decision record for the
commitment scheme (`spec/SPEC.md`): the leaf version, what a leaf
commits to, the witness structure, and the validation pipeline. The
spec states behavior only. This record says why, what the evidence
was, and what the scheme leaves to Phase 4. It is the counterpart of
the VM record (`docs/vm-record.md`) and the condition record
(`docs/condition-record.md`) for the layer that joins the VM and the
validator to base consensus.

## 1. Reference provenance

- **BIP341.** The leaf version derivation, the annex rule, the
  control block, the TapLeaf and TapBranch folds, and the tweak
  check are BIP341's, restated in the spec so a reader predicts a
  vector without leaving the tree. The leaf version pool is BIP341's
  footnote on leaf versions, read 2026-09-06: a leaf version is
  even, never `0x50`, and the values recommended for use are the
  even bytes from `0xc0` to `0xfe` plus `0x66`, `0x7e`, `0x80`,
  `0x84`, `0x96`, `0x98`, `0xba`, `0xbc`, and `0xbe`, chosen so that
  neither the version nor the version with its parity bit set is a
  valid first opcode of a P2WPKH pubkey or a P2WSH script.
- **BIP341 wallet test vectors**, vendored under
  `vectors/upstream/bip341/`. Their script-tree cases carry leaf
  hashes and merkle roots for leaf versions 192 and 250, an
  independent oracle for the tagged leaf and branch construction
  under a leaf version other than tapscript's.
- **Known leaf version claims**, checked 2026-09-06: tapscript is
  `0xc0` (BIP342). Elements assigns `0xc4` to its tapscript and
  `0xbe` to Simplicity (`src/script/interpreter.h` at the master
  branch). The introspection Lisp's author floated `0xc2` for bll in
  the public threads. No registry exists.
- **Chia puzzle hashes.** A Chia coin commits to its puzzle by tree
  hash, and a puzzle recomputes its own and its successors' puzzle
  hashes in-program from curried values, the pattern
  `puzzles/lib/curry-hash.blib` reproduces. CHIP-0049 moves Chia's
  last serialization-bound identity, the block generator's, to the
  tree hash as well.

## 2. Measurements

Program bytes as compiled on 2026-09-06 from the sources in
`puzzles/`, the evidence the design decisions below cite. Witness
bytes weigh one unit each, four to a vbyte.

| artifact | bytes |
| --- | --- |
| vault, curried instance | 2,562 |
| vault, uncurried | 2,346 |
| vault with a single path kept, trigger | 1,508 |
| vault with a single path kept, recovery | 1,190 |
| vault with a single path kept, follower | 1,066 |
| vault with a single path kept, leader | 1,342 |
| `curry-hash.blib` alone, seven values | 499 |
| follower path, root supplied in the solution and asserted, guards kept | 440 |
| follower path, no guards, no reconstruction | 121 |

Two facts fall out. Splitting the vault into per-path leaves alone
roughly halves the reveal, because every path that reconstructs its
own root carries the 499-byte library beside the domain guards and
the seven curried values. Supplying a program's own root in the
solution and asserting it removes the library from every path that
does not build a successor, which for the vault is every path but
the trigger.

## 3. Design decision record

1. **The leaf version byte.** RATIFIED (decision by Evan,
   2026-09-06): `0xd0`, PROVISIONAL until deployment. The unit plan
   proposed `0xc2`, the lowest compliant value above tapscript, and
   Evan asked whether Liquid or bll had taken it. They had, in
   effect: `0xc2` is the byte floated for bll and `0xc4` is
   Elements' tapscript, so the run above `0xc0` is spoken for and a
   sequential pick invites collision with whichever of them deploys
   first. `0xd0` is in BIP341's recommended pool, clear of every
   known claim, and visibly distant from the run. The byte is the
   one constant in the scheme that a signet or Inquisition
   deployment can reassign without touching anything else, which is
   why it carries the PROVISIONAL marker and nothing else in the
   spec depends on its value.

2. **The leaf commits to the tree hash.** RATIFIED (decision by
   Evan, 2026-09-06, via the approved unit plan). The leaf script is
   the program's 32-byte tree hash and the serialized program is a
   witness element the validator checks against it. The
   alternative, the serialized program as the leaf script, saves 32
   witness bytes and one tree hash per spend and was declined
   because it breaks covenant recursion: the vault's trigger path
   must compute the triggered coin's root, which under a
   bytes-committed leaf is a tagged hash over the successor's
   serialization, and no VM operator serializes a node. Under a
   tree-hash commitment the successor's identity is
   `curried-tree-hash` over values the program holds, then two
   tagged hashes with `sha256`. This is the Chia identity model,
   corroborated by CHIP-0049 spending a hard fork to remove the one
   serialization-bound identity Chia had left. D5's one-spelling
   rule stays the wire rule: the tree hash is over the node, and
   the node has one serialization.

3. **Domain separation is stated and pinned.** RATIFIED (decision
   by Evan, 2026-09-06, via the approved unit plan). Objection O17
   asked that a hash tree living beside taproot commitments hash
   distinctly from the TapLeaf and TapBranch tags. Spec section 2.4
   states the disjointness as a first-byte fact over every digest
   kind consensus computes, a tree hash's preimage beginning with
   `0x01` or `0x02` and a tagged hash's with the tag digest's first
   byte, none of which is `0x01` or `0x02`. The table is exhaustive
   over the tags in use and gains a row with any new tag, the
   check that keeps the argument true. The vector pinning it lands
   with the reference witness layer.

4. **The witness is exactly four elements and no annex.** RATIFIED
   (decision by Evan, 2026-09-06, via the approved unit plan).
   Solution, program, leaf script, control block, in BIP341's order.
   A fifth element or a missing one is `bad_witness`. The annex is
   rejected rather than ignored: the signature asserts sign
   program-composed messages that never commit to the annex, so an
   ignored annex would be a third-party malleability surface, a
   relay peer able to attach one to a signed input and change its
   wtxid. Rejecting is a tightening under a soft fork and continues
   C16's decline of the annex as a carrier. Reintroduction trigger,
   as in C16: a ratified upstream annex format plus relay policy,
   at which point a committed annex could be admitted.

5. **Surplus solution data is tolerated, at the element boundary
   it is not.** RATIFIED (decision by Evan, 2026-09-06, via the
   approved unit plan), closing entry 9 of the VM record and
   objection O14. Both sides as recorded there: the deviation would
   reject solution bytes evaluation never touched, closing a
   wtxid-malleability vector authors cannot reliably close alone,
   at the cost of defining "touched", which entangles the
   evaluation-order question of entry 8. The default keeps CLVM's
   tolerance. Bitcoin's own precedent decided it: tapscript is
   strict at the element boundary, a spend failing unless exactly
   one element remains, and tolerant inside an element, a script
   free to push and drop data no check reads. The scheme mirrors
   that split exactly. The element count is strict, and inside the
   solution element the program decides. Standard-layer templates
   check the shape of the solution they consume.

6. **The budget derives from witness weight.** RATIFIED (decision
   by Evan, 2026-09-06, via the approved unit plan). Objection O21
   holds both sides: a declared budget makes cost knowable before
   deserialization and reads as an explicit fee commitment, a
   derived budget adds no witness element and no contested
   namespace. Derived was taken: the per-input budget is a function
   of the input's own witness weight, fixed in COSTS.md section 9
   at Phase 4, and no other input's witness moves it, which keeps
   the per-input independence the condition layer's composition
   guarantee relies on. Deserialization and the leaf check are
   uncharged because the weight mapping already prices every
   witness byte and both are linear in those bytes.

7. **Per-path leaves are BIP341's, not the scheme's.** RATIFIED
   (decision by Evan, 2026-09-06, via the approved unit plan). Once
   a leaf commits to one program, a puzzle with several spend paths
   is several curried programs in several leaves of one tree, and a
   spend reveals the executed path plus 32 bytes of control block
   per tree level. The scheme adds no mechanism: spec section 2.3
   states that a tree holds any number of BitLisp leaves beside
   leaves of other versions, and the puzzle discipline follows. The
   measured saving on the vault is 840 to 1,280 bytes per spend
   before the discipline in decision 8 is applied.

8. **Self-identity is guess-and-assert, successors are
   reconstructed.** RATIFIED (decision by Evan, 2026-09-06, via the
   approved unit plan) as the standard-layer rule, applied to the
   vault at unit 9 with the bytes reported. A program that names its
   own root takes it from the solution and asserts it with
   `ASSERT_MY_TAPTREE`, which proves the coin's actual root equals
   the supplied one at 32 solution bytes and no library code. A
   program that builds another program's root, the trigger building
   the triggered coin's, reconstructs it from curried values, the
   only place `curry-hash.blib` and the tagged leaf and branch
   hashing are needed. A leaf that never reconstructs anything can
   have its leaf hash curried into its siblings as a constant: the
   triggered coin's recovery leaf does not depend on the target, so
   the vault's trigger can carry that leaf hash as a value and
   reconstruct only the withdrawal leaf. The other side, kept for
   the singleton: reconstruction proves the tree is exactly this
   program under the nothing-up-my-sleeve key and nothing else,
   which an owner-funded coin does not need (the wallet checks the
   curry before funding, the posture `docs/puzzles/vault.md` already
   records) but a coin third parties rely on may. The singleton's
   posture is re-decided at its re-pin.

9. **Shared library code is revealed per spend.** RATIFIED
   (decision by Evan, 2026-09-06, via the approved unit plan). The
   only way v0 consensus could commit library code once is a
   validator-known library, the standard-layer shorthand
   experiment already parked in Phase 4, and decision 8 removes
   most of the need. The tagged leaf and branch hashing a successor
   builder needs is a small library file beside `curry-hash.blib`,
   its tag digests compile-time constants as the curry library's
   are. That file is a new library surface under the language
   freeze, admitted as the scheme's own consequence and recorded
   with this unit in the execution plan.

10. **The singleton's constant scriptPubKey stands.** RATIFIED
    (decision by Evan, 2026-09-06, via the approved unit plan). The
    plan asked the scheme to answer the singleton's workaround
    first. It cannot: the obstacle is the tweak, not the leaf.
    State placed in any leaf moves the root and the scriptPubKey
    with it, and no operator recognizes a parent's tweaked key, so
    the parent's scriptPubKey stays unrecognizable however the
    leaves are arranged. The workaround stands, the singleton
    changes only in how its leaf hashes, and the revisit of the
    tweak operator (condition-record decision 3) stays at the
    Phase 4 gate.

11. **The whole architecture document is written, not two
    sections.** RATIFIED (decision by Evan, 2026-09-06, via the
    approved unit plan). The unit's charter named sections 2 and 3.
    Sections 1 and 4 were written with them because section 4 is
    the enumeration of failure modes over stages already stated in
    VALIDATION.md plus the two the scheme adds, `bad_witness` and
    `leaf_mismatch`, and a stub status line in a normative document
    is the placeholder the quality mandate forbids.

## 4. Carried to Phase 4

- The weight mapping (COSTS.md section 9): the budget function and
  the per-byte witness charge. Nothing about fees or the gate can be
  said before it exists.
- The standard-layer shorthand experiment: whether a validator-known
  library is worth its consensus surface, measured after the
  benchmark puzzles are re-pinned under decision 8.
- The tweak operator revisit, condition-record decision 3, at the
  asset token study.
- Relay policy for the leaf version: today's policy discourages
  unknown leaf versions, a deployment question for Phase 6.
- The commitment-hash utility: a command printing a leaf hash, a
  merkle root, and a scriptPubKey from program sources, lands with
  the reference witness layer now that the scheme fixes its output.
