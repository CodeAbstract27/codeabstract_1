"""
Tests for the escaping and marking layer (``web.highlight``).

This module is the only place in the web interface that produces HTML from
somebody else's text, and the templates render its output with ``|safe``.
That is only true because of these tests: if escaping regresses here, every
pane in the application becomes an injection point at once.

The second thing under test is that marking is *correct*, not merely
present. A ``VAR_1`` substituted inside a ``VAR_10`` is the Phase 0 D2
defect wearing different clothes, and every new substitution pass has to be
shown not to have reintroduced it.
"""

import re

from web import highlight
from web.highlight import (
    highlight_abstract_code,
    highlight_feedback,
    highlight_original_code,
    highlight_token_text,
    highlight_vault_rows,
)


def mapping(**entries):
    """Build a view mapping from ``token=(name, label, lineno)`` triples."""
    return {
        token: {'name': name, 'label': label, 'lineno': lineno}
        for token, (name, label, lineno) in entries.items()
    }


# ═══════════════════════════════════════════════════════════
# Escaping
# ═══════════════════════════════════════════════════════════

class TestEscaping:
    """Source code is not markup, and must never become markup."""

    def test_script_tag_in_source_is_escaped(self):
        source = 'label = "<script>alert(1)</script>"'
        lines = highlight_original_code(source, {})

        assert '<script>' not in lines[0].html
        assert '&lt;script&gt;' in lines[0].html

    def test_script_tag_in_abstract_code_is_escaped(self):
        lines = highlight_abstract_code('x = "</textarea><script>x</script>"', {})
        assert '<script>' not in lines[0].html

    def test_angle_brackets_and_ampersands_survive_as_text(self):
        lines = highlight_original_code('if a < b and c > d & e:', {})
        assert '&lt;' in lines[0].html
        assert '&gt;' in lines[0].html
        assert '&amp;' in lines[0].html

    def test_a_hostile_identifier_name_cannot_break_out_of_a_tooltip(self):
        """
        The name goes into a ``title`` attribute.

        A name containing a quote would close the attribute and let the rest
        become markup — so the attribute value is escaped with ``quote=True``,
        not just for element text.
        """
        view = mapping(VAR_0=('" onmouseover="alert(1)', 'IDENTIFIER', 1))
        lines = highlight_abstract_code('VAR_0 = 1', view)

        assert 'onmouseover="alert(1)"' not in lines[0].html
        assert '&quot;' in lines[0].html

    def test_feedback_escapes_before_marking(self):
        view = mapping(VAR_0=('total', 'IDENTIFIER', 4))
        rendered = highlight_feedback('<img src=x onerror=alert(1)> VAR_0', view)

        assert '<img' not in rendered
        assert '&lt;img' in rendered

    def test_vault_rows_are_escaped(self):
        rows = highlight_vault_rows([{
            'token': 'VAR_0', 'name': '<b>evil</b>', 'label': 'IDENTIFIER',
            'lineno': 1, 'occurrences': 1, 'scope': '', 'detector': 'x',
            'confidence': 1.0, 'masked': False,
        }])
        assert '<b>' not in rows[0]['name']
        assert '&lt;b&gt;' in rows[0]['name']

    def test_escaping_never_manufactures_a_token(self):
        """
        Escaping runs before token matching, so it must not create matches.

        ``html.escape`` emits ``&amp;``, ``&lt;``, ``&gt;`` and ``&#x27;`` —
        none of which is ``PREFIX_<digits>`` — and it alters no character a
        real token contains.
        """
        import html as html_module

        for hostile in ['&<>"\'', 'a & b', "it's <b>"]:
            assert not highlight.TOKEN_PATTERN.search(html_module.escape(hostile))


# ═══════════════════════════════════════════════════════════
# Abstract pane
# ═══════════════════════════════════════════════════════════

