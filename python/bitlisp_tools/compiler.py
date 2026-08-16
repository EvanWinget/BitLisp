"""Compiler: v0 authoring language to program trees.

The language is the text syntax plus bare names. A name is anything
the reader would reject as an unknown symbol, so strings, hex,
operator names, and decimals keep exactly their raw meaning and the
language occupies only text that previously errored. Atoms quote
themselves, names resolve to environment paths or inline constant
values, and the special forms are program, defun, defconstant,
defmacro, if, list, and qq with unquote. Everything else a source
expression can say is an operator application.

A compiled program's environment is the pair (function tree . args).
The function tree holds every reachable function body, balanced in
declaration order, and a call site rebuilds the layout by consing
the tree it received onto its evaluated arguments, so recursion and
mutual recursion need no further machinery. A program whose body
reaches no function is emitted bare with its arguments at the
environment root. Constants never enter the tree: a constant
reference inlines its value as a quoted literal at the use site.

Macro expansion is the one source-to-source rewrite: before
anything compiles, every macro call is replaced by the value its
compiled body computes over the raw argument source, repeatedly,
until no macro call remains. Emission after expansion is direct,
with one size-only exception: a nil literal is emitted as the nil
atom, whose path lookup yields nil, one byte instead of the two a
quoted nil takes.

Parsing and every other tree walk here are iterative. Code
emission and macro expansion recurse with the source's nesting
depth, a bound accepted because source is authored rather than
attacker-supplied: past the interpreter's limit every surface
reports unusable input, exit 2, never a crash or a wrong artifact.

The compiler also builds a symbol table for the debugger: the tree
hash of each compiled function body, keyed exactly as the VM's
sha256tree operator hashes, mapped to the function's name and
parameter names. Atom bodies stay out of the table, because an atom
is not distinguishable from ordinary data by its hash.
"""

import hashlib

from bitlisp import conditions
from bitlisp.errors import BitLispError
from bitlisp.machine import run
from bitlisp.operators import OPERATORS
from bitlisp.sexp import NIL, int_to_atom, is_atom, is_pair

from .keywords import ATOM_TO_NAME
from .printer import _atom_text
from .reader import ParseError, _known_token, _parse, definable, tokenize

_QUOTE = b"\x01"
_APPLY = b"\x02"
_IF_OP = b"\x03"
_CONS = b"\x04"

# The environment root, its first child, and its rest child, as the
# VM's path lookup numbers them.
_TOP, _LEFT, _RIGHT = 1, 2, 3

_PROGRAM, _DEFUN, _DEFCONSTANT, _DEFMACRO, _IF, _LIST, _QQ, _UNQUOTE = (
    "program",
    "defun",
    "defconstant",
    "defmacro",
    "if",
    "list",
    "qq",
    "unquote",
)
RESERVED_WORDS = frozenset(
    {_PROGRAM, _DEFUN, _DEFCONSTANT, _DEFMACRO, _IF, _LIST, _QQ, _UNQUOTE}
)

# The names a macro's returned atoms may resolve to besides the
# caller's own definitions: the expression forms the compiler
# provides everywhere.
_EXPRESSION_FORMS = frozenset({_IF, _LIST, _QQ, _UNQUOTE})

# One macro execution's compile-time budget on the reference VM,
# the same inclusive cost the spend runner applies when the caller
# names none.
MACRO_COST_BUDGET = 11_000_000_000

# How many times a macro's output may itself expand before the
# compiler rejects the chain. A self-splicing macro spends one
# level per argument plus one for the final empty round, so this
# bounds such calls at 99 arguments while staying far inside the
# interpreter's recursion limit.
MACRO_DEPTH_LIMIT = 100

# How many macro executions one compile may spend in total, all
# bodies combined. The depth cap bounds each chain but not the
# number of chains: a macro whose template splices two calls to
# itself doubles the work per level, staying under both per-chain
# guards while the total explodes, so the total is guarded too.
MACRO_EXPANSION_LIMIT = 10_000


class _ExpansionWork:
    """One compile's expansion context: the remaining macro
    executions, shared by every body so branching expansion cannot
    multiply work past the cap, and which world is expanding.
    strict is the program world, where a caller's misspelled
    argument names become errors. The macro world, a declaration
    expanding inside another macro's body, judges nothing extra:
    what it cannot resolve stays data and rides the compiled body
    out to the call sites."""

    __slots__ = ("remaining", "strict")

    def __init__(self, strict=True):
        self.remaining = MACRO_EXPANSION_LIMIT
        self.strict = strict


