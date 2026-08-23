"""
Value-Level Secret Detection

Phase 0 / D1 fix.

The original CLASSIFY(E) implementation judged a node purely on its *name*.
That left every secret **value** exposed: a variable named ``api_key`` was
tokenised, but the string literal holding the key was a separate Constant
node judged on its own text, and so was transmitted verbatim.

This module detects secrets by the *shape of the value itself*, independently
of what the surrounding identifier happens to be called:

* ``looks_like_credential(value)`` — high-confidence known credential formats
  (Stripe, AWS, GitHub, Slack, Google, OpenAI, JWT, PEM blocks, connection
  strings carrying inline credentials, ``Authorization`` header values).
* ``is_high_entropy_secret(value)`` — the long tail: opaque high-entropy
  strings that match no known vendor format.
* ``is_secret_value(value)`` — the union of the two, used by CLASSIFY.

Detection here runs at **every privacy level**, including ``low``.  A
credential is never business-sensitive-but-shareable; it is always a secret.
"""

import math
import re
from collections import Counter
from typing import Optional

# ═══════════════════════════════════════════════════════════
# Known credential formats
# ═══════════════════════════════════════════════════════════
# Ordered roughly by specificity.  Each entry is (name, compiled pattern).
# These are matched against the raw literal value, case-sensitively unless
# the pattern says otherwise, because most vendor prefixes are case-bearing.

