"""
ABSTRACT(S, k) Algorithm Implementation

Implements formal Algorithm 1 from specification.

Performs AST-based semantic abstraction to transform proprietary
Python code into privacy-safe intermediate representation.

Phase 0 fixes applied here:

* **D1** — secret *values* are now redacted independently of the privacy
  level, via three cooperating mechanisms: shape-based detection in
  ``core.secret_detector``, a label-inheritance pre-pass that propagates
  SECRET from a binding to the literal bound to it, and per-fragment
  f-string handling that replaces the old blanket skip.
* **D3** — ``ast.alias`` nodes are abstracted, so vendor SDKs and internal
  package names no longer pass through verbatim.  Allowlisted modules are
  preserved *consistently* at their use sites, closing the alignment
  channel that let an observer pin tokens to surviving import names.
* **D5** — the privacy level is threaded all the way down, so ``critical``
  is no longer byte-identical to ``high``.
"""
"""Formal Algorithm -1"""
import ast
import uuid
import warnings
from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple

from algorithms.classify import Decision, classify_with_evidence
from algorithms.encrypt import encrypt_mapping
from algorithms.helpers import (
    is_semantically_significant,
    label_to_prefix,
)
from config.allowlist import is_safe_module
from config.ignore_rules import OverrideRules
from config.patterns import SECRET_PATTERNS
from config.settings import PRIVACY_LEVELS
from core.context_extractor import get_context
from core.context_features import analyze_context, inherited_secret_labels
from core.pattern_matcher import matches_any
from core.secret_detector import build_fstring_template, is_secret_value
from core.symbol_table import build_scopes, resolve_binding_scope
from core.token_generator import TokenGenerator


@dataclass
class AbstractionResult:
    """Result of the ABSTRACT(S, k) algorithm."""

    abstract_code: str
    encrypted_mapping: bytes
    encryption_key: bytes
    session_id: str
    statistics: Dict = field(default_factory=dict)
    # Phase 1: abstract line number → original line number.  The LLM sees
    # the unparsed code and cites *its* line numbers; without this index
    # those citations were never translated back.
    line_map: Dict[int, int] = field(default_factory=dict)
    # Phase 4: names that survived, and why.  Counting how much was hidden
    # tells the user nothing about their exposure -- what left the machine
    # is what was *kept*.  Feeds the privacy report.
    kept: list = field(default_factory=list)
    # Phase 4: which language adapter ran.  Python here by construction;
    # ``algorithms.abstract_source`` sets it for other languages.
    language: str = "python"