# The condition vocabulary, one name per assigned opcode, written
# out literally so a reviewer can check it by eye. A test pins the
# set against CONDITION_COSTS so a vocabulary change fails loudly
# here.
CONDITION_NAMES = (
    "CREATE_OUTPUT",
    "CREATE_OUTPUT_TAPROOT",
    "ASSERT_SIG_MY_TXID",
    "ASSERT_SIG_MY_SCRIPTPUBKEY",
    "ASSERT_SIG_MY_AMOUNT",
    "ASSERT_SIG_MY_SCRIPTPUBKEY_AMOUNT",
    "ASSERT_SIG_MY_TXID_AMOUNT",
    "ASSERT_SIG_MY_TXID_SCRIPTPUBKEY",
    "ASSERT_SIG_RAW",
    "ASSERT_SIG_MY_OUTPOINT",
    "ASSERT_LOCKTIME_HEIGHT",
    "ASSERT_LOCKTIME_TIME",
    "ASSERT_SEQUENCE_HEIGHT",
    "ASSERT_SEQUENCE_TIME",
    "ASSERT_MY_OUTPOINT",
    "ASSERT_MY_TXID",
    "ASSERT_MY_SCRIPTPUBKEY",
    "ASSERT_MY_AMOUNT",
    "ASSERT_MY_TAPROOT",
    "ANNOUNCE",
    "ASSERT_ANNOUNCEMENT",
    "SEND_MESSAGE",
    "RECEIVE_MESSAGE",
    "RESERVE_FEE",
    "SEAL",
    "SEAL_OUTPUTS",
)
CONDITION_CONSTANTS = {
    name: int_to_atom(getattr(conditions, name)) for name in CONDITION_NAMES
}

SYMBOLS_SCHEMA = "bitlisp-sym-v0"


class CompileError(Exception):
    """Source that reads as an s-expression but is not a valid program."""

    def __init__(self, message, offset=None):
        super().__init__(message if offset is None else f"{message} at offset {offset}")
        self.offset = offset


class Symbol:
    """A bare name in source, carrying its offset for error messages."""

    __slots__ = ("name", "offset")

    def __init__(self, name, offset):
        self.name = name
        self.offset = offset

    def __repr__(self):
        return f"Symbol({self.name!r})"


def _symbol_or_atom(token, offset):
    node = _known_token(token, offset)
    if node is not None:
        return node
    return Symbol(token, offset)


def parse_source(text):
    """The source tree for exactly one expression, names allowed."""
    nodes = _parse(tokenize(text), _symbol_or_atom, single=True)
    if not nodes:
        raise ParseError("empty input", len(text))
    return nodes[0]


def parse_source_many(text):
    """The source tree list for zero or more expressions."""
    return _parse(tokenize(text), _symbol_or_atom, single=False)


def source_text(tree):
    """The text spelling of a source tree, names rendered as
    written. A root atom is data, never operator position, so a
    constant whose bytes happen to be an opcode prints as its
    value, not as the operator's name."""
    pieces = []
    stack = [(0, tree, False)]
    while stack:
        kind, current, operator_position = stack.pop()
        if kind == 1:
            if isinstance(current, Symbol):
                pieces.append(" . ")
                pieces.append(current.name)
                pieces.append(")")
            elif current == NIL:
                pieces.append(")")
            elif is_atom(current):
                pieces.append(" . ")
                pieces.append(_atom_text(current, False))
                pieces.append(")")
            else:
                pieces.append(" ")
                stack.append((1, current[1], False))
                stack.append((0, current[0], False))
        elif isinstance(current, Symbol):
            pieces.append(current.name)
        elif is_atom(current):
            pieces.append(_atom_text(current, operator_position))
        else:
            pieces.append("(")
            stack.append((1, current[1], False))
            stack.append((0, current[0], True))
    return "".join(pieces)


def first_symbol(tree):
    """The first Symbol in a source tree, or None."""
    stack = [tree]
    while stack:
        current = stack.pop()
        if isinstance(current, Symbol):
            return current
        if is_pair(current):
            stack.append(current[1])
            stack.append(current[0])
    return None


def _symbol_names(tree):
    """Every name a source tree mentions, quoted content included:
    reachability stays conservative and the quote rule is enforced
    where the content compiles."""
    names = set()
    stack = [tree]
    while stack:
        current = stack.pop()
        if isinstance(current, Symbol):
            names.add(current.name)
        elif is_pair(current):
            stack.append(current[1])
            stack.append(current[0])
    return names


def _check_name(symbol, what):
    if not isinstance(symbol, Symbol):
        raise CompileError(f"{what} name must be a bare name")
    if symbol.name in RESERVED_WORDS:
        raise CompileError(f"{symbol.name!r} is a reserved word", symbol.offset)
    if symbol.name in CONDITION_CONSTANTS:
        raise CompileError(f"{symbol.name!r} is a condition constant", symbol.offset)
    return symbol.name


def _check_params(tree):
    """Validates a parameter tree, returning its arity as the pair
    (exact, count): a proper list of n spine entries takes exactly n
    arguments, a dotted or bare-name tail takes at least the count
    before it, and the tail name binds the remaining argument list."""
    seen = set()
    stack = [tree]
    while stack:
        current = stack.pop()
        if isinstance(current, Symbol):
            name = _check_name(current, "parameter")
            if name in seen:
                raise CompileError(f"duplicate parameter {name!r}", current.offset)
            seen.add(name)
        elif is_pair(current):
            stack.append(current[1])
            stack.append(current[0])
        elif current != NIL:
            raise CompileError("parameter must be a bare name")
    count = 0
    spine = tree
    while is_pair(spine):
        count += 1
        spine = spine[1]
    return (spine == NIL, count)


