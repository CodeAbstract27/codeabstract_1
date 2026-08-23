"""
Privacy Report

Phase 4 — output format #5 in the proposal, absent until now.

Every number the tool printed after a run described what it had *hidden*:
"42 identifiers abstracted", "13 secrets found". Those are reassuring and
close to useless. What a user needs before pressing send is the opposite
list — what is still in the payload, and on whose decision.

So the report has three sections, in the order they matter:

1. **Kept** — what remains readable in the outbound code, each with the
   reason it survived: an allowlisted import, a ``keep:`` rule, or a
   privacy level that does not cover its category. This is the exposure
   surface, and it is deliberately printed first.
2. **Unsure** — decisions the detector made below its own review
   threshold. A hybrid detector that reports confidence and then hides it
   is no better than the regex system it replaced (Phase 2).
3. **Hidden** — what was replaced, grouped by label and by which detector
   fired. Useful for auditing the *detector*, which is why the evidence
   travels with each entry.

**Secret values are masked by default.** A mapping entry's ``name`` for a
SECRET is frequently the credential itself — that is what redaction means.
Writing the report to a file would otherwise copy every secret in the file
into a second plaintext artifact, defeating the run that produced it.
:func:`build_report` masks them unless the caller passes ``reveal=True``,
which the CLI only does for terminal display.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from algorithms.classify import REVIEW_THRESHOLD

# Longest prefix of a secret shown when masking. Enough to recognise which
# credential an entry refers to, far too little to use.
MASK_PREFIX = 3


def mask_secret(value: str) -> str:
    """
    Render a secret so it can be identified but not used.

    ``sk_live_51H8xY…`` becomes ``sk_…(24 chars)``. Short values are hidden
    entirely: three characters of a six-character password is most of it.
    """
    text = str(value)
    if len(text) <= MASK_PREFIX * 2:
        return f"…({len(text)} chars)"
    return f"{text[:MASK_PREFIX]}…({len(text)} chars)"


def mask_mapping_table(mapping_table: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Copy a mapping table with every secret value replaced by its mask.

    Masking the ``name`` alone is not enough. Each entry also carries a
    ``ctx`` snippet -- the +/-k *original* source lines around the symbol --
    and the line that bound a credential contains the credential. So every
    secret value is masked out of every snippet as well, whichever entry
    that snippet belongs to.

    Shared by both the web interface and ``codeabstract translate``: the
    CLI path called RECONSTRUCT against the raw, unmasked mapping table
    directly, so its "Source Context" blocks printed the same credential
    values this function exists to keep off the wire -- found by running
    the CLI translate command end to end with a fresh, non-`--reveal`d
    session and reading the terminal output. Both callers must go through
    this, not just the web one.

    Returned by value; the caller's table is untouched, since RECONSTRUCT
    and the session store both still need the real one.

    Args:
        mapping_table: Decrypted mapping, token -> entry.

    Returns:
        A copy safe to render, and safe to reconstruct against.
    """
    secrets: List[str] = [
        str(entry.get('name', ''))
        for entry in mapping_table.values()
        if entry.get('label') == 'SECRET' and entry.get('name')
    ]
    # Longest first: a short secret that is a substring of a longer one must
    # not mask half of it and leave the rest legible.
    secrets.sort(key=len, reverse=True)

    def scrub(text: str) -> str:
        for secret in secrets:
            if secret in text:
                text = text.replace(secret, mask_secret(secret))
        return text

    masked: Dict[str, Dict] = {}
    for token, entry in mapping_table.items():
        copy = dict(entry)
        if copy.get('label') == 'SECRET':
            copy['name'] = mask_secret(str(copy.get('name', '')))

        ctx = copy.get('ctx')
        if isinstance(ctx, dict) and ctx.get('snippet'):
            ctx = dict(ctx)
            ctx['snippet'] = scrub(str(ctx['snippet']))
            copy['ctx'] = ctx

        masked[token] = copy
    return masked


