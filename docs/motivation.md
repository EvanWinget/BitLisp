# Motivation

Informative, not normative. Why this project exists and what it is
trying to learn. 2026-07-31.

## A research project, stated plainly

BitLisp is research. The goal is a working, measurable understanding
of the pros and cons of alternatives to Bitcoin Script: an executable
spec, a vector corpus, and measured numbers instead of estimates. It
is not a soft-fork proposal, and we plan on the assumption that
nothing here is adopted within ten years. The companion
[evaluation](bitcoin-script-successor-evaluation.md) estimates 25 to
35 percent odds of any successor activating on that horizon (its
section 8), and the work is scoped to be worth doing even at zero.
Whoever asks "what should follow Script?" later should find artifacts
here, not opinions.

## The capabilities that matter

Bitcoin exists for self-custodial money, so the first-principles
question is what the contract layer must support for self-custody to
scale. Our working answer, argued quantitatively in the evaluation
(sections 2 and 6):

1. **Committing to outputs.** A coin should be able to enforce
   properties of the transaction that spends it: where the value
   goes, in what amounts, after what delay. This is the primitive
   under vaults, congestion batching, and every pooled-custody
   design.
2. **Shared UTXOs with unilateral exit.** Fixed block space caps
   per-user-UTXO self-custody, Lightning channels included, below two
   hundred million user lifecycles per year even at full blocks
   (evaluation section 2.2). Reaching further requires many users in
   one UTXO, and sharing is only custody if any user can leave alone,
   without cooperation from the others.
3. **Signatures over program-chosen messages.** Verifying a signature
   against a message the program assembles, not only the transaction
   digest. This is what channel state succession (LN-Symmetry) and
   non-interactive oracle contracts need.
4. **Computation at spend time.** Merkle membership proofs, amount
   arithmetic, state succession. Pooled designs need these exactly at
   exit time, where today's workarounds are weakest.

## Where Script falls short

Script can check signatures, hash preimages, and timelocks against
the spending transaction. It cannot see the transaction's outputs, so
it cannot express "this coin may only move to these destinations".
Its arithmetic is limited to 4-byte integers, and the opcodes that
would help (concatenation, multiplication, string operations) have
been disabled since 2010. There is no way to carry state from one
spend to the next.

The point is not that Script is broken. It is that protocols needing
these capabilities buy them through workarounds whose prices are
visible today: presigned transaction trees with key deletion
(vaults), trusted operators (statechains), interactive n-of-n
ceremonies (channel factories), and challenge games with capital
lockup and liveness requirements (BitVM). The evaluation tabulates
these in section 2.4. Doing nothing does not avoid the costs, it
moves them onto users.

## Simplicity

[Simplicity](https://github.com/BlockstreamResearch/simplicity)
deserves to be named first among successor efforts. It is deployed on
Liquid and handling real user funds today, which no other Script
alternative can claim, and its formal verification story is
unmatched: machine-checked semantics and static cost bounds known
before execution. We are not building on it because the evaluation
(section 4.2) judged its consensus surface too large for Bitcoin's
qualified-reviewer set. That is a judgment about review economics,
not about soundness, and we hold it at moderate confidence. Its
pre-execution cost bounds are worth learning from regardless.

## bllsh

Anthony Towns' [bllsh](https://github.com/ajtowns/bllsh) implements
bll, the other live Lisp direction: a Lisp VM with transaction
introspection operators, in the Elements tradition. We took it
seriously enough to build against it. The paused companion repo
`bll-consensus` holds a C++ evaluator (libbll) developed with bllsh
as its differential oracle, plus the spec, cost, and divergence
records that effort produced. *(Placeholder: a short write-up of what
the bll-consensus phase measured and taught, extracted from that
repo's records.)*

We paused that line when the evaluation concluded (sections 4.3 and
6) that an introspection interface, whatever its VM, gives up
properties a condition-emission interface keeps, most importantly
purity and the non-interactive composition it enables. That is the
evaluation's load-bearing judgment, held at 72 percent confidence and
awaiting hostile review, so bllsh remains the standing comparison
point. Its operator set is kept side by side with ours in
[opcode-comparison.md](opcode-comparison.md).

## BitLisp

BitLisp is the artifact for the remaining branch: the conditions
architecture. A pure CLVM-derived VM evaluates the program committed
in an output against spender-supplied witness arguments and returns a
condition list. A single validator then matches those conditions
against the transaction. Chia has operated this architecture in
production since 2021, which gives most of the VM a deployed oracle
to diff against. The genuinely novel part, matching conditions
against a Bitcoin transaction, has no deployed precedent anywhere.
That is why the matching rules get adversarial vectors before any
feature work builds on them.

The questions this repo exists to answer with measurements rather
than estimates:

- Do witness sizes, after the compression work, fit the unilateral
  exit budget the scaling argument requires (evaluation section 2.3)?
- Can the matching layer be specified tightly enough that adversarial
  vectors stop finding theft bugs?
- *(Placeholder: further measurement questions as Phase 4
  approaches.)*

The phased plan and done-criteria live in
[execution-plan.md](execution-plan.md). The four design obligations
the evaluation imposes are in its section 7.

## Non-goals

- **Near-term soft-fork advocacy.** The evaluation's answer to "what
  should Bitcoin do next" is CTV plus CSFS (its section 1). Nothing
  here competes with that.
- **A production implementation.** The Python code is an executable
  spec, optimized to be read.
- **Winning the argument.** If hostile review breaks the
  conditions-over-introspection judgment, documenting how it broke is
  a success for this project, not a failure.
