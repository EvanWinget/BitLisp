"""Compiler: v0 authoring language to program trees.

The language is the text syntax plus bare names. A name is anything
the reader would reject as an unknown symbol, so strings, hex,
operator names, and decimals keep exactly their raw meaning and the
language occupies only text that previously errored. Atoms quote
themselves, names resolve to environment paths or inline constant
values, and the special forms are program, defun, defun-inline,
defconstant, include, if, list, list*, assert, and, and or.
Everything
else a source expression can say is an operator application.

A compiled program's environment is the pair (function tree . args).
The function tree holds every reachable function body, balanced in
declaration order, and a call site rebuilds the layout by consing
the tree it received onto its evaluated arguments, so recursion and
mutual recursion need no further machinery. A program whose body
reaches no function is emitted bare with its arguments at the
environment root. Constants never enter the tree: a defconstant
value compiles and runs on the reference VM at its declaration,
budgeted, and a constant reference inlines the computed value as a
quoted literal at the use site.

There are no source-to-source rewrites. Emission is direct, with
one size-only exception: a nil literal is emitted as the nil atom,
whose path lookup yields nil, one byte instead of the two a quoted
nil takes.

Parsing and every other tree walk here are iterative. Code
emission recurses with the source's nesting depth, a bound
accepted because source is authored rather than attacker-supplied:
past the interpreter's limit every surface reports unusable input,
exit 2, never a crash or a wrong artifact.

The compiler also builds a symbol table for the debugger: the tree
hash of each compiled function body, keyed exactly as the VM's
sha256tree operator hashes, mapped to the function's name and
parameter names. Atom bodies stay out of the table, because an atom
is not distinguishable from ordinary data by its hash.
"""

import hashlib
import os

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
_FIRST = b"\x05"
_REST = b"\x06"
_RAISE = b"\x08"

# The environment root, its first child, and its rest child, as the
# VM's path lookup numbers them.
_TOP, _LEFT, _RIGHT = 1, 2, 3

(
    _PROGRAM,
    _DEFUN,
    _DEFUN_INLINE,
    _DEFCONSTANT,
    _INCLUDE,
    _IF,
    _LIST,
    _LIST_STAR,
    _ASSERT,
    _AND,
    _OR,
) = (
    "program",
    "defun",
    "defun-inline",
    "defconstant",
    "include",
    "if",
    "list",
    "list*",
    "assert",
    "and",
    "or",
)
RESERVED_WORDS = frozenset(
    {
        _PROGRAM,
        _DEFUN,
        _DEFUN_INLINE,
        _DEFCONSTANT,
        _INCLUDE,
        _IF,
        _LIST,
        _LIST_STAR,
        _ASSERT,
        _AND,
        _OR,
    }
)

# The declaration heads a program form accepts, the one tuple the
# REPL's line dispatch reads too, so the two surfaces cannot drift.
DECLARATION_KEYWORDS = (_DEFUN, _DEFUN_INLINE, _DEFCONSTANT, _INCLUDE)

# How deep inline calls may nest inside inline bodies before the
# compiler rejects the program: recursion needs the function tree,
# which is what defun is for.
INLINE_DEPTH_LIMIT = 100

# How many structural nodes one inline expansion may emit. The
# depth cap alone cannot bound size: a chain of doubling inlines
# squares its tree per declaration while nesting only linearly, so
# the size cap is what turns that into a compile error instead of
# an artifact too large to serialize.
INLINE_SIZE_LIMIT = 1_000_000


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
    "ASSERT_MY_TAPTREE",
    "ANNOUNCE",
    "ASSERT_ANNOUNCEMENT",
    "ASSURE",
    "REQUIRE",
    "RESERVE_FEE",
    "SEAL",
    "SEAL_OUTPUTS",
)
CONDITION_CONSTANTS = {
    name: int_to_atom(getattr(conditions, name)) for name in CONDITION_NAMES
}

SYMBOLS_SCHEMA = "bitlisp-sym-v0"

# The inclusive budget a defconstant value evaluates under, the
# runner's default spend budget, so compile-time evaluation can
# never outrun what a spend could.
CONSTANT_COST_BUDGET = 11_000_000_000


class CompileError(Exception):
    """Source that reads as an s-expression but is not a valid program."""

    def __init__(self, message, offset=None):
        super().__init__(message if offset is None else f"{message} at offset {offset}")
        self.offset = offset
        # True once an inline frame has named this error, so outer
        # frames pass it through instead of stacking prefixes.
        self.inline_named = False


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


