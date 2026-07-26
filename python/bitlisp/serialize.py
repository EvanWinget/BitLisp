"""Strict canonical serialization, the CLVM wire format.

CLVM deserializers accept non-minimal length encodings, trailing
bytes, and back-references. BitLisp rejects all three, a recorded
divergence: witness bytes must have exactly one accepted spelling
per program.

Both directions are iterative on purpose: tree depth must not be
limited by the Python recursion limit.
"""

from .errors import BitLispError
from .sexp import is_atom

# Length prefix forms: (leading byte low-bit mask, extra length bytes,
# smallest length that requires this form). An encoding is canonical
# only if the length could not fit a shorter form.
_FORMS = (
    (0x80, 0x3F, 0, 0),
    (0xC0, 0x1F, 1, 0x40),
    (0xE0, 0x0F, 2, 0x2000),
    (0xF0, 0x07, 3, 0x100000),
    (0xF8, 0x03, 4, 0x8000000),
)
_MAX_LENGTH = 0x400000000 - 1  # 34-bit length field

_PARSE, _CONS = 0, 1


def serialize(node):
    """Canonical bytes for a node, the unique accepted spelling."""
    out = bytearray()
    stack = [node]
    while stack:
        n = stack.pop()
        if is_atom(n):
            _write_atom(out, n)
        else:
            out.append(0xFF)
            stack.append(n[1])
            stack.append(n[0])
    return bytes(out)


def _write_atom(out, atom):
    length = len(atom)
    if length == 1 and atom[0] <= 0x7F:
        out += atom
        return
    for prefix, mask, extra, _floor in _FORMS:
        if length <= (mask << (8 * extra)) | ((1 << (8 * extra)) - 1):
            out.append(prefix | (length >> (8 * extra)))
            low_bits = length & ((1 << (8 * extra)) - 1)
            out += low_bits.to_bytes(extra, "big") if extra else b""
            out += atom
            return
    raise BitLispError("bad_encoding", "atom too long to serialize")


def deserialize(data):
    """Parses exactly one node from all of data, strictly."""
    pos = 0
    values = []
    tasks = [_PARSE]
    while tasks:
        task = tasks.pop()
        if task == _CONS:
            right = values.pop()
            left = values.pop()
            values.append((left, right))
            continue
        if pos >= len(data):
            raise BitLispError("bad_encoding", "truncated input")
        b0 = data[pos]
        pos += 1
        if b0 == 0xFF:
            tasks.append(_CONS)
            tasks.append(_PARSE)
            tasks.append(_PARSE)
            continue
        if b0 <= 0x7F:
            values.append(bytes([b0]))
            continue
        if b0 >= 0xFC:
            raise BitLispError("bad_encoding", f"invalid prefix byte {b0:#x}")
        for prefix, mask, extra, floor in _FORMS:
            if prefix <= b0 <= prefix | mask:
                high = b0 & mask
                if pos + extra > len(data):
                    raise BitLispError("bad_encoding", "truncated length field")
                length = int.from_bytes(data[pos : pos + extra], "big")
                length |= high << (8 * extra)
                pos += extra
                if length < floor:
                    raise BitLispError("bad_encoding", "non-minimal length encoding")
                if pos + length > len(data):
                    raise BitLispError("bad_encoding", "truncated atom")
                atom = data[pos : pos + length]
                pos += length
                if length == 1 and atom[0] <= 0x7F:
                    raise BitLispError(
                        "bad_encoding", "one-byte atom must use the one-byte form"
                    )
                values.append(atom)
                break
    if pos != len(data):
        raise BitLispError("bad_encoding", "trailing bytes after node")
    return values[0]
