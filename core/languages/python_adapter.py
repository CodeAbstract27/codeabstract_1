"""
Python Adapter

Phase 4. Python does not go through the generic symbol pipeline, and this
adapter exists to say so explicitly rather than leave the routing implicit.

The native engine in :mod:`algorithms.abstract` knows things the
language-agnostic interface deliberately does not model: the lexical scope
tree with ``global``/``nonlocal`` handling (Phase 1), usage-based context
features (Phase 2), whole-template f-string classification (Phase 0), and
comment re-injection. Re-expressing Python through
:class:`~core.languages.base.SourceSymbol` would throw all of that away to
gain uniformity nobody benefits from — and would leave the project's most
heavily tested path rewritten for the sake of symmetry.

So the interface is what a *new* language implements to reach parity;
Python is routed to the engine that already exceeds it. The one thing this
adapter owns is the extension mapping, so that ``abstract_file`` has a
single place to ask what language a path is.
"""

from typing import List, Tuple

from core.languages.base import SourceSymbol


class PythonAdapter:
    """Routing entry for Python. Abstraction happens in the native engine."""

    language = "python"
    extensions: Tuple[str, ...] = ('.py', '.pyi')

    def availability(self) -> Tuple[bool, str]:
        """Always available — the parser is in the standard library."""
        return True, ""

    def is_builtin(self, name: str) -> bool:
        from algorithms.helpers import BUILTINS
        return name in BUILTINS

    def symbols(self, source_code: str) -> List[SourceSymbol]:
        """
        Not implemented, by design.

        Raises:
            NotImplementedError: Always. :func:`algorithms.abstract_source
            .abstract_source` routes Python to :func:`algorithms.abstract
            .abstract`; anything reaching here has bypassed that routing.
        """
        raise NotImplementedError(
            "Python is abstracted by algorithms.abstract, not through the "
            "generic symbol pipeline — see this module's docstring."
        )