class TestAbstractPane:

    def test_known_tokens_are_wrapped_with_their_label(self):
        view = mapping(SECRET_0=('sk_…(20 chars)', 'SECRET', 3))
        lines = highlight_abstract_code('KEY = SECRET_0', view)

        assert 'class="tok tok-secret"' in lines[0].html
        assert 'data-token="SECRET_0"' in lines[0].html
        assert lines[0].tokens == ['SECRET_0']

    def test_an_unknown_token_is_left_alone(self):
        """
        A bare ``VAR_9`` the user typed is not something this run produced.

        Marking it would claim the mapping can resolve it, which it cannot.
        """
        lines = highlight_abstract_code('x = VAR_9', {})
        assert '<span' not in lines[0].html
        assert lines[0].tokens == []

    def test_var_1_is_not_matched_inside_var_10(self):
        view = mapping(
            VAR_1=('alpha', 'IDENTIFIER', 1),
            VAR_10=('omega', 'IDENTIFIER', 2),
        )
        lines = highlight_abstract_code('VAR_10 = VAR_1', view)

        assert lines[0].tokens == ['VAR_10', 'VAR_1']
        assert lines[0].html.count('<span') == 2
        # The giveaway for the D2 defect: a stray '0' left outside the span.
        assert '</span>0' not in lines[0].html

    def test_line_map_links_the_panes(self):
        lines = highlight_abstract_code('a = 1\nb = 2', {}, line_map={1: 5, 2: 9})
        assert [line.linked for line in lines] == [5, 9]

    def test_string_keyed_line_map_still_links(self):
        """The map survives a JSON round trip, so string keys must work."""
        lines = highlight_abstract_code('a = 1', {}, line_map={'1': 42})
        assert lines[0].linked == 42

    def test_missing_line_map_leaves_lines_unlinked(self):
        lines = highlight_abstract_code('a = 1', {}, line_map=None)
        assert lines[0].linked is None

    def test_the_strongest_label_wins_a_shared_line(self):
        view = mapping(
            SECRET_0=('sk_…', 'SECRET', 1),
            VAR_0=('rate', 'VALUE', 1),
        )
        lines = highlight_abstract_code('VAR_0 = SECRET_0', view)
        assert lines[0].label == 'SECRET'
        assert lines[0].css == 'tok-secret'

    def test_line_numbering_starts_at_one(self):
        lines = highlight_abstract_code('a\nb\nc', {})
        assert [line.number for line in lines] == [1, 2, 3]


# ═══════════════════════════════════════════════════════════
# Original pane
# ═══════════════════════════════════════════════════════════

class TestOriginalPane:

    def test_the_binding_line_is_marked(self):
        view = mapping(SECRET_0=('sk_…', 'SECRET', 2))
        lines = highlight_original_code('import os\nKEY = "x"\nprint(KEY)', view)

        assert lines[1].label == 'SECRET'
        assert lines[0].label == ''

    def test_every_occurrence_is_marked_not_only_the_definition(self):
        """
        A credential read on five lines was exposed on five lines.

        Marking only where it was bound understates the exposure, which is
        the opposite of what a privacy view is for.
        """
        view = {
            'SECRET_0': {
                'name': 'sk_…', 'label': 'SECRET', 'lineno': 1,
                'occurrences': [{'lineno': 1}, {'lineno': 3}],
            },
        }
        lines = highlight_original_code('KEY = "x"\n\nuse(KEY)', view)
        assert [line.label for line in lines] == ['SECRET', '', 'SECRET']

    def test_original_lines_link_to_themselves(self):
        lines = highlight_original_code('a\nb', {})
        assert [line.linked for line in lines] == [1, 2]

    def test_malformed_occurrences_do_not_crash_the_pane(self):
        view = {
            'VAR_0': {
                'name': 'x', 'label': 'IDENTIFIER', 'lineno': 1,
                'occurrences': [None, {'lineno': 'nonsense'}, {'lineno': 2}],
            },
        }
        lines = highlight_original_code('a\nb', view)
        assert lines[1].label == 'IDENTIFIER'


