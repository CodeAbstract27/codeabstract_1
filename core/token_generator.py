"""
Token Generator

Manages counter-based token creation with consistent prefix_counter naming.
Ensures deterministic, monotonically increasing token IDs per prefix.
"""

from typing import Dict


class TokenGenerator:
    """
    Generates unique tokens with prefix-based counters.

    Tokens follow the format: PREFIX_N where PREFIX is one of
    FUNC, VAR, SECRET, CONST and N is a zero-based counter.
    """

    def __init__(self, counters: Dict[str, int] = None):
        """
        Initialize with optional starting counters.

        Args:
            counters: Dict mapping prefix → starting counter value.
                      Defaults to all zeros.
        """
        self.counters: Dict[str, int] = counters if counters is not None else {
            'FUNC': 0,
            'VAR': 0,
            'SECRET': 0,
            'CONST': 0,
        }

    def generate(self, prefix: str) -> str:
        """
        Generate the next token for a given prefix.

        Args:
            prefix: One of FUNC, VAR, SECRET, CONST.

        Returns:
            Token string like "FUNC_0", "VAR_3", etc.
        """
        if prefix not in self.counters:
            self.counters[prefix] = 0

        token = f"{prefix}_{self.counters[prefix]}"
        self.counters[prefix] += 1
        return token

    def get_counts(self) -> Dict[str, int]:
        """Return a copy of current counter values."""
        return dict(self.counters)
