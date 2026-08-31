"""
JavaScript / TypeScript Adapter

Phase 4 — the "second language" workstream, and the cleanest available
answer to the question of whether this approach is a Python ``ast`` trick.

Built on tree-sitter, which gives a concrete syntax tree: every node keeps
its byte range, so abstraction is a set of range replacements over the
original text rather than a parse-and-reprint. Three consequences, all of
which matter more than they sound:

* **Formatting, comments and blank lines survive**, because nothing is
  reprinted. The Python path cannot offer that — ``ast.unparse`` rebuilds
  the file — which is why Phase 1 had to build a line index and a comment
  re-injection pass to recover what unparsing destroyed.
* **Line numbers are exact.** The line map is the identity, so an LLM's
  "line 34" is line 34 of the developer's file with no translation step
  and no chance of a wrong one.
* **A parse error is recoverable.** tree-sitter produces a tree with
  ERROR nodes rather than raising, so a file with a syntax error still
  abstracts. This adapter nonetheless *refuses* such a file
  (:meth:`JavaScriptAdapter.symbols` raises), because a misparsed region
  is exactly where a secret would be missed, and failing closed is the
  rule the rest of the system follows.

What this adapter deliberately does not do is model JavaScript scoping
properly. It tracks the chain of enclosing functions and classes, which
distinguishes two ``result`` variables in two functions — the Phase 1 / D4
property. It does not model hoisting, closures capturing a binding from an
outer scope, or block scoping of ``let`` versus ``var``. The effect is
conservative in the direction that matters: two distinct symbols may share
a name and therefore share a token, which costs precision in the mapping,
never privacy. The limitation is stated here and in the upgrade plan
rather than buried.
"""

from typing import Dict, List, Optional, Set, Tuple

from config.allowlist import is_safe_js_module
from core.languages.base import (
    KIND_CLASS,
    KIND_FUNCTION,
    KIND_MODULE,
    KIND_NUMBER,
    KIND_PARAMETER,
    KIND_PROPERTY,
    KIND_STRING,
    KIND_VARIABLE,
    SourceSymbol,
)

# ═══════════════════════════════════════════════════════════
# Names that must survive
# ═══════════════════════════════════════════════════════════
# The JavaScript counterpart of ``algorithms.helpers.BUILTINS``. Abstracting
# ``map``, ``length`` or ``console`` would cost most of the model's ability
# to read the code while protecting nothing: these names are in every
# JavaScript file ever written, so they identify nobody.

JS_GLOBALS: Set[str] = {
    # Runtime globals
    'console', 'process', 'require', 'module', 'exports', 'globalThis',
    'window', 'document', 'navigator', 'location', 'history', 'localStorage',
    'sessionStorage', 'fetch', 'setTimeout', 'setInterval', 'clearTimeout',
    'clearInterval', 'queueMicrotask', 'structuredClone', 'Buffer',
    '__dirname', '__filename',

    # Standard objects and constructors
    'Object', 'Array', 'String', 'Number', 'Boolean', 'Symbol', 'BigInt',
    'Math', 'JSON', 'Date', 'RegExp', 'Error', 'TypeError', 'RangeError',
    'SyntaxError', 'ReferenceError', 'EvalError', 'URIError',
    'Promise', 'Proxy', 'Reflect', 'Map', 'Set', 'WeakMap', 'WeakSet',
    'ArrayBuffer', 'DataView', 'Function', 'Intl', 'URL', 'URLSearchParams',
    'AbortController', 'Headers', 'Request', 'Response', 'FormData',
    'TextEncoder', 'TextDecoder', 'Infinity', 'NaN', 'undefined', 'null',
    'true', 'false', 'this', 'super', 'arguments',

    # Prototype methods that appear as property identifiers everywhere
    'length', 'push', 'pop', 'shift', 'unshift', 'slice', 'splice',
    'concat', 'join', 'indexOf', 'lastIndexOf', 'includes', 'find',
    'findIndex', 'filter', 'map', 'reduce', 'forEach', 'some', 'every',
    'sort', 'reverse', 'flat', 'flatMap', 'keys', 'values', 'entries',
    'then', 'catch', 'finally', 'resolve', 'reject', 'all', 'race',
    'toString', 'valueOf', 'hasOwnProperty', 'constructor', 'prototype',
    'call', 'apply', 'bind', 'log', 'warn', 'info', 'debug', 'trace',
    'parse', 'stringify', 'split', 'trim', 'replace', 'replaceAll',
    'toLowerCase', 'toUpperCase', 'startsWith', 'endsWith', 'padStart',
    'padEnd', 'repeat', 'charAt', 'charCodeAt', 'substring', 'substr',
    'test', 'exec', 'match', 'matchAll', 'get', 'set', 'has', 'delete',
    'add', 'clear', 'size', 'from', 'of', 'isArray', 'assign', 'freeze',
    'default',

    # TypeScript type names that are part of the language, not the domain
    'string', 'number', 'boolean', 'any', 'unknown', 'never', 'void',
    'object', 'symbol', 'bigint', 'Record', 'Partial', 'Required',
    'Readonly', 'Pick', 'Omit', 'Exclude', 'Extract', 'ReturnType',
    'Parameters', 'Awaited', 'Array',
}