def abstract(
    source_code: str,
    context_window: int = 3,
    privacy_level: str = "high",
    overrides: Optional[OverrideRules] = None,
    keep_comments: bool = False,
) -> AbstractionResult:
    """
    ABSTRACT(S, k) — Semantic Abstraction Algorithm.

    Parses Python source code into an AST, traverses all nodes,
    classifies each identifier/constant for sensitivity, generates
    unique tokens with consistent reuse, replaces nodes in the AST,
    then unparses back to abstract source code.  The mapping table
    is encrypted with Fernet before returning.

    Args:
        source_code: Python source code S.
        context_window: Context window size k (default: 3).
        privacy_level: Privacy level (low|medium|high|critical).
        overrides: Optional project rules from ``.codeabstractignore``
            (Phase 1).  These can keep an identifier readable, force one
            to SECRET, or mark an internal module safe to name.  They
            cannot un-redact a value the credential detector flagged.
        keep_comments: Opt into re-injecting screened comments (Phase 1).
            Comments are stripped by default -- see
            ``core.comment_handler`` for why that is the policy rather
            than an accident of ``ast.unparse``.

    Returns:
        AbstractionResult containing abstract code, encrypted mapping,
        encryption key, session ID, and statistics.

    Raises:
        ValueError: If the source code contains syntax errors.

    Implements:
        Algorithm 1 from formal specification.
    """
    # ───────────────────────────────────────────────────
    # Step 1: Parse source code to AST
    # ───────────────────────────────────────────────────
    try:
        ast_tree = ast.parse(source_code)
    except SyntaxError as e:
        raise ValueError(f"Invalid Python syntax at line {e.lineno}: {e.msg}")

    # ───────────────────────────────────────────────────
    # Step 2: Initialize data structures
    # ───────────────────────────────────────────────────
    # Split once and reuse for every get_context() call below -- see the
    # docstring on core.context_extractor.get_context. Re-splitting the
    # full source per mapped identifier made context extraction the
    # dominant cost on large files (profiled: ~24% of total abstraction
    # time on a 2,500-identifier file), scaling O(identifiers x file
    # size) instead of O(file size).
    source_lines = source_code.split('\n')
    mapping_table: Dict[str, Dict] = {}  # M in the algorithm
    counters = {
        'FUNC': 0, 'VAR': 0, 'SECRET': 0, 'CONST': 0,
        'CLASS': 0, 'NUM': 0, 'MODULE': 0,
    }
    # Phase 1 / D4: the token cache is keyed by *binding*, not by spelling.
    # See ``_symbol_key`` — two variables sharing a name in different
    # scopes are now different symbols and get different tokens.
    seen: Dict[tuple, str] = {}
    occurrences: Dict[str, list] = {}     # token → [{lineno, col}, …]
    definition_lines: Dict[str, int] = {}  # token → line of its binding site
    # Phase 4: (name, reason) → record of a name that was deliberately kept.
    kept: Dict[tuple, Dict] = {}

    # Step 3: Token generator
    token_gen = TokenGenerator(counters)

    # Phase 1 / D4: lexical scope analysis
    scopes = build_scopes(ast_tree)

    # Phase 1: project overrides (.codeabstractignore)
    rules = overrides if overrides is not None else OverrideRules()

    # Step 4: Statistics tracking
    stats = {
        'total_nodes': 0,
        'abstracted_nodes': 0,
        'skipped_nodes': 0,
        'secrets_found': 0,
        'values_found': 0,
        'modules_abstracted': 0,
        'modules_preserved': 0,
        'overrides_applied': 0,
        'low_confidence_nodes': 0,
    }

    # ───────────────────────────────────────────────────
    # Step 5a: Build parent map (needed to swap Constant → Name nodes)
    # ───────────────────────────────────────────────────
    parent_map: Dict[int, ast.AST] = {}
    for node in ast.walk(ast_tree):
        for child in ast.iter_child_nodes(node):
            parent_map[id(child)] = node

    # ───────────────────────────────────────────────────
    # Step 5b: Propagate SECRET from bindings to bound literals
    #          (Phase 0 / D1)
    # ───────────────────────────────────────────────────
    # Phase 2: usage-based signals subsume the narrower Phase 0 pass --
    # assignments and keywords still propagate SECRET, and env reads,
    # auth headers, credential sinks and callee signatures now do too.
    context_evidence = analyze_context(ast_tree)
    inherited_labels = inherited_secret_labels(context_evidence)

    # Evidence is gathered per *node*, but the decision to abstract is made
    # per *symbol*.  Without this aggregation, `material = vault.get_secret()`
    # marked only the assignment target, and the later `use(material)`
    # classified as an ordinary identifier and survived at low privacy --
    # the value was redacted in one place and printed in the next.
    symbol_evidence = _aggregate_evidence_by_symbol(
        ast_tree, scopes, context_evidence,
    )

    # ───────────────────────────────────────────────────
    # Step 5c: Classify f-string literal fragments
    #          (Phase 0 / D1 — replaces the old blanket skip)
    # ───────────────────────────────────────────────────
    fstring_children, fstring_redact = _scan_fstrings(ast_tree, inherited_labels)

    # ───────────────────────────────────────────────────
    # Step 5d: Resolve imports before anything else, so module
    #          bindings and their use sites agree (Phase 0 / D3)
    # ───────────────────────────────────────────────────
    forced_keys: Set[tuple] = set()
    preserved_keys: Set[tuple] = set()
    _register_imports(
        ast_tree=ast_tree,
        source_code=source_code,
        context_window=context_window,
        mapping_table=mapping_table,
        seen=seen,
        token_gen=token_gen,
        scopes=scopes,
        rules=rules,
        forced_keys=forced_keys,
        preserved_keys=preserved_keys,
        stats=stats,
        kept=kept,
        definition_lines=definition_lines,
    )

    # ───────────────────────────────────────────────────
    # Step 5e: Traverse AST
    # ───────────────────────────────────────────────────
    for node in ast.walk(ast_tree):
        stats['total_nodes'] += 1

        # Imports were fully resolved in Step 5d — every alias is either
        # already tokenised or deliberately preserved.  Re-visiting them
        # here would allocate a second token for a name that already has
        # one, desynchronising the import from its use sites.
        if isinstance(node, ast.alias):
            stats['skipped_nodes'] += 1
            continue

        in_fstring = id(node) in fstring_children
        redact_fragment = id(node) in fstring_redact

        # Literal fragments of a safe f-string stay put: abstracting
        # ordinary prose costs utility and protects nothing.
        if in_fstring and not redact_fragment:
            stats['skipped_nodes'] += 1
            continue

        # Extract node name
        node_name = _get_node_name(node)
        if not node_name:
            stats['skipped_nodes'] += 1
            continue

        # Phase 1 / D4: identify the symbol this occurrence belongs to.
        symbol_key = _symbol_key(node, node_name, scopes)

        # Allowlisted imports are preserved at their use sites too, so an
        # observer cannot align a surviving import against a token.
        if symbol_key in preserved_keys:
            stats['skipped_nodes'] += 1
            continue

        # A name bound by an import Step 5d already tokenised bypasses every
        # filter below: leaving a use site un-abstracted while its import was
        # rewritten would emit code that no longer resolves.
        forced = symbol_key in forced_keys

        # Step 6: Skip non-significant nodes.  This has to run *after* the
        # symbol is resolved, so that `forced` can override it — `import
        # stripe as s` binds a single-character name that the significance
        # filter drops at every level below 'critical', which would rewrite
        # the import to `import MODULE_0` and leave `s.charge()` referring to
        # a name nothing binds.  Same for aliases shadowing a builtin.
        if not forced and not is_semantically_significant(node, privacy_level):
            stats['skipped_nodes'] += 1
            continue

        # Step 7: Classify node
        if redact_fragment:
            decision = Decision(
                label='SECRET', confidence=0.95, detector='fstring-template',
                evidence=['literal fragment of a credential-shaped f-string'],
            )
        elif rules.is_forced_secret(node_name):
            decision = Decision(
                label='SECRET', confidence=1.0, detector='override',
                evidence=['forced by .codeabstractignore'],
            )
            stats['overrides_applied'] += 1
        else:
            decision = classify_with_evidence(
                node,
                inherited_labels.get(id(node)),
                symbol_evidence.get(symbol_key) or context_evidence.get(id(node)),
            )
        label = decision.label
        if decision.needs_review:
            stats['low_confidence_nodes'] += 1

        # Phase 1: a 'keep' rule recovers utility for a name the classifier
        # over-reached on.  It deliberately cannot rescue a genuine secret:
        # if the node still classifies SECRET on its own evidence, the rule
        # is ignored, so no config file can put a credential on the wire.
        # It cannot rescue an abstracted import binding either, for the same
        # reason the significance filter cannot: the import is already
        # rewritten, so keeping the use site would leave it unresolvable.
        if not forced and label != 'SECRET' and rules.should_keep(node_name):
            stats['overrides_applied'] += 1
            stats['skipped_nodes'] += 1
            _record_kept(kept, node_name, 'keep rule', getattr(node, 'lineno', 1), label)
            continue

        # Check privacy level filtering (`forced` resolved above, alongside
        # the significance filter it also overrides).
        if not forced and not _should_abstract(label, privacy_level):
            stats['skipped_nodes'] += 1
            _record_kept(
                kept, node_name, f"privacy level '{privacy_level}'",
                getattr(node, 'lineno', 1), label,
            )
            continue

        # Update statistics
        if label == 'SECRET':
            stats['secrets_found'] += 1
        elif label == 'VALUE':
            stats['values_found'] += 1

        lineno = getattr(node, 'lineno', 1)

        # Step 8: Token generation (one token per symbol, reused across
        # every occurrence of that symbol)
        if symbol_key in seen:
            token = seen[symbol_key]
        else:
            # Determine effective node type for prefix selection.
            # If this Attribute is the func of a Call, treat as method → FUNC.
            node_type_name = type(node).__name__
            if isinstance(node, ast.Attribute):
                parent = parent_map.get(id(node))
                if isinstance(parent, ast.Call) and parent.func is node:
                    node_type_name = 'FunctionDef'  # → FUNC prefix

            # Generate new token
            prefix = label_to_prefix(label, node_type_name, node)
            token = token_gen.generate(prefix)

            # Store in mapping table
            mapping_table[token] = {
                'name': node_name,
                'label': label,
                'node_type': type(node).__name__,
                'lineno': lineno,
                'ctx': get_context(source_code, lineno, context_window, lines=source_lines),
                'scope': _scope_path(node, scopes),
                'confidence': decision.confidence,
                'detector': decision.detector,
                'evidence': decision.evidence,
            }

            # Cache token for reuse
            seen[symbol_key] = token

        # Phase 1: record every occurrence, and prefer the binding site as
        # the reported definition line.  Walk order is breadth-first, so a
        # use can be reached before its own definition.
        occurrences.setdefault(token, []).append({
            'lineno': lineno,
            'col': getattr(node, 'col_offset', 0),
        })
        if _is_binding_occurrence(node) and token not in definition_lines:
            definition_lines[token] = lineno

        # Step 9: Replace node in AST
        _replace_node_name(node, token, parent_map, in_fstring=in_fstring)
        stats['abstracted_nodes'] += 1

    # ───────────────────────────────────────────────────
    # Step 9b: Finalise mapping entries (Phase 1)
    # ───────────────────────────────────────────────────
    for token, entry in mapping_table.items():
        entry_occurrences = occurrences.get(token, [])
        entry['occurrences'] = entry_occurrences

        definition_line = definition_lines.get(token)
        if definition_line is None and entry_occurrences:
            definition_line = min(o['lineno'] for o in entry_occurrences)

        if definition_line is not None and definition_line != entry['lineno']:
            entry['lineno'] = definition_line
            entry['ctx'] = get_context(source_code, definition_line, context_window, lines=source_lines)

    stats['unique_symbols'] = len(mapping_table)
    stats['shadowed_symbols'] = _count_shadowed(mapping_table)

    # ───────────────────────────────────────────────────
    # Step 10: Unparse AST to abstract code
    # ───────────────────────────────────────────────────
    ast.fix_missing_locations(ast_tree)
    abstract_code = ast.unparse(ast_tree)

    # ───────────────────────────────────────────────────
    # Step 10b: Index abstract lines back to original lines (Phase 1)
    # ───────────────────────────────────────────────────
    # The mutated tree still carries the *original* line numbers — only
    # names were changed — so pairing it against a re-parse of the emitted
    # code yields the translation the LLM's "line N" citations need.
    line_map = _build_line_map(ast_tree, abstract_code)

    # ───────────────────────────────────────────────────
    # Step 10c: Optionally re-inject screened comments (Phase 1)
    # ───────────────────────────────────────────────────
    stats['comments_kept'] = 0
    if keep_comments:
        from core.comment_handler import extract_comments, reinject_comments

        name_to_token = {
            entry['name']: token for token, entry in mapping_table.items()
        }
        before = abstract_code
        abstract_code = reinject_comments(
            abstract_code=abstract_code,
            source_code=source_code,
            line_map=line_map,
            name_to_token=name_to_token,
        )
        if abstract_code != before:
            stats['comments_kept'] = (
                len(abstract_code.splitlines()) - len(before.splitlines())
            )
            # Injected lines shift the numbering the LLM will cite.
            line_map = _build_line_map(ast_tree, abstract_code)
        stats['comments_total'] = len(extract_comments(source_code))

    # ───────────────────────────────────────────────────
    # Step 11: Encrypt mapping
    # ───────────────────────────────────────────────────
    encrypted_mapping, encryption_key = encrypt_mapping(mapping_table)

    # ───────────────────────────────────────────────────
    # Step 12: Generate session ID
    # ───────────────────────────────────────────────────
    session_id = str(uuid.uuid4())

    return AbstractionResult(
        abstract_code=abstract_code,
        encrypted_mapping=encrypted_mapping,
        encryption_key=encryption_key,
        session_id=session_id,
        statistics=stats,
        line_map=line_map,
        kept=_finalise_kept(kept),
    )