# ═══════════════════════════════════════════════════════════
# Feedback pane
# ═══════════════════════════════════════════════════════════

class TestFeedbackPane:

    def test_restored_names_are_marked_with_their_token(self):
        view = mapping(FUNC_0=('calculate_commission', 'IDENTIFIER', 11))
        rendered = highlight_feedback('calculate_commission (line 11) is slow.', view)

        assert 'class="restored' in rendered
        assert 'data-token="FUNC_0"' in rendered

    def test_an_unresolved_token_is_flagged(self):
        """
        The one failure of the round trip that reads as success.

        A response full of ``VAR_9999`` still looks like prose; without a
        mark, nothing tells the user it came from the wrong session.
        """
        rendered = highlight_feedback('VAR_9999 is unused.', {})
        assert 'class="unresolved"' in rendered

    def test_a_name_without_a_line_citation_is_not_marked(self):
        """
        Only RECONSTRUCT's own ``name (line N)`` output is a restoration.

        The same word in ordinary prose is a coincidence, and marking it
        would attribute the model's wording to the mapping.
        """
        view = mapping(VAR_0=('total', 'IDENTIFIER', 4))
        rendered = highlight_feedback('The total looks wrong.', view)
        assert 'class="restored' not in rendered

    def test_a_longer_name_wins_over_a_name_it_contains(self):
        view = mapping(
            VAR_0=('total', 'IDENTIFIER', 4),
            VAR_1=('total_price', 'IDENTIFIER', 8),
        )
        rendered = highlight_feedback('total_price (line 8) is wrong.', view)

        assert 'data-token="VAR_1"' in rendered
        assert 'data-token="VAR_0"' not in rendered

    def test_secret_names_arrive_already_masked(self):
        """
        This module never masks; it is handed the browser-safe view.

        The assertion is that it does not *undo* the masking done upstream —
        the mask reaches the rendered page intact.
        """
        view = mapping(SECRET_0=('sk_…(33 chars)', 'SECRET', 3))
        rendered = highlight_feedback('sk_…(33 chars) (line 3) is exposed.', view)
        assert 'tok-secret' in rendered


class TestRawResponsePane:

    def test_known_tokens_are_marked(self):
        view = mapping(VAR_0=('total', 'IDENTIFIER', 4))
        rendered = highlight_token_text('VAR_0 is recomputed.', view)
        assert 'class="tok tok-identifier"' in rendered

    def test_unknown_tokens_are_marked_unresolved(self):
        rendered = highlight_token_text('VAR_7 is odd.', {})
        assert 'class="unresolved"' in rendered

    def test_prose_is_untouched_apart_from_escaping(self):
        rendered = highlight_token_text('No issues found.', {})
        assert rendered == 'No issues found.'


class TestLabelStyling:

    def test_each_label_has_its_own_class(self):
        classes = {
            highlight.label_class(label)
            for label in ('SECRET', 'VALUE', 'IDENTIFIER')
        }
        assert len(classes) == 3

    def test_an_unknown_label_falls_back_rather_than_vanishing(self):
        assert highlight.label_class('BRAND_NEW') == highlight.DEFAULT_LABEL_CLASS

    def test_every_emitted_class_exists_in_the_stylesheet(self):
        """
        A class the CSS does not define renders as unmarked text.

        That failure is invisible in a unit test of the HTML, so the
        stylesheet is checked against the class list here.
        """
        from pathlib import Path

        css = Path(__file__).resolve().parents[2] / 'web' / 'static' / 'app.css'
        text = css.read_text(encoding='utf-8')

        for name in list(highlight.LABEL_CLASSES.values()) + ['unresolved', 'restored']:
            assert re.search(r'[.\s]' + re.escape(name) + r'\b', text), (
                f"{name} is emitted by web/highlight.py but not styled"
            )
