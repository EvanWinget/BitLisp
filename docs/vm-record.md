# BitLisp VM record

The evidence and rationale record behind [spec/VM.md](../spec/VM.md):
the divergence table, the oracle provenance, and the design decision
record. The spec states behavior and is complete enough on its own to
predict every vector's outcome. This record states why each behavior
was chosen, where the oracle evidence comes from, and which decisions
are ratified or still open. Nothing in this file is needed to
evaluate a program.

## 1. Divergence from CLVM

Every entry names the divergence, the rationale, and the vectors that
pin it. No divergence exists outside this table. "Both oracles" means
`chia-rs` flags 0 (consensus) and the `clvm` Python package. The
divergence labels D1 to D9 are stable and are cited from the spec,
the vectors, and the diff harness.

| # | Area | CLVM behavior | BitLisp behavior | Rationale | Vectors |
| --- | --- | --- | --- | --- | --- |
| D1 | BLS operators | `point_add`, `pubkey_for_exp`, BLS extension ops present | absent, `unknown_operator` | Bitcoin has no BLS. Removing them removes their entire attack and cost surface. | `vm/dispatch.json`, upstream corpus D1 bucket |
| D2 | Signature verification | `secp256k1_verify` (0x13d61f00) and `secp256r1_verify` (0x1c3a8f00) post-hardfork ops: ECDSA verifies that raise on any failure, message digest exactly 32 bytes, SEC1 compressed and uncompressed pubkeys both accepted, high-s signatures rejected (probed 2026-07-28) | `secp_verify` (0x0f), BIP340 Schnorr over secp256k1, tri-state result, both ECDSA ops absent (`unknown_operator`) | Native taproot scheme: batchable at the condition layer, non-malleable signature encoding, one curve and one scheme in the consensus core. Ratified curation, see section 3. | `vm/secp.json` |
| D3 | Unknown operators, outside the reserved families of VM.md section 3.2 | Both oracles accept unknown opcodes, cost derived from the opcode bytes, result nil. Reserved atoms are rejected by both oracles and by BitLisp alike, so they sit outside this divergence. The consensus oracle also gives real semantics to opcodes BitLisp classes as unknown: `softfork` (an assert-only guard whose declared cost must match), `coinid`, `modpow`, `%`, the D1 BLS set, and two four-byte secp verify opcodes, none of which follow the cost-from-opcode-bytes rule | `unknown_operator` error | The operator set is closed by design. Bitcoin soft-forks at the tapleaf-version level, not through unknown-opcode acceptance. Ratified, see section 3. | `vm/dispatch.json`, upstream corpus D3 bucket |
| D4 | Pair in operator position | Both oracles accept `((X) . args)` when `X` is a lone atom, a legacy apply-style rule: `X` dispatches on the arguments unevaluated, charging apply's 90. Both reject a proper-list tail in the operator pair, and they disagree only on an improper dotted atom tail: `chia-rs` ignores the dotted tail and dispatches on the head, `clvm` rejects it | `operator_not_atom` error for every pair in operator position | The construct adds no expressive power and its one disputed edge is silently ignored program bytes, a malleability surface. Strict rejection of the whole family is the smaller, reviewable surface. Ratified, see section 3. | `vm/dispatch.json`, upstream corpus D4 bucket |
| D5 | Deserialization strictness | Both oracles accept non-minimal length encodings (the `0xfc` six-byte length prefix included, which is non-minimal for every size it can represent), trailing bytes, and (chia-rs) `0xfe` back-references | `bad_encoding` for all three (VM.md section 2) | Witness bytes must have exactly one accepted spelling per program. Malleability of the serialized form is a consensus hazard in the Bitcoin context. | `vm/serialize.json` |
| D6 | `/` with negative operands | Consensus (`chia-rs`): floor division. The `clvm` package injects a policy error ("deprecated") that is not consensus | Floor division, matching consensus | Intersection parity targets the consensus oracle. The Python package's rejection is library policy, the diff harness treats it as an expected divergence. Ratified, see section 3. | `vm/arith.json`, upstream corpus D6 bucket |
| D7 | Zero cost budget | Both oracles treat `max_cost = 0` as unlimited | A zero budget is a real budget, no program succeeds under it (VM.md section 3.3) | A zero sentinel meaning unlimited is a library convenience, not consensus behavior. In the Bitcoin context the budget derives from transaction weight and is never legitimately zero, and an accidental zero must fail closed rather than open. Ratified, see section 3. | `vm/dispatch.json` |
| D8 | Resource limits outside the cost model | The consensus oracle enforces caps the cost model never sees: at most 62,500,000 atoms and as many pairs per run (deserialization spends one count per atom and two per cons, probed at the boundary: a 62.7 million node budget fails "too many pairs" before evaluation, 62.4 million deserializes), a 4 GiB atom-byte heap, 20,000,000-entry value and environment stacks, and a two-argument `substr` whose default end index passes through a signed 32-bit cast, rejecting data atoms of 2^31 bytes or more | No equivalent limits: BitLisp is bounded by the cost budget, and its deserializer by the input's size alone | Every cap sits far outside the reachable regime. The cheapest evaluation-time trigger costs about 5.6e10 against the harness budget of 1.1e10, and the deserialization trigger needs roughly 42 MB of input against Bitcoin's 4 MB witness ceiling. PROVISIONAL, see section 3: the Phase 4 budget and input-size bounds must be recorded against these thresholds, or the caps mirrored fail-closed. | none, unreachable (section 3) |
| D9 | `sha256tree` | Deployed consensus (flags 0) treats opcode `0x3f` as an unknown operator under the D3 acceptance rule: arguments evaluate, cost derives from the opcode byte, result nil. The pinned oracle wheel carries a `sha256tree` operator at the same opcode behind its release flag, scheduled for consensus activation in Chia's next hard fork (CHIP-0049, in review) | `sha256tree` is a table operator with the wheel's semantics, cost constants, and opcode | Covenant recursion computes program commitments in-program, the pattern behind upstream's own promotion of the operator. Adopting the upstream opcode, semantics, and constants keeps the operator inside the diffable intersection once upstream activates. Decision by Evan, ratified, see section 3. | `vm/sha256tree.json` (BitLisp column), the oracle column pinned per run by the flags-0 leg of `tools/diff_sha256tree.py` |