# ═══════════════════════════════════════════════════════════
# Phase 4 — the ledger of what was kept
# ═══════════════════════════════════════════════════════════

def _record_kept(
    kept: Dict[tuple, Dict],
    name: str,
    reason: str,
    lineno: int,
    label: str,
) -> None:
    """
    Note a name that reached the LLM unchanged, and why.

    Phase 4.  Every count in ``statistics`` describes what was *hidden*,
    which is the half of the picture that reassures rather than informs.
    The privacy report needs the other half: an allowlisted import, a
    ``keep:`` rule and a name below the privacy level's threshold are all
    deliberate decisions, and the user is entitled to see each one rather
    than infer it from a total.

    Deduplicated by ``(name, reason)`` and counted, so a variable used
    forty times is one line in the report with an occurrence count.
    """
    key = (name, reason)
    record = kept.get(key)
    if record is None:
        kept[key] = {
            'name': name,
            'reason': reason,
            'label': label,
            'lineno': lineno,
            'occurrences': 1,
        }
        return

    record['occurrences'] += 1
    record['lineno'] = min(record['lineno'], lineno)


def _finalise_kept(kept: Dict[tuple, Dict]) -> list:
    """Return the kept ledger as a list ordered by first appearance."""
    return sorted(kept.values(), key=lambda r: (r['lineno'], r['name']))