def constant_text(value):
    """The declaration spelling of a computed constant value: an
    atom is its own spelling, a pair re-reads as the same value
    only quoted."""
    if is_pair(value):
        return source_text((_QUOTE, value))
    return source_text(value)


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
    """The compile-time namespace: functions and constants by name.

    A name is claimed once across functions, constants, the
    condition constants, the reserved words, and any caller-supplied
    taken set, so one spelling can never mean two things.
    """

    def __init__(self):
        self.functions = {}
        self.inlines = {}
        self.constants = {}

    def _claim(self, symbol, taken):
        name = _check_name(symbol, "definition")
        if (
            name in self.functions
            or name in self.inlines
            or name in self.constants
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

    def add_defun_inline(self, form, taken=frozenset()):
        """Adds one (defun-inline name params body) source form.
        The body is stored as written and splices at each call site
        a program reaches, never entering the function tree."""
        items = _form_items(form, _DEFUN_INLINE, 4)
        name = self._claim(items[1], taken)
        arity = _check_params(items[2])
        self.inlines[name] = (items[2], items[3], arity)
        return name

    def add_defconstant(self, form, taken=frozenset()):
        """Adds one (defconstant name value) source form. The value
        compiles against the declarations already made and runs on
        the reference VM now, under CONSTANT_COST_BUDGET, so a
        constant holds computed data and sees only what is declared
        above it. Declaration order matters for constants alone."""
        items = _form_items(form, _DEFCONSTANT, 3)
        name = self._claim(items[1], taken)
        try:
            program, _ = _compile(self, None, items[2])
            _, value = run(program, NIL, CONSTANT_COST_BUDGET)
        except CompileError as exc:
            raise CompileError(f"in {name!r}: {exc}") from None
        except BitLispError as exc:
            raise CompileError(
                f"in {name!r}: the value raised {exc.code}: {exc}"
            ) from None
        self.constants[name] = value
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
    _DEFUN_INLINE: "(defun-inline name params body)",
    _DEFCONSTANT: "(defconstant name value)",
    _INCLUDE: '(include "file")',
}


def declaration_keyword(tree):
    """The declaration keyword heading a source tree, or None."""
    if is_pair(tree) and isinstance(tree[0], Symbol):
        if tree[0].name in DECLARATION_KEYWORDS:
            return tree[0].name
    return None


def _compose(parent, child):
    """The path reaching child within the subtree parent reaches."""
    return (child << (parent.bit_length() - 1)) | (
        parent & ((1 << (parent.bit_length() - 1)) - 1)
    )


def _bind_params(tree, root):
    """The name-to-node map a parameter tree induces at root, each
    name bound to its environment path atom."""
    bindings = {}
    stack = [(tree, root)]
    while stack:
        current, path = stack.pop()
        if isinstance(current, Symbol):
            bindings[current.name] = int_to_atom(path)
        elif is_pair(current):
            stack.append((current[0], _compose(path, _LEFT)))
            stack.append((current[1], _compose(path, _RIGHT)))
    return bindings


def _bind_inline_params(params, arguments):
    """The name-to-node map an inline call induces: each parameter
    name binds its argument's compiled expression, a destructured
    name reaching its component through first and rest steps over
    that expression, and a tail name binding the remaining
    arguments as a built list. Every reference re-emits its node,
    the call-by-name contract: used twice evaluates twice, unused
    never evaluates."""
    bindings = {}
    stack = []
    spine = params
    index = 0
    while is_pair(spine):
        stack.append((spine[0], arguments[index]))
        index += 1
        spine = spine[1]
    if isinstance(spine, Symbol):
        rest = NIL
        for argument in reversed(arguments[index:]):
            rest = _proper_list(_CONS, argument, rest)
        bindings[spine.name] = rest
    while stack:
        tree, node = stack.pop()
        if isinstance(tree, Symbol):
            bindings[tree.name] = node
        elif is_pair(tree):
            stack.append((tree[0], _proper_list(_FIRST, node)))
            stack.append((tree[1], _proper_list(_REST, node)))
    return bindings


def _check_arity(name, arguments, arity, offset):
    """The one arity check every call site shares, so wording and
    behavior cannot drift apart."""
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


def _reachable_names(defs, body):
    """The functions a body can reach, conservatively: every
    mentioned name counts, shadowing ignored, so the set can only
    be too large, never too small. An inline body's mentions count
    through the inline, because its splice will reference them. An
    unreached body never compiles, so an error inside one surfaces
    the first time a program reaches it."""
    reachable = set()
    walked_inlines = set()
    pending = _symbol_names(body)
    while pending:
        name = pending.pop()
        if name in defs.functions and name not in reachable:
            reachable.add(name)
            pending |= _symbol_names(defs.functions[name][1])
        elif name in defs.inlines and name not in walked_inlines:
            walked_inlines.add(name)
            pending |= _symbol_names(defs.inlines[name][1])
    return reachable


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


