"""Compiler: v0 authoring language to program trees.

The language is the text syntax plus bare names. A name is anything
the reader would reject as an unknown symbol, so strings, hex,
operator names, and decimals keep exactly their raw meaning and the
language occupies only text that previously errored. Atoms quote
themselves, names resolve to environment paths or inline constant
values, and the special forms are program, defun, defconstant, if,
and list. Everything else a source expression can say is an
operator application.

A compiled program's environment is the pair (function tree . args).
The function tree holds every reachable function body, balanced in
declaration order, and a call site rebuilds the layout by consing
the tree it received onto its evaluated arguments, so recursion and
mutual recursion need no further machinery. A program whose body
reaches no function is emitted bare with its arguments at the
environment root. Constants never enter the tree: a constant
reference inlines its value as a quoted literal at the use site.

Code is emitted directly, with no rewriting passes. The one
size-only exception: a nil literal is emitted as the nil atom, whose
path lookup yields nil, one byte instead of the two a quoted nil
takes.

Parsing and every tree walk here are iterative. Code emission alone
recurses with the source's nesting depth, a bound accepted because
source is authored rather than attacker-supplied: past the
interpreter's limit every surface reports unusable input, exit 2,
never a crash or a wrong artifact.

The compiler also builds a symbol table for the debugger: the tree
hash of each compiled function body, keyed exactly as the VM's
sha256tree operator hashes, mapped to the function's name and
parameter names. Atom bodies stay out of the table, because an atom
is not distinguishable from ordinary data by its hash.
"""

import hashlib

from bitlisp import conditions
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

_PROGRAM, _DEFUN, _DEFCONSTANT, _IF, _LIST = (
    "program",
    "defun",
    "defconstant",
    "if",
    "list",
)
RESERVED_WORDS = frozenset({_PROGRAM, _DEFUN, _DEFCONSTANT, _IF, _LIST})

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
    """The compile-time namespace: functions and constants by name.

    A name is claimed once across functions, constants, the
    condition constants, the reserved words, and any caller-supplied
    taken set, so one spelling can never mean two things.
    """

    def __init__(self):
        self.functions = {}
        self.constants = {}

    def _claim(self, symbol, taken):
        name = _check_name(symbol, "definition")
        if name in self.functions or name in self.constants or name in taken:
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
}


def declaration_keyword(tree):
    """The declaration keyword heading a source tree, or None."""
    if is_pair(tree) and isinstance(tree[0], Symbol):
        if tree[0].name in (_DEFUN, _DEFCONSTANT):
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


def _reachable(defs, body):
    """The function names reachable from a body, conservatively:
    every mentioned name counts, shadowing ignored, so the set can
    only be too large, never too small."""
    reached = set()
    pending = list(_symbol_names(body))
    while pending:
        name = pending.pop()
        if name in reached or name not in defs.functions:
            continue
        reached.add(name)
        pending.extend(_symbol_names(defs.functions[name][1]))
    return reached


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
    reachable set, shared by the main body and every function body."""

    def __init__(self, defs, fn_paths):
        self.defs = defs
        self.fn_paths = fn_paths

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
        raise CompileError(f"unknown name {name!r}", symbol.offset)

    def _named_form(self, head, tail, bindings):
        name = head.name
        if name == _IF:
            return self._if(head, tail, bindings)
        if name == _LIST:
            return self._list(head, tail, bindings)
        if name in (_PROGRAM, _DEFUN, _DEFCONSTANT):
            raise CompileError(f"{name} form is not an expression", head.offset)
        if name in bindings:
            raise CompileError(f"{name!r} is a parameter, not a function", head.offset)
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

    def _call(self, head, tail, bindings):
        name = head.name
        arguments = _proper_items(tail, name, head.offset)
        exact, count = self.defs.functions[name][2]
        if exact and len(arguments) != count:
            raise CompileError(
                f"{name!r} takes {count} argument(s), got {len(arguments)}",
                head.offset,
            )
        if not exact and len(arguments) < count:
            raise CompileError(
                f"{name!r} takes at least {count} argument(s), got {len(arguments)}",
                head.offset,
            )
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
    reached = _reachable(defs, body)
    fn_names = [name for name in defs.functions if name in reached]
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
        else:
            raise CompileError("expected defun or defconstant")
    return _compile(defs, params, items[-1])


def compile_expression(source, defs):
    """The program node and symbol table for one bare expression
    against a definitions space. The expression has no parameters,
    so the compiled program ignores its environment."""
    tree = parse_source(source) if isinstance(source, str) else source
    if program_form(tree):
        return compile_program(tree)
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