class Definitions:
    """The compile-time namespace: functions, constants, and macros
    by name.

    A name is claimed once across functions, constants, macros, the
    condition constants, the reserved words, and any caller-supplied
    taken set, so one spelling can never mean two things.
    """

    def __init__(self):
        self.functions = {}
        self.constants = {}
        self.macros = {}

    def _claim(self, symbol, taken):
        name = _check_name(symbol, "definition")
        if (
            name in self.functions
            or name in self.constants
            or name in self.macros
            or name in taken
        ):
            raise CompileError(f"{name!r} is already defined", symbol.offset)
        return name

    def add_defun(self, form, taken=frozenset()):
        """Adds one (defun name params body) source form. The body
        is stored as written and compiles when a program reaches it,
        so definitions may reference names that arrive later."""
        items = _form_items(form, _DEFUN, 4)
        name = self._claim(items[1], taken)
        arity = _check_params(items[2])
        self.functions[name] = (items[2], items[3], arity)
        return name

    def add_defconstant(self, form, taken=frozenset()):
        """Adds one (defconstant name value) source form. The value
        is data taken verbatim, never evaluated, so it cannot
        mention names."""
        items = _form_items(form, _DEFCONSTANT, 3)
        name = self._claim(items[1], taken)
        symbol = first_symbol(items[2])
        if symbol is not None:
            raise CompileError(
                f"{symbol.name!r} in a defconstant value, "
                "which is data and cannot hold names",
                symbol.offset,
            )
        self.constants[name] = items[2]
        return name

    def add_defmacro(self, form, taken=frozenset()):
        """Adds one (defmacro name params body) source form. The
        body compiles here, at declaration, in the macro world: its
        parameters, the macros declared before it, the operators,
        and the expression forms, but never the program's functions
        or constants, so each macro is a self-contained program.
        Later macros can therefore use earlier ones in their
        bodies, while calls in function bodies and the main body
        expand against every macro regardless of order. What an
        earlier macro splices in stays data when it resolves
        nowhere here, and resolves again wherever the compiled
        body's output finally lands."""
        items = _form_items(form, _DEFMACRO, 4)
        name = self._claim(items[1], taken)
        arity = _check_params(items[2])
        macro_defs = Definitions()
        macro_defs.macros = dict(self.macros)
        expanded = _expand(
            items[3],
            macro_defs,
            _symbol_names(items[2]),
            0,
            _ExpansionWork(strict=False),
        )
        compilation = _Compilation(macro_defs, {}, macro_name=name)
        program = compilation.expression(expanded, _bind_params(items[2], _TOP))
        self.macros[name] = (items[2], items[3], arity, program)
        return name


def _form_items(form, keyword, count):
    """The exactly-count items of a special form, head included."""
    items = []
    node = form
    while is_pair(node):
        items.append(node[0])
        node = node[1]
    if node != NIL or len(items) != count:
        raise CompileError(
            f"{keyword} takes {count - 1} parts: {_FORM_SHAPES[keyword]}"
        )
    return items


_FORM_SHAPES = {
    _DEFUN: "(defun name params body)",
    _DEFCONSTANT: "(defconstant name value)",
    _DEFMACRO: "(defmacro name params body)",
}


def declaration_keyword(tree):
    """The declaration keyword heading a source tree, or None."""
    if is_pair(tree) and isinstance(tree[0], Symbol):
        if tree[0].name in (_DEFUN, _DEFCONSTANT, _DEFMACRO):
            return tree[0].name
    return None


def _compose(parent, child):
    """The path reaching child within the subtree parent reaches."""
    return (child << (parent.bit_length() - 1)) | (
        parent & ((1 << (parent.bit_length() - 1)) - 1)
    )


def _bind_params(tree, root):
    """The name-to-path map a parameter tree induces at root."""
    bindings = {}
    stack = [(tree, root)]
    while stack:
        current, path = stack.pop()
        if isinstance(current, Symbol):
            bindings[current.name] = path
        elif is_pair(current):
            stack.append((current[0], _compose(path, _LEFT)))
            stack.append((current[1], _compose(path, _RIGHT)))
    return bindings


def _lower_symbols(tree):
    """The argument source as the value a macro runs over: every
    name becomes its spelling as an atom, exactly how the macro's
    own compiled body expects to read it."""
    if isinstance(tree, Symbol):
        return tree.name.encode()
    if is_pair(tree):
        return (_lower_symbols(tree[0]), _lower_symbols(tree[1]))
    return tree


def _name_spelling(atom):
    """The name an atom's bytes spell, or None when they spell no
    single reader-accepted name."""
    try:
        text = atom.decode()
    except UnicodeDecodeError:
        return None
    if text and text.isprintable() and definable(text):
        return text
    return None


