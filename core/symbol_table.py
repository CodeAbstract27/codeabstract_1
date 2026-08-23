"""
Lexical Scope Analysis

Phase 1 / D4 fix.

ABSTRACT(S, k) originally cached tokens in a single flat ``name -> token``
dict covering the whole module.  Two different variables that happened to
share a spelling therefore shared a token, and the mapping entry recorded
only the line of whichever one the traversal reached first::

    def alpha(data):
        result = data * 2      # VAR_1 recorded here
        return result

    def beta(data):
        result = data + 1      # same token, this line never recorded
        return result

An LLM reporting a bug in ``VAR_1`` inside ``FUNC_1`` sent the developer to
``alpha()``.  That is the failure mode bidirectional mapping exists to
prevent, and it capped mapping accuracy well below the 85% target.

This module builds a lexical scope tree so tokens can be keyed by
*binding* rather than by spelling.  Each ``(scope, name)`` pair gets its
own token, and each token records the line of its own binding.

Scoping follows Python's actual rules, including the two that trip up
naive implementations:

* **Class scopes are not in the lookup chain of nested functions.** A
  method does not see its class body's names, so resolution skips class
  scopes when walking outward.
* **Comprehensions have their own scope** (Python 3), so the loop variable
  of a comprehension does not leak into the enclosing function.

``global`` and ``nonlocal`` declarations are honoured.
"""

import ast
from typing import Dict, List, Optional, Set

# Scope kinds
MODULE = 'module'
FUNCTION = 'function'
CLASS = 'class'
COMPREHENSION = 'comprehension'


class Scope:
    """A single lexical scope in the scope tree."""

    __slots__ = (
        'kind', 'name', 'parent', 'children',
        'bindings', 'global_names', 'nonlocal_names', 'uid',
    )

    _counter = 0

    def __init__(self, kind: str, name: str, parent: Optional['Scope'] = None):
        Scope._counter += 1
        self.uid: int = Scope._counter
        self.kind: str = kind
        self.name: str = name
        self.parent: Optional[Scope] = parent
        self.children: List['Scope'] = []
        self.bindings: Set[str] = set()
        self.global_names: Set[str] = set()
        self.nonlocal_names: Set[str] = set()

        if parent is not None:
            parent.children.append(self)

    @property
    def path(self) -> str:
        """Dotted, human-readable scope path, e.g. ``module.Payment.charge``."""
        if self.parent is None:
            return self.name
        return f"{self.parent.path}.{self.name}"

    def binds(self, name: str) -> bool:
        """True if *name* is bound directly in this scope."""
        return name in self.bindings

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Scope {self.kind}:{self.path}>"