# ═══════════════════════════════════════════════════════════
# Phase 1 / D4 — symbol identity
# ═══════════════════════════════════════════════════════════

def _symbol_key(node: ast.AST, node_name: str, scopes) -> tuple:
    """
    Build the cache key identifying the *symbol* an occurrence belongs to.

    Three namespaces, because three different things were previously
    colliding in one flat dict:

    * ``('var', scope_uid, name)`` — scoped variables, parameters,
      functions and classes.  This is the D4 fix: ``result`` in ``alpha``
      and ``result`` in ``beta`` resolve to different scopes and so become
      different symbols.
    * ``('attr', name)`` — attribute names.  Attributes belong to objects,
      not to lexical scopes, so ``self.api_key`` stays consistent across
      every method that touches it.
    * ``('const', type, value)`` — literals.  Keeping these out of the
      variable namespace stops a string literal ``"endpoint"`` sharing a
      token with a variable named ``endpoint``, which previously collapsed
      ``{"endpoint": endpoint}`` into ``{VAR_7: VAR_7}``.
    """
    if isinstance(node, ast.Attribute):
        return ('attr', node_name)

    if isinstance(node, ast.Constant):
        return ('const', type(node.value).__name__, node_name)

    scope = scopes.node_scopes.get(id(node), scopes.module_scope)

    # A function or class binds its own name in the *enclosing* scope, and
    # ScopeBuilder records the node there, so no adjustment is needed.
    binding_scope = resolve_binding_scope(node_name, scope)
    return ('var', binding_scope.uid, node_name)