## 2. Oracle provenance

Oracles are released artifacts: the wheels pinned as dev dependencies
in `pyproject.toml` (extra `oracles`), and vendored snapshots from
tagged upstream releases where no usable wheel exists. Pin bumps and
snapshot refreshes follow the adopt/take/decline triage in
`docs/execution-plan.md`.

| Oracle | Version | Pinned | Upstream commit | Notes |
| --- | --- | --- | --- | --- |
| `clvm` (PyPI) | 0.9.15 | 2026-07-26 | 00c47c9b | Python oracle. Carries non-consensus library policy (see D6), lacks the consensus operand size limits (VM.md section 4), checks the cost budget only after an operator completes, and checks apply's cost immediately where consensus defers the check to the applied program's first charge (VM.md section 3.2). The diff harness tolerates all four, each tagged in its output. |
| `chia-rs` (PyPI) | 0.46.0 | 2026-07-26 | 7d487907 | Consensus oracle, run with flags 0 |
| Chia CLVM command tests (Chia-Network/clvm) | 0.9.15 | 2026-07-28 | 00c47c9b | Official CLVM tests for the operator intersection, vendored as data in `vectors/upstream/clvm/` with a provenance file, executed by `tools/run_upstream.py` |
| BIP 340 vectors (bitcoin/bips) | 2023-04-20 revision | 2026-07-28 | 200f9b26 | Official test vectors for `secp_verify`, vendored as data in `vectors/upstream/bip340/` with a provenance file |
| Bitcoin Core test framework | v31.1 | 2026-07-28 | 9be056a8 | `secp_verify` differential oracle and signer, vendored verbatim in `tools/oracle/bitcoincore/` with a provenance README. The implementation Core cross-checks its consensus code with, validated against libsecp256k1 in Core's CI |

