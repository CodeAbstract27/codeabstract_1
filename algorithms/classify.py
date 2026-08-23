"""
CLASSIFY(E) Algorithm Implementation

Implements formal Algorithm 2 from specification.

Classifies AST nodes into sensitivity categories:
- SECRET: credentials, API keys, tokens, passwords
- VALUE: business-sensitive values (prices, rates, endpoints)
- IDENTIFIER: default classification

Phase 0 / D1: classification now considers three signals, not one.

  1. The node's *name*      — the original regex pass over SECRET/VALUE patterns.
  2. The node's *value*     — shape-based credential detection (see
                              ``core.secret_detector``).  This is what stops a
                              literal like ``"sk_live_..."`` being transmitted
                              verbatim just because the Constant node holding
                              it has no name of its own.
  3. An *inherited* label   — propagated from the binding context, so that
                              ``db_pass = "hunter2"`` marks the literal SECRET
                              even though neither the value's shape nor the
                              literal's own text gives it away.

Signals are evaluated most-conservative-first: any one of them saying SECRET
wins.
"""

import ast
import re
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Sequence

from config.patterns import SECRET_PATTERNS, VALUE_PATTERNS
from core.pattern_matcher import matches_any
from core.secret_detector import (
    as_text,
    build_fstring_template,
    is_endpoint_value,
    is_high_entropy_secret,
    is_placeholder,
    is_secret_value,
    matched_credential_format,
)

Label = Literal['SECRET', 'VALUE', 'IDENTIFIER']

# Confidence below which a decision is worth a human glance rather than
# silent application. Surfaced by the CLI review step.
REVIEW_THRESHOLD = 0.60


@dataclass
class Decision:
    """
    A classification together with its confidence and its reasons.

    Phase 2.  The original CLASSIFY returned a bare label, which made every
    decision equally authoritative: a vendor-format key match and a
    substring hit on ``.*auth.*`` were indistinguishable downstream.  That
    is fine for a pure regex system and useless for a hybrid one, where the
    whole point is to route confident cases automatically and uncertain
    ones to review.
    """

    label: Label
    confidence: float
    detector: str
    evidence: List[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        """True if this decision is too uncertain to apply silently."""
        return self.confidence < REVIEW_THRESHOLD

    def describe(self) -> str:
        """One-line justification for the privacy report."""
        reasons = "; ".join(self.evidence) if self.evidence else "no specific evidence"
        return f"{self.label} ({self.confidence:.2f}, {self.detector}): {reasons}"


def classify_with_evidence(
    node: ast.AST,
    inherited: Optional[str] = None,
    context=None,
) -> Decision:
    """
    Hybrid classification: decide a label, a confidence, and the reasons.

    Phase 2.  Detectors are consulted in descending order of precision, and
    the first one to fire wins.  Ordering matters more than any individual
    detector: a vendor-published key format is near-certain evidence, while
    a substring match on ``.*auth.*`` is a hint, and collapsing the two into
    one boolean was what made the old classifier impossible to tune.

    Tiers, highest precision first:

    1. **Known credential format** — the value matches a published vendor
       key layout (Stripe, AWS, JWT, PEM …).  Definitional, not heuristic.
    2. **Propagated / context** — the binding says so: assigned to
       ``api_key``, passed as ``password=``, read from ``os.environ``.
       See ``core.context_features``.
    3. **Name pattern** — the original regex pass.
    4. **Entropy** — long opaque blobs matching no known format.
    5. **Numeric literal** — business-sensitive by default.

    Args:
        node: AST node E.
        inherited: Label propagated from the binding context, if any.
        context: Optional :class:`core.context_features.ContextEvidence`
            for this node.

    Returns:
        A :class:`Decision`.
    """
    literal = _get_literal_text(node)
    return classify_signals(
        text=_get_node_text(node),
        literal=literal,
        is_numeric_literal=(
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float, complex))
        ),
        inherited=inherited,
        context_score=context.score if context is not None else 0.0,
        context_signals=context.signals if context is not None else [],
        # Bare-literal only: a name (empty `literal`) still runs the
        # normal Tier 3 name-pattern check unaffected. See Tier 3 below.
        literal_is_placeholder=(
            isinstance(node, (ast.Constant, ast.JoinedStr))
            and bool(literal)
            and is_placeholder(literal)
        ),
    )