def _aggregate_evidence_by_symbol(
    tree: ast.AST,
    scopes,
    context_evidence: Dict[int, "object"],
) -> Dict[tuple, "object"]:
    """
    Pool usage evidence across every occurrence of each symbol.

    A value is a credential because of what happens to it *anywhere*, not
    only at the occurrence being looked at. Reading a token out of the
    environment on one line and passing it to a logger on the next are
    facts about one symbol, and the classifier has to see both.

    Args:
        tree: Parsed module AST.
        scopes: The :class:`core.symbol_table.ScopeBuilder` for this tree.
        context_evidence: Per-node evidence from ``analyze_context``.

    Returns:
        symbol key → combined ContextEvidence.
    """
    from core.context_features import ContextEvidence

    pooled: Dict[tuple, ContextEvidence] = {}

    for node in ast.walk(tree):
        evidence = context_evidence.get(id(node))
        if evidence is None or not evidence.signals:
            continue

        name = _get_node_name(node)
        if not name:
            continue

        try:
            key = _symbol_key(node, name, scopes)
        except Exception as exc:
            # The unguarded call at the main traversal site (~line 240)
            # never raises on the 120-file real corpus, so this branch is
            # a safety net, not an expected path. Warn rather than swallow:
            # a node landing here means its evidence -- possibly a signal
            # that the value is a credential -- is silently dropped, which
            # is a privacy-relevant regression to lose track of.
            warnings.warn(
                f"_symbol_key failed for {type(node).__name__} {name!r}: "
                f"{exc!r}; evidence for this occurrence was dropped",
                RuntimeWarning,
                stacklevel=2,
            )
            continue

        pooled.setdefault(key, ContextEvidence()).signals.extend(evidence.signals)

    return pooled


def _scope_path(node: ast.AST, scopes) -> str:
    """Human-readable scope path recorded on the mapping entry."""
    if isinstance(node, ast.Attribute):
        return 'attribute'
    if isinstance(node, ast.Constant):
        return 'literal'

    scope = scopes.node_scopes.get(id(node), scopes.module_scope)
    name = _get_node_name(node)
    if not name:
        return scope.path
    return resolve_binding_scope(name, scope).path


