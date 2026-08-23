"""
Usage-Based Sensitivity Signals

Phase 2 — the "context features" workstream.

Name matching asks *what is this called*. That is a weak question, and it is
the one every simple obfuscator already answers. A variable called ``t`` can
hold a bearer token; a variable called ``api_key_format_docs`` holds nothing
sensitive at all.

This module asks a different question: *what is done with this value*. A
value read from ``os.environ``, passed as ``password=``, compared with
``hmac.compare_digest``, or interpolated into an ``Authorization`` header is
a credential no matter what it is named. That is the signal a regex over
identifiers cannot see, and it is what separates semantic abstraction from
find-and-replace.

Each signal carries a weight, and weights combine into a score per node.
Nothing here is a hard rule: the score feeds the confidence-bearing
classifier in ``algorithms.classify``, which decides the label and records
*why* it decided.

This subsumes the SECRET-propagation pre-pass written in Phase 0 — that pass
was a narrow special case of context analysis (assignment, keyword, dict,
comparison), and it now lives here alongside the rest.
"""

import ast
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from config.patterns import SECRET_PATTERNS
from core.pattern_matcher import matches_any
from core.secret_detector import build_fstring_template, is_secret_value

# ═══════════════════════════════════════════════════════════
# Known sensitive sources and sinks
# ═══════════════════════════════════════════════════════════

# Calls whose *return value* is a credential by construction.
SECRET_SOURCES: Set[str] = {
    'getenv', 'environ', 'getpass', 'get_password', 'get_secret',
    'get_secret_value', 'get_credential', 'get_token', 'fetch_secret',
    'decrypt', 'unseal', 'read_secret',
}

# Calls that consume credentials.
SECRET_SINKS: Set[str] = {
    'compare_digest', 'check_password', 'verify_password', 'authenticate',
    'login', 'sign', 'hmac', 'new', 'encrypt', 'set_password',
    'basic_auth', 'bearer_auth',
}

# HTTP headers and payload keys that carry credentials.
AUTH_KEYS: Set[str] = {
    'authorization', 'auth', 'x-api-key', 'x-auth-token', 'api-key',
    'proxy-authorization', 'cookie', 'set-cookie', 'x-access-token',
}

# Weight assigned to each signal. These are ordering hints for the
# confidence tiers, not calibrated probabilities -- calibration needs the
# annotated dataset this phase is gated on.
SIGNAL_WEIGHTS: Dict[str, float] = {
    'secret_assign': 0.90,       # api_key = <here>
    'secret_attr_assign': 0.90,  # self.api_key = <here>
    'secret_kwarg': 0.90,        # connect(password=<here>)
    'secret_dict_key': 0.85,     # {"api_key": <here>}
    'secret_compare': 0.85,      # if token == <here>
    'env_read': 0.80,            # os.environ["..."] / getenv("...")
    'auth_header': 0.85,         # {"Authorization": <here>}
    'secret_sink': 0.85,         # compare_digest(<here>, ...)
    'secret_source': 0.80,       # <here> = vault.get_secret(...)
    'secret_param': 0.80,        # f(<here>) where f's parameter is secret-named
    'secret_return': 0.60,       # return <here>, from get_token()
    'credential_template': 0.85,  # p = <here>, and p fills f"...://u:{p}@h"
}