def _lift(value, defs, shadowed, evidence, offset):
    """The value a macro returned, read back as one expression. An
    expression headed by the quote opcode passes through whole, its
    content data by construction, and the walk is expression
    directed so only a head position can mean quote: an argument
    whose value merely starts with the quote byte, like the number
    one, stays an ordinary argument.

    An atom whose bytes spell one name the reader would accept
    becomes a name when the name resolves where the call sits, the
    classic Chialisp rule, and also when it is in the evidence,
    the names the caller wrote in this call's own arguments. The
    second clause is a recorded divergence with a deliberately
    one-hop scope: this call's argument source is the only place
    the reader's provenance is still attached, so a misspelled
    argument reaches the resolver as a name and fails as the
    unknown name it is, exactly as the direct spelling would,
    where Chialisp reads it back as data and compiles the typo
    silently. Everything else is data, including names spelled
    only inside templates or inherited through other macros, whose
    provenance the VM boundary erased: computed bytes that spell
    an in-scope name resolve and capture, and stale spellings that
    resolve nowhere pass as data, the sharp edges Chialisp authors
    already know. Quote data that must stay data.

    evidence is None in the macro world, declaration-time
    expansion inside another macro's body, where what resolves
    lifts and the rest stays data, riding the compiled body out
    to the call sites where resolution happens against real
    scope.

    The lifted names carry the macro call's offset, so a
    downstream error points at the call site."""
    if is_pair(value):
        if is_atom(value[0]) and value[0] == _QUOTE:
            return value
        return (
            _lift(value[0], defs, shadowed, evidence, offset),
            _lift_tail(value[1], defs, shadowed, evidence, offset),
        )
    if value == NIL:
        return value
    text = _name_spelling(value)
    if text is None:
        return value
    if _resolvable(text, defs, shadowed):
        return Symbol(text, offset)
    if evidence is not None and text in evidence:
        return Symbol(text, offset)
    return value


def _resolvable(name, defs, shadowed):
    """True when a name means something where an expansion sits.
    This is the read-back's copy of the resolution domain that
    _reference and _named_form implement as control flow, and the
    two must cover the same names: a category added to one and not
    the other either turns valid names into silent data or valid
    data into spurious names."""
    return (
        name in shadowed
        or name in defs.functions
        or name in defs.constants
        or name in defs.macros
        or name in CONDITION_CONSTANTS
        or name in _EXPRESSION_FORMS
    )


def _lift_tail(node, defs, shadowed, evidence, offset):
    """An argument spine of a macro's returned value, each element
    lifted as an expression. The spine's own pairs never mean
    quote, whatever their first bytes are."""
    if not is_pair(node):
        return node
    return (
        _lift(node[0], defs, shadowed, evidence, offset),
        _lift_tail(node[1], defs, shadowed, evidence, offset),
    )


def _expand(tree, defs, shadowed, depth, work):
    """The source tree with every macro call replaced by what the
    macro's program computes over the raw, unevaluated argument
    source. The returned value is read back as source and expanded
    again, one depth level deeper, so a macro may emit calls to
    other macros or splice its own name back in, terminating by
    consuming its argument list. Quoted content is data and is
    never entered. A qq template is entered only through its
    unquote escapes. strict selects the read-back rule: the
    program world judges, the macro world defers, as _lift
    states."""
    if not is_pair(tree):
        return tree
    head, tail = tree
    if is_atom(head) and head == _QUOTE:
        return tree
    if isinstance(head, Symbol):
        if head.name == _QQ:
            return (head, _expand_template(tail, defs, shadowed, depth, work, 1))
        if head.name in defs.macros and head.name not in shadowed:
            return _expand_call(head, tail, defs, shadowed, depth, work)
    return (
        _expand(head, defs, shadowed, depth, work),
        _expand_tail(tail, defs, shadowed, depth, work),
    )


def _expand_tail(node, defs, shadowed, depth, work):
    """The argument spine of a form, each element expanded as an
    expression. The spine itself is never mistaken for a call, so
    a bare macro name sitting as an argument stays a name and gets
    the value-position error at emission."""
    if not is_pair(node):
        return node
    return (
        _expand(node[0], defs, shadowed, depth, work),
        _expand_tail(node[1], defs, shadowed, depth, work),
    )


def _expand_template(node, defs, shadowed, depth, work, level):
    """A qq template with its level-one unquote escapes expanded.
    A nested qq deepens the level, an unquote raises it back, and
    both are walked as data otherwise, mirroring how the template
    emits: this walk and _Compilation._template must locate the
    same escape positions on every tree, and a test holds them to
    it. Malformed escape arities pass through untouched here and
    are rejected once, at emission."""
    if not is_pair(node):
        return node
    head, tail = node
    if isinstance(head, Symbol):
        if head.name == _QQ:
            return (
                head,
                _expand_template(tail, defs, shadowed, depth, work, level + 1),
            )
        if head.name == _UNQUOTE:
            if level == 1:
                return (head, _expand_tail(tail, defs, shadowed, depth, work))
            return (
                head,
                _expand_template(tail, defs, shadowed, depth, work, level - 1),
            )
    return (
        _expand_template(head, defs, shadowed, depth, work, level),
        _expand_template(tail, defs, shadowed, depth, work, level),
    )


