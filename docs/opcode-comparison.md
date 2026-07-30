# Opcode inventory: CLVM, bllsh, BitLisp

Informative, not normative. This document places the three operator
sets side by side to show what each design has that the others lack.
The BitLisp column restates the v0 operator table in
[spec/VM.md](../spec/VM.md) section 4, which is the normative source.

Sources, as read on 2026-07-29:

- **CLVM**: the consensus operator set as dispatched by the pinned
  consensus oracle `chia-rs` 0.46.0 (upstream commit `7d487907`,
  provenance in [vm-record.md](vm-record.md)), cross-read against the
  `clvm_rs` dispatch table in `references/`. Flag-gated and
  guard-only operators are marked.
- **bllsh**: Anthony Towns' bll implementation,
  [github.com/ajtowns/bllsh](https://github.com/ajtowns/bllsh),
  master commit `04f924f6` (2025-07-08), from `opcodes.py` and
  `README.md`. bllsh is an experimental REPL, not a deployed
  consensus system, so its operator set is a design sketch and a
  moving target.
- **BitLisp**: spec/VM.md section 4, Phase 1 complete.

Opcode numbers are not comparable across columns. BitLisp inherits
CLVM's numeric assignments on everything shared, while bllsh numbers
its own space. "absent" means no operator provides the capability in
that system.

## Evaluator core

| Capability | CLVM | bllsh | BitLisp |
| --- | --- | --- | --- |
| quote | `q` 0x01 | `q` (special form, no table id) | `q` 0x01 |
| apply | `a` 0x02 | `a` (special form, id 0x01 reserved in a source comment) | `a` 0x02 |
| environment access | atom program is a path, a bit walk into the environment tree | atom program is a lookup keyed on the atom | atom program is a path, the CLVM rule |
| conditional | `i` 0x03, eager | `i` 0x05, eager | `i` 0x03, eager |
| raise | `x` 0x08 | `x` 0x04 | `x` 0x08 |
| softfork guard | `softfork` 0x24, two live extensions | `sf` (special form, id 0x02 reserved, unimplemented) | absent, declined (divergence D3) |
| partial application | absent | `partial` (special form, id 0x03 reserved) | absent |
| unknown operator policy | accepted, returns nil at a cost decoded from the opcode bytes | not specified | rejected with `unknown_operator`, closed set (D3) |

## Tree and list operations

| Capability | CLVM | bllsh | BitLisp |
| --- | --- | --- | --- |
| pair construction | `c` 0x04 | `rc` 0x06, list construction with arguments reversed | `c` 0x04 |
| first | `f` 0x05 | `h` 0x07 | `f` 0x05 |
| rest | `r` 0x06 | `t` 0x08 | `r` 0x06 |
| pair test | `l` 0x07 | `l` 0x09 | `l` 0x07 |
| list to binary tree | absent | `b` 0x0a | absent |

## Boolean operations

| Capability | CLVM | bllsh | BitLisp |
| --- | --- | --- | --- |
| not | `not` 0x20 | `notall` with one argument | `not` 0x20 |
| any | `any` 0x21 | `any` 0x0d | `any` 0x21 |
| all | `all` 0x22 | `all` 0x0c | `all` 0x22 |
| not-all | composable from `not` and `all` | `notall` 0x0b | composable from `not` and `all` |

## Comparison, bytes, strings

| Capability | CLVM | bllsh | BitLisp |
| --- | --- | --- | --- |
| atom equality | `=` 0x09 | `=` 0x0e | `=` 0x09 |
| deep tree equality | absent | `===` 0xff | absent |
| lexicographic byte compare | `>s` 0x0a, greater | `<s` 0x0f, less | `>s` 0x0a |
| byte length | `strlen` 0x0d | `strlen` 0x10 | `strlen` 0x0d |
| slice | `substr` 0x0c | `substr` 0x11 | `substr` 0x0c |
| concatenate | `concat` 0x0e | `cat` 0x12 | `concat` 0x0e |

## Arithmetic

| Capability | CLVM | bllsh | BitLisp |
| --- | --- | --- | --- |
| add | `+` 0x10 | `+` 0x17 | `+` 0x10 |
| subtract | `-` 0x11 | `-` 0x18 | `-` 0x11 |
| multiply | `*` 0x12 | `*` 0x19 | `*` 0x12 |
| divide | `/` 0x13 | absent | `/` 0x13 |
| divmod | `divmod` 0x14 | absent | `divmod` 0x14 |
| modulo | `%` 0x3d, post-hardfork | `%` 0x1a | absent (D3 unknown) |
| modular exponentiation | `modpow` 0x3c, post-hardfork | absent | absent (D3 unknown) |
| signed integer compare | `>` 0x15, greater | `<` 0x1e, less | `>` 0x15 |

bllsh has no division operator at all. A `div` implementation exists
in its source but is commented out and unregistered, leaving `%` as
the only division-family operation.

## Bitwise

| Capability | CLVM | bllsh | BitLisp |
| --- | --- | --- | --- |
| and | `logand` 0x18 | `&` 0x14 | `logand` 0x18 |
| or | `logior` 0x19 | \| 0x15 | `logior` 0x19 |
| xor | `logxor` 0x1a | `^` 0x16 | `logxor` 0x1a |
| complement | `lognot` 0x1b | `~` 0x13, a nand fold, complement with one argument | `lognot` 0x1b |
| shifts | `ash` 0x16 and `lsh` 0x17 | `shift` 0x1b, one operator for both directions | `ash` 0x16 and `lsh` 0x17 |

The semantics differ more than the names. CLVM and BitLisp bitwise
operators read atoms as sign-extended two's-complement integers.
bllsh operates on byte strings.

## Serialization operators

| Capability | CLVM | bllsh | BitLisp |
| --- | --- | --- | --- |
| deserialize inside the VM | absent, serialization sits outside the VM | `rd` 0x20 | absent, same boundary as CLVM |
| serialize inside the VM | absent | `wr` 0x21 | absent |

## Hashing

| Capability | CLVM | bllsh | BitLisp |
| --- | --- | --- | --- |
| sha256 | `sha256` 0x0b | `sha256` 0x22 | `sha256` 0x0b |
| sha256 tree hash | `sha256tree` 0x3f, flag-gated today, promoted to consensus in the Chia 3.0 hard fork (CHIP-0049, in review) | absent | `sha256tree` 0x3f (divergence D9, adopted 2026-07-29) |
| keccak256 | `keccak256` 0x3e, inside the softfork guard (extension 1) only | absent | absent (D3 unknown) |
| ripemd160 | absent | `ripemd160` 0x23 | absent (declined, D2 record) |
| hash160 | absent | `hash160` 0x24 | absent (declined, D2 record) |
| hash256 | absent | `hash256` 0x25 | absent |
| coin id derivation | `coinid` 0x30, post-hardfork | absent | absent (Chia-specific, D3 unknown) |

## Signatures and elliptic curves

| Capability | CLVM | bllsh | BitLisp |
| --- | --- | --- | --- |
| BLS12-381 family | `point_add` 0x1d, `pubkey_for_exp` 0x1e, `bls_*` 0x31 to 0x3b, post-hardfork | absent | absent (D1) |
| BIP340 Schnorr verify | absent | `bip340_verify` 0x26 | `secp_verify` 0x0f (D2) |
| ECDSA secp256k1 verify | `secp256k1_verify`, four-byte opcode 0x13d61f00, post-hardfork | `ecdsa_verify` 0x27 | absent (declined, D2 record) |
| ECDSA secp256r1 verify | `secp256r1_verify`, four-byte opcode 0x1c3a8f00, post-hardfork | absent | absent (declined, D2 record) |
| EC linear combination | absent | `secp256k1_muladd` 0x28 | absent (declined, D2 record) |

## Transaction introspection

| Capability | CLVM | bllsh | BitLisp |
| --- | --- | --- | --- |
| transaction field access | absent | `tx` 0x29 | absent |
| sighash computation | absent | `bip342_txmsg` 0x2a | absent |

This row is the architectural divide, not a vocabulary gap. bllsh is
the introspection design: programs read the transaction directly, so
these two operators are its counterpart to an entire condition layer.
CLVM and BitLisp are condition-emission designs: programs return a
condition list and a validator matches it against the transaction.
In BitLisp that surface belongs to
[spec/CONDITIONS.md](../spec/CONDITIONS.md) and
[spec/MATCHING.md](../spec/MATCHING.md), owed by Phase 2.

## Observations

- **BitLisp relative to CLVM** is a strict curation: the shared core
  keeps CLVM's names, numbers, and semantics bit for bit, the BLS
  family, softfork guard, post-hardfork extensions, and unknown-op
  acceptance are removed, and there are two additions. `secp_verify`
  sits on 0x0f, a byte unassigned in both oracles, and `sha256tree`
  sits on 0x3f with upstream's own opcode, semantics, and cost
  constants, adopted while the operator is still flag-gated there so
  the two converge when Chia's 3.0 fork activates. Every removal and
  addition has a rationale row in the divergence table in
  [vm-record.md](vm-record.md).
- **bllsh relative to CLVM** reworks the core rather than curating
  it: division is gone, the two shifts collapse into one operator,
  bitwise moves from integers to byte strings, list construction
  replaces bare cons, and serialization, legacy Bitcoin hashes,
  ECDSA, EC arithmetic, and transaction introspection come in.
- **The three converge** on exactly one piece of new ground: BIP340
  verification over secp256k1. BitLisp's `secp_verify` follows
  bllsh's `bip340_verify` precedent for tri-state semantics (empty
  signature returns nil, invalid signature raises), a debt recorded
  in the D2 entry of [vm-record.md](vm-record.md). CLVM is the
  outlier with raise-only
  ECDSA.
- **What only BitLisp has** is mostly not visible in an opcode
  table: the closed operator set, strict canonical deserialization,
  and the fail-closed zero budget are properties of the dispatch and
  serialization rules, pinned by the divergence table rather than by
  new opcodes.