def _lazy_if(condition, then_branch, else_branch):
    """The lazy branch idiom every branching form compiles through.
    The VM's i evaluates all three arguments, so the branches
    travel quoted and apply runs only the selected one in the
    unchanged environment, path 1."""
    selector = _proper_list(_IF_OP, condition, _quote(then_branch), _quote(else_branch))
    return _proper_list(_APPLY, selector, int_to_atom(_TOP))


# The two constant nodes the branching forms share. Emitted trees
# are immutable, so one node can sit in many outputs, and building
# each once makes the byte identity of single-operand and and or
# structural rather than coincidental.
_TRUE = _quote(int_to_atom(1))
_RAISE_CALL = _proper_list(_RAISE)


def _inline_error(name, message, offset=None):
    """A CompileError already carrying its inline frame's name, so
    outer frames pass it through."""
    error = CompileError(f"in {name!r}: {message}", offset)
    error.inline_named = True
    return error


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


class _Compilation:
    """One compile: the definitions and the function paths, shared
    by the main body and every function body."""

    def __init__(self, defs, fn_paths):
        self.defs = defs
        self.fn_paths = fn_paths
        self.inline_depth = 0
        # The size memo maps node ids to structural sizes, and the
        # measured list keeps every memoized node alive so a
        # recycled id can never alias a new node.
        self.node_sizes = {}
        self.measured_nodes = []

    def _node_size(self, node):
        """Structural node count of an emitted tree, memoized
        across the shared subtrees splicing creates, so measuring
        costs one visit per distinct node."""
        sizes = self.node_sizes
        stack = [node]
        while stack:
            current = stack.pop()
            key = id(current)
            if key in sizes:
                continue
            if not is_pair(current):
                sizes[key] = 1
                self.measured_nodes.append(current)
                continue
            left_key, right_key = id(current[0]), id(current[1])
            if left_key in sizes and right_key in sizes:
                sizes[key] = 1 + sizes[left_key] + sizes[right_key]
                self.measured_nodes.append(current)
            else:
                stack.append(current)
                stack.append(current[0])
                stack.append(current[1])
        return sizes[id(node)]

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
            return bindings[name]
        if name in self.defs.constants:
            # A constant's value was computed at its declaration,
            # so the stored tree is a plain node.
            return _quote(self.defs.constants[name])
        if name in CONDITION_CONSTANTS:
            return _quote(CONDITION_CONSTANTS[name])
        if name in self.defs.functions or name in self.defs.inlines:
            raise CompileError(f"function {name!r} used as a value", symbol.offset)
        raise CompileError(f"unknown name {name!r}", symbol.offset)

    def _named_form(self, head, tail, bindings):
        name = head.name
        if name == _IF:
            return self._if(head, tail, bindings)
        if name == _LIST:
            return self._list(head, tail, bindings)
        if name == _LIST_STAR:
            return self._list_star(head, tail, bindings)
        if name == _ASSERT:
            return self._assert(head, tail, bindings)
        if name == _AND:
            return self._and(head, tail, bindings)
        if name == _OR:
            return self._or(head, tail, bindings)
        if name in (_PROGRAM, _DEFUN, _DEFUN_INLINE, _DEFCONSTANT, _INCLUDE):
            raise CompileError(f"{name} form is not an expression", head.offset)
        if name in bindings:
            raise CompileError(f"{name!r} is a parameter, not a function", head.offset)
        if name in self.defs.inlines:
            return self._inline_call(head, tail, bindings)
        if name in self.defs.functions:
            return self._call(head, tail, bindings)
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
        return _lazy_if(condition, then_branch, else_branch)

    def _list(self, head, tail, bindings):
        items = _proper_items(tail, _LIST, head.offset)
        result = NIL
        for item in reversed(items):
            result = _proper_list(_CONS, self.expression(item, bindings), result)
        return result

    def _list_star(self, head, tail, bindings):
        # The last argument is the tail the others cons onto, so
        # the built list ends in it instead of nil, and a lone
        # tail compiles bare.
        items = _proper_items(tail, _LIST_STAR, head.offset)
        if not items:
            raise CompileError("list* takes items and a final tail", head.offset)
        compiled = [self.expression(item, bindings) for item in items]
        result = compiled[-1]
        for item in reversed(compiled[:-1]):
            result = _proper_list(_CONS, item, result)
        return result

    def _assert(self, head, tail, bindings):
        items = _proper_items(tail, _ASSERT, head.offset)
        if not items:
            raise CompileError("assert takes conditions and a final value", head.offset)
        compiled = [self.expression(item, bindings) for item in items]
        # A falsy condition selects the raise, so nothing after it
        # evaluates and the spend fails there.
        result = compiled[-1]
        for condition in reversed(compiled[:-1]):
            result = _lazy_if(condition, result, _RAISE_CALL)
        return result

    def _and(self, head, tail, bindings):
        items = _proper_items(tail, _AND, head.offset)
        # The result is boolean, 1 or nil, never an operand's
        # value, and the first falsy operand ends evaluation.
        result = _TRUE
        compiled = [self.expression(item, bindings) for item in items]
        for condition in reversed(compiled):
            result = _lazy_if(condition, result, NIL)
        return result

    def _or(self, head, tail, bindings):
        items = _proper_items(tail, _OR, head.offset)
        # 1 at the first truthy operand, which ends evaluation, nil
        # when every operand is falsy.
        result = NIL
        compiled = [self.expression(item, bindings) for item in items]
        for condition in reversed(compiled):
            result = _lazy_if(condition, _TRUE, result)
        return result

    def _inline_call(self, head, tail, bindings):
        """The body compiled at the call site, parameter references
        replaced by the arguments' compiled expressions. Nothing
        enters the function tree: an inline call pays no apply and
        no path lookup. The depth cap makes an inline calling
        itself a compile error rather than a hang, and the size cap
        does the same for expansions that multiply a tree per level
        while nesting only a little."""
        name = head.name
        arguments = _proper_items(tail, name, head.offset)
        _check_arity(name, arguments, self.defs.inlines[name][2], head.offset)
        params, body, _ = self.defs.inlines[name]
        compiled = [self.expression(argument, bindings) for argument in arguments]
        self.inline_depth += 1
        try:
            if self.inline_depth > INLINE_DEPTH_LIMIT:
                raise _inline_error(
                    name,
                    f"inline expansion exceeds {INLINE_DEPTH_LIMIT} levels",
                    head.offset,
                )
            try:
                result = self.expression(body, _bind_inline_params(params, compiled))
            except CompileError as exc:
                # One wrap, at the innermost inline frame, so the
                # error names the function whose declaring text the
                # offset indexes, and every outer frame passes it
                # through instead of stacking prefixes.
                if exc.inline_named:
                    raise
                raise _inline_error(name, str(exc)) from None
            if self._node_size(result) > INLINE_SIZE_LIMIT:
                raise _inline_error(
                    name,
                    f"inline expansion exceeds {INLINE_SIZE_LIMIT} nodes",
                    head.offset,
                )
            return result
        finally:
            self.inline_depth -= 1

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
            # An authored string or hex atom in head position can
            # spell a name, so the error shows what a reader would
            # see in the hex.
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