def _check_arity(name, arguments, arity, offset):
    """One arity check for calls and macro calls, so the two sites
    cannot drift apart in behavior or wording."""
    exact, count = arity
    if exact and len(arguments) != count:
        raise CompileError(
            f"{name!r} takes {count} argument(s), got {len(arguments)}", offset
        )
    if not exact and len(arguments) < count:
        raise CompileError(
            f"{name!r} takes at least {count} argument(s), got {len(arguments)}",
            offset,
        )


def _argument_names(node):
    """The names a caller wrote in a macro call's own arguments,
    the one place the reader's provenance is still attached when
    the expansion is read back. The walk is expression directed
    like the read-back itself: spine pairs never mean quote, and
    quoted content and qq templates are excluded, because their
    spellings are data to the read-back and must not vouch for
    output atoms."""
    names = set()

    def spine(node):
        while is_pair(node):
            element(node[0])
            node = node[1]
        if isinstance(node, Symbol):
            names.add(node.name)

    def element(expr):
        if isinstance(expr, Symbol):
            names.add(expr.name)
            return
        if not is_pair(expr):
            return
        head = expr[0]
        if is_atom(head) and head == _QUOTE:
            return
        if isinstance(head, Symbol) and head.name == _QQ:
            return
        element(head)
        spine(expr[1])

    spine(node)
    return names


def _expand_call(head, tail, defs, shadowed, depth, work):
    """One macro call replaced by its expansion."""
    name = head.name
    if depth == MACRO_DEPTH_LIMIT:
        raise CompileError(
            f"macro expansion depth exceeded {MACRO_DEPTH_LIMIT} levels",
            head.offset,
        )
    if work.remaining == 0:
        raise CompileError(
            f"macro expansion exceeded {MACRO_EXPANSION_LIMIT} executions",
            head.offset,
        )
    work.remaining -= 1
    arguments = _proper_items(tail, name, head.offset)
    _check_arity(name, arguments, defs.macros[name][2], head.offset)
    program = defs.macros[name][3]
    try:
        _, value = run(program, _lower_symbols(tail), MACRO_COST_BUDGET)
    except BitLispError as exc:
        raise CompileError(
            f"macro {name!r} failed: {exc.code}: {exc}", head.offset
        ) from None
    # Typo evidence: only what the caller wrote in this call, and
    # only in the program world. The macro world passes none.
    evidence = _argument_names(tail) if work.strict else None
    lifted = _lift(value, defs, shadowed, evidence, head.offset)
    return _expand(lifted, defs, shadowed, depth + 1, work)


def _expanded_bodies(defs, body, work, session_names):
    """The reachable function bodies, expanded, conservatively:
    every name a post-expansion body mentions counts, shadowing
    ignored, so the set can only be too large, never too small.
    Expansion must come first because a macro may emit a call to a
    function its source never names. An unreached body never
    expands and never compiles. The sweep runs in declaration
    order, restarting until no new body is reached, so which body
    an expansion error names is deterministic."""
    bodies = {}
    mentioned = _symbol_names(body)
    changed = True
    while changed:
        changed = False
        for name in defs.functions:
            if name in bodies or name not in mentioned:
                continue
            fn_params, fn_body, _ = defs.functions[name]
            shadow = _symbol_names(fn_params) | session_names
            try:
                expanded = _expand(fn_body, defs, shadow, 0, work)
            except CompileError as exc:
                raise CompileError(f"in {name!r}: {exc}") from None
            bodies[name] = expanded
            mentioned |= _symbol_names(expanded)
            changed = True
    return bodies


def _tree_paths(names, root):
    """Each name's path when the list is built as a balanced tree at
    root, the same split _build_tree makes."""
    paths = {}
    stack = [(names, root)]
    while stack:
        group, path = stack.pop()
        if len(group) == 1:
            paths[group[0]] = path
        else:
            half = len(group) // 2
            stack.append((group[:half], _compose(path, _LEFT)))
            stack.append((group[half:], _compose(path, _RIGHT)))
    return paths


def _build_tree(items):
    """The balanced tree over a nonempty item list, a single item
    sitting bare rather than wrapped in a pair."""
    if len(items) == 1:
        return items[0]
    half = len(items) // 2
    return (_build_tree(items[:half]), _build_tree(items[half:]))


def _proper_items(node, what, offset_hint=None):
    items = []
    while is_pair(node):
        items.append(node[0])
        node = node[1]
    if node != NIL and not isinstance(node, Symbol):
        raise CompileError(f"{what} takes a proper argument list", offset_hint)
    if isinstance(node, Symbol):
        raise CompileError(f"{what} takes a proper argument list", node.offset)
    return items