@dataclass
class ContextEvidence:
    """Accumulated usage signals for a single AST node."""

    signals: List[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        """
        Combined confidence that this node is a credential, in [0, 1).

        Signals combine as independent evidence — the probability that
        *none* of them is right — so several weak signals can add up, but
        no finite set of them reaches certainty.
        """
        if not self.signals:
            return 0.0

        remaining = 1.0
        for signal in set(self.signals):
            remaining *= (1.0 - SIGNAL_WEIGHTS.get(signal, 0.5))
        return round(1.0 - remaining, 4)

    def describe(self) -> str:
        """Human-readable justification, for the privacy report."""
        return ", ".join(sorted(set(self.signals)))


def _is_secret_name(name: Optional[str]) -> bool:
    """True if *name* matches a SECRET name pattern."""
    if not name:
        return False
    return matches_any(name.lower(), SECRET_PATTERNS)


def _call_name(node: ast.AST) -> Optional[str]:
    """Final attribute or name of a call target: ``a.b.c()`` → ``'c'``."""
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


class ContextAnalyzer(ast.NodeVisitor):
    """
    Walks a module and records how each value is used.

    Produces ``evidence``: ``id(node)`` → :class:`ContextEvidence`.
    """

    def __init__(self, tree: ast.AST):
        self.evidence: Dict[int, ContextEvidence] = {}
        self._function_params: Dict[str, List[str]] = {}
        self._secret_functions: Set[str] = set()
        self._template_fed: Set[str] = set()
        self._tree = tree

    # ── recording ──────────────────────────────────────

    def _mark(self, node: Optional[ast.AST], signal: str) -> None:
        """
        Attach *signal* to *node*, following into f-string fragments.

        Marking is deliberately shallow: it follows the value being bound,
        not arbitrary sub-expressions, so ``token = build(user_id)`` does
        not drag ``user_id`` into the secret class.
        """
        if node is None:
            return

        self.evidence.setdefault(id(node), ContextEvidence()).signals.append(signal)

        if isinstance(node, ast.JoinedStr):
            for value in node.values:
                if isinstance(value, ast.Constant):
                    self.evidence.setdefault(
                        id(value), ContextEvidence()
                    ).signals.append(signal)

    # ── pre-pass: learn the module's own functions ─────

    def collect_signatures(self) -> None:
        """
        Record each local function's parameter names.

        This is what lets ``store(secret_token)`` mark its argument when
        ``store``'s parameter is named ``api_key`` — the sensitivity lives
        in the callee's signature, not at the call site.
        """
        for node in ast.walk(self._tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                params = [
                    a.arg for a in (
                        list(getattr(args, 'posonlyargs', []) or [])
                        + list(args.args or [])
                        + list(args.kwonlyargs or [])
                    )
                ]
                self._function_params[node.name] = params
                if _is_secret_name(node.name):
                    self._secret_functions.add(node.name)

        self._collect_credential_templates()

    def _collect_credential_templates(self) -> None:
        """
        Record the names that fill a placeholder in a credential template.

        Phase 0 taught the detector to flatten
        ``f"postgres://admin:{db_pass}@10.2.3.4/prod"`` into
        ``postgres://admin:{}@10.2.3.4/prod`` so the connection-string
        pattern could see it, and redacted the template's literal
        fragments. It stopped there — so the system identified the
        placeholder as a password position and then transmitted the
        password that filled it.

        ``db_pass`` survived that only because its own binding happened to
        be named after a secret. Rename it ``p`` and every other signal
        disappears, which is precisely the case flattening exists to catch:
        the credential is not in any one fragment, it is in the assembly.

        Shallow, like :meth:`_mark`: only a bare ``Name`` inside the
        interpolation is recorded, so ``f"...{build(user_id)}..."`` names no
        binding and ``user_id`` is not dragged in by association.
        """
        for node in ast.walk(self._tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            if not is_secret_value(build_fstring_template(node)):
                continue

            for value in node.values:
                if isinstance(value, ast.FormattedValue) and isinstance(
                    value.value, ast.Name
                ):
                    self._template_fed.add(value.value.id)

    # ── assignments ────────────────────────────────────

    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            signal = self._target_signal(target)
            if signal:
                self._mark(node.value, signal)

        # `x = os.environ["KEY"]` / `x = vault.get_secret()`
        if self._is_secret_source(node.value):
            for target in node.targets:
                self._mark(target, 'secret_source')
                self._mark(node.value, 'secret_source')

        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        signal = self._target_signal(node.target)
        if signal:
            self._mark(node.value, signal)
        if self._is_secret_source(node.value):
            self._mark(node.target, 'secret_source')
        self.generic_visit(node)

    def _target_signal(self, target: ast.AST) -> Optional[str]:
        """Which signal, if any, an assignment target confers on its value."""
        if isinstance(target, ast.Name) and _is_secret_name(target.id):
            return 'secret_assign'
        if isinstance(target, ast.Name) and target.id in self._template_fed:
            return 'credential_template'
        if isinstance(target, ast.Attribute) and _is_secret_name(target.attr):
            return 'secret_attr_assign'
        if isinstance(target, ast.Subscript):
            key = target.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                if _is_secret_name(key.value):
                    return 'secret_assign'
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                signal = self._target_signal(element)
                if signal:
                    return signal
        return None

    def _is_secret_source(self, node: Optional[ast.AST]) -> bool:
        """
        True if *node* reads from a known credential source.

        Covers both call form (``os.getenv("K")``, ``vault.get_secret()``)
        and subscript form (``os.environ["K"]``). The subscript case was
        the one that mattered in practice and is easy to miss, because it
        is the idiom most real code uses.
        """
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            return bool(name and name.lower() in SECRET_SOURCES)

        if isinstance(node, ast.Subscript):
            name = _call_name(node.value)
            return bool(name and name.lower() in SECRET_SOURCES)

        return False

    # ── calls ──────────────────────────────────────────

    def visit_Call(self, node: ast.Call):
        callee = _call_name(node.func)

        # connect(password="...")
        for keyword in node.keywords:
            if _is_secret_name(keyword.arg):
                self._mark(keyword.value, 'secret_kwarg')

        # compare_digest(<here>, ...) / authenticate(<here>)
        if callee and callee.lower() in SECRET_SINKS:
            for argument in node.args:
                self._mark(argument, 'secret_sink')

        # os.environ.get("API_KEY") → the *call* yields a secret
        if self._is_secret_source(node):
            self._mark(node, 'env_read')

        # "db://{}:{}@host".format(user, password) — the same construct as
        # the f-string, spelled the older way. The template is recognised
        # as a connection string and redacted; the arguments that fill its
        # placeholders were not, so the credential travelled beside the
        # redacted string that described it.
        self._mark_format_arguments(node)

        # store(x) where store's own parameter is secret-named
        if callee in self._function_params:
            params = self._function_params[callee]
            for index, argument in enumerate(node.args):
                if index < len(params) and _is_secret_name(params[index]):
                    self._mark(argument, 'secret_param')

        self.generic_visit(node)

    def _mark_format_arguments(self, node: ast.Call) -> None:
        """
        Mark the arguments of ``"<credential template>".format(...)``.

        ``str.format`` and the ``%`` operator are the pre-f-string spellings
        of the same idea, and a codebase old enough to hold a hardcoded
        password is likely to use them.  Every argument is marked rather
        than guessing which placeholder is the password position: they all
        end up inside a string the detector has already called a credential.

        Only a literal template is considered, so ``template.format(x)``
        — where the template is a variable — marks nothing.
        """
        if not isinstance(node.func, ast.Attribute) or node.func.attr != 'format':
            return

        template = node.func.value
        if not isinstance(template, ast.Constant):
            return
        if not is_secret_value(template.value):
            return

        for argument in node.args:
            self._mark(argument, 'credential_template')
        for keyword in node.keywords:
            self._mark(keyword.value, 'credential_template')

    def visit_BinOp(self, node: ast.BinOp):
        """``"db://%s:%s@host" % (user, password)`` — the ``%`` spelling."""
        if isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant):
            if is_secret_value(node.left.value):
                operands = (
                    node.right.elts
                    if isinstance(node.right, (ast.Tuple, ast.List))
                    else [node.right]
                )
                for operand in operands:
                    self._mark(operand, 'credential_template')
        self.generic_visit(node)

    # ── containers ─────────────────────────────────────

    def visit_Dict(self, node: ast.Dict):
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            key_text = key.value.lower()
            if key_text in AUTH_KEYS:
                self._mark(value, 'auth_header')
            elif _is_secret_name(key.value):
                self._mark(value, 'secret_dict_key')
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        # os.environ["STRIPE_KEY"] — the whole expression is a secret read
        target = _call_name(node.value)
        if target and target.lower() in SECRET_SOURCES:
            self._mark(node, 'env_read')
        self.generic_visit(node)

    # ── comparisons ────────────────────────────────────

    def visit_Compare(self, node: ast.Compare):
        operands = [node.left] + list(node.comparators)
        if any(self._operand_is_secret(op) for op in operands):
            for operand in operands:
                if isinstance(operand, (ast.Constant, ast.JoinedStr)):
                    self._mark(operand, 'secret_compare')
        self.generic_visit(node)

    def _operand_is_secret(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return _is_secret_name(node.id)
        if isinstance(node, ast.Attribute):
            return _is_secret_name(node.attr)
        return False

    # ── returns ────────────────────────────────────────

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if _is_secret_name(node.name):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Return) and inner.value is not None:
                    self._mark(inner.value, 'secret_return')
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


def analyze_context(tree: ast.AST) -> Dict[int, ContextEvidence]:
    """
    Analyse how every value in *tree* is used.

    Args:
        tree: Parsed module AST.

    Returns:
        ``id(node)`` → :class:`ContextEvidence` for every node that
        attracted at least one signal.
    """
    analyzer = ContextAnalyzer(tree)
    analyzer.collect_signatures()
    analyzer.visit(tree)
    return analyzer.evidence


def inherited_secret_labels(
    evidence: Dict[int, ContextEvidence],
    threshold: float = 0.80,
) -> Dict[int, str]:
    """
    Reduce context evidence to the SECRET-inheritance map ABSTRACT consumes.

    Preserves the Phase 0 propagation contract — assignments, keyword
    arguments, dict entries and comparisons all still force SECRET — while
    letting the additional Phase 2 signals contribute.

    Args:
        evidence: Output of :func:`analyze_context`.
        threshold: Minimum combined score to force a SECRET label.

    Returns:
        ``id(node)`` → ``'SECRET'``.
    """
    return {
        node_id: 'SECRET'
        for node_id, item in evidence.items()
        if item.score >= threshold
    }