# Node types carrying an identifier we may want to abstract.
_NAME_NODES = {
    'identifier',
    'property_identifier',
    'shorthand_property_identifier',
    'shorthand_property_identifier_pattern',
    'type_identifier',
}

# Identifiers reached as members of something else. These key in the
# 'property' namespace: ``gateway.charge()`` and the ``charge()`` method
# that defines it are the same name and must get the same token.
# A shorthand property (``{ checkoutCart }``) is *not* here: it names a
# property but it also references the local binding, so it has to share
# that binding's token or the emitted object stops referring to anything.
_MEMBER_NODES = {
    'property_identifier',
}

# Nodes that open a new named scope, and the field their name lives in.
_SCOPE_NODES = {
    'function_declaration': 'name',
    'function_expression': 'name',
    'generator_function_declaration': 'name',
    'class_declaration': 'name',
    'class': 'name',
    'method_definition': 'name',
    'interface_declaration': 'name',
}

# Declaration nodes whose ``name`` field is a binding site.
_BINDING_PARENTS = {
    'variable_declarator', 'function_declaration', 'class_declaration',
    'method_definition', 'public_field_definition', 'property_signature',
    'interface_declaration', 'generator_function_declaration',
    'required_parameter', 'optional_parameter',
}


class LanguageUnavailable(RuntimeError):
    """Raised when tree-sitter or a grammar is not installed."""