def _quote(node):
    return (_QUOTE, node)


def _proper_list(*nodes):
    result = NIL
    for node in reversed(nodes):
        result = (node, result)
    return result


class _Compilation:
    """One compile: the definitions, the function paths, and the
    reachable set, shared by the main body and every function body.
    macro_name is set only when the body being compiled is a
    macro's own, where macro names quote themselves as spellings so
    a template can splice them back into emitted source."""

    def __init__(self, defs, fn_paths, macro_name=None):
        self.defs = defs
        self.fn_paths = fn_paths
        self.macro_name = macro_name

    def expression(self, expr, bindings):
        if isinstance(expr, Symbol):
            return self._reference(expr, bindings)
        if is_atom(expr):
            # Atoms quote themselves. Nil is the one atom whose path
            # lookup already yields its own value, so it goes out
            # bare, one byte instead of two.
            if expr == NIL:
                return NIL
            return _quote(expr)
        head, tail = expr
        if isinstance(head, Symbol):
            return self._named_form(head, tail, bindings)
        if is_pair(head):
            raise CompileError("expression in operator position")
        if head == _QUOTE:
            symbol = first_symbol(tail)
            if symbol is not None:
                raise CompileError(
                    f"{symbol.name!r} in quoted content, "
                    "which is data and cannot hold names",
                    symbol.offset,
                )
            return expr
        return self._operator(head, tail, bindings)

    def _reference(self, symbol, bindings):
        name = symbol.name
        if name in bindings:
            return int_to_atom(bindings[name])
        if name in self.defs.constants:
            # A constant's value was checked symbol-free at its
            # definition, so the stored tree is already a node.
            return _quote(self.defs.constants[name])
        if name in CONDITION_CONSTANTS:
            return _quote(CONDITION_CONSTANTS[name])
        if name in self.defs.functions:
            raise CompileError(f"function {name!r} used as a value", symbol.offset)
        if name in self.defs.macros or name == self.macro_name:
            if self.macro_name is not None:
                # In a macro body a macro's name is its spelling,
                # so a template can cons it onto a shortened
                # argument list and splice the call back into the
                # emitted source, its own name included.
                return _quote(name.encode())
            raise CompileError(f"macro {name!r} used as a value", symbol.offset)
        raise CompileError(f"unknown name {name!r}", symbol.offset)

    def _named_form(self, head, tail, bindings):
        name = head.name
        if name == _IF:
            return self._if(head, tail, bindings)
        if name == _LIST:
            return self._list(head, tail, bindings)
        if name == _QQ:
            return self._qq(head, tail, bindings)
        if name == _UNQUOTE:
            raise CompileError("unquote outside a qq template", head.offset)
        if name in (_PROGRAM, _DEFUN, _DEFCONSTANT, _DEFMACRO):
            raise CompileError(f"{name} form is not an expression", head.offset)
        if name in bindings:
            raise CompileError(f"{name!r} is a parameter, not a function", head.offset)
        if name in self.defs.functions:
            return self._call(head, tail, bindings)
        if name == self.macro_name:
            raise CompileError(
                f"macro {name!r} cannot be called inside its own body", head.offset
            )
        if name in self.defs.constants or name in CONDITION_CONSTANTS:
            raise CompileError(f"{name!r} is a constant, not a function", head.offset)
        raise CompileError(f"unknown name {name!r}", head.offset)

    def _if(self, head, tail, bindings):
        items = _proper_items(tail, _IF, head.offset)
        if len(items) != 3:
            raise CompileError("if takes a condition and two branches", head.offset)
        condition, then_branch, else_branch = (
            self.expression(item, bindings) for item in items
        )
        # The VM's i evaluates all three arguments, so the branches
        # travel quoted and apply runs only the selected one in the
        # unchanged environment, path 1.
        selector = _proper_list(
            _IF_OP, condition, _quote(then_branch), _quote(else_branch)
        )
        return _proper_list(_APPLY, selector, int_to_atom(_TOP))

    def _list(self, head, tail, bindings):
        items = _proper_items(tail, _LIST, head.offset)
        result = NIL
        for item in reversed(items):
            result = _proper_list(_CONS, self.expression(item, bindings), result)
        return result

    def _qq(self, head, tail, bindings):
        items = _proper_items(tail, _QQ, head.offset)
        if len(items) != 1:
            raise CompileError("qq takes 1 part: (qq template)", head.offset)
        return self._template(items[0], bindings, 1)

    def _template(self, node, bindings, level):
        # A template emits code that builds itself as data: names
        # become their spellings, atoms quote, pairs cons. A nested
        # qq deepens the level and is rebuilt as data, an unquote
        # raises it back, and only a level-one unquote escapes to
        # an ordinary compiled expression.
        if isinstance(node, Symbol):
            return _quote(node.name.encode())
        if is_atom(node):
            if node == NIL:
                return NIL
            return _quote(node)
        nhead, ntail = node
        if isinstance(nhead, Symbol) and nhead.name == _QQ:
            return _proper_list(
                _CONS,
                _quote(nhead.name.encode()),
                self._template(ntail, bindings, level + 1),
            )
        if isinstance(nhead, Symbol) and nhead.name == _UNQUOTE:
            if level == 1:
                items = _proper_items(ntail, _UNQUOTE, nhead.offset)
                if len(items) != 1:
                    raise CompileError(
                        "unquote takes 1 part: (unquote expression)", nhead.offset
                    )
                return self.expression(items[0], bindings)
            return _proper_list(
                _CONS,
                _quote(nhead.name.encode()),
                self._template(ntail, bindings, level - 1),
            )
        return _proper_list(
            _CONS,
            self._template(nhead, bindings, level),
            self._template(ntail, bindings, level),
        )

    def _call(self, head, tail, bindings):
        name = head.name
        arguments = _proper_items(tail, name, head.offset)
        _check_arity(name, arguments, self.defs.functions[name][2], head.offset)
        # The callee sees the caller's layout rebuilt: the function
        # tree it received at path 2, consed onto the evaluated
        # arguments as a proper list.
        argument_list = NIL
        for argument in reversed(arguments):
            argument_list = _proper_list(
                _CONS, self.expression(argument, bindings), argument_list
            )
        environment = _proper_list(_CONS, int_to_atom(_LEFT), argument_list)
        return _proper_list(_APPLY, int_to_atom(self.fn_paths[name]), environment)

    def _operator(self, op, tail, bindings):
        # Reserved opcodes are rejected too: they raise at run time
        # by design, so accepting one here would compile a program
        # that can never do anything but fail.
        if op != _APPLY and op not in OPERATORS:
            label = "0x" + op.hex() if op else "()"
            # A macro can emit computed bytes that spell a name,
            # which stay data and can land here as head bytes, so
            # the error spells what a reader would see in the hex.
            text = _name_spelling(op)
            if text is not None:
                label = f"{label}, which spells {text!r}"
            raise CompileError(f"unknown operator {label}")
        name = ATOM_TO_NAME[op]
        arguments = _proper_items(tail, name)
        compiled = [self.expression(argument, bindings) for argument in arguments]
        return (op, _proper_list(*compiled))