def _compile(defs, params, body):
    """The program node and symbol table for one body against one
    definitions space, params None for a bare expression."""
    reachable = _reachable_names(defs, body)
    fn_names = [name for name in defs.functions if name in reachable]
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
        fn_params, fn_body, _ = defs.functions[name]
        try:
            compiled = compilation.expression(fn_body, _bind_params(fn_params, _RIGHT))
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


def _include_name(form):
    """The file name one (include "file") form names. The name is a
    string atom: a bare name would answer to the namespace rules,
    and nothing else spells a file. The name may carry subdirectory
    components under an include directory, and a name that is
    absolute or climbs out of its directory is rejected, so the
    search path is the whole resolution story."""
    items = _form_items(form, _INCLUDE, 2)
    atom = items[1]
    if isinstance(atom, Symbol):
        raise CompileError(
            f"include takes a quoted file name, got the bare name {atom.name!r}",
            atom.offset,
        )
    if is_pair(atom):
        raise CompileError("include takes a quoted file name")
    try:
        name = atom.decode()
    except UnicodeDecodeError:
        raise CompileError("include takes a quoted file name") from None
    if not name or not name.isprintable():
        raise CompileError("include takes a quoted file name")
    if os.path.isabs(name) or os.path.normpath(name).split(os.sep)[0] == os.pardir:
        raise CompileError(
            f'include file "{name}" must be a relative path inside the include path'
        )
    return name


def _resolve_include(name, include_paths, offset):
    """The first include directory holding name, in search-path
    order. The search path is explicit: no implicit current
    directory, so where a program compiles never changes what it
    includes."""
    if not include_paths:
        raise CompileError(
            f'include file "{name}" not found: the include search path is empty',
            offset,
        )
    for directory in include_paths:
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            return path
    raise CompileError(f'include file "{name}" not found on the include path', offset)