def display_mapping(
    mapping_table: Dict[str, Dict],
    reveal: bool = False,
) -> Dict[str, Dict]:
    """A mapping table safe to show or reconstruct against, unless *reveal*."""
    return dict(mapping_table) if reveal else mask_mapping_table(mapping_table)


@dataclass
class HiddenItem:
    """One symbol that was replaced by a token."""

    token: str
    name: str
    label: str
    detector: str
    confidence: float
    lineno: int
    occurrences: int
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'token': self.token,
            'name': self.name,
            'label': self.label,
            'detector': self.detector,
            'confidence': round(self.confidence, 2),
            'lineno': self.lineno,
            'occurrences': self.occurrences,
            'evidence': list(self.evidence),
        }


@dataclass
class KeptItem:
    """One name that reached the provider unchanged."""

    name: str
    reason: str
    label: str
    lineno: int
    occurrences: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'reason': self.reason,
            'label': self.label,
            'lineno': self.lineno,
            'occurrences': self.occurrences,
        }


@dataclass
class PrivacyReport:
    """What a single abstraction hid, kept, and was unsure about."""

    session_id: str
    source_file: str
    privacy_level: str
    language: str
    detector_version: str
    hidden: List[HiddenItem] = field(default_factory=list)
    kept: List[KeptItem] = field(default_factory=list)
    uncertain: List[HiddenItem] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)
    secrets_masked: bool = True

    # -- derived ------------------------------------------------------

    @property
    def hidden_by_label(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self.hidden:
            counts[item.label] = counts.get(item.label, 0) + 1
        return counts

    @property
    def hidden_by_detector(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self.hidden:
            counts[item.detector] = counts.get(item.detector, 0) + 1
        return counts

    @property
    def kept_by_reason(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self.kept:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        return counts

    def headline(self) -> str:
        """One line for the end of a run."""
        secrets = self.hidden_by_label.get('SECRET', 0)
        return (
            f"{len(self.hidden)} symbols hidden ({secrets} secret), "
            f"{len(self.kept)} kept readable, "
            f"{len(self.uncertain)} below the {REVIEW_THRESHOLD:.2f} "
            f"confidence threshold"
        )

    # -- serialisation ------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            'session_id': self.session_id,
            'source_file': self.source_file,
            'privacy_level': self.privacy_level,
            'language': self.language,
            'detector_version': self.detector_version,
            'secrets_masked': self.secrets_masked,
            'summary': {
                'hidden': len(self.hidden),
                'kept': len(self.kept),
                'uncertain': len(self.uncertain),
                'hidden_by_label': self.hidden_by_label,
                'hidden_by_detector': self.hidden_by_detector,
                'kept_by_reason': self.kept_by_reason,
            },
            'kept': [item.to_dict() for item in self.kept],
            'uncertain': [item.to_dict() for item in self.uncertain],
            'hidden': [item.to_dict() for item in self.hidden],
            'statistics': self.statistics,
        }

    def to_markdown(self) -> str:
        """Render as Markdown, for attaching to a compliance ticket."""
        lines = [
            f"# Privacy Report — {self.source_file}",
            "",
            f"- Session: `{self.session_id}`",
            f"- Privacy level: **{self.privacy_level}**",
            f"- Language: {self.language}",
            f"- Detector: `{self.detector_version}`",
            f"- {self.headline()}",
            "",
            "## Kept readable (sent to the provider as-is)",
            "",
        ]

        if self.kept:
            lines += ["| Name | Reason | Line | Occurrences |",
                      "|---|---|---|---|"]
            lines += [
                f"| `{item.name}` | {item.reason} | {item.lineno} | {item.occurrences} |"
                for item in self.kept
            ]
        else:
            lines.append("Nothing — every eligible name was abstracted.")

        lines += ["", "## Unsure (below the review threshold)", ""]
        if self.uncertain:
            lines += ["| Token | Name | Label | Confidence | Detector |",
                      "|---|---|---|---|---|"]
            lines += [
                f"| `{item.token}` | `{item.name}` | {item.label} | "
                f"{item.confidence:.2f} | {item.detector} |"
                for item in self.uncertain
            ]
        else:
            lines.append("None — every decision met the confidence threshold.")

        lines += ["", "## Hidden", ""]
        lines += ["| Label | Count |", "|---|---|"]
        lines += [
            f"| {label} | {count} |"
            for label, count in sorted(self.hidden_by_label.items())
        ]
        lines += ["", "| Detector | Count |", "|---|---|"]
        lines += [
            f"| {detector} | {count} |"
            for detector, count in sorted(self.hidden_by_detector.items())
        ]

        if self.secrets_masked:
            lines += [
                "",
                "> Secret values are masked in this report. They are the "
                "credentials the run exists to protect, and a report file "
                "quoting them would be a second copy of the leak.",
            ]

        return "\n".join(lines) + "\n"


# ═══════════════════════════════════════════════════════════
# Construction
# ═══════════════════════════════════════════════════════════

def build_report(
    mapping_table: Dict[str, Dict],
    statistics: Optional[Dict[str, Any]] = None,
    kept: Optional[List[Dict]] = None,
    session_id: str = "",
    source_file: str = "",
    privacy_level: str = "high",
    language: str = "python",
    reveal: bool = False,
) -> PrivacyReport:
    """
    Build a report from a decrypted mapping table.

    Args:
        mapping_table: Decrypted mapping, token → entry.
        statistics: The abstraction's statistics dict.
        kept: :attr:`algorithms.abstract.AbstractionResult.kept`.
        session_id: Session the report describes.
        source_file: Path of the original file.
        privacy_level: Level the run used.
        language: Source language.
        reveal: Show secret values in full. Off by default — see the
            module docstring.

    Returns:
        A :class:`PrivacyReport`.
    """
    from config.settings import detector_version

    hidden: List[HiddenItem] = []
    uncertain: List[HiddenItem] = []

    for token, entry in mapping_table.items():
        name = entry.get('name', '')
        label = entry.get('label', 'IDENTIFIER')
        if label == 'SECRET' and not reveal:
            name = mask_secret(name)

        item = HiddenItem(
            token=token,
            name=name,
            label=label,
            detector=entry.get('detector', 'unspecified'),
            confidence=float(entry.get('confidence', 1.0)),
            lineno=int(entry.get('lineno', 0) or 0),
            occurrences=len(entry.get('occurrences', []) or []),
            evidence=list(entry.get('evidence', []) or []),
        )
        hidden.append(item)
        if item.confidence < REVIEW_THRESHOLD:
            uncertain.append(item)

    hidden.sort(key=lambda i: (i.lineno, i.token))
    uncertain.sort(key=lambda i: i.confidence)

    kept_items = [
        KeptItem(
            name=record.get('name', ''),
            reason=record.get('reason', 'unspecified'),
            label=record.get('label', 'IDENTIFIER'),
            lineno=int(record.get('lineno', 0) or 0),
            occurrences=int(record.get('occurrences', 1) or 1),
        )
        for record in (kept or [])
    ]

    return PrivacyReport(
        session_id=session_id,
        source_file=str(source_file),
        privacy_level=privacy_level,
        language=language,
        detector_version=detector_version(),
        hidden=hidden,
        kept=kept_items,
        uncertain=uncertain,
        statistics=dict(statistics or {}),
        secrets_masked=not reveal,
    )


def report_for_result(
    result,
    source_file: str = "",
    privacy_level: str = "high",
    reveal: bool = False,
) -> PrivacyReport:
    """
    Build a report straight from an :class:`~algorithms.abstract.AbstractionResult`.

    Decrypts the mapping in memory using the key the caller already holds;
    nothing is written anywhere.
    """
    from algorithms.encrypt import decrypt_mapping

    mapping_table = decrypt_mapping(result.encrypted_mapping, result.encryption_key)
    return build_report(
        mapping_table=mapping_table,
        statistics=result.statistics,
        kept=result.kept,
        session_id=result.session_id,
        source_file=source_file,
        privacy_level=privacy_level,
        language=getattr(result, 'language', 'python'),
        reveal=reveal,
    )