def tree_hash(node):
    """The sha256 tree hash of a node, exactly as the sha256tree
    operator computes it: leaves hash 0x01 plus the atom, pairs hash
    0x02 plus both child hashes."""
    hashes = []
    stack = [(False, node)]
    while stack:
        combine, current = stack.pop()
        if combine:
            first = hashes.pop()
            rest = hashes.pop()
            hashes.append(hashlib.sha256(b"\x02" + first + rest).digest())
        elif is_pair(current):
            stack.append((True, None))
            stack.append((False, current[0]))
            stack.append((False, current[1]))
        else:
            hashes.append(hashlib.sha256(b"\x01" + current).digest())
    return hashes[0]


def _compile(defs, params, body, session_names=frozenset()):
    """The program node and symbol table for one body against one
    definitions space, params None for a bare expression.
    session_names are the REPL's def bindings, folded into the
    resolution shadow: any macro output atom spelling one becomes
    a name and fails as unknown, however it arose, because the
    raw path reads that spelling as the binding and one spelling
    must never mean two things. Resolution-side, the rule holds
    through macro composition for free."""
    shadow = _symbol_names(params) if params is not None else frozenset()
    shadow = shadow | session_names
    work = _ExpansionWork()
    body = _expand(body, defs, shadow, 0, work)
    expanded = _expanded_bodies(defs, body, work, session_names)
    fn_names = [name for name in defs.functions if name in expanded]
    has_tree = bool(fn_names)
    fn_paths = _tree_paths(fn_names, _LEFT) if has_tree else {}
    compilation = _Compilation(defs, fn_paths)

    main_bindings = {}
    if params is not None:
        main_bindings = _bind_params(params, _RIGHT if has_tree else _TOP)
    main = compilation.expression(body, main_bindings)

    table = {"functions": {}, "main_params": params}
    bodies = []
    for name in fn_names:
        fn_params, _, _ = defs.functions[name]
        try:
            compiled = compilation.expression(
                expanded[name], _bind_params(fn_params, _RIGHT)
            )
        except CompileError as exc:
            # A body compiles when a program reaches it, which in
            # the REPL is a later line than the one that declared
            # it, so the error names whose text the offset indexes.
            raise CompileError(f"in {name!r}: {exc}") from None
        bodies.append(compiled)
        if is_pair(compiled):
            table["functions"].setdefault(tree_hash(compiled).hex(), (name, fn_params))

    if not has_tree:
        return main, table
    program = _proper_list(
        _APPLY,
        _quote(main),
        _proper_list(_CONS, _quote(_build_tree(bodies)), int_to_atom(_TOP)),
    )
    return program, table