class JavaScriptAdapter:
    """
    Abstracts JavaScript and TypeScript via tree-sitter.

    One class serves both: the grammars differ, the traversal does not.
    TypeScript's extra nodes (``required_parameter``, ``type_identifier``,
    ``interface_declaration``) are simply absent from a JavaScript tree.
    """

    language = "javascript"
    extensions: Tuple[str, ...] = ('.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx')

    # Extension → which grammar to load.
    _TYPESCRIPT_EXTENSIONS = {'.ts', '.mts', '.cts'}
    _TSX_EXTENSIONS = {'.tsx'}

    def __init__(self, dialect: str = "javascript"):
        self.dialect = dialect

    # -- availability -------------------------------------------------

    def availability(self) -> Tuple[bool, str]:
        """Whether tree-sitter and at least the JavaScript grammar exist."""
        try:
            import tree_sitter  # noqa: F401
        except ImportError:
            return False, (
                "tree-sitter is not installed: "
                "pip install 'codeabstract[javascript]'"
            )
        try:
            import tree_sitter_javascript  # noqa: F401
        except ImportError:
            return False, (
                "the JavaScript grammar is not installed: "
                "pip install 'codeabstract[javascript]'"
            )
        return True, ""

    @classmethod
    def dialect_for(cls, extension: str) -> str:
        """Grammar name for a file extension."""
        extension = extension.lower()
        if extension in cls._TSX_EXTENSIONS:
            return 'tsx'
        if extension in cls._TYPESCRIPT_EXTENSIONS:
            return 'typescript'
        return 'javascript'

    def _parser(self):
        from tree_sitter import Language, Parser

        if self.dialect in ('typescript', 'tsx'):
            try:
                import tree_sitter_typescript as grammar
            except ImportError as exc:
                raise LanguageUnavailable(
                    "the TypeScript grammar is not installed: "
                    "pip install 'codeabstract[javascript]'"
                ) from exc
            raw = (
                grammar.language_tsx() if self.dialect == 'tsx'
                else grammar.language_typescript()
            )
        else:
            try:
                import tree_sitter_javascript as grammar
            except ImportError as exc:
                raise LanguageUnavailable(
                    "the JavaScript grammar is not installed: "
                    "pip install 'codeabstract[javascript]'"
                ) from exc
            raw = grammar.language()

        return Parser(Language(raw))

    def is_builtin(self, name: str) -> bool:
        """True for language globals and standard members."""
        return name in JS_GLOBALS

    # -- extraction ---------------------------------------------------

    def symbols(self, source_code: str) -> List[SourceSymbol]:
        """
        Extract every abstractable symbol.

        Raises:
            LanguageUnavailable: If tree-sitter or the grammar is missing.
            ValueError: If the file does not parse cleanly. A region
                tree-sitter could not understand is a region where a
                credential could hide, so the file is refused rather than
                partially abstracted.
        """
        available, reason = self.availability()
        if not available:
            raise LanguageUnavailable(reason)

        parser = self._parser()
        data = source_code.encode('utf-8')
        tree = parser.parse(data)

        if tree.root_node.has_error:
            line = self._first_error_line(tree.root_node)
            raise ValueError(
                f"Invalid {self.dialect} syntax near line {line}. "
                "The file was not abstracted: a region the parser cannot "
                "read is a region a secret could hide in."
            )

        collector = _Collector(self, data)
        collector.collect_credential_templates(tree.root_node)
        collector.visit(tree.root_node)
        return collector.finish()

    def comments(self, source_code: str) -> List[Tuple[int, int, str]]:
        """
        Every comment in *source_code*, as ``(start_byte, end_byte, text)``.

        Taken from the parse tree rather than a regex, so that ``//`` inside
        a string literal or a regex literal is not mistaken for a comment —
        the same reason :func:`core.comment_handler.extract_comments` uses
        ``tokenize`` for Python.

        Args:
            source_code: The source file's text.

        Returns:
            Comment ranges in source order. Empty if the file does not parse.
        """
        available, _ = self.availability()
        if not available:
            return []

        try:
            tree = self._parser().parse(source_code.encode('utf-8'))
        except Exception:                                  # pragma: no cover
            return []

        data = source_code.encode('utf-8')
        found: List[Tuple[int, int, str]] = []
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type == 'comment':
                found.append((
                    node.start_byte,
                    node.end_byte,
                    data[node.start_byte:node.end_byte].decode('utf-8', 'replace'),
                ))
                continue
            stack.extend(node.children)

        found.sort(key=lambda item: item[0])
        return found

    @staticmethod
    def _first_error_line(node) -> int:
        """Line of the first ERROR or MISSING node, for the message."""
        stack = [node]
        while stack:
            current = stack.pop()
            if current.type == 'ERROR' or current.is_missing:
                return current.start_point[0] + 1
            stack.extend(reversed(current.children))
        return node.start_point[0] + 1


