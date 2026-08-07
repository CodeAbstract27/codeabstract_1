"""
Tests for core/context_extractor.py

Covers:
- Normal extraction at middle of file
- Boundary clamping at start and end
- Window size 0 (single line)
- Large window on small file
- Correct field values in returned dict
- Multi-line snippet correctness
"""

import pytest

from core.context_extractor import get_context


# Helper: build a multi-line source string
def _make_source(num_lines: int) -> str:
    """Create a numbered source string: 'line_1\nline_2\n...'"""
    return "\n".join(f"line_{i}" for i in range(1, num_lines + 1))


class TestGetContext:
    """Test suite for get_context() / GetContext(S, lineno, k)."""

    # ─── Return structure ──────────────────────────────────

    def test_returns_dict_with_required_keys(self):
        """Return value must contain snippet, start_line, end_line, target_line."""
        source = _make_source(10)
        ctx = get_context(source, 5, window_size=2)
        assert "snippet" in ctx
        assert "start_line" in ctx
        assert "end_line" in ctx
        assert "target_line" in ctx

    def test_target_line_equals_input(self):
        """target_line field must equal the line_number argument."""
        source = _make_source(10)
        ctx = get_context(source, 7, window_size=3)
        assert ctx["target_line"] == 7

    # ─── Normal middle-of-file extraction ─────────────────

    def test_middle_extraction_correct_bounds(self):
        """k=2 window on line 5 of 10-line file: start=3, end=7."""
        source = _make_source(10)
        ctx = get_context(source, 5, window_size=2)
        assert ctx["start_line"] == 3
        assert ctx["end_line"] == 7

    def test_snippet_contains_target_line(self):
        """Snippet must contain text from the target line."""
        source = "alpha\nbeta\ngamma\ndelta\nepsilon"
        ctx = get_context(source, 3, window_size=1)
        assert "gamma" in ctx["snippet"]

    def test_snippet_contains_context_lines(self):
        """Snippet must include lines within the k-window."""
        source = "alpha\nbeta\ngamma\ndelta\nepsilon"
        ctx = get_context(source, 3, window_size=1)
        # k=1: lines 2,3,4 → beta, gamma, delta
        assert "beta" in ctx["snippet"]
        assert "delta" in ctx["snippet"]

    def test_snippet_excludes_out_of_window(self):
        """Snippet must NOT include lines outside the k-window."""
        source = "alpha\nbeta\ngamma\ndelta\nepsilon"
        ctx = get_context(source, 3, window_size=1)
        assert "alpha" not in ctx["snippet"]
        assert "epsilon" not in ctx["snippet"]

    # ─── Boundary clamping ──────────────────────────────────

    def test_start_clamps_to_1_at_beginning(self):
        """When target is near start, start_line must clamp to 1 (not go negative)."""
        source = _make_source(10)
        ctx = get_context(source, 2, window_size=5)
        assert ctx["start_line"] == 1

    def test_end_clamps_to_total_lines_at_end(self):
        """When target is near end, end_line must clamp to total lines."""
        source = _make_source(10)
        ctx = get_context(source, 9, window_size=5)
        assert ctx["end_line"] == 10

    def test_first_line_extraction(self):
        """Extracting context for line 1 with large k should start at line 1."""
        source = _make_source(20)
        ctx = get_context(source, 1, window_size=10)
        assert ctx["start_line"] == 1
        assert ctx["target_line"] == 1

    def test_last_line_extraction(self):
        """Extracting context for last line with large k should end at last line."""
        source = _make_source(20)
        ctx = get_context(source, 20, window_size=10)
        assert ctx["end_line"] == 20
        assert ctx["target_line"] == 20

    # ─── Window size edge cases ─────────────────────────────

    def test_window_size_zero_returns_single_line(self):
        """k=0 should return only the target line itself."""
        source = "alpha\nbeta\ngamma\ndelta\nepsilon"
        ctx = get_context(source, 3, window_size=0)
        assert ctx["start_line"] == 3
        assert ctx["end_line"] == 3
        assert ctx["snippet"] == "gamma"

    def test_large_window_on_small_file(self):
        """k larger than file length should not raise; bounds clamp correctly."""
        source = "only_line"
        ctx = get_context(source, 1, window_size=100)
        assert ctx["start_line"] == 1
        assert ctx["end_line"] == 1
        assert ctx["snippet"] == "only_line"

    def test_full_file_window(self):
        """k large enough to cover entire file returns all lines."""
        source = _make_source(5)
        ctx = get_context(source, 3, window_size=100)
        assert ctx["start_line"] == 1
        assert ctx["end_line"] == 5

    # ─── Snippet content ────────────────────────────────────

    def test_snippet_is_string(self):
        """Snippet must be a string."""
        source = _make_source(10)
        ctx = get_context(source, 5, window_size=2)
        assert isinstance(ctx["snippet"], str)

    def test_snippet_line_count_matches_window(self):
        """With k=2 on a non-boundary line, snippet has 5 lines (2+1+2)."""
        source = _make_source(20)
        ctx = get_context(source, 10, window_size=2)
        # lines 8,9,10,11,12 → 5 lines
        snippet_lines = ctx["snippet"].split("\n")
        assert len(snippet_lines) == 5

    def test_start_line_leq_target_leq_end_line(self):
        """Invariant: start_line ≤ target_line ≤ end_line."""
        source = _make_source(15)
        for lineno in range(1, 16):
            ctx = get_context(source, lineno, window_size=3)
            assert ctx["start_line"] <= ctx["target_line"] <= ctx["end_line"]

    # ─── Default window size ────────────────────────────────

    def test_default_window_size_is_3(self):
        """Default window size should be 3 (±3 lines)."""
        source = _make_source(20)
        ctx_default = get_context(source, 10)
        ctx_explicit = get_context(source, 10, window_size=3)
        assert ctx_default == ctx_explicit