def classify_signals(
    text: str = "",
    literal: str = "",
    is_numeric_literal: bool = False,
    inherited: Optional[str] = None,
    context_score: float = 0.0,
    context_signals: Optional[Sequence[str]] = None,
    literal_is_placeholder: bool = False,
) -> Decision:
    """
    The classification tiers, over plain signals rather than an AST node.

    Phase 4 split this out of :func:`classify_with_evidence` so that a
    second language can reach the same decisions. The JavaScript adapter
    has a tree-sitter CST, not a Python ``ast`` node, and re-implementing
    the tiers against it would have produced two detectors that drift apart
    — with the evaluation measuring only one of them.

    Args:
        text: Combined name-and-value text, the signal the name patterns
            match against.
        literal: Raw literal content, for value-shape detection.
        is_numeric_literal: True if the node is a numeric constant.
        inherited: Label propagated from the binding context.
        context_score: Usage-signal score (:mod:`core.context_features`).
        context_signals: Names of the usage signals that fired.
        literal_is_placeholder: True when ``literal`` is itself a
            recognised placeholder ("your-api-key-here"). Tier 3's
            name-pattern match runs over ``text``, which for a bare
            literal *is* the literal's own content -- without this,
            placeholder prose that mentions a credential-sounding word
            ("api", "key", "secret") was promoted to SECRET by the very
            text that marks it as a placeholder to a human reader too.
            Left ``False`` (the default) for identifier names, where
            ``literal`` is empty and Tier 3 must fire normally.

    Returns:
        A :class:`Decision`.
    """
    context_signals = list(context_signals or [])

    # ── Tier 1: known credential format ────────────────
    if literal:
        vendor_format = matched_credential_format(literal)
        if vendor_format:
            return Decision(
                label='SECRET',
                confidence=0.99,
                detector='credential-format',
                evidence=[f"matches published {vendor_format} key format"],
            )

    # ── Tier 2: binding context ────────────────────────
    if inherited == 'SECRET' or context_score >= 0.80:
        reasons = (
            [f"usage: {signal}" for signal in sorted(set(context_signals))]
            or ["propagated from a secret-named binding"]
        )
        return Decision(
            label='SECRET',
            confidence=max(0.90, context_score),
            detector='context',
            evidence=reasons,
        )

    # ── Tier 3: name patterns ──────────────────────────
    text_lower = text.lower() if text else ""

    if text_lower and matches_any(text_lower, SECRET_PATTERNS) and not literal_is_placeholder:
        return Decision(
            label='SECRET',
            confidence=0.75,
            detector='name-pattern',
            evidence=["identifier matches a SECRET name pattern"],
        )

    # ── Tier 4: entropy ────────────────────────────────
    if literal and is_high_entropy_secret(literal):
        return Decision(
            label='SECRET',
            confidence=0.65,
            detector='entropy',
            evidence=["long, opaque, high-entropy literal"],
        )

    if text_lower and matches_any(text_lower, VALUE_PATTERNS):
        return Decision(
            label='VALUE',
            confidence=0.70,
            detector='name-pattern',
            evidence=["identifier matches a business VALUE pattern"],
        )

    # ── Tier 4b: endpoint literals ─────────────────────
    # The VALUE counterpart of Tier 1: an endpoint is an endpoint whatever
    # the identifier holding it is called. Without this, ``medium`` matched
    # its documentation only when the *name* said "url" -- and tokenised
    # that name while sending the URL it was bound to.
    if literal and is_endpoint_value(literal):
        return Decision(
            label='VALUE',
            confidence=0.70,
            detector='endpoint-literal',
            evidence=["literal is a URL or IP address"],
        )

    # ── Tier 5: numeric literals ───────────────────────
    if is_numeric_literal:
        return Decision(
            label='VALUE',
            confidence=0.55,
            detector='literal-type',
            evidence=["numeric literal, business-sensitive by default"],
        )

    # ── Weak context, below the SECRET bar ─────────────
    if context_score > 0.0:
        return Decision(
            label=inherited or 'IDENTIFIER',
            confidence=round(0.50 + context_score / 2, 4),
            detector='context-weak',
            evidence=[f"usage: {signal}" for signal in sorted(set(context_signals))],
        )

    if inherited:
        return Decision(
            label=inherited,
            confidence=0.60,
            detector='inherited',
            evidence=["propagated from the enclosing binding"],
        )

    return Decision(
        label='IDENTIFIER',
        confidence=0.50,
        detector='default',
        evidence=["no sensitivity signal found"],
    )