def _is_binding_occurrence(node: ast.AST) -> bool:
    """
    True if this occurrence is where the symbol is *defined*.

    Used to pick the line reported to the developer.  A breadth-first walk
    can reach a use before its definition, so the first occurrence seen is
    not reliably the binding site.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                         ast.ClassDef, ast.arg)):
        return True
    if isinstance(node, ast.Name):
        return isinstance(node.ctx, ast.Store)
    return False


def _count_shadowed(mapping_table: Dict[str, Dict]) -> int:
    """
    Number of tokens whose name is shared by another, differently-scoped
    token.

    A non-zero value is the signal that scope-aware mapping is doing work
    the old flat cache could not: every one of these would have collapsed
    into a single token pointing at a single line.
    """
    counts: Dict[str, int] = {}
    for entry in mapping_table.values():
        counts[entry['name']] = counts.get(entry['name'], 0) + 1
    return sum(count for count in counts.values() if count > 1)


# ═══════════════════════════════════════════════════════════
# Phase 1 — abstract ↔ original line translation
# ═══════════════════════════════════════════════════════════

def _build_line_map(mutated_tree: ast.AST, abstract_code: str) -> Dict[int, int]:
    """
    Map each line of the emitted abstract code to its line in the original.

    The LLM only ever sees the unparsed output, so every line number it
    cites refers to that text.  Nothing translated those citations before,
    which meant "the bug is on line 4" pointed at line 4 of a file the
    developer has never seen.

    Abstraction renames nodes but never restructures the tree, so the
    mutated tree (which still carries original line numbers) and a re-parse
    of the emitted code are isomorphic.  Walking them in lockstep pairs the
    two numbering schemes.  The walk stops descending wherever the shapes
    disagree rather than guessing, so a partial map is possible but a wrong
    one is not.

    Args:
        mutated_tree: The AST after abstraction, still holding original linenos.
        abstract_code: The unparsed abstract source.

    Returns:
        ``{abstract_lineno: original_lineno}``.
    """
    try:
        abstract_tree = ast.parse(abstract_code)
    except SyntaxError:
        return {}

    line_map: Dict[int, int] = {}

    def pair(original: ast.AST, emitted: ast.AST) -> None:
        original_line = getattr(original, 'lineno', None)
        emitted_line = getattr(emitted, 'lineno', None)
        if original_line is not None and emitted_line is not None:
            # Outermost node wins: statement-level positions are the ones
            # an LLM actually cites.
            line_map.setdefault(emitted_line, original_line)

        original_children = list(ast.iter_child_nodes(original))
        emitted_children = list(ast.iter_child_nodes(emitted))
        if len(original_children) != len(emitted_children):
            return

        for original_child, emitted_child in zip(original_children, emitted_children):
            if type(original_child) is not type(emitted_child):
                continue
            pair(original_child, emitted_child)

    pair(mutated_tree, abstract_tree)
    return line_map


# ═══════════════════════════════════════════════════════════
# Phase 0 / D1 — SECRET label propagation
# ═══════════════════════════════════════════════════════════

def _is_secret_name(name: Optional[str]) -> bool:
    """True if *name* matches a SECRET pattern."""
    if not name:
        return False
    return matches_any(name.lower(), SECRET_PATTERNS)


def _target_is_secret(target: ast.AST) -> bool:
    """
    True if an assignment target names a secret.

    Handles plain names (``api_key = ...``), attributes
    (``self.api_key = ...``) and subscripts (``cfg["api_key"] = ...``).
    """
    if isinstance(target, ast.Name):
        return _is_secret_name(target.id)
    if isinstance(target, ast.Attribute):
        return _is_secret_name(target.attr)
    if isinstance(target, ast.Subscript):
        key = target.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return _is_secret_name(key.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_target_is_secret(elt) for elt in target.elts)
    return False


def _mark_secret(node: ast.AST, inherited: Dict[int, str]) -> None:
    """
    Mark *node* — and, for f-strings, its literal fragments — as SECRET.

    Marking is shallow by design: it follows the value being bound, not
    arbitrary sub-expressions, so ``token = build(user_id)`` does not drag
    ``user_id`` into the SECRET class.
    """
    if node is None:
        return

    inherited[id(node)] = 'SECRET'

    if isinstance(node, ast.JoinedStr):
        for value in node.values:
            if isinstance(value, ast.Constant):
                inherited[id(value)] = 'SECRET'


def _build_inherited_labels(tree: ast.AST) -> Dict[int, str]:
    """
    Propagate SECRET from binding contexts to the literals they bind.

    Phase 0 / D1.  Shape detection catches credentials that *look* like
    credentials; this catches the ones that do not.  ``db_pass = "hunter2"``
    carries no recognisable format and not enough entropy to trip any
    detector — the only signal is the name it is bound to, and that signal
    lives on a different AST node than the value.

    Covered bindings:

    * ``api_key = "..."`` and ``self.api_key = "..."`` (Assign, AnnAssign)
    * ``connect(password="...")`` (keyword arguments)
    * ``{"api_key": "..."}`` (dict entries)
    * ``if token == "...":`` (comparisons against a secret-named operand)

    Args:
        tree: Parsed AST.

    Returns:
        Mapping of ``id(node)`` → ``'SECRET'`` for every node that inherits
        the label.
    """
    inherited: Dict[int, str] = {}

    for node in ast.walk(tree):
        # ── name = "secret" / self.name = "secret" ──────
        if isinstance(node, ast.Assign):
            if any(_target_is_secret(t) for t in node.targets):
                _mark_secret(node.value, inherited)

        elif isinstance(node, ast.AnnAssign):
            if node.target is not None and _target_is_secret(node.target):
                _mark_secret(node.value, inherited)

        # ── f(password="secret") ───────────────────────
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if _is_secret_name(kw.arg):
                    _mark_secret(kw.value, inherited)

        # ── {"api_key": "secret"} ──────────────────────
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and _is_secret_name(key.value)
                ):
                    _mark_secret(value, inherited)

        # ── if api_key == "secret" ─────────────────────
        elif isinstance(node, ast.Compare):
            operands = [node.left] + list(node.comparators)
            if any(_target_is_secret(op) for op in operands):
                for op in operands:
                    if isinstance(op, (ast.Constant, ast.JoinedStr)):
                        _mark_secret(op, inherited)

    return inherited


# ═══════════════════════════════════════════════════════════
# Phase 0 / D1 — f-string fragment handling
# ═══════════════════════════════════════════════════════════

def _scan_fstrings(
    tree: ast.AST,
    inherited: Dict[int, str],
) -> Tuple[Set[int], Set[int]]:
    """
    Decide, per f-string, whether its literal fragments must be redacted.

    The previous implementation skipped every Constant inside a JoinedStr
    outright, to avoid corrupting the f-string during unparse.  That made
    f-strings a reliable exfiltration path at *every* privacy level:
    ``f"Bearer sk_live_..."`` was transmitted intact.

    The fix classifies the f-string as a whole.  A credential split between
    a literal prefix and an interpolation — as in::

        f"postgres://admin:{db_pass}@10.2.3.4:5432/prod_billing"

    matches no individual fragment, but the flattened template
    ``postgres://admin:{}@10.2.3.4:5432/prod_billing`` matches the
    connection-string detector. When the whole template reads as a secret,
    every literal fragment in it is redacted; otherwise fragments are left
    alone, as ordinary prose.

    Args:
        tree: Parsed AST.
        inherited: Label-inheritance map from :func:`_build_inherited_labels`.

    Returns:
        ``(all_fragment_ids, fragments_to_redact)``.
    """
    all_fragments: Set[int] = set()
    to_redact: Set[int] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue

        fragments = [
            child for child in node.values
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        ]
        for fragment in fragments:
            all_fragments.add(id(fragment))

        template = build_fstring_template(node)
        is_secret = (
            inherited.get(id(node)) == 'SECRET'
            or is_secret_value(template)
        )

        if is_secret:
            for fragment in fragments:
                # Empty fragments carry nothing and cannot hold a token.
                if fragment.value:
                    to_redact.add(id(fragment))

    return all_fragments, to_redact


# ═══════════════════════════════════════════════════════════
# Phase 0 / D3 — import abstraction
# ═══════════════════════════════════════════════════════════

def _register_imports(
    ast_tree: ast.AST,
    source_code: str,
    context_window: int,
    mapping_table: Dict[str, Dict],
    seen: Dict[tuple, str],
    token_gen: TokenGenerator,
    scopes,
    rules: OverrideRules,
    forced_keys: Set[tuple],
    preserved_keys: Set[tuple],
    stats: Dict,
    kept: Dict[tuple, Dict],
    definition_lines: Dict[str, int],
) -> None:
    """
    Tokenise non-allowlisted imports, and record allowlisted bindings.

    Runs *before* the main traversal so that a module's binding and every
    later use site resolve to the same token, whichever the walk reaches
    first.  Mutates ``mapping_table``, ``seen``, ``forced_names``,
    ``preserved_names`` and ``stats`` in place.

    Relative imports are always treated as internal: ``from .billing import
    ledger`` names a package belonging to the user, not a public one.
    """
    for node in ast.walk(ast_tree):

        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue

        # An import binds in whichever scope it appears in — usually the
        # module, but a function-local import binds locally.
        import_scope = scopes.node_scopes.get(id(node), scopes.module_scope)

        def binding_key(bound_name: str) -> tuple:
            return ('var', import_scope.uid, bound_name)

        # ── import x, import a.b.c ─────────────────────
        if isinstance(node, ast.Import):
            for alias in node.names:
                binding = alias.asname or alias.name.split('.', 1)[0]

                if is_safe_module(alias.name) or rules.is_safe_module(alias.name):
                    preserved_keys.add(binding_key(binding))
                    stats['modules_preserved'] += 1
                    _record_kept(
                        kept, alias.name, 'allowlisted module',
                        getattr(node, 'lineno', 1), 'IDENTIFIER',
                    )
                    continue

                token = _module_token(
                    original=alias.name,
                    binding_key=binding_key(binding),
                    node=node,
                    source_code=source_code,
                    context_window=context_window,
                    mapping_table=mapping_table,
                    seen=seen,
                    token_gen=token_gen,
                    definition_lines=definition_lines,
                )
                alias.name = token
                alias.asname = None
                forced_keys.add(binding_key(binding))
                stats['modules_abstracted'] += 1

        # ── from x import y ────────────────────────────
        else:
            # level > 0 means a relative import — always internal.
            module_is_safe = node.level == 0 and (
                is_safe_module(node.module) or rules.is_safe_module(node.module)
            )

            if not module_is_safe and node.module:
                node.module = _module_token(
                    original=node.module,
                    binding_key=None,
                    node=node,
                    source_code=source_code,
                    context_window=context_window,
                    mapping_table=mapping_table,
                    seen=seen,
                    token_gen=token_gen,
                    definition_lines=definition_lines,
                )

            for alias in node.names:
                # Wildcard imports bind no inspectable name.
                if alias.name == '*':
                    continue

                binding = alias.asname or alias.name

                if module_is_safe:
                    preserved_keys.add(binding_key(binding))
                    stats['modules_preserved'] += 1
                    _record_kept(
                        kept, f"{node.module}.{alias.name}", 'allowlisted module',
                        getattr(node, 'lineno', 1), 'IDENTIFIER',
                    )
                    continue

                token = _module_token(
                    original=alias.name,
                    binding_key=binding_key(binding),
                    node=node,
                    source_code=source_code,
                    context_window=context_window,
                    mapping_table=mapping_table,
                    seen=seen,
                    token_gen=token_gen,
                    definition_lines=definition_lines,
                )
                alias.name = token
                alias.asname = None
                forced_keys.add(binding_key(binding))
                stats['modules_abstracted'] += 1


def _module_token(
    original: str,
    binding_key: Optional[tuple],
    node: ast.AST,
    source_code: str,
    context_window: int,
    mapping_table: Dict[str, Dict],
    seen: Dict[tuple, str],
    token_gen: TokenGenerator,
    definition_lines: Dict[str, int],
) -> str:
    """
    Return a stable ``MODULE_n`` token for *original*, creating it if needed.

    When *binding_key* is given, the token is also cached under the bound
    symbol so that use sites (``stripe.charge()``) reuse it.  The module
    path itself lives in its own ``('module', …)`` namespace so that a
    variable which happens to share the module's name does not collide
    with it.

    The entry carries the same ``confidence``/``detector``/``evidence``
    fields the main loop writes, so every row in the mapping table has one
    shape, and seeds ``definition_lines`` with the import statement: the
    main walk skips ``ast.alias`` nodes, so without this Step 9b would find
    no binding occurrence and fall back to the first *use* line.
    """
    module_key = ('module', original)

    if module_key in seen:
        token = seen[module_key]
    else:
        token = token_gen.generate('MODULE')
        lineno = getattr(node, 'lineno', 1)
        mapping_table[token] = {
            'name': original,
            'label': 'IDENTIFIER',
            'node_type': 'alias',
            'lineno': lineno,
            'ctx': get_context(source_code, lineno, context_window),
            'scope': 'import',
            'confidence': 1.0,
            'detector': 'import',
            'evidence': ['module import'],
        }
        definition_lines[token] = lineno
        seen[module_key] = token

    if binding_key:
        seen[binding_key] = token

    return token


# ═══════════════════════════════════════════════════════════
# Private helper functions
# ═══════════════════════════════════════════════════════════

def _get_node_name(node: ast.AST) -> Optional[str]:
    """Extract the identifier name from an AST node."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    elif isinstance(node, ast.ClassDef):
        return node.name
    elif isinstance(node, ast.arg):
        return node.arg
    elif isinstance(node, ast.Attribute):
        return node.attr
    elif isinstance(node, ast.alias):
        return node.asname or node.name.split('.', 1)[0]
    elif isinstance(node, ast.Constant):
        return str(node.value)
    return None


