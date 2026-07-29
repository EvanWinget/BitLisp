# Vendored Bitcoin Core test-framework crypto

Bitcoin Core's test-only secp256k1 and BIP 340 implementation,
vendored verbatim as the `secp_verify` differential oracle. This is
the code Core itself uses to cross-check its consensus signing and
verification, continuously validated against libsecp256k1 in Core's
own CI. It is test tooling only: nothing under `python/bitlisp/`
imports it, and `tools/diff_secp.py` is its only consumer.

## Provenance

- Source repository: https://github.com/bitcoin/bitcoin
- Release tag: v31.1 (commit 9be056a8a72b624dae9623b2f7bded92c2a21c91)
- License: MIT
- Import date: 2026-07-28

Vendored verbatim:

| File | Upstream path | sha256 |
| --- | --- | --- |
| `test_framework/key.py` | `test/functional/test_framework/key.py` | `1f48819cbecacb5916a32a4930b4576ab362c190fa552342378e5c809a6bae77` |
| `test_framework/crypto/secp256k1.py` | `test/functional/test_framework/crypto/secp256k1.py` | `cab75b7335f839b88eb8517b417715858e538aaf0071f6c01ec4eb3e1867f246` |

Ours, not upstream: the two `__init__.py` files and
`test_framework/util.py`, a minimal stub of the two helpers the
vendored files import for their embedded self-tests, so the verbatim
files resolve their imports without dragging in Core's full test
utility module.

The vendored files are exempt from repository lint, like
`vectors/upstream/`. Refreshing this snapshot is an upstream pin bump
and follows the same governance as every other oracle pin.