def classify_node(node: ast.AST, inherited: Optional[str] = None) -> Label:
    """
    CLASSIFY(E) — Sensitivity Classification Algorithm.

    Examines an AST node's name, its literal value, and any label inherited
    from its binding context to determine sensitivity classification.

    Args:
        node: AST node E.
        inherited: Optional label propagated from the enclosing assignment,
            keyword argument or dict entry.  ``'SECRET'`` here forces a
            SECRET classification — see ``algorithms.abstract`` for how the
            inheritance map is built.

    Returns:
        Label: 'SECRET', 'VALUE', or 'IDENTIFIER'.

    Implements:
        Algorithm 2 from formal specification.
    """
    # ── Step 0: inherited label wins outright ──────────
    # A literal bound to a secret-named target is a secret, whatever it
    # looks like on its own.
    if inherited == 'SECRET':
        return 'SECRET'

    # ── Step 1: value-shape detection ──────────────────
    # Runs before name matching because a credential is a credential
    # regardless of what the surrounding identifier is called.
    literal = _get_literal_text(node)
    if literal and is_secret_value(literal):
        return 'SECRET'

    # A bare literal whose own text is a recognised placeholder ("your-
    # api-key-here") must not be promoted to SECRET at Step 3 just because
    # that placeholder prose *mentions* a credential-sounding word -- that
    # is the same reason it reads as a placeholder to a human. This is
    # narrowed to literal nodes: an identifier *name* still runs the
    # SECRET_PATTERNS check normally, and a literal bound to a secret-
    # named target was already forced to SECRET in Step 0 above.
    is_bare_literal = isinstance(node, (ast.Constant, ast.JoinedStr))
    literal_is_placeholder = bool(literal) and is_placeholder(literal)

    # ── Step 2: extract text signal from node ──────────
    text = _get_node_text(node)

    if not text:
        return inherited or 'IDENTIFIER'

    # Convert to lowercase for case-insensitive matching
    text_lower = text.lower()

    # ── Step 3: check SECRET patterns ──────────────────
    if matches_any(text_lower, SECRET_PATTERNS) and not (is_bare_literal and literal_is_placeholder):
        return 'SECRET'

    # ── Step 4: check VALUE patterns ───────────────────
    if matches_any(text_lower, VALUE_PATTERNS):
        return 'VALUE'

    # ── Step 4b: numeric constants are inherently business-sensitive ──
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, complex)):
        return 'VALUE'

    # ── Step 5: fall back to inherited, then default ───
    if inherited:
        return inherited

    return 'IDENTIFIER'


def _get_literal_text(node: ast.AST) -> str:
    """
    Extract the raw string content a node carries, for value-shape detection.

    For a plain ``Constant`` this is the string itself.  For an f-string
    (``JoinedStr``) it is the flattened template, so that a credential split
    across literal fragments and interpolations is still detectable — see
    :func:`core.secret_detector.build_fstring_template`.

    Args:
        node: AST node.

    Returns:
        The literal text, or an empty string if the node carries none.
    """
    if isinstance(node, ast.Constant):
        # ``bytes`` as well as ``str``: every credential format the
        # detector knows is an ASCII wire format, and code that speaks to a
        # socket or an HMAC routine holds one as bytes.  Restricting this to
        # ``str`` let ``b"sk_live_..."`` past value-shape detection
        # entirely -- see ``core.secret_detector.as_text``.
        return as_text(node.value)

    if isinstance(node, ast.JoinedStr):
        return build_fstring_template(node)

    return ""


def _get_node_text(node: ast.AST) -> str:
    """
    Combine name(E) and literal_value(E) as text signal.

    Extracts all relevant textual information from the AST node
    to feed into pattern matching.

    Args:
        node: AST node.

    Returns:
        Combined text string for pattern matching.
    """
    text_parts: List[str] = []

    # Extract name from various node types
    if isinstance(node, ast.Name):
        text_parts.append(node.id)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        text_parts.append(node.name)
    elif isinstance(node, ast.ClassDef):
        text_parts.append(node.name)
    elif isinstance(node, ast.arg):
        text_parts.append(node.arg)
    elif isinstance(node, ast.Attribute):
        text_parts.append(node.attr)
    elif isinstance(node, ast.alias):
        # Phase 0 / D3: imports carry vendor and internal package names.
        text_parts.append(node.asname or node.name)

    # Extract literal value from Constant nodes
    if isinstance(node, ast.Constant):
        text_parts.append(str(node.value))

    # For assignment nodes, also check target names and values
    elif isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                text_parts.append(target.id)
        if isinstance(node.value, ast.Constant):
            text_parts.append(str(node.value.value))

    return ' '.join(text_parts)