def _replace_node_name(
    node: ast.AST,
    token: str,
    parent_map: Optional[Dict[int, ast.AST]] = None,
    in_fstring: bool = False,
):
    """
    Replace the node's identifier with the given token.

    For Constant nodes, swaps the node with an ast.Name so that
    ast.unparse() emits the token *unquoted* (e.g. ``CONST_1``
    instead of ``'CONST_1'``).

    Inside an f-string that swap is illegal — ``JoinedStr.values`` accepts
    only Constant and FormattedValue — so the fragment's string content is
    rewritten in place instead, yielding ``f'SECRET_0{VAR_1}'``.  The token
    is still plain text in the emitted code, so RECONSTRUCT resolves it
    exactly as it would anywhere else.
    """
    if isinstance(node, ast.Name):
        node.id = token
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node.name = token
    elif isinstance(node, ast.ClassDef):
        node.name = token
    elif isinstance(node, ast.arg):
        node.arg = token
    elif isinstance(node, ast.Attribute):
        node.attr = token
    elif isinstance(node, ast.alias):
        node.name = token
        node.asname = None
    elif isinstance(node, ast.Constant):
        if in_fstring:
            # Keep it a Constant; rewrite the literal text it contributes.
            node.value = token
            return
        # Swap Constant → Name so unparse doesn't add quotes
        replacement = ast.Name(id=token, ctx=ast.Load())
        ast.copy_location(replacement, node)
        if parent_map is not None:
            parent = parent_map.get(id(node))
            if parent:
                _swap_child(parent, node, replacement)
                return
        # Fallback: modify value in-place (will be quoted)
        node.value = token


