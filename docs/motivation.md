# Motivation

BitLisp is a research project. The goal is a working,
measurable understanding of the pros and cons of alternatives
to Bitcoin Script. It is not a soft-fork proposal.

## Scaling and self-custody improvements

Bitcoin owners should have the option of using Bitcoin as self-custodial
money and Bitcoin should scale to support a global population while
retaining its decentralization properties. Improvements that bring us
closer to a scalable, self-custodial solution include:

- **Vaults.** Coins held so that send transactions pass through a
  public delay with a recovery path. A key compromise becomes
  observable and reversible before funds finish moving.
- **Pooled custody with unilateral exit.** Many users share one UTXO
  and any one of them can withdraw alone, without the others
  cooperating or even being online. Fixed block space caps
  per-user-UTXO self-custody below two hundred million users per year
  at full blocks, so self-custody at global scale requires sharing UTXOs.
- **Symmetric channels.** Channels where the latest state wins
  (LN-Symmetry), replacing penalty-based enforcement and shrinking
  what channel partners must watch for.
- **Non-interactive protocols.** Oracle contracts that one party can
publish and another can take later, with no signing ceremony that
requires interactivity.

## What the contract layer must support

Stated as contract-layer capabilities, those improvements need:

1. **Committing to outputs.** A coin can enforce properties of the
   transaction that spends it: where the value goes, in what amounts,
   after what delay. This is the primitive under vaults and pooled
   custody.
2. **Signatures over program-chosen messages.** Verifying a signature
   against a message the program assembles, not only the transaction
   digest. Symmetric channels and oracle contracts need this.
3. **Computation at spend time.** Merkle membership proofs, amount
   arithmetic, state succession. Pool exits need all three at once.

## Limitations of Script

Script works well for many users and scaling solutions today. Script can
check signatures, hash preimages, and timelocks against the spending
transaction. Script cannot see the transaction's outputs, so it cannot
express "this coin may only move to these destinations". There is no way
to carry state from one spend to the next. Its arithmetic is limited to
4-byte integers.

Protocols needing these capabilities buy them through workarounds whose
prices are visible today: presigned transaction trees with key deletion
(vaults), trusted operators (statechains), interactive n-of-n ceremonies
(channel factories), and challenge games with capital lockup and
liveness requirements (BitVM). Doing nothing does not avoid the costs, it
moves them onto users.

These gaps can be patched by activating new Script opcodes, and fork
candidates (CTV, CSFS, CAT, wider arithmetic) would enhance the
capabilities of Script. The limits show up at scale: pooled constructions
built from opcode covenants produce large, hard-to-audit scripts whose
exit sizes sit at the edge of the block space budget, and every contract
re-implements its own verification rather than sharing one reviewed
validator. A research question is whether a purpose-built layer clears
these limits.

## Simplicity

[Simplicity](https://github.com/BlockstreamResearch/simplicity)
is deployed on Liquid and handling real user funds today, which no other
Script alternative can claim, and it has formal verification:
machine-checked semantics and static cost bounds known before execution.
The review surface is large because the combinator language, its
execution machine, and the catalog of jets together form a large body of
new consensus code.

## bllsh

Anthony Towns' [bllsh](https://github.com/ajtowns/bllsh) explores a
Lisp VM with transaction introspection operators. Programs read fields
of the spending transaction directly and fail the spend when a check
does not hold. It is an experimental REPL rather than a deployed system.
Its operator set is kept side by side with ours in [opcode-comparison.md](opcode-comparison.md).

## BitLisp

BitLisp is an alternative Lisp direction which is more similar to Chia's
model where a VM evaluates the program committed in an output against
spender-supplied witness arguments and returns a condition list. A
single validator then matches those conditions against the transaction.
Chia has operated this architecture in production since 2021, which
gives most of the VM a deployed oracle to diff against. The genuinely
novel part, validating conditions against a Bitcoin transaction, has no
deployed precedent anywhere.

The questions this repo exists to answer with measurements rather
than estimates:

- Do witness sizes fit the unilateral exit budget the scaling argument requires?
- Can the validation layer be specified tightly enough that adversarial
  vectors stop finding theft bugs?
- *(Placeholder: further measurement questions as Phase 4
  approaches.)*