def _include_items(path, name):
    """The declaration items of one include file: exactly one
    parenthesized list of declarations and nothing after it, so a
    file reads whole or not at all."""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise CompileError(f'include file "{name}": {exc}') from None
    if text.startswith("\ufeff"):
        raise CompileError(f'include file "{name}" starts with a byte-order mark')
    try:
        forms = parse_source_many(text)
    except ParseError as exc:
        raise CompileError(f'in include "{name}": {exc}') from None
    if len(forms) != 1 or not (is_pair(forms[0]) or forms[0] == NIL):
        raise CompileError(f'include file "{name}" must hold one declaration list')
    items = []
    node = forms[0]
    while is_pair(node):
        items.append(node[0])
        node = node[1]
    if node != NIL:
        raise CompileError(f'include file "{name}" must hold one declaration list')
    return items


# The splice stack's marker for a finished file, popping its chain
# entry.
_INCLUDE_END = object()


def _spliced(declarations, include_paths, loaded=None):
    """Declaration and origin pairs with every include resolved
    depth first in place, origin naming the include file a
    declaration came from, None for the program's own text. A file
    loads once per loaded set, identified by its stat identity so
    aliased spellings of one file cannot load it twice: a repeat
    include is skipped where the names would otherwise collide, and
    an include chain reaching a file still being spliced is a
    cycle, an error naming the chain. A caller passing its own
    loaded set widens the load-once scope, the REPL to its
    session."""
    result = []
    if loaded is None:
        loaded = set()
    chain = []
    stack = [(declaration, None) for declaration in reversed(declarations)]
    while stack:
        declaration, origin = stack.pop()
        if declaration is _INCLUDE_END:
            chain.pop()
            continue
        if declaration_keyword(declaration) != _INCLUDE:
            result.append((declaration, origin))
            continue
        try:
            name = _include_name(declaration)
            offset = declaration[0].offset if origin is None else None
            path = _resolve_include(name, include_paths, offset)
            stat = os.stat(path)
        except CompileError as exc:
            if origin is None:
                raise
            raise CompileError(f'in include "{origin}": {exc}') from None
        except OSError as exc:
            raise CompileError(f'include file "{name}": {exc}') from None
        identity = (stat.st_dev, stat.st_ino)
        if any(identity == seen for seen, _ in chain):
            names = [seen_name for _, seen_name in chain]
            names = names[
                next(i for i, (seen, _) in enumerate(chain) if seen == identity) :
            ]
            raise CompileError("include cycle: " + " includes ".join([*names, name]))
        if identity in loaded:
            continue
        loaded.add(identity)
        chain.append((identity, name))
        stack.append((_INCLUDE_END, None))
        for item in reversed(_include_items(path, name)):
            stack.append((item, name))
    return result


def included_declarations(form, include_paths, loaded=None):
    """The declaration and origin pairs one (include "file") form
    splices, nested includes resolved, for a caller that holds its
    own namespace, the REPL's session declarations. Passing a
    loaded set carries the load-once scope across calls."""
    return _spliced([form], include_paths, loaded)


def compile_program(source, include_paths=()):
    """The program node and symbol table for one self-contained
    (program params declaration* body) form, given as text or as a
    parsed source tree. Session definitions are invisible on
    purpose, and include files resolve only through include_paths,
    first match winning: what compiles from a file compiles
    identically pasted anywhere the search path is the same."""
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
    for declaration, origin in _spliced(items[1:-1], include_paths):
        keyword = declaration_keyword(declaration)
        try:
            if keyword == _DEFUN:
                defs.add_defun(declaration)
            elif keyword == _DEFUN_INLINE:
                defs.add_defun_inline(declaration)
            elif keyword == _DEFCONSTANT:
                defs.add_defconstant(declaration)
            else:
                raise CompileError(
                    "expected defun, defun-inline, defconstant, or include"
                )
        except CompileError as exc:
            # An included declaration's offsets index its own file's
            # text, so the error names the file, as a function body's
            # error names the function.
            if origin is None:
                raise
            raise CompileError(f'in include "{origin}": {exc}') from None
    return _compile(defs, params, items[-1])


def compile_expression(source, defs, include_paths=()):
    """The program node and symbol table for one bare expression
    against a definitions space. The expression has no parameters,
    so the compiled program ignores its environment. A program form
    ignores the definitions, staying self-contained, its includes
    resolving through include_paths."""
    tree = parse_source(source) if isinstance(source, str) else source
    if program_form(tree):
        return compile_program(tree, include_paths)
    return _compile(defs, None, tree)


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