def _swap_child(
    parent: ast.AST,
    old_node: ast.AST,
    new_node: ast.AST,
):
    """
    Replace *old_node* with *new_node* inside *parent*.

    Walks every field of the parent AST node.  If the field holds
    a single node reference, it is replaced directly via setattr.
    If the field holds a list (e.g. ``body``, ``targets``), the
    matching element is swapped in-place.
    """
    for field, value in ast.iter_fields(parent):
        if value is old_node:
            setattr(parent, field, new_node)
            return
        if isinstance(value, list):
            for i, item in enumerate(value):
                if item is old_node:
                    value[i] = new_node
                    return


def _should_abstract(label: str, privacy_level: str) -> bool:
    """
    Determine whether a node should be abstracted based on its
    classification label and the current privacy level.

    Phase 0 / D5: this now reads the ``PRIVACY_LEVELS`` table in
    ``config.settings`` rather than duplicating its rules inline.  The
    table was previously dead code, which is how ``critical`` came to be
    indistinguishable from ``high``.

    Privacy levels control aggressiveness:
    - low:      Only SECRET
    - medium:   SECRET + VALUE
    - high:     SECRET + VALUE + IDENTIFIER
    - critical: Everything, including single-character names
    """
    level = PRIVACY_LEVELS.get(privacy_level, PRIVACY_LEVELS['medium'])

    if label == 'SECRET':
        return level.get('abstract_secrets', True)
    if label == 'VALUE':
        return level.get('abstract_values', False)
    return level.get('abstract_identifiers', False)