The intersection is additionally pinned by Chia's official CLVM
command tests, vendored at the release tag matching the pinned `clvm`
wheel. The runner re-derives every expectation semantically rather
than comparing tool output, and sorts every case BitLisp
intentionally rejects into a divergence bucket that asserts the exact
BitLisp outcome under its table row (D1, D3, D4, D6). The consensus
oracle must reproduce every success expectation, the divergence
buckets included, where it is the only implementation that can
confirm the file: the single exception is the `py_limits` case below,
which no limit-enforcing implementation reproduces. One case, the
`power-1` exponentiation, records the corpus's own provenance limit:
its expectation came from the Python `clvm` package, which lacks the
consensus operand size limits, and bitlisp and the consensus oracle
both reject its over-cap product where the file expects success. Six
cases pin the upstream text reader rather than the VM and are only
required to fail. Any case fitting no bucket fails the run.

Divergent operators are tested against their own oracles.
`secp_verify` runs the official BIP 340 vectors byte-for-byte in the
unit suite and `vectors/vm/secp.json`, and `tools/diff_secp.py`
diffs it against the Bitcoin Core implementation on
signer-generated triples and a mutation battery. The originally
planned `coincurve` wheel is not used: no released build supports
the pinned Python, and the vendored oracle additionally provides
the signer a differential needs. When a system libsecp256k1 with
the schnorrsig module is present, `tools/diff_secp.py` adds the C
library Bitcoin Core links as a third verifier: it re-runs the
official vectors and votes on every generated triple. The leg is
opportunistic on developer machines, required in CI, and the
pinned oracles never depend on it.

`sha256tree` is tested against the pinned consensus wheel itself.
The released artifact carries the operator behind its
`ENABLE_SHA256_TREE` flag and separately exports the `tree_hash`
puzzle-hash utility, the algorithm Chia consensus has applied to
puzzle commitments since genesis. `tools/diff_sha256tree.py` runs
four legs per corpus: the operator's (result, cost) against the
flag-enabled wheel at the exact budget boundary, the result against
the utility, the result against an in-language tree-hash program
built from intersection operators and run through both pinned
oracles at flags 0, and the D9 oracle column itself, every generated
program run through both oracles at flags 0, which must accept the
opcode as unknown and return nil. The first two legs are two views
of the one pinned wheel and only the first checks cost, so the cost
constants rest on the flag-enabled wheel alone. The other two legs
cross both oracles. No deployed VM dispatches the opcode yet, and
every leg is released-binary evidence.

## 3. Design decision record

Decisions taken during Phase 1, each ratified or explicitly left
open. Overturning a ratified decision is a spec amendment plus
vector update in one reviewed commit. Items marked open name the
phase that owes the answer.

