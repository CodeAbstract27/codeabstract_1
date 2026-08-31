"""
De-tokenisation and Fix Application

Phase 1.

The proposal's CLI mock-up ends with ``Apply suggested fixes? [Y/n]``, and
the pipeline diagram's final stage is "Apply to original code".  Neither
existed: the developer got prose with original names substituted in, and
had to retype any suggested code by hand.

This module closes that loop.  It pulls fenced code blocks out of an LLM
response, replaces the abstraction tokens in them with the original
identifiers, and produces a unified diff against the developer's file.

**On what is and is not automated.** A whole-file rewrite can be diffed and
applied safely, because the result is a complete program that either parses
or does not.  A partial snippet cannot: knowing where a fragment belongs
means matching it against the original structure, and guessing wrong writes
broken code into someone's repository.  So snippets are de-tokenised and
handed back for the developer to place, and only whole-file suggestions are
offered as an applicable patch.  The honest boundary is worth more than an
impressive-looking auto-patcher that occasionally corrupts a file.
"""

import ast
import difflib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from algorithms.encrypt import decrypt_mapping

# Fenced code blocks, with or without a language tag.
_CODE_BLOCK = re.compile(
    r'```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```',
    re.DOTALL,
)

_TOKEN = re.compile(r'\b((?:FUNC|VAR|SECRET|CONST|NUM|CLASS|MODULE)_\d+)\b')


@dataclass
class SuggestedFix:
    """One code block recovered from an LLM response."""

    index: int
    language: str
    abstract_code: str
    restored_code: str
    tokens_restored: int
    unresolved_tokens: List[str] = field(default_factory=list)
    parses: bool = False
    is_whole_file: bool = False

    @property
    def applicable(self) -> bool:
        """
        True if this block can be safely written over the original file.

        Requires a complete, parseable module with every token resolved —
        an unresolved token would write a literal ``VAR_7`` into the file.
        """
        return self.parses and self.is_whole_file and not self.unresolved_tokens


def extract_code_blocks(llm_response: str) -> List[tuple]:
    """
    Pull fenced code blocks out of an LLM response.

    Args:
        llm_response: The raw response text.

    Returns:
        List of ``(language, code)`` tuples in order of appearance.
    """
    return [
        (match.group(1).lower(), match.group(2))
        for match in _CODE_BLOCK.finditer(llm_response)
    ]


def detokenise(code: str, mapping_table: Dict) -> tuple:
    """
    Replace abstraction tokens in *code* with their original identifiers.

    This is the inverse of the substitution RECONSTRUCT performs on prose,
    but it emits bare identifiers rather than ``name (line N)`` references —
    the output has to be valid source, not a readable annotation.

    Uses the same single-pass, longest-token-first strategy as RECONSTRUCT
    so that ``VAR_1`` cannot substitute itself inside ``VAR_10``.

    Args:
        code: Abstract code containing tokens.
        mapping_table: Decrypted mapping table.

    Returns:
        ``(restored_code, tokens_restored, unresolved_tokens)``.
    """
    found = _TOKEN.findall(code)
    if not found:
        return code, 0, []

    known = sorted(
        {token for token in found if token in mapping_table},
        key=len,
        reverse=True,
    )
    unresolved = sorted({token for token in found if token not in mapping_table})

    if not known:
        return code, 0, unresolved

    pattern = re.compile(
        r'\b(' + '|'.join(re.escape(token) for token in known) + r')\b'
    )
    restored_count = 0

    def _replace(match: "re.Match") -> str:
        nonlocal restored_count
        restored_count += 1
        return mapping_table[match.group(1)]['name']

    return pattern.sub(_replace, code), restored_count, unresolved


def _looks_like_whole_file(code: str, original_source: str) -> bool:
    """
    Decide whether a block is a full-file rewrite rather than a fragment.

    A whole-file suggestion re-states the module's top-level definitions.
    Requiring most of them to reappear keeps a single revised function from
    being mistaken for the whole module and overwriting everything else.
    """
    try:
        suggested = ast.parse(code)
        original = ast.parse(original_source)
    except SyntaxError:
        return False

    def top_level_names(tree: ast.AST) -> set:
        names = set()
        for node in getattr(tree, 'body', []):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
        return names

    original_names = top_level_names(original)
    if not original_names:
        # No definitions to compare structurally (a plain script). A bare
        # line-count check is not evidence of a rewrite: an unrelated code
        # block that merely happens to be long enough would pass it, and
        # applying it would silently discard the developer's actual file —
        # exactly the failure mode this module exists to avoid. Require the
        # block to also share most of the original's content.
        if len(code.strip().splitlines()) < len(original_source.strip().splitlines()):
            return False
        similarity = difflib.SequenceMatcher(
            None, original_source.split(), code.split()
        ).ratio()
        return similarity >= 0.4

    suggested_names = top_level_names(suggested)
    covered = len(original_names & suggested_names) / len(original_names)
    return covered >= 0.8


def recover_fixes(
    llm_response: str,
    encrypted_mapping: bytes,
    encryption_key: bytes,
    original_source: str = "",
) -> List[SuggestedFix]:
    """
    Recover every applicable code suggestion from an LLM response.

    Args:
        llm_response: Raw response text.
        encrypted_mapping: Encrypted mapping table M̃.
        encryption_key: Encryption key K.
        original_source: The developer's original file, used to tell a
            whole-file rewrite from a fragment.

    Returns:
        One :class:`SuggestedFix` per fenced code block.

    Raises:
        ValueError: If the mapping table cannot be decrypted.
    """
    mapping_table = decrypt_mapping(encrypted_mapping, encryption_key)
    fixes: List[SuggestedFix] = []

    for index, (language, block) in enumerate(extract_code_blocks(llm_response)):
        # Non-Python fences (shell, json, diff) are not applicable code.
        if language and language not in ('python', 'py', 'python3'):
            continue

        restored, restored_count, unresolved = detokenise(block, mapping_table)

        parses = True
        try:
            ast.parse(restored)
        except SyntaxError:
            parses = False

        fixes.append(SuggestedFix(
            index=index,
            language=language or 'python',
            abstract_code=block,
            restored_code=restored,
            tokens_restored=restored_count,
            unresolved_tokens=unresolved,
            parses=parses,
            is_whole_file=(
                parses
                and bool(original_source)
                and _looks_like_whole_file(restored, original_source)
            ),
        ))

    return fixes


def build_diff(
    original_source: str,
    restored_code: str,
    file_name: str = "original.py",
) -> str:
    """
    Produce a unified diff between the original file and a suggestion.

    Args:
        original_source: Current file contents.
        restored_code: De-tokenised suggestion.
        file_name: Label used in the diff header.

    Returns:
        Unified diff text; empty string when the two are identical.
    """
    original_lines = original_source.splitlines(keepends=True)
    suggested_lines = restored_code.splitlines(keepends=True)

    if not restored_code.endswith('\n') and suggested_lines:
        suggested_lines[-1] += '\n'

    diff = difflib.unified_diff(
        original_lines,
        suggested_lines,
        fromfile=f"a/{file_name}",
        tofile=f"b/{file_name}",
        n=3,
    )
    return ''.join(diff)