def program_form(tree):
    """True when a source tree is a (program ...) form."""
    return is_pair(tree) and isinstance(tree[0], Symbol) and tree[0].name == _PROGRAM


def compile_program(source):
    """The program node and symbol table for one self-contained
    (program params declaration* body) form, given as text or as a
    parsed source tree. Session definitions are invisible on
    purpose: what compiles from a file compiles identically pasted."""
    tree = parse_source(source) if isinstance(source, str) else source
    if not program_form(tree):
        raise CompileError("input must be a (program ...) form")
    items = _proper_items(tree[1], _PROGRAM, tree[0].offset)
    if len(items) < 2:
        raise CompileError(
            "program takes parameters, declarations, and one body",
            tree[0].offset,
        )
    params = items[0]
    _check_params(params)
    defs = Definitions()
    for declaration in items[1:-1]:
        keyword = declaration_keyword(declaration)
        if keyword == _DEFUN:
            defs.add_defun(declaration)
        elif keyword == _DEFCONSTANT:
            defs.add_defconstant(declaration)
        elif keyword == _DEFMACRO:
            defs.add_defmacro(declaration)
        else:
            raise CompileError("expected defun, defconstant, or defmacro")
    return _compile(defs, params, items[-1])


def compile_expression(source, defs, session_names=frozenset()):
    """The program node and symbol table for one bare expression
    against a definitions space. The expression has no parameters,
    so the compiled program ignores its environment. session_names
    are the caller's bindings outside the language, the REPL's def
    names, barred from macro output. A program form ignores them,
    staying self-contained."""
    tree = parse_source(source) if isinstance(source, str) else source
    if program_form(tree):
        return compile_program(tree)
    return _compile(defs, None, tree, session_names)


def bind_values(params, env):
    """The name-to-value map when env is a call-time environment,
    (function tree . arguments), or None where the shapes disagree.
    Display-side: the debugger names a function's live arguments."""
    if not is_pair(env):
        return None
    bindings = {}
    stack = [(params, env[1])]
    while stack:
        tree, value = stack.pop()
        if isinstance(tree, Symbol):
            bindings[tree.name] = value
        elif is_pair(tree):
            if not is_pair(value):
                return None
            # Right pushed first so the left name pops first and the
            # map iterates in declaration order.
            stack.append((tree[1], value[1]))
            stack.append((tree[0], value[0]))
        elif tree == NIL and value != NIL:
            return None
    return bindings


def symbols_to_json(table):
    """The bitlisp-sym-v0 object for a program's symbol table. Only
    a program form has one to write: a bare expression declares no
    parameters."""
    if table["main_params"] is None:
        raise ValueError("only a compiled program form has a symbol file")
    return {
        "schema": SYMBOLS_SCHEMA,
        "functions": {
            key: {"name": name, "params": source_text(params)}
            for key, (name, params) in table["functions"].items()
        },
        "main_params": source_text(table["main_params"]),
    }


def load_symbols(data):
    """The functions map of a bitlisp-sym-v0 object, validated
    closed: unknown keys, malformed hashes, and parameter text that
    is not a parameter tree are all rejected."""
    if not isinstance(data, dict) or set(data) != {
        "schema",
        "functions",
        "main_params",
    }:
        raise ValueError("symbol file must hold schema, functions, main_params")
    if data["schema"] != SYMBOLS_SCHEMA:
        raise ValueError(f"symbol file schema is not {SYMBOLS_SCHEMA}")
    if not isinstance(data["main_params"], str):
        raise ValueError("main_params must be a string")
    _loaded_params(data["main_params"])
    if not isinstance(data["functions"], dict):
        raise ValueError("functions must be an object")
    functions = {}
    for key, entry in data["functions"].items():
        if len(key) != 64 or set(key) - set("0123456789abcdef"):
            raise ValueError(f"malformed tree hash {key!r}")
        if not isinstance(entry, dict) or set(entry) != {"name", "params"}:
            raise ValueError("a function entry holds name and params")
        if not isinstance(entry["name"], str) or not isinstance(entry["params"], str):
            raise ValueError("a function entry holds two strings")
        if (
            not definable(entry["name"])
            or not entry["name"].isprintable()
            or entry["name"] in RESERVED_WORDS
            or entry["name"] in CONDITION_CONSTANTS
        ):
            # The file is untrusted input and its names land in the
            # debugger display, so a name must be a spelling the
            # compiler accepts for a function, narrowed further to
            # printable characters: definable alone would pass
            # every control and format character the reader's
            # four-character whitespace set does not claim, and a
            # terminal obeys those.
            raise ValueError(f"malformed function name {entry['name']!r}")
        functions[key] = (entry["name"], _loaded_params(entry["params"]))
    return functions


def _loaded_params(text):
    """A parameter tree from symbol-file text, every rejection a
    ValueError: the file is input, not source."""
    try:
        params = parse_source(text)
        _check_params(params)
    except (ParseError, CompileError) as exc:
        raise ValueError(f"malformed params {text!r}: {exc}") from None
    return params
