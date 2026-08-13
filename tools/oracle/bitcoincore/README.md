# Vendored Bitcoin Core test framework

Bitcoin Core's test-only secp256k1 and BIP 340 implementation,
vendored verbatim as the `secp_verify` differential oracle, and its
transaction message classes, vendored verbatim as the serialization
oracle for the txid and outputs-hash derivations of the seal family.
This is the code Core itself uses to cross-check its consensus
signing, verification, and wire encoding, continuously validated in
Core's own CI. It is test tooling only: nothing under
`python/bitlisp/` imports it. Its consumers are `tools/diff_secp.py`
and the test suites `python/tests/test_secp256k1.py`,
`test_taproot.py`, `test_signature_assert_invariants.py`, and
`test_seal_invariants.py`.

## Provenance

- Source repository: https://github.com/bitcoin/bitcoin
- Release tag: v31.1 (commit 9be056a8a72b624dae9623b2f7bded92c2a21c91)
- License: MIT, the file headers reference the accompanying `COPYING`,
  carried here so the notice travels with the snapshot
- Import date: 2026-07-28

Vendored verbatim:

| File | Upstream path | sha256 |
| --- | --- | --- |
| `test_framework/key.py` | `test/functional/test_framework/key.py` | `1f48819cbecacb5916a32a4930b4576ab362c190fa552342378e5c809a6bae77` |
| `test_framework/crypto/secp256k1.py` | `test/functional/test_framework/crypto/secp256k1.py` | `cab75b7335f839b88eb8517b417715858e538aaf0071f6c01ec4eb3e1867f246` |
| `test_framework/messages.py` | `test/functional/test_framework/messages.py` | `c786651a517a49dd084b1d76072f755d40c5483f5be53b7322ca4f3403548b26` |
| `test_framework/crypto/siphash.py` | `test/functional/test_framework/crypto/siphash.py` | `7af3111be53124afb78a607cb9bfe3fdd5a64717c95a279d5962cda9a0853ab1` |

`messages.py` and `crypto/siphash.py` were added 2026-08-09 from the
same release tag as the original import, an extension of the
snapshot at the existing pin, not a pin bump.

Ours, not upstream: the two `__init__.py` files and
`test_framework/util.py`, a minimal stub of the three helpers the
vendored files import, so the verbatim files resolve their imports
without dragging in Core's full test utility module. Two of the
stubbed helpers run live: `assert_not_equal` on verification and
signing paths, and `assert_equal` at import time on messages.py's
serialization sanity check. Both stubs reproduce upstream
semantics exactly.

The vendored files are exempt from repository lint, like
`vectors/upstream/`. Refreshing this snapshot is an upstream pin bump
and follows the same governance as every other oracle pin.
