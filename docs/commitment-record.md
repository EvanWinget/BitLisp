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
  byte that can begin a valid P2WPKH pubkey or a valid P2WSH
  script, which lets a script-path spend be recognized without the
  spent output.
- **BIP342.** The sigops budget, 50 plus the serialized size of
  the input's witness in bytes with its compact-size prefix,
  decremented by 50 per signature check, the precedent for a
  per-input budget derived from the input's own witness. Also the
  initial-stack bounds tapscript keeps, 520 bytes per element and
  1,000 elements, which the scheme does not.
- **BIP341 wallet test vectors**, vendored under
  `vectors/upstream/bip341/`. Their script-tree cases carry leaf
  hashes and merkle roots for leaf versions 192 and 250, an
  independent oracle for the tagged leaf and branch construction
  under a leaf version other than tapscript's.
- **Known leaf version claims**, checked 2026-09-06: tapscript is
  `0xc0` (BIP342). Elements assigns `0xc4` to its tapscript and
  `0xbe` to Simplicity (`src/script/interpreter.h` at commit
  `c7e856fab1b0c4d37005e25c0940184d812a26a0`). The project's
  synthesis of the 2022 to 2024 public threads (git-ignored
  `references/discussions/`) records the introspection Lisp's
  author floating `0xc2` for bll, the message itself not pinned:
  neither delving 636 nor delving 682 names a byte, and the
  vendored bllsh test framework uses tapscript's `0xc0`. No
  registry exists.
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
   effect: `0xc2` is the byte the thread synthesis records as
   floated for bll and `0xc4` is Elements' tapscript, so the run
   above `0xc0` is spoken for and a
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
   alternative, the serialized program as the leaf script, saves 33
   witness bytes, the leaf script element and its length prefix,
   and one tree hash per spend, and was declined because it prices
   covenant recursion out: the vault's trigger path must compute
   the triggered coin's root, which under a bytes-committed leaf is
   a tagged hash over the successor's serialization. No VM operator
   serializes a node, and a program serializing its successor
   in-language would carry the serializer's code and pay its cost
   on every spend. Under a tree-hash commitment the successor's
   identity is `curried-tree-hash` over values the program holds,
   then two tagged hashes with `sha256`. This is the Chia identity model,
   corroborated by CHIP-0049 spending a hard fork to remove the one
   serialization-bound identity Chia had left. D5's one-spelling
   rule stays the wire rule: the tree hash is over the node, and
   the node has one serialization.

3. **Domain separation is stated and pinned.** RATIFIED (decision
   by Evan, 2026-09-06, via the approved unit plan). Objection O17
   asked that a hash tree living beside taproot commitments hash
   distinctly from the TapLeaf and TapBranch tags. Spec section 2.4
   answers twice. Structurally, a tree hash never enters the script
   tree as a node: it is the leaf script, wrapped under TapLeaf
   with the leaf version, so no tree hash is ever a merkle node.
   Then by preimage, over every tag a BitLisp validator hashes
   under, BIP340's challenge tag included: a tree hash's preimage
   begins with `0x01` or `0x02` and a tagged hash's with the tag
   digest's first byte, none of which is `0x01` or `0x02`. The
   table is exhaustive over those tags and gains a row with any new
   one, the check that keeps the argument true. TapSighash is base
   consensus's key-path digest, computed by no BitLisp rule, and
   its first byte is `0xf4` regardless. The table is pinned by a
   test rather than the vector this entry first promised (decision
   by Evan, 2026-09-06, steelmanned both ways): the table fits no
   suite's case shape, and a test can state the argument as well as
   the values, recomputing every row from the tag strings and
   checking that the rows are exactly the tags in use, every tagged
   digest passing through one function. Writing that test found the
   challenge row wrong:
   the table had named the tag `BIP340/challenge` with first byte
   `0x07`, and BIP340 spells it `BIP0340/challenge`, first byte
   `0x7b`. Corrected the same day, the argument unchanged.