_CREDENTIAL_PATTERNS = [
    # ── Payment providers ────────────────────────────────
    ("stripe",      re.compile(r'\b[sprk]k_(live|test)_[A-Za-z0-9]{8,}')),
    ("paypal",      re.compile(r'\b(?:access_token\$production\$|ppsecret_)[A-Za-z0-9_\-]{8,}')),

    # ── Cloud providers ──────────────────────────────────
    ("aws_access",  re.compile(r'\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b')),
    ("google",      re.compile(r'\bAIza[0-9A-Za-z_\-]{35}\b')),
    ("azure_sas",   re.compile(r'\bsig=[A-Za-z0-9%/+]{40,}')),

    # ── Source hosting ───────────────────────────────────
    ("github",      re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b')),
    ("github_pat",  re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}\b')),
    ("gitlab",      re.compile(r'\bglpat-[A-Za-z0-9_\-]{16,}\b')),

    # ── Messaging / SaaS ─────────────────────────────────
    ("slack",       re.compile(r'\bxox[abposr]-[A-Za-z0-9\-]{8,}')),
    ("sendgrid",    re.compile(r'\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}')),
    ("twilio",      re.compile(r'\bSK[0-9a-fA-F]{32}\b')),
    ("shopify",     re.compile(r'\bshp(at|ca|pa|ss)_[0-9a-fA-F]{32}\b')),
    ("npm",         re.compile(r'\bnpm_[A-Za-z0-9]{36}\b')),

    # ── AI providers ─────────────────────────────────────
    ("anthropic",   re.compile(r'\bsk-ant-[A-Za-z0-9_\-]{16,}')),
    ("openai",      re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}')),

    # ── Secret managers ──────────────────────────────────
    ("vault",       re.compile(r'\bhvs\.[A-Za-z0-9_\-]{20,}')),

    # ── Format-based (vendor agnostic) ───────────────────
    # JSON Web Token: two base64url segments, both starting with the
    # canonical '{"' prefix that encodes to 'eyJ'.
    ("jwt",         re.compile(r'\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}')),
    # PEM armoured private key / certificate blocks.
    ("pem",         re.compile(r'-----BEGIN[ A-Z]*(?:PRIVATE KEY|RSA|CERTIFICATE|OPENSSH)')),
    # Authorization header values: "Bearer <blob>", "Basic <blob>", "Token <blob>".
    # The blob may be an interpolation placeholder ("{}") rather than a
    # literal.  f"Bearer {token}" is how an auth header is actually built,
    # and requiring 8+ literal characters meant the flattened template
    # "Bearer {}" matched nothing — the very case build_fstring_template
    # exists to catch, and the one its docstring cites.  Only the exact
    # "{}" that flattening emits is accepted, so ordinary prose ("bearer of
    # this note", "the token is missing") stays unflagged.
    ("auth_header", re.compile(
        r'(?i)\b(?:bearer|basic|token)\s+(?:\{\}|[A-Za-z0-9._\-+/=]{8,})')),
    # Connection strings carrying inline credentials:
    #   postgres://user:password@host/db     mongodb+srv://u:p@cluster
    # The password position may be an f-string placeholder ("{}"), which is
    # exactly the case that leaked before this fix.
    ("conn_string", re.compile(r'\b[a-z][a-z0-9+.\-]*://[^\s:@/]+:[^\s@/]*@')),
]

# Values that look secret-ish but are placeholders, not real credentials.
# Redacting these costs utility for no privacy gain.
#
# The marker word must be the whole value, or be followed by an explicit
# `_`/`-` separator before any further word/hyphen text. Two bugs this
# guards against, both found by direct testing rather than inferred:
#
# 1. The old `word[_\-]?\w*` shape allowed only *one* separator before a
#    run of `\w` (which excludes `-`), so a multi-hyphen placeholder like
#    "your-api-key-here" itself -- the exact example in this module's own
#    docstring -- failed to match past "your-api" and fell through to
#    entropy scoring as a live secret.
# 2. Requiring the separator (rather than making it optional) matters more
#    than that: "my"/"your"/"some" are ordinary English words, and a real
#    credential that happens to start with one -- "mySuperSecretProd...",
#    "yourCompanyStripeLiveKey..." -- was being swallowed by the *previous*
#    fix's `word[\w\-]*` (optional separator, so the marker matched with no
#    separator at all and `\w*` mopped up the rest), silently exempting it
#    from secret detection. Real placeholders are written with an explicit
#    separator; real secrets that start with these words are not.
_PLACEHOLDER_PATTERN = re.compile(
    r'(?i)^(?:'
    r'x{3,}|\*{3,}|\.{3,}|-{3,}|_{3,}|'
    r'(?:your|my|some)(?:[_\-][\w\-]*)?|'
    r'<[^>]*>|\{\{[^}]*\}\}|\$\{[^}]*\}|'
    r'(?:test|dummy|sample|example|placeholder|changeme|todo|fixme|redacted|none|null)'
    r'(?:[_\-][\w\-]*)?'
    r')$'
)

# A scheme://host URL with no inline credentials is a business VALUE
# (an endpoint), not a secret.  Excluded from the entropy path so that
# "https://api.payment.com/v2" is not misfiled as a credential.
_BARE_URL_PATTERN = re.compile(r'^[a-z][a-z0-9+.\-]*://', re.IGNORECASE)

# Entropy thresholds.  Deliberately conservative: a false positive here
# costs LLM utility, and the name-based and propagation paths already catch
# the common cases that fall below these bars.
_MIN_ENTROPY_LENGTH = 24
_MIN_ENTROPY_BITS = 3.8


def shannon_entropy(text: str) -> float:
    """
    Shannon entropy of *text* in bits per character.

    A uniformly random lowercase-alphanumeric string scores ~5.2;
    English prose scores ~2.5–3.5.

    Args:
        text: The string to measure.

    Returns:
        Entropy in bits per character (0.0 for empty or single-character input).
    """
    if not text:
        return 0.0

    length = len(text)
    counts = Counter(text)
    return -sum(
        (count / length) * math.log2(count / length)
        for count in counts.values()
    )


def as_text(value) -> str:
    """
    Coerce a literal to the text the detectors match against.

    ``str`` passes through.  ``bytes`` and ``bytearray`` are decoded as
    UTF-8, because every credential format in
    :data:`_CREDENTIAL_PATTERNS` is an ASCII wire format and the code that
    handles one often holds it as bytes -- ``hmac.new(b"sk_live_...")`` is
    the idiomatic spelling.  Judging ``b"sk_live_..."`` only by what
    ``str()`` happens to render made the literal's *prefix* decide whether
    the credential was detected.

    Undecodable bytes are a binary blob rather than text, and return ``''``
    so the caller treats them as carrying no signal instead of raising.

    Args:
        value: A ``str``, ``bytes`` or ``bytearray`` literal.

    Returns:
        The decoded text, or ``''`` for anything else.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode('utf-8')
        except UnicodeDecodeError:
            return ''
    return ''


def matched_credential_format(value) -> Optional[str]:
    """
    Return the name of the credential format *value* matches, or None.

    Exposed separately from :func:`looks_like_credential` so that the
    privacy report (Phase 4) can tell the user *which* detector fired.

    Args:
        value: Raw literal value.

    Returns:
        Format name (e.g. ``'stripe'``, ``'jwt'``) or None.
    """
    value = as_text(value)
    if not value:
        return None

    for name, pattern in _CREDENTIAL_PATTERNS:
        if pattern.search(value):
            return name
    return None


def looks_like_credential(value) -> bool:
    """
    True if *value* matches a known credential format.

    High precision: these patterns encode vendor-published key formats,
    so a match is near-certain to be a real secret.

    Args:
        value: Raw literal value.

    Returns:
        True if the value matches a known credential shape.
    """
    return matched_credential_format(value) is not None


def is_placeholder(value) -> bool:
    """
    True if *value* is an obvious placeholder rather than a live secret.

    Placeholders (``"your-api-key-here"``, ``"xxxxx"``, ``"<TOKEN>"``) are
    left intact: redacting them removes context the LLM needs and protects
    nothing.

    Args:
        value: Raw literal value.

    Returns:
        True if the value looks like a placeholder.
    """
    value = as_text(value)
    if not value:
        return False
    return _PLACEHOLDER_PATTERN.match(value.strip()) is not None


def is_high_entropy_secret(value) -> bool:
    """
    True if *value* is a long, opaque, high-entropy string.

    Catches the tail of credentials that match no published vendor format.
    Guarded against the common false positives: prose (contains whitespace),
    endpoints (bare ``scheme://`` URLs), filesystem paths, and single-class
    strings such as long hyphenated slugs.

    Args:
        value: Raw literal value.

    Returns:
        True if the value looks like an opaque secret blob.
    """
    value = as_text(value)
    if not value:
        return False

    candidate = value.strip()

    # Prose and multi-word values are not opaque blobs.
    if len(candidate) < _MIN_ENTROPY_LENGTH or re.search(r'\s', candidate):
        return False

    # Endpoints and filesystem paths are business VALUEs, not credentials.
    if _BARE_URL_PATTERN.match(candidate):
        return False
    if candidate.startswith(('/', './', '../', '~/')) or re.match(r'^[A-Za-z]:[\\/]', candidate):
        return False

    if is_placeholder(candidate):
        return False

    # Require genuine character-class mixing: opaque keys carry both
    # letters and digits.  This rejects long dotted module paths and
    # kebab-case slugs, which are structural, not secret.
    has_letter = bool(re.search(r'[A-Za-z]', candidate))
    has_digit = bool(re.search(r'\d', candidate))
    if not (has_letter and has_digit):
        return False

    return shannon_entropy(candidate) >= _MIN_ENTROPY_BITS


# A dotted quad with every octet in range.  Deliberately strict: '1.0' is a
# version, '10.9.9.9' is a host, and a looser pattern makes the difference
# invisible.
_IPV4_PATTERN = re.compile(
    r'^(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}'
    r'(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$'
)


def is_endpoint_value(value) -> bool:
    """
    True if *value* is an endpoint literal — a URL or an IPv4 address.

    The ``medium`` privacy level is documented as abstracting business
    VALUEs "rates, fees, endpoints", and it did so only when the
    *identifier* was named like one.  The literal was a separate node with
    no name of its own, so ``endpoint_url = "https://api.payment.com/v2"``
    tokenised the name and transmitted the URL — the same split between
    binding and value that Phase 0 / D1 fixed on the SECRET axis and left
    open on this one.

    Credentials are handled before this is consulted, so a connection
    string carrying an inline password is already a SECRET and never
    reaches here as a mere endpoint.

    Deliberately narrow: URLs and dotted quads only.  A bare hostname is
    not included because ``foo.bar.baz`` is as likely to be a module path
    or a filename as a host, and a false VALUE costs the LLM the context it
    needs to be useful.

    Args:
        value: Raw literal value.

    Returns:
        True if the value names a network endpoint.
    """
    value = as_text(value)
    if not value:
        return False

    candidate = value.strip()
    if is_placeholder(candidate):
        return False

    return bool(
        _BARE_URL_PATTERN.match(candidate) or _IPV4_PATTERN.match(candidate)
    )


def is_secret_value(value) -> bool:
    """
    True if *value* should be treated as a secret on the strength of its
    own content, regardless of the identifier it is bound to.

    This is the entry point used by CLASSIFY(E).  It fires at every privacy
    level — see module docstring.

    Args:
        value: Raw literal value.

    Returns:
        True if the value is a credential or an opaque high-entropy blob.
    """
    value = as_text(value)
    if not value:
        return False

    if is_placeholder(value):
        return False

    return looks_like_credential(value) or is_high_entropy_secret(value)


def build_fstring_template(node) -> str:
    """
    Reconstruct an f-string as a flat template for whole-value classification.

    Literal fragments are concatenated verbatim and interpolations collapse
    to ``{}``.  This is what makes connection strings detectable: in

        f"postgres://admin:{db_pass}@10.2.3.4:5432/prod_billing"

    no individual fragment carries the ``user:pass@host`` shape, but the
    assembled template ``postgres://admin:{}@10.2.3.4:5432/prod_billing``
    does.

    Args:
        node: An ``ast.JoinedStr`` node.

    Returns:
        The flattened template string.
    """
    import ast  # local import: keeps this module import-light for reuse

    parts = []
    for value in getattr(node, 'values', []):
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append('{}')
    return ''.join(parts)