class _Collector:
    """
    One traversal of a parsed file.

    Kept separate from the adapter so that the adapter stays stateless and
    can be reused across files.
    """

    def __init__(self, adapter: JavaScriptAdapter, data: bytes):
        self.adapter = adapter
        self.data = data
        self.symbols: List[SourceSymbol] = []
        # Names bound by an allowlisted import: kept everywhere, so that a
        # surviving ``import express`` cannot be aligned against a token
        # (the Phase 0 / D3 argument, in JavaScript).
        self.preserved_names: Set[str] = set()
        # Names bound by a non-allowlisted import: always abstracted, even
        # at a privacy level that would otherwise keep identifiers, or the
        # emitted file would reference a module that no longer exists.
        self.module_names: Set[str] = set()
        # node id → 'SECRET', propagated from a binding to what it binds.
        self.inherited: Dict[int, str] = {}
        self._module_specifiers: Dict[int, bool] = {}
        # Names that fill a placeholder in a credential-shaped template
        # literal. Gathered before the main walk, because the binding
        # (``const p = "…"``) usually precedes the template that consumes
        # it, and a single top-down pass would have judged it already.
        self._template_fed: Set[str] = set()

    # -- helpers ------------------------------------------------------

    def text(self, node) -> str:
        return self.data[node.start_byte:node.end_byte].decode('utf-8', 'replace')

    def _scope_of(self, node) -> str:
        """
        Dotted path of enclosing named functions and classes.

        A construct's own name belongs to the scope *containing* it, not to
        the scope it opens: ``function charge()`` declares ``charge`` in the
        module, and attributing it to scope ``charge`` would leave the
        declaration and every call site in different scopes — which is
        precisely how a name ends up with two tokens and the output stops
        being valid code.
        """
        parts: List[str] = []
        child = node
        current = node.parent
        while current is not None:
            field = _SCOPE_NODES.get(current.type)
            if field:
                name_node = current.child_by_field_name(field)
                if name_node is not None and name_node.id != child.id:
                    parts.append(self.text(name_node))
            child = current
            current = current.parent
        return '.'.join(reversed(parts)) or 'module'

    def _is_binding(self, node) -> bool:
        parent = node.parent
        if parent is None:
            return False
        if parent.type in _BINDING_PARENTS:
            name_field = parent.child_by_field_name('name')
            if name_field is not None and name_field.id == node.id:
                return True
            # TypeScript parameters put the identifier in ``pattern``.
            pattern = parent.child_by_field_name('pattern')
            if pattern is not None and pattern.id == node.id:
                return True
        if node.type == 'shorthand_property_identifier_pattern':
            return True  # ``const { ledger } = require(…)`` binds ``ledger``

        return parent.type == 'formal_parameters'

    def _kind_of(self, node) -> str:
        parent = node.parent
        parent_type = parent.type if parent is not None else ''

        if parent_type in ('class_declaration', 'class', 'interface_declaration'):
            return KIND_CLASS
        if parent_type in (
            'function_declaration', 'function_expression',
            'generator_function_declaration', 'method_definition',
        ):
            return KIND_FUNCTION
        if parent_type in ('formal_parameters', 'required_parameter', 'optional_parameter'):
            return KIND_PARAMETER
        if node.type in (
            'property_identifier', 'shorthand_property_identifier',
            'shorthand_property_identifier_pattern',
        ):
            return KIND_PROPERTY
        if parent_type == 'variable_declarator':
            # ``const handler = () => …`` declares a function, and calling
            # it VAR_n would mislead the model about what it is.
            value = parent.child_by_field_name('value')
            if value is not None and value.type in (
                'arrow_function', 'function_expression', 'function',
            ):
                return KIND_FUNCTION
        return KIND_VARIABLE

    # -- secret propagation -------------------------------------------

    def _propagate(self, node) -> None:
        """
        Mark values bound to secret-named things, mirroring Phase 0 / D1.

        ``const apiKey = "abc123"`` must redact the literal even though the
        literal's own shape says nothing. The name is classified with the
        same tiers the driver uses, so this cannot disagree with the main
        classifier about what a secret name looks like.
        """
        from algorithms.classify import classify_signals

        pairs = []
        if node.type in ('variable_declarator', 'public_field_definition'):
            pairs.append((node.child_by_field_name('name'),
                          node.child_by_field_name('value')))
        elif node.type == 'pair':
            pairs.append((node.child_by_field_name('key'),
                          node.child_by_field_name('value')))
        elif node.type == 'assignment_expression':
            pairs.append((node.child_by_field_name('left'),
                          node.child_by_field_name('right')))

        for name_node, value_node in pairs:
            if name_node is None or value_node is None:
                continue

            # For ``this.apiKey = x`` the informative half is the property.
            if name_node.type == 'member_expression':
                prop = name_node.child_by_field_name('property')
                name_node = prop if prop is not None else name_node

            name = self.text(name_node).strip('\'"')
            if (
                classify_signals(text=name).label != 'SECRET'
                and name not in self._template_fed
            ):
                continue

            for target in self._literal_nodes(value_node):
                self.inherited[target.id] = 'SECRET'

    def _literal_nodes(self, node) -> List:
        """String fragments and numbers beneath *node*."""
        found = []
        stack = [node]
        while stack:
            current = stack.pop()
            if current.type in ('string_fragment', 'number'):
                found.append(current)
            stack.extend(current.children)
        return found

    # -- imports ------------------------------------------------------

    def _handle_import(self, node) -> None:
        """
        Record an import's module specifier and the names it binds.

        Allowlisted modules keep their names; everything else — including
        every relative path, which is by definition inside the user's own
        project — is abstracted along with the names it introduces.
        """
        source = node.child_by_field_name('source')
        if source is None:
            return

        specifier = self.text(source).strip('\'"`')
        safe = is_safe_js_module(specifier)

        fragment = self._string_fragment(source)
        if fragment is not None:
            self._module_specifiers[fragment.id] = safe

        for bound in self._imported_names(node):
            name = self.text(bound)
            (self.preserved_names if safe else self.module_names).add(name)

    def _handle_require(self, node) -> None:
        """``const fs = require('fs')`` — the CommonJS spelling of an import."""
        function = node.child_by_field_name('function')
        arguments = node.child_by_field_name('arguments')
        if function is None or arguments is None:
            return
        if self.text(function) != 'require':
            return

        strings = [c for c in arguments.children if c.type == 'string']
        if not strings:
            return

        specifier = self.text(strings[0]).strip('\'"`')
        safe = is_safe_js_module(specifier)

        fragment = self._string_fragment(strings[0])
        if fragment is not None:
            self._module_specifiers[fragment.id] = safe

        declarator = node.parent
        if declarator is not None and declarator.type == 'variable_declarator':
            name_node = declarator.child_by_field_name('name')
            if name_node is not None:
                # ``const fs = require(…)`` and
                # ``const { ledger } = require(…)`` both bind names here.
                for bound in self._pattern_names(name_node):
                    name = self.text(bound)
                    (self.preserved_names if safe else self.module_names).add(name)

    def _pattern_names(self, node) -> List:
        """Identifiers a binding pattern introduces, destructuring included."""
        if node.type == 'identifier':
            return [node]

        bound = []
        stack = [node]
        while stack:
            current = stack.pop()
            if current.type in (
                'identifier', 'shorthand_property_identifier_pattern',
            ):
                bound.append(current)
                continue
            stack.extend(current.children)
        return bound

    @staticmethod
    def _string_fragment(string_node):
        for child in string_node.children:
            if child.type == 'string_fragment':
                return child
        return None

    def _imported_names(self, node) -> List:
        """Identifiers an import statement binds into the local scope."""
        bound = []
        stack = list(node.children)
        while stack:
            current = stack.pop()
            if current.type == 'string':
                continue  # the specifier, not a binding
            if current.type in ('identifier', 'shorthand_property_identifier'):
                bound.append(current)
            stack.extend(current.children)
        return bound

    # -- template strings ---------------------------------------------

    def _handle_template(self, node) -> None:
        """
        Classify a template literal as a whole, not fragment by fragment.

        ```Bearer ${token}``` is a credential split across a literal and an
        interpolation; each half on its own looks innocent. Flattening to
        ``Bearer {}`` and testing that is the Phase 0 f-string fix, applied
        to the construct JavaScript uses for the same job.
        """
        from core.secret_detector import is_secret_value

        flattened = []
        fragments = []
        for child in node.children:
            if child.type == 'string_fragment':
                flattened.append(self.text(child))
                fragments.append(child)
            elif child.type == 'template_substitution':
                flattened.append('{}')

        template = ''.join(flattened)
        if template and is_secret_value(template):
            for fragment in fragments:
                self.inherited[fragment.id] = 'SECRET'

    # -- "+"-concatenated strings ---------------------------------------

    def _flatten_concat(self, node) -> Optional[str]:
        """
        Flatten a chain of ``+`` string-literal concatenation into the text
        it assembles at runtime, or ``None`` if any operand is not a plain
        string literal.

        The counterpart of ``_handle_template`` for the older concatenation
        spelling: ``"sk_live_" + "abc123..."`` is the same split-credential
        shape as a template literal's ``${}``, and each half can fall
        individually below the entropy floor or a vendor prefix's minimum
        length while the assembled string is a live-looking key.

        Deliberately narrow: an operand that is an ``identifier`` (a
        fragment held in a variable assigned on an earlier line) returns
        ``None`` for the whole chain -- resolving that needs dataflow
        analysis this adapter does not attempt, the same boundary
        documented on the Python side's ``core.context_features``.
        """
        if node.type == 'string':
            fragment = self._string_fragment(node)
            return self.text(fragment) if fragment is not None else ''
        if node.type == 'binary_expression':
            operator = node.child_by_field_name('operator')
            left = node.child_by_field_name('left')
            right = node.child_by_field_name('right')
            if operator is None or self.text(operator) != '+':
                return None
            if left is None or right is None:
                return None
            left_text = self._flatten_concat(left)
            right_text = self._flatten_concat(right)
            if left_text is not None and right_text is not None:
                return left_text + right_text
        return None

    def _handle_binary_concat(self, node) -> None:
        """
        Classify a ``+``-concatenated string chain as a whole.

        A credential built from adjacent literal fragments carries no name
        signal at all -- there is no binding for ``_propagate`` to inherit
        from -- so whole-chain value-shape detection is the only signal
        available.
        """
        from core.secret_detector import is_secret_value

        flattened = self._flatten_concat(node)
        if not flattened or not is_secret_value(flattened):
            return

        for leaf in self._literal_nodes(node):
            self.inherited[leaf.id] = 'SECRET'

    def collect_credential_templates(self, node) -> None:
        """
        Record the names that fill a placeholder in a credential template.

        The mirror of ``ContextAnalyzer._collect_credential_templates``.
        Redacting the template's literal fragments and stopping there
        identifies ``${p}`` as a password position and then ships the
        password: in ``const p = "hunter2"`` the binding carries no signal
        of its own, and it is the assembly that gives it away.

        Shallow, like ``_propagate``: only a bare identifier inside the
        substitution is recorded, so ``${build(userId)}`` names no binding
        and ``userId`` is left alone.
        """
        from core.secret_detector import is_secret_value

        if node.type == 'template_string':
            flattened = []
            substitutions = []
            for child in node.children:
                if child.type == 'string_fragment':
                    flattened.append(self.text(child))
                elif child.type == 'template_substitution':
                    flattened.append('{}')
                    substitutions.append(child)

            template = ''.join(flattened)
            if template and is_secret_value(template):
                for substitution in substitutions:
                    for inner in substitution.children:
                        if inner.type == 'identifier':
                            self._template_fed.add(self.text(inner))

        for child in node.children:
            self.collect_credential_templates(child)

    # -- traversal ----------------------------------------------------

    def visit(self, node) -> None:
        if node.type in ('import_statement', 'export_statement'):
            self._handle_import(node)
        elif node.type == 'call_expression':
            self._handle_require(node)
        elif node.type == 'template_string':
            self._handle_template(node)
        elif node.type == 'binary_expression':
            self._handle_binary_concat(node)

        self._propagate(node)

        if node.type in _NAME_NODES:
            self._add_name(node)
        elif node.type == 'string_fragment':
            self._add_literal(node, KIND_STRING, numeric=False)
        elif node.type == 'number' and self._is_numeric_literal(node):
            self._add_literal(node, KIND_NUMBER, numeric=True)

        for child in node.children:
            self.visit(child)

    @staticmethod
    def _is_numeric_literal(node) -> bool:
        """
        Distinguish the literal ``42`` from TypeScript's ``number`` keyword.

        Both are nodes of type ``number`` in the TypeScript grammar, and
        tokenising the keyword produced ``amount: NUM_0`` — a type
        annotation replaced by a token, which is neither valid TypeScript
        nor a privacy gain.
        """
        if node.parent is not None and node.parent.type == 'predefined_type':
            return False
        return node.child_count == 0 and node.type == 'number'

    def _add_name(self, node) -> None:
        name = self.text(node)
        if not name:
            return

        if name in self.module_names:
            kind, namespace = KIND_MODULE, 'module'
        else:
            kind = self._kind_of(node)
            namespace = 'property' if node.type in _MEMBER_NODES else None

        self.symbols.append(SourceSymbol(
            name=name,
            kind=kind,
            namespace=namespace,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            lineno=node.start_point[0] + 1,
            col=node.start_point[1],
            scope=self._scope_of(node),
            is_binding=self._is_binding(node),
            inherited=self.inherited.get(node.id),
        ))

    def _add_literal(self, node, kind: str, numeric: bool) -> None:
        safe_module = self._module_specifiers.get(node.id)
        if safe_module is True:
            return  # an allowlisted specifier stays readable

        kind = KIND_MODULE if safe_module is False else kind

        self.symbols.append(SourceSymbol(
            name=self.text(node),
            kind=kind,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            lineno=node.start_point[0] + 1,
            col=node.start_point[1],
            scope=self._scope_of(node),
            is_binding=False,
            is_literal=True,
            is_numeric=numeric,
            inherited=self.inherited.get(node.id),
        ))

    def _resolve_bindings(self) -> None:
        """
        Point every use at the scope that declares it.

        Without this, a use keys on the scope it *appears* in: a module-level
        ``COUPON_SECRET`` read inside a function was a different symbol from
        the ``COUPON_SECRET`` declared above it, so the two got different
        tokens and the emitted file referenced a constant that no longer
        existed. This is the JavaScript form of the lookup chain
        ``core.symbol_table`` builds for Python (Phase 1 / D4), in the
        smaller shape this adapter can honestly support: enclosing function
        and class scopes, innermost first, falling back to the module.

        Hoisting, closures over rebound variables and ``let``-vs-``var``
        block scoping are *not* modelled. The failure mode is two distinct
        symbols sharing one token — less precise mapping, never a leak.
        """
        declared: Dict[str, Set[str]] = {}
        for symbol in self.symbols:
            if symbol.is_binding and not symbol.namespace:
                declared.setdefault(symbol.scope, set()).add(symbol.name)

        for symbol in self.symbols:
            if symbol.is_binding or symbol.namespace or symbol.is_literal:
                continue

            parts = symbol.scope.split('.') if symbol.scope != 'module' else []
            resolved = 'module'
            while parts:
                candidate = '.'.join(parts)
                if symbol.name in declared.get(candidate, ()):
                    resolved = candidate
                    break
                parts.pop()
            symbol.scope = resolved

    def finish(self) -> List[SourceSymbol]:
        """
        Return symbols in source order, with imports and scopes resolved.

        A name bound by an allowlisted import is dropped from the list
        entirely — at its declaration *and* at every use site — so that the
        surviving ``express`` in the output cannot be aligned against a
        token elsewhere in the file.
        """
        self._resolve_bindings()

        kept: List[SourceSymbol] = []
        for symbol in self.symbols:
            if symbol.kind == KIND_MODULE:
                kept.append(symbol)
                continue
            if not symbol.is_literal and symbol.name in self.preserved_names:
                continue
            if not symbol.is_literal and symbol.name in self.module_names:
                symbol.kind = KIND_MODULE
                symbol.namespace = 'module'
            kept.append(symbol)

        kept.sort(key=lambda s: s.start_byte)
        return kept


# ═══════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════

def build_adapter(extension: str = '.js') -> JavaScriptAdapter:
    """Adapter configured for the grammar matching *extension*."""
    return JavaScriptAdapter(dialect=JavaScriptAdapter.dialect_for(extension))
