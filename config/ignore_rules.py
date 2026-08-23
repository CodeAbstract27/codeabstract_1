"""
Project-Level Abstraction Overrides

Phase 1.

The proposal names false positives as a headline risk and commits to a
"whitelist system + user override option" as the mitigation.  Neither
existed: every classification decision was final, and a developer whose
harmless ``rate_limiter`` got abstracted had no way to say so.

This module reads a ``.codeabstractignore`` file — walking up from the
source file to the repository root — and turns it into a set of overrides
applied during abstraction.

Format, one rule per line, ``#`` starts a comment::

    # Keep these readable: they carry no IP and the LLM needs them.
    keep:customer_id
    keep:handle_*

    # Force these to SECRET even though the name looks innocuous.
    secret:tenant_ref

    # Treat this internal package as safe to name.
    module:acme_common

    # A bare name is shorthand for keep:
    request_id

Glob syntax (``*``, ``?``, ``[seq]``) is supported in all three rules.

**``keep`` never overrides value-level secret detection.** If a literal
trips the credential detector it is redacted regardless, and a rule cannot
turn that off. An override exists to recover utility, not to disable the
guarantee — a config file should never be able to put a live API key on
the wire.
"""

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

IGNORE_FILENAME = ".codeabstractignore"

# How far up the directory tree to search before giving up.
_MAX_PARENTS = 25


@dataclass
class OverrideRules:
    """Parsed contents of a ``.codeabstractignore`` file."""

    keep: List[str] = field(default_factory=list)
    force_secret: List[str] = field(default_factory=list)
    safe_modules: List[str] = field(default_factory=list)
    source_path: Optional[Path] = None

    def __bool__(self) -> bool:
        return bool(self.keep or self.force_secret or self.safe_modules)

    def should_keep(self, name: str) -> bool:
        """True if *name* is exempt from identifier abstraction."""
        return _matches(name, self.keep)

    def is_forced_secret(self, name: str) -> bool:
        """True if *name* must be classified SECRET regardless of pattern."""
        return _matches(name, self.force_secret)

    def is_safe_module(self, module_path: str) -> bool:
        """True if *module_path* may be named verbatim to the LLM."""
        if not module_path:
            return False
        root = module_path.split('.', 1)[0]
        return _matches(module_path, self.safe_modules) or _matches(
            root, self.safe_modules
        )

    def summary(self) -> str:
        """One-line description for the privacy report and CLI output."""
        if not self:
            return "no overrides"
        parts = []
        if self.keep:
            parts.append(f"{len(self.keep)} keep")
        if self.force_secret:
            parts.append(f"{len(self.force_secret)} forced-secret")
        if self.safe_modules:
            parts.append(f"{len(self.safe_modules)} safe-module")
        return ", ".join(parts)


def _matches(name: str, patterns: List[str]) -> bool:
    """True if *name* matches any glob in *patterns*."""
    if not name or not patterns:
        return False
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def parse_rules(text: str, source_path: Optional[Path] = None) -> OverrideRules:
    """
    Parse the contents of a ``.codeabstractignore`` file.

    Unknown directives are ignored rather than raising: a typo in a config
    file should not stop someone abstracting their code, and the rule
    simply has no effect.

    Args:
        text: Raw file contents.
        source_path: Path the rules came from, recorded for reporting.

    Returns:
        Populated :class:`OverrideRules`.
    """
    rules = OverrideRules(source_path=source_path)

    for raw_line in text.splitlines():
        line = raw_line.split('#', 1)[0].strip()
        if not line:
            continue

        if ':' in line:
            directive, _, value = line.partition(':')
            directive = directive.strip().lower()
            value = value.strip()
        else:
            directive, value = 'keep', line

        if not value:
            continue

        if directive == 'keep':
            rules.keep.append(value)
        elif directive == 'secret':
            rules.force_secret.append(value)
        elif directive == 'module':
            rules.safe_modules.append(value)
        # Anything else: unknown directive, silently inert.

    return rules


def find_rules_file(start: Optional[Path] = None) -> Optional[Path]:
    """
    Locate the nearest ``.codeabstractignore`` at or above *start*.

    Args:
        start: File or directory to search from. Defaults to the CWD.

    Returns:
        Path to the rules file, or None if there is none.
    """
    current = Path(start) if start else Path.cwd()
    if current.is_file():
        current = current.parent

    try:
        current = current.resolve()
    except OSError:
        return None

    for _ in range(_MAX_PARENTS):
        candidate = current / IGNORE_FILENAME
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent

    return None


def load_rules(start: Optional[Path] = None) -> OverrideRules:
    """
    Find and parse the applicable ``.codeabstractignore``.

    Returns empty rules when no file exists or it cannot be read, so
    abstraction always has a usable rule set.

    Args:
        start: File or directory to search from. Defaults to the CWD.

    Returns:
        Populated (possibly empty) :class:`OverrideRules`.
    """
    path = find_rules_file(start)
    if path is None:
        return OverrideRules()

    try:
        return parse_rules(path.read_text(encoding='utf-8'), source_path=path)
    except OSError:
        return OverrideRules()