1. **D3 (unknown operators).** RATIFIED (decision by Evan,
   2026-07-29): strict rejection stands and the operator set is
   closed. BitLisp's upgrade path is new tapleaf versions for coins
   created after a fork and reserved conditions for coins already
   deployed. A CLVM-style `softfork` guard is declined for v0. The
   alternative was analyzed twice (discussions with Evan, 2026-07-26
   and 2026-07-29, the second with oracle probes) and the record
   below replaces the earlier provisional entry, correcting one of
   its claims.

   - CLVM's unknown-opcode acceptance is not an upgrade path for
     value-returning operators. An unknown operator evaluates its
     arguments, charges a cost decoded from the opcode bytes, and
     returns nil into the continuing program. Assigning it real
     semantics later would change what deployed programs compute,
     not merely what is valid, which is not a soft fork. Chia's
     documentation states this directly, and Chia shipped its new
     operators first inside the `softfork` guard, then promoted
     them to first-class value-returning operators with a hard
     fork.
   - CLVM's `softfork` guard is sound and is assert-only by
     construction: the declared cost must equal the guarded
     program's actual cost, and the guarded result is always nil,
     so no value crosses the boundary. New operators arrive as
     verifiers, never as producers. Value-producing behavior can be
     simulated by commit-and-verify: the spender supplies the
     claimed result as witness data, the guard recomputes it and
     raises on mismatch, and the outer program uses the supplied
     value. Old nodes use it unverified, new nodes enforce it,
     which is the stricter-only direction a soft fork requires.
     This covers most verify-shaped features at a cost in witness
     bytes and program shape.
   - Probed 2026-07-29 against the consensus oracle at flags 0:
     `softfork` (0x24) with an unrecognized extension id charges
     the declared cost plus argument evaluation and returns nil
     without ever touching the guarded program (garbage bytes and
     a quoted raise both pass identically). A declared cost of
     zero or beyond the budget fails as `cost_exceeded`, a
     negative one fails the positive-int argument check, and the
     two extensions live in consensus enforce exact declared-cost
     equality. A v0 guard would therefore be small and
     oracle-verifiable. This corrects the earlier entry here,
     which claimed the guard's containment machinery must be
     perfect from v0: that machinery ships with the first live
     extension, a consensus event under any upgrade mechanism.
   - The guard is declined on redundancy, not on risk or size.
     Upgrades split into two jobs. Coins created after a fork can
     commit to anything, so a new tapleaf version serves them
     completely, value-returning operators included. Chia built
     the guard for exactly this job because its bare puzzle-hash
     commitments carry no version byte, leaving no other
     soft-fork route to new VM semantics, while Bitcoin provides
     the boundary natively. Coins already deployed are frozen at
     their leaf version, and anything a soft fork can deliver to
     them is verify-shaped by construction, since old nodes must
     be able to skip it. The guard and reserved conditions
     deliver exactly that, at the same granularity (old nodes
     keep enforcing everything outside the unchecked region), so
     shipping both would pay for two mechanisms doing one job.
   - Reserved conditions are the designated mechanism for the
     deployed-coin job. Conditions are inert data in a program's
     output, so a fork can assign meaning to a reserved condition
     code without changing what any program computes, and
     enforcement only ever tightens, the stricter-only direction
     a soft fork requires. This is the OP_NOP path that shipped
     CLTV and CSV, and the path Chia itself uses to extend its
     condition vocabulary. It also follows this architecture's
     grain: verification already lives at the condition layer
     (the AGG_SIG family), and the rule for unknown condition
     codes has to be written in MATCHING.md either way, so the
     reserved answer adds no new mechanism. That rule is
     load-bearing for extensibility and is designed as such in
     Phase 2. A guard remains addable in a later leaf version if
     in-VM verification over program-internal values ever proves
     necessary, while a shipped guard could never be removed.
2. **D2 (crypto family curation).** RATIFIED (decisions by Evan,
   2026-07-28). The crypto family is `sha256` plus `secp_verify`,
   nothing else, and `secp_verify` is BIP340 only. The family
   enumeration was amended by entry 7 below: `sha256tree` joined on
   2026-07-29, and the rest of this entry stands.

   - **ECDSA declined.** The consensus oracle's `secp256k1_verify`
     and `secp256r1_verify` were probed 2026-07-28: raise-style
     ECDSA verifies, digest exactly 32 bytes, SEC1 compressed and
     uncompressed pubkeys both accepted, high-s signatures
     rejected, flat cost (1300061 total on the k1 worked-example
     shape). Declined because ECDSA is the wrong scheme for the
     taproot context: it cannot be batch verified, and it drags a
     second signature scheme's attack surface into the consensus
     core. The r1 op adds a second curve for passkey interop that
     v0 does not target. Adopting either later is a mechanical
     intersection addition with the diff harness behind it, so the
     decline is cheap to reverse, while BIP340 would always be the
     novel work item.
   - **Tri-state semantics** follow tapscript's CHECKSIG rule and
     bllsh's `bip340_verify` precedent rather than Chia's
     raise-only secp ops: an empty signature is a graceful nil, an
     invalid non-empty signature is a hard failure.
   - **Message exactly 32 bytes** follows bllsh and the Chia digest
     rule. BIP348's CHECKSIGFROMSTACK instead passes
     arbitrary-length messages unhashed to BIP 340 verification.
     Recorded as a deliberate divergence from that design: the
     fixed width keeps the operator surface minimal and makes
     hashing explicit in programs, and `sha256` lands in the same
     family.
   - **Considered and declined:** bllsh's `secp256k1_muladd` (a
     general EC linear-combination primitive enabling in-language
     key tweaks and adaptor patterns, too much novel consensus
     surface for v0), `ripemd160` and `hash160` (legacy address
     interop only), and `keccak256`, `coinid`, `modpow`, `%`
     (Chia-specific, remaining D3 unknowns).
   - **Opcode 0x0f** is the lowest nonzero byte unassigned in both
     oracles, probed 2026-07-28 under two argument shapes (integer
     and pair arguments) to separate genuinely unknown opcodes
     from assigned operators that return nil. Below 0x40 the
     unassigned bytes are 0x0f, 0x1c, 0x1f, 0x23, 0x25 to 0x2f,
     0x3e, and 0x3f. Every byte from 0x40 through 0xff is also
     unknown to both oracles (their unknown-op cost classes differ
     in argument sensitivity, which the probe distinguishes from
     assignment).
   - **Cost 1300000 is PROVISIONAL.** There is no oracle to
     inherit from. The constant adopts the magnitude of the
     consensus oracle's ECDSA verify pending Phase 4 measurement.
     Phase 4 should also decide whether the empty-signature branch
     gets a cheaper price, by analogy with tapscript, where an
     empty signature does not count toward the sigops budget.
