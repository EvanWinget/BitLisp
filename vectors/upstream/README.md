# Vendored upstream vectors

Upstream test vectors vendored as data: Chia's official vectors for
the operator intersection, and the official BIP 340 vectors for
`secp_verify`. CI never fetches from the network.

Every import must carry a provenance header (a `_provenance` key or an
adjacent `.provenance.json` file) recording:

- source repository and path
- commit hash
- upstream license
- import date and importing commit

Files here keep their original upstream format and are exempt from the
`bitlisp-vector-v0` envelope and from repository lint. Imports happen in
Phase 1 alongside the intersection diff harness.