class ScopeBuilder(ast.NodeVisitor):
    """
    Builds the scope tree and records which scope every AST node sits in.

    Two products come out of a single traversal:

    * ``node_scopes`` — ``id(node)`` → the :class:`Scope` the node is
      lexically located in.
    * the scope tree itself, with each scope's bound names populated.
    """

    def __init__(self):
        self.module_scope = Scope(MODULE, 'module')
        self._stack: List[Scope] = [self.module_scope]
        self.node_scopes: Dict[int, Scope] = {}

    # ── scope stack helpers ────────────────────────────

    @property
    def current(self) -> Scope:
        return self._stack[-1]

    def _push(self, kind: str, name: str) -> Scope:
        scope = Scope(kind, name, self.current)
        self._stack.append(scope)
        return scope

    def _pop(self) -> None:
        self._stack.pop()

    def _bind(self, name: Optional[str]) -> None:
        if name:
            self.current.bindings.add(name)

    def _bind_target(self, node: Optional[ast.AST]) -> None:
        """
        Record the names an assignment target binds.

        Attribute and Subscript targets (``self.x = 1``, ``d['k'] = 1``)
        mutate an existing object rather than binding a new name, so they
        introduce nothing into the scope.
        """
        if node is None:
            return
        if isinstance(node, ast.Name):
            self._bind(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for element in node.elts:
                self._bind_target(element)
        elif isinstance(node, ast.Starred):
            self._bind_target(node.value)

    # ── generic ────────────────────────────────────────

    def visit(self, node: ast.AST):
        self.node_scopes[id(node)] = self.current
        return super().visit(node)

    # ── functions ──────────────────────────────────────

    def _visit_function(self, node):
        # Decorators, defaults and annotations are evaluated in the
        # *enclosing* scope, before the function scope exists.
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
            self.visit(default)
        if getattr(node, 'returns', None):
            self.visit(node.returns)

        # The function's own name binds in the enclosing scope.
        self._bind(node.name)

        self._push(FUNCTION, node.name)
        try:
            for arg in self._all_args(node.args):
                self.node_scopes[id(arg)] = self.current
                self._bind(arg.arg)
                if arg.annotation:
                    self.visit(arg.annotation)
            for statement in node.body:
                self.visit(statement)
        finally:
            self._pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    @staticmethod
    def _all_args(args: ast.arguments) -> List[ast.arg]:
        collected = list(getattr(args, 'posonlyargs', []) or [])
        collected += list(args.args or [])
        if args.vararg:
            collected.append(args.vararg)
        collected += list(args.kwonlyargs or [])
        if args.kwarg:
            collected.append(args.kwarg)
        return collected

    def visit_Lambda(self, node: ast.Lambda):
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
            self.visit(default)

        self._push(FUNCTION, '<lambda>')
        try:
            for arg in self._all_args(node.args):
                self.node_scopes[id(arg)] = self.current
                self._bind(arg.arg)
            self.visit(node.body)
        finally:
            self._pop()

    # ── classes ────────────────────────────────────────

    def visit_ClassDef(self, node: ast.ClassDef):
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword)

        self._bind(node.name)

        self._push(CLASS, node.name)
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self._pop()

    # ── comprehensions (own scope in Python 3) ─────────

    def _visit_comprehension(self, node):
        # The first iterable is evaluated in the enclosing scope.
        generators = node.generators
        if generators:
            self.visit(generators[0].iter)

        self._push(COMPREHENSION, '<comprehension>')
        try:
            for index, generator in enumerate(generators):
                self._bind_target(generator.target)
                self.visit(generator.target)
                if index > 0:
                    self.visit(generator.iter)
                for condition in generator.ifs:
                    self.visit(condition)

            if isinstance(node, ast.DictComp):
                self.visit(node.key)
                self.visit(node.value)
            else:
                self.visit(node.elt)
        finally:
            self._pop()

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_DictComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension

    # ── binding statements ─────────────────────────────

    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            self._bind_target(target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        self._bind_target(node.target)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign):
        self._bind_target(node.target)
        self.generic_visit(node)

    def visit_NamedExpr(self, node):  # walrus operator
        self._bind_target(node.target)
        self.generic_visit(node)

    def _visit_for(self, node):
        self._bind_target(node.target)
        self.generic_visit(node)

    visit_For = _visit_for
    visit_AsyncFor = _visit_for

    def _visit_with(self, node):
        for item in node.items:
            self._bind_target(item.optional_vars)
        self.generic_visit(node)

    visit_With = _visit_with
    visit_AsyncWith = _visit_with

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        self._bind(node.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self._bind(alias.asname or alias.name.split('.', 1)[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            if alias.name != '*':
                self._bind(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global):
        self.current.global_names.update(node.names)
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal):
        self.current.nonlocal_names.update(node.names)
        self.generic_visit(node)

    # ── structural pattern matching (3.10+) ────────────

    def visit_MatchAs(self, node):
        self._bind(getattr(node, 'name', None))
        self.generic_visit(node)

    def visit_MatchStar(self, node):
        self._bind(getattr(node, 'name', None))
        self.generic_visit(node)

    def visit_MatchMapping(self, node):
        self._bind(getattr(node, 'rest', None))
        self.generic_visit(node)


def build_scopes(tree: ast.AST) -> ScopeBuilder:
    """
    Analyse *tree* and return the populated :class:`ScopeBuilder`.

    Args:
        tree: Parsed module AST.

    Returns:
        A ScopeBuilder carrying ``node_scopes`` and ``module_scope``.
    """
    builder = ScopeBuilder()
    for statement in getattr(tree, 'body', []):
        builder.visit(statement)
    builder.node_scopes[id(tree)] = builder.module_scope
    return builder


def resolve_binding_scope(name: str, scope: Scope) -> Scope:
    """
    Find the scope that *name* is bound in, as seen from *scope*.

    Implements Python's LEGB walk with the two rules that matter here:
    ``global``/``nonlocal`` declarations redirect the lookup, and class
    scopes are skipped when searching outward (a method cannot see its
    class body's names).

    A name bound nowhere — a builtin, or a global assigned in another
    module — resolves to module scope, so every occurrence of it still
    agrees on one token.

    Args:
        name: The identifier being resolved.
        scope: The scope the occurrence sits in.

    Returns:
        The :class:`Scope` that owns the binding.
    """
    # Explicit declarations win.
    if name in scope.global_names:
        return _module_of(scope)

    if name in scope.nonlocal_names:
        candidate = scope.parent
        while candidate is not None:
            if candidate.kind == FUNCTION and candidate.binds(name):
                return candidate
            candidate = candidate.parent
        return _module_of(scope)

    # The scope the occurrence is in is always consulted first, even if it
    # is a class scope.
    if scope.binds(name):
        return scope

    candidate = scope.parent
    while candidate is not None:
        # Class scopes are not part of the enclosing lookup chain.
        if candidate.kind != CLASS and candidate.binds(name):
            return candidate
        candidate = candidate.parent

    return _module_of(scope)


def _module_of(scope: Scope) -> Scope:
    """Walk to the module scope at the root of *scope*'s tree."""
    current = scope
    while current.parent is not None:
        current = current.parent
    return current