3. **D4 (pair operator).** RATIFIED (decision by Evan, 2026-07-29):
   strict rejection of the whole family stands. Probes (2026-07-26,
   sharpened 2026-07-29) settled the facts. The lone-atom shape
   `((X) . args)` is in both oracles with identical semantics and
   cost: `X` dispatches on its arguments unevaluated, charging
   apply's 90 in place of quote costs, so `((+) 1 2)` gives 3 at
   cost 845 on both wheels where `(+ (q . 1) (q . 2))` costs 796.
   Both oracles reject a proper-list tail in the operator pair
   and an inner pair, and the sole disagreement is an improper
   dotted atom tail, which `chia-rs` ignores and `clvm` rejects.
   Grounds for rejecting the family anyway:

   - The construct adds no expressive power. `((X) a b)` computes
     exactly what `(X (q . a) (q . b))` computes, differing only
     in cost accounting.
   - Accepting it means specifying a second dispatch mode for
     every operator, accidental corner semantics included: both
     oracles evaluate `((q) 1 2)` to nil at cost 91, a fossil of
     how the apply path routes the quote atom, and the spec would
     have to state such outcomes as normative with no design
     rationale available.
   - The dotted-tail edge stays a divergence under any acceptance
     rule, because silently ignored program bytes are witness
     malleability surface BitLisp cannot adopt.
   - Rejection is continuous with D3, D5, and D7: a closed
     grammar, one dispatch rule (the operator must be an atom),
     one accepted spelling per behavior. Nothing a deployed coin
     could want rides on the family, and the one-way door points
     the safe direction: the family could be added in a later
     leaf version, while removal after v0 would confiscate from
     any coin that used it.
4. **D6 (negative division).** Floor semantics RATIFIED (decision by
   Evan, 2026-07-26): `/` keeps consensus floor division on negative
   operands, and the alternatives (rejecting negative operands in
   consensus, or dropping `/` for `divmod` alone) are declined. The
   upstream deprecation traces to an admitted implementation bug,
   not a design position: the original Python operator carried a
   branch its own comment called "a buggy behavior from the initial
   implementation" (a quotient of exactly -1 with a nonzero
   remainder was rounded toward zero), consensus settled on clean
   floor division, and the Python library then deprecated negative
   operands in February 2023 rather than model the settled outcome.
   BitLisp matches the consensus binary, which the diff harness
   verifies on every run.
