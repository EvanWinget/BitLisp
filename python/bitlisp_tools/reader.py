"""Assembler: text s-expressions to program trees.

The reader is context-free and total over str input: it returns a
node or raises ParseError, nothing else. Unknown bare symbols are
rejected rather than silently becoming the bytes of their own name,
so a misspelled operator fails here instead of assembling into data
that fails at runtime. Literal name bytes are written as a string or
as hex.

Parsing is iterative with an explicit frame stack: tree depth must
not be limited by the Python recursion limit.
"""

from bitlisp.sexp import NIL, int_to_atom

from .keywords import NAME_TO_ATOM

_HEX_DIGITS = set("0123456789abcdefABCDEF")

# Decimal digits are exactly ASCII 0 to 9. Python's int() and
# str.isdigit() also accept unicode digits, the same lookalike
# hazard the whitespace set below guards against.
_DIGITS = set("0123456789")

# Whitespace is exactly these four characters. Unicode whitespace is
# not a separator: it falls into a bare token and is rejected there,
# so a lookalike space can never silently split an expression.
_WHITESPACE = " \t\r\n"


class ParseError(Exception):
    """Text that is not a well-formed BitLisp s-expression."""

    def __init__(self, message, offset):
        super().__init__(f"{message} at offset {offset}")
        self.offset = offset


def tokenize(text):
    """The (token, offset) list for text, comments and whitespace dropped.

    A token is "(", ")", a quoted string carrying its delimiters, or a
    bare run ending at whitespace, a paren, a quote character, or ";".
    The dot of a dotted tail arrives as the bare token ".".
    """
    tokens = []
    i = 0
    end = len(text)
    while i < end:
        ch = text[i]
        if ch in _WHITESPACE:
            i += 1
        elif ch == ";":
            while i < end and text[i] != "\n":
                i += 1
        elif ch in "()":
            tokens.append((ch, i))
            i += 1
        elif ch in "\"'":
            close = text.find(ch, i + 1)
            if close < 0:
                raise ParseError("unterminated string", i)
            tokens.append((text[i : close + 1], i))
            i = close + 1
        else:
            start = i
            while i < end and text[i] not in _WHITESPACE and text[i] not in "()\"';":
                i += 1
            tokens.append((text[start:i], start))
    return tokens


def _atom_from_token(token, offset):
    """The atom a non-paren token denotes: string, hex, name, or decimal."""
    if token[0] in "\"'":
        try:
            return token[1:-1].encode()
        except UnicodeEncodeError:
            # A Python str can hold lone surrogates, which UTF-8
            # cannot represent. The reader stays total: ParseError,
            # never a codec exception.
            raise ParseError("string contents not encodable as UTF-8", offset) from None
    if token.startswith("0x"):
        digits = token[2:]
        if not set(digits) <= _HEX_DIGITS:
            raise ParseError(f"bad hex atom {token!r}", offset)
        if len(digits) % 2:
            digits = "0" + digits
        return bytes.fromhex(digits)
    atom = NAME_TO_ATOM.get(token)
    if atom is not None:
        return atom
    body = token[1:] if token.startswith("-") else token
    if body and set(body) <= _DIGITS:
        return int_to_atom(int(token))
    raise ParseError(f"unknown symbol {token!r}", offset)


def assemble(text):
    """The node for exactly one text s-expression, ParseError on failure.

    Each stack frame is one open list: its elements so far, the node
    after the dot if one has been seen, whether the dot has been seen,
    and the offset of the opening paren for the missing-paren error.
    """
    result = None
    have_result = False
    stack = []
    for token, offset in tokenize(text):
        if have_result and not stack:
            raise ParseError("trailing tokens", offset)
        if token == "(":
            stack.append([[], None, False, offset])
            continue
        if token == ".":
            if not stack:
                raise ParseError("dot outside a pair", offset)
            frame = stack[-1]
            if not frame[0]:
                raise ParseError("dot with no head", offset)
            if frame[2]:
                raise ParseError("second dot in list", offset)
            frame[2] = True
            continue
        if token == ")":
            if not stack:
                raise ParseError("unexpected )", offset)
            items, tail, saw_dot, _ = stack.pop()
            if saw_dot and tail is None:
                raise ParseError("dot with no tail", offset)
            node = tail if saw_dot else NIL
            for item in reversed(items):
                node = (item, node)
        else:
            node = _atom_from_token(token, offset)
        if stack:
            frame = stack[-1]
            if not frame[2]:
                frame[0].append(node)
            elif frame[1] is None:
                frame[1] = node
            else:
                raise ParseError("element after dotted tail", offset)
        else:
            result = node
            have_result = True
    if stack:
        raise ParseError("missing )", stack[-1][3])
    if not have_result:
        raise ParseError("empty input", len(text))
    return result
