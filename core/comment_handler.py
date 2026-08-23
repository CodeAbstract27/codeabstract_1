"""
Comment Extraction and Re-injection

Phase 1 — the comment policy decision.

``ast.unparse`` discards every comment, because comments are not AST nodes.
Up to now that was a side effect nobody had chosen: the strongest
privacy behaviour in the system, and simultaneously a large utility cost,
arrived by accident and was documented nowhere.

**The policy, stated explicitly.** Comments are stripped by default. A
comment is free-form prose written by the people who own the code, and it
is where business context lives most densely — ``# 2.5% Stripe commission,
renegotiated Q3`` gives away more than the identifier it sits above. It is
also the part of a file the abstraction engine can reason about least,
since there is no structure to classify, only text.

Preservation is therefore opt-in (``--keep-comments``), and even then every
comment is screened: comments whose text trips the secret or business-value
classifier are dropped, and identifiers mentioned inside a surviving
comment are rewritten to their tokens so prose cannot leak a name the code
took care to hide.

Re-injection is validated. If the result does not parse, the un-injected
code is used instead — a comment is never worth emitting a broken file for.
"""

import io
import re
import tokenize
from dataclasses import dataclass
from typing import Dict, List, Optional

from config.patterns import SECRET_PATTERNS, VALUE_PATTERNS
from core.pattern_matcher import matches_any
from core.secret_detector import is_secret_value


@dataclass
class Comment:
    """A single comment recovered from the source."""

    lineno: int
    col: int
    text: str          # including the leading '#'
    own_line: bool     # True if nothing but whitespace precedes it


def extract_comments(source_code: str) -> List[Comment]:
    """
    Recover every comment in *source_code* with its position.

    Uses ``tokenize`` rather than a regex so that ``#`` inside a string
    literal is not mistaken for a comment.

    Args:
        source_code: Python source.

    Returns:
        Comments in source order. Empty if the source cannot be tokenised.
    """
    comments: List[Comment] = []
    lines = source_code.split('\n')

    try:
        tokens = tokenize.generate_tokens(io.StringIO(source_code).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            lineno, col = token.start
            prefix = lines[lineno - 1][:col] if lineno - 1 < len(lines) else ''
            comments.append(Comment(
                lineno=lineno,
                col=col,
                text=token.string,
                own_line=not prefix.strip(),
            ))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # A file we cannot tokenise simply yields no comments; abstraction
        # itself has already parsed the source, so this is not fatal.
        return []

    return comments


def is_sensitive_comment(text: str) -> bool:
    """
    True if a comment must be dropped rather than preserved.

    Screens on the same signals used for code: credential shapes in the
    text, SECRET name patterns, and business-VALUE patterns.

    Args:
        text: Comment text, with or without the leading ``#``.

    Returns:
        True if the comment should not be sent to the LLM.
    """
    body = text.lstrip('#').strip()
    if not body:
        return False

    # A credential pasted into a comment is still a credential.
    for word in re.split(r'\s+', body):
        if is_secret_value(word.strip('.,;:()[]{}\'"')):
            return True

    lowered = body.lower()
    return matches_any(lowered, SECRET_PATTERNS) or matches_any(lowered, VALUE_PATTERNS)


def rewrite_identifiers(text: str, name_to_token: Dict[str, str]) -> str:
    """
    Replace original identifiers mentioned in comment prose with their tokens.

    Without this, ``# see calculate_commission`` would reintroduce a name
    the code had just abstracted away.

    Args:
        text: Comment text.
        name_to_token: Original name → token.

    Returns:
        The comment with known identifiers rewritten.
    """
    if not name_to_token:
        return text

    # Longest first so a name is never partially matched by a shorter one.
    names = sorted(
        (n for n in name_to_token if n and n.isidentifier()),
        key=len,
        reverse=True,
    )
    if not names:
        return text

    pattern = re.compile(
        r'\b(' + '|'.join(re.escape(name) for name in names) + r')\b'
    )
    return pattern.sub(lambda m: name_to_token[m.group(1)], text)


def sanitise_comment(
    comment: Comment,
    name_to_token: Dict[str, str],
) -> Optional[str]:
    """
    Screen and rewrite one comment for transmission.

    Args:
        comment: The comment to screen.
        name_to_token: Original name → token, for prose rewriting.

    Returns:
        The comment text to emit, or None if it must be dropped.
    """
    if is_sensitive_comment(comment.text):
        return None
    return rewrite_identifiers(comment.text, name_to_token)


def reinject_comments(
    abstract_code: str,
    source_code: str,
    line_map: Dict[int, int],
    name_to_token: Dict[str, str],
) -> str:
    """
    Put screened comments back into the abstract code.

    The line index runs abstract → original; inverting it says which
    abstract line each original line became, which is where a comment that
    sat above that original line belongs.

    Comments are emitted on their own line, indented to match the statement
    they precede. Trailing comments (``x = 1  # note``) are promoted to
    their own line above the statement, because column positions do not
    survive unparsing.

    Args:
        abstract_code: The unparsed abstract source.
        source_code: The original source.
        line_map: ``{abstract_lineno: original_lineno}``.
        name_to_token: Original name → token, for prose rewriting.

    Returns:
        Abstract code with comments re-injected, or the input unchanged if
        the result would not parse.
    """
    import ast

    comments = extract_comments(source_code)
    if not comments or not line_map:
        return abstract_code

    # original line → abstract line
    inverted: Dict[int, int] = {}
    for abstract_line, original_line in sorted(line_map.items()):
        inverted.setdefault(original_line, abstract_line)

    original_lines_sorted = sorted(inverted)

    def next_abstract_line(original_line: int) -> Optional[int]:
        """First abstract line whose original line is at or after this one."""
        for candidate in original_lines_sorted:
            if candidate >= original_line:
                return inverted[candidate]
        return None

    # abstract line → comment texts to insert above it
    pending: Dict[int, List[str]] = {}
    for comment in comments:
        cleaned = sanitise_comment(comment, name_to_token)
        if cleaned is None:
            continue
        target = next_abstract_line(comment.lineno)
        if target is None:
            continue
        pending.setdefault(target, []).append(cleaned)

    if not pending:
        return abstract_code

    output: List[str] = []
    for index, line in enumerate(abstract_code.split('\n'), start=1):
        for comment_text in pending.get(index, []):
            indent = line[:len(line) - len(line.lstrip())]
            output.append(f"{indent}{comment_text}")
        output.append(line)

    injected = '\n'.join(output)

    # A comment is never worth emitting a file that will not parse.
    try:
        ast.parse(injected)
    except SyntaxError:
        return abstract_code

    return injected