5. **D7 (zero budget).** Fail-closed RATIFIED (decision by Evan,
   2026-07-26): a zero `max_cost` rejects every program where the
   oracles treat it as unlimited. A budget bug must reject every
   spend, a recoverable liveness failure, rather than hand out
   unlimited execution, a soundness failure. Still open: whether the
   reference should also enforce the unsigned 64-bit budget bound the
   hardened implementation will have (VM.md section 3.3 currently
   records the bound without enforcing it). The bound interacts with
   serialization: a budget below 10 * 2^34 makes a result atom too
   long for the wire format unbuildable (VM.md section 2), and the
   u64 bound alone does not. The Phase 4 weight mapping should record
   its maximum grantable budget against that threshold so the
   serializer's rejection of unrepresentable results is provably
   dead in consensus.
6. **D8 (oracle resource caps).** Recorded, not mirrored (source
   audit against clvm_rs 0.18.0 with oracle probes, 2026-07-28).
   The oracle's allocator caps, interpreter stack caps, and the
   substr signed-32-bit default end are consensus behavior on the
   Chia side that no BitLisp vector can currently reach: the
   evaluation-time triggers need several times the harness budget
   and the deserialization trigger needs about ten times the witness
   ceiling. Two ways to close the row, to be decided with the Phase
   3 budget mapping. Either record the maximum grantable budget and
   the embedding's input-size bound and prove every cap unreachable,
   making the row permanently dead the way VM.md section 2 argues
   the wire cap dead, or mirror the caps fail-closed so the two
   implementations agree even in regimes no transaction can produce.
   Mirroring the deserializer's node budget is the strongest
   candidate since its trigger is input size, not cost, and the
   input-size bound belongs to the embedding rather than the spec.
7. **D9 (sha256tree adoption).** RATIFIED (decision by Evan,
   2026-07-29): `sha256tree` joins the v0 table at `0x3f` with the
   pinned wheel's semantics and cost constants.

   - In-language tree hashing (recursive `sha256` over the leaf and
     pair tags) is expressible with the v0 intersection, so the
     operator adds cost efficiency and witness compactness, not
     capability. It was adopted anyway because the demand is
     structural: covenant recursion computes a child program's
     commitment in-program, the dominant pattern in Chia's deployed
     puzzles, and upstream is promoting the same operator to
     consensus (CHIP-0049) on that evidence. Carrying the recursive
     program in every witness that needs it spends bytes exactly
     where the witness-size obligation is tightest.
   - Opcode `0x3f` matches the upstream assignment, so the operator
     joins the diffable intersection when upstream activates. The
     probe record in the D2 entry above lists `0x3f` among the bytes
     unassigned in both oracles: that statement described flags-0
     dispatch and stands, the wheel carries the operator behind a
     release flag.
   - Semantics and constants were verified against the pinned wheel
     by probe on 2026-07-29 (tree hashes, totals at the exact budget
     boundary, arity errors, flags-0 unknown acceptance) and are
     pinned continuously by `tools/diff_sha256tree.py` (section 2).
     CHIP-0049 is still in review upstream, so a constants change
     before activation is possible: that lands as an ordinary
     pin-bump triage, adopt or keep, one reviewed commit, and Phase 4
     re-measures every inherited constant regardless.
   - The algorithm is Chia's puzzle-hash tree hash unchanged. A
     tagged-hash variant with a protocol-specific prefix was
     considered and declined: it would forfeit the released-binary
     oracle and the future intersection to buy cross-protocol domain
     separation the commitment context already provides. Recorded
     consequence: a BitLisp node and a Chia node with equal trees
     share a tree hash.
   - The per-node charge rule exists to close a work-amplification
     hazard, not only to price the hashing. Evaluation builds shared
     structure cheaply: `(c 1 1)` doubles the environment reachable
     from its result for one 50-cost cons, and k nested applies of
     that shape, a few hundred cost units each, reach 2^k visited
     nodes for build cost linear in k. The wire format's lack of
     back-references is no defense, because the sharing is built by
     evaluation, never spelled in the witness. The walk charges
     every visited node as it is reached and stops at
     `cost_exceeded`, bounding the work a budget can buy. An
     implementation that hashes first and charges after is open to
     unbounded work under a small budget, the same hazard class as
     the substr copy-on-slice note in COSTS.md section 5.
