"""Assembler: text s-expressions to program trees.

The reader is context-free and total over str input: it returns a
node or raises ParseError, nothing else. Unknown bare symbols are
rejected rather than silently becoming the bytes of their own name,
so a misspelled operator fails here instead of assembling into data
that fails at runtime. Literal name bytes are written as a string or
as hex.

A caller may pass definition bindings, a dict from bare names to
nodes. A binding is consulted only where the resolver would
otherwise reject an unknown symbol, after string, hex, operator
name, and decimal all decline, so a binding can never change the
meaning of text that already parses. The bound node splices in
wherever the name sits, head position and dotted tails included.

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


def _known_token(token, offset):
    """The atom a non-paren token denotes, or None for an unknown
    symbol: string, hex, operator name, or decimal, malformed
    spellings of those raising ParseError."""
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
        try:
            return int_to_atom(int(token))
        except ValueError:
            # CPython caps decimal string conversion at a digit
            # limit. The reader stays total, ParseError and never
            # the interpreter's limit error, and hex spells an atom
            # of any size.
            raise ParseError("decimal atom past the digit limit", offset) from None
    return None


def _node_from_token(token, offset, names):
    """The node a non-paren token denotes, bindings consulted last."""
    node = _known_token(token, offset)
    if node is not None:
        return node
    if names:
        bound = names.get(token)
        if bound is not None:
            return bound
    raise ParseError(f"unknown symbol {token!r}", offset)


def definable(text):
    """True when text is exactly one bare token the resolver rejects
    as an unknown symbol, the shape a definition name must have.
    Structural tokens, strings, operator names, decimals, malformed
    hex or decimal spellings, and text the tokenizer would trim (a
    comment, a quote character, surrounding whitespace) are not
    definable, so every accepted name can be written back and read."""
    try:
        tokens = tokenize(text)
    except ParseError:
        return False
    if len(tokens) != 1:
        return False
    token, offset = tokens[0]
    if token != text or token in ("(", ")", "."):
        return False
    try:
        return _known_token(token, offset) is None
    except ParseError:
        return False


def _parse(tokens, names, single):
    """The node list for a token stream.

    Each stack frame is one open list: its elements so far, the node
    after the dot if one has been seen, whether the dot has been seen,
    and the offset of the opening paren for the missing-paren error.
    """
    results = []
    stack = []
    for token, offset in tokens:
        if single and results and not stack:
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
            node = _node_from_token(token, offset, names)
        if stack:
            frame = stack[-1]
            if not frame[2]:
                frame[0].append(node)
            elif frame[1] is None:
                frame[1] = node
            else:
                raise ParseError("element after dotted tail", offset)
        else:
            results.append(node)
    if stack:
        raise ParseError("missing )", stack[-1][3])
    return results


def assemble(text, names=None):
    """The node for exactly one text s-expression, ParseError on failure."""
    nodes = _parse(tokenize(text), names, single=True)
    if not nodes:
        raise ParseError("empty input", len(text))
    return nodes[0]


def assemble_many(text, names=None):
    """The node list for zero or more text s-expressions."""
    return _parse(tokenize(text), names, single=False)