4. **The witness is four elements, and an annex only under a self
   assert.** RATIFIED (decision by Evan, 2026-09-06, revising the
   approved unit plan at the PR's review). Solution, program, leaf
   script, control block, in BIP341's order. A fifth element or a
   missing one is `bad_witness`. The unit plan rejected the annex
   outright, on an asymmetry with the solution: a program can read
   any solution byte and so commit to it, while no operator reads
   the annex, so nothing could commit to one and an ignored annex
   would be bytes any relay peer could attach to a signed input to
   change its wtxid. Review priced what rejection costs: a soft
   fork only tightens, so a later annex use for BitLisp inputs
   would need a new leaf version, where tapscript's
   commit-and-reserve idiom keeps it under one. Binding an annex
   hash into the signature digests, tapscript's shape, was weighed
   and declined because it protects signed spends only, and this
   vocabulary is built for keyless paths. The annex is instead
   admitted exactly when the condition list carries
   `ASSERT_MY_ANNEX` over its BIP341 `sha_annex` digest, the
   condition-record's decision 30 and divergence C25: keyless
   paths are protected by default, a program that wants an annex
   commits to it, and the door stays open under this leaf version.
   Tapscript also bounds each initial stack element at 520 bytes
   and the stack at 1,000 elements. The scheme keeps neither as
   such: a program element cannot fit in 520 bytes, the element
   count is fixed at four, and decision 12 sets the bound the
   scheme does keep.

5. **Surplus solution data is tolerated, at the element boundary
   it is not.** RATIFIED (decision by Evan, 2026-09-06, via the
   approved unit plan), closing entry 9 of the VM record and
   objection O14. Both sides as recorded there: the deviation would
   reject solution bytes evaluation never touched, closing a
   wtxid-malleability vector authors cannot reliably close alone,
   at the cost of defining "touched", which entangles the
   evaluation-order question of entry 8. The default keeps CLVM's
   tolerance. Bitcoin's own precedent decided the boundary:
   tapscript fails a spend unless exactly one element remains, so
   a third party can add no element, and a witness element the
   script drops unread is tolerated because the author wrote the
   drop. The scheme matches that boundary exactly, the element
   count strict. Inside the element the defaults differ and this
   record says so: tapscript is strict unless a script opts out
   with a drop, while CLVM's destructuring ignores a solution tail
   unless a program opts in with a shape check. The standard-layer
   obligation is that opt-in: templates check the shape of the
   solution they consume, and the vault does at its re-pin.
   Addendum (decision by Evan, 2026-09-06, at the PR's review):
   the compiler emits that shape check by default for every
   `program` form's parameter list, so strictness becomes the
   default for every compiled program at a few bytes each with no
   new consensus surface. A compiler behavior change, not a
   language surface, landing with unit 9. A seal does not close
   this: seals commit to the transaction's outputs, non-witness
   data, and read no witness byte.

6. **The budget derives from witness weight.** RATIFIED (decision
   by Evan, 2026-09-06, via the approved unit plan). Objection O21
   holds both sides: a declared budget makes cost knowable before
   deserialization and reads as an explicit fee commitment, a
   derived budget adds no witness element and no contested
   namespace. Derived was taken: the per-input budget is a function
   of the input's own witness weight, fixed in COSTS.md section 9
   at Phase 4, and no other input's witness moves it, which keeps
   the per-input independence the condition layer's composition
   guarantee relies on. BIP342's sigops budget is the precedent,
   50 plus the input's serialized witness size in bytes, so the
   shape has deployed history under taproot itself. Section 9
   decides the two parameters that precedent settles for tapscript,
   whether length prefixes count and whether a constant offset
   applies. Deserialization and the leaf check are uncharged
   because the weight mapping already prices every witness byte
   and both are linear in those bytes.

7. **Per-path leaves are BIP341's, not the scheme's.** RATIFIED
   (decision by Evan, 2026-09-06, via the approved unit plan). Once
   a leaf commits to one program, a puzzle with several spend paths
   is several curried programs in several leaves of one tree, and a
   spend reveals the executed path plus 32 bytes of control block
   per tree level. The scheme adds no mechanism: spec section 2.3
   states that a tree holds any number of BitLisp leaves beside
   leaves of other versions, and the puzzle discipline follows. The
   measured saving on the vault is 840 to 1,280 bytes per spend
   before the discipline in decision 8 is applied. The alternative
   a Chia reader raises is program-level Merkleization: one leaf
   committing to a root over sub-programs, the executed
   sub-program and its path proof arriving in the solution. It
   saves the same bytes and keeps one tree hash as the puzzle's
   identity. Declined: the taproot path costs the same 32 bytes
   per level and base consensus verifies it at no VM cost, where
   an in-program proof carries a verifier in every leaf and pays a
   `sha256` per level, and `ASSERT_MY_TAPTREE` already binds the
   whole tree at one condition. A puzzle that needs one identity
   for its tree has it: the merkle root.

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

12. **Every spender-chosen element is bounded at 10,000 bytes.**
    RATIFIED (decision by Evan, 2026-09-06, at the PR's review,
    revising the approved unit plan). The solution, the program,
    and the annex are each at most `MAX_WITNESS_ELEMENT_SIZE =
    10,000` bytes. The plan set no bound, on the argument that the
    derived budget and the block weight limit price every byte
    and deserialization is linear. Review asked for a limit as
    the deserialization-side counterpart of tapscript's 520-byte
    element bound, a constant a reviewer can check rather than an
    argument. The number is Bitcoin's own legacy script cap,
    already reused by the condition layer as the scriptPubKey
    operand bound, so the scheme adds no new magnitude. It binds
    the singleton: its solution carries two full transaction
    serializations, so a lineage whose parent or grandparent
    transaction is large cannot be proven, a limit the owner
    controls and the singleton doc records. Both node elements
    and the annex share the bound so the rule is one sentence. The
    leaf script's width and the control block's length were
    already fixed.

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

## 5. The reference witness layer

Landed 2026-09-06, the PR after the scheme. `python/bitlisp/`
gained `commitment.py` (the tree hash, the tagged hashes, the
control block) and `spend.py` (the stages of spec section 4 for one
input), the vector corpus a `spend` suite, and the front end
`bitlisp-commit`, the commitment-hash utility queued 2026-08-14.
Three choices made there, none a change to the scheme:

- Base consensus's control block checks are run by the reference
  as a precondition and reported outside the error taxonomy
  (`BaseConsensusError`), never as a code a vector could pin: the
  spec says a spend failing them never reaches it, and a reference
  that read the triple unchecked would call spends valid that base
  consensus rejects. A vector whose witness fails them is
  malformed.
- The annex admission rule is one function run twice on the
  reference path, at stage 5 by the spend entry and first in
  transaction validation, because the validation vectors and the
  runner assemble transaction views without the spend entry and
  the view's invariant must hold for them too. It lives with the
  per-input stages, and transaction validation imports it, so the
  dependency runs from the later stage to the earlier one.
- The witness form of `bitlisp-run` and the REPL is deferred to
  unit 9's first PR, where the vault is the first consumer.

Writing the vectors found spec section 3.3 wrong about the nil
program (its empty condition list is valid under CONDITIONS.md and
the corpus, so the nil leaf is spendable by anyone) and the digest
table wrong about the challenge tag (decision 3). Both corrected
in their own spec commits.
