"""
Phase 1 mapping regression suite.

Covers the scoped symbol table (D4), occurrence records, abstract-to-
original line translation, project overrides, the comment policy, and
fix application.

As in the Phase 0 suite, assertions are behavioural: they state what the
developer must end up seeing, not how the engine arrives at it.
"""

import ast

import pytest

from algorithms.abstract import abstract
from algorithms.apply_fix import build_diff, detokenise, recover_fixes
from algorithms.encrypt import decrypt_mapping
from algorithms.reconstruct import reconstruct
from config.ignore_rules import OverrideRules, parse_rules

SHADOWED_SOURCE = '''def alpha(data):
    result = data * 2
    return result

def beta(data):
    result = data + 1
    return result
'''


def _mapping(result):
    return decrypt_mapping(result.encrypted_mapping, result.encryption_key)


# ═══════════════════════════════════════════════════════════
# D4 — scope-aware token identity
# ═══════════════════════════════════════════════════════════

class TestD4ScopedSymbols:
    """Identically-named symbols in different scopes must not collide."""

    def test_shadowed_names_get_distinct_tokens(self):
        result = abstract(SHADOWED_SOURCE, privacy_level="high")
        mapping = _mapping(result)

        result_tokens = [t for t, e in mapping.items() if e['name'] == 'result']
        assert len(result_tokens) == 2, (
            "alpha.result and beta.result must be different symbols"
        )

    def test_each_token_records_its_own_definition_line(self):
        result = abstract(SHADOWED_SOURCE, privacy_level="high")
        mapping = _mapping(result)

        lines = sorted(
            e['lineno'] for e in mapping.values() if e['name'] == 'result'
        )
        assert lines == [2, 6], f"expected definition lines 2 and 6, got {lines}"

    def test_scope_is_recorded(self):
        result = abstract(SHADOWED_SOURCE, privacy_level="high")
        mapping = _mapping(result)

        scopes = {
            e['scope'] for e in mapping.values() if e['name'] == 'result'
        }
        assert scopes == {'module.alpha', 'module.beta'}

    def test_reconstruct_points_at_the_right_function(self):
        """The end-to-end symptom D4 described."""
        result = abstract(SHADOWED_SOURCE, privacy_level="high")
        mapping = _mapping(result)

        beta_token = next(
            t for t, e in mapping.items()
            if e['name'] == 'result' and e['scope'] == 'module.beta'
        )
        translated = reconstruct(
            f"The bug is in {beta_token}.",
            result.encrypted_mapping, result.encryption_key,
        )
        assert "line 6" in translated
        assert "line 2" not in translated.split("Source Context")[0]

    def test_occurrences_are_recorded(self):
        result = abstract(SHADOWED_SOURCE, privacy_level="high")
        mapping = _mapping(result)

        for entry in mapping.values():
            if entry['name'] == 'result':
                linenos = [o['lineno'] for o in entry['occurrences']]
                assert len(linenos) == 2, "assignment and return"

    def test_class_body_does_not_leak_into_methods(self):
        """
        Python scoping: a method does not see its class body's names, so
        the two `rate` bindings are genuinely different symbols.
        """
        source = '''
class Payment:
    rate = 0.02
    def charge(self, amount):
        rate = 0.05
        return amount * rate
'''
        result = abstract(source, privacy_level="high")
        mapping = _mapping(result)
        scopes = {e['scope'] for e in mapping.values() if e['name'] == 'rate'}
        assert scopes == {'module.Payment', 'module.Payment.charge'}

    def test_literal_does_not_collide_with_variable(self):
        """
        A string literal sharing a variable's spelling previously collapsed
        `{"endpoint": endpoint}` into `{VAR_7: VAR_7}`.
        """
        source = 'def f(x):\n    endpoint = x\n    return {"endpoint": endpoint}\n'
        result = abstract(source, privacy_level="high")
        mapping = _mapping(result)

        tokens = [t for t, e in mapping.items() if e['name'] == 'endpoint']
        assert len(tokens) == 2, "the literal and the variable are distinct"

    def test_global_declaration_resolves_to_module_scope(self):
        source = '''
counter_value = 0

def bump():
    global counter_value
    counter_value += 1
'''
        result = abstract(source, privacy_level="high")
        mapping = _mapping(result)
        tokens = [t for t, e in mapping.items() if e['name'] == 'counter_value']
        assert len(tokens) == 1, "a global is one symbol, not two"

    def test_comprehension_has_its_own_scope(self):
        source = '''
def outer(values):
    item = 1
    return [item for item in values]
'''
        result = abstract(source, privacy_level="high")
        mapping = _mapping(result)
        scopes = {e['scope'] for e in mapping.values() if e['name'] == 'item'}
        assert len(scopes) == 2, "comprehension target is not the outer local"


# ═══════════════════════════════════════════════════════════
# Line translation
# ═══════════════════════════════════════════════════════════

class TestLineTranslation:
    """LLM line citations must land on the developer's own lines."""

    COMMENTED_SOURCE = '''# header comment
# another header line


import os


# explain the constant
RATE_VALUE = 0.029


def compute(amount):
    """Docstring."""

    # inline note
    fee = amount * RATE_VALUE
    return fee
'''

    def test_line_map_is_built(self):
        result = abstract(self.COMMENTED_SOURCE, privacy_level="high")
        assert result.line_map, "a line index must be produced"

    def test_map_points_at_real_statements(self):
        result = abstract(self.COMMENTED_SOURCE, privacy_level="high")
        original_lines = self.COMMENTED_SOURCE.split('\n')

        for _, original in result.line_map.items():
            text = original_lines[original - 1].strip()
            assert text and not text.startswith('#'), (
                f"line {original} is blank or a comment: {text!r}"
            )

    def test_citation_is_translated(self):
        result = abstract(self.COMMENTED_SOURCE, privacy_level="high")
        abstract_lines = result.abstract_code.split('\n')

        # Find the abstract line holding the multiplication.
        target = next(
            i for i, line in enumerate(abstract_lines, 1) if '*' in line
        )
        expected = result.line_map[target]

        translated = reconstruct(
            f"The bug is on line {target}.",
            result.encrypted_mapping, result.encryption_key,
            line_map=result.line_map,
        )
        assert f"line {expected}" in translated
        assert expected != target, "this fixture must actually shift lines"

    def test_ranges_are_translated(self):
        result = abstract(self.COMMENTED_SOURCE, privacy_level="high")
        pairs = sorted(result.line_map.items())
        first, second = pairs[0], pairs[-1]

        translated = reconstruct(
            f"See lines {first[0]}-{second[0]}.",
            result.encrypted_mapping, result.encryption_key,
            line_map=result.line_map,
        )
        assert f"{first[1]}-{second[1]}" in translated

    def test_unknown_line_is_left_alone(self):
        result = abstract(self.COMMENTED_SOURCE, privacy_level="high")
        translated = reconstruct(
            "Check line 9999.",
            result.encrypted_mapping, result.encryption_key,
            line_map=result.line_map,
        )
        assert "line 9999" in translated

    def test_without_line_map_behaviour_is_unchanged(self):
        """Sessions created before Phase 1 must keep working."""
        result = abstract(self.COMMENTED_SOURCE, privacy_level="high")
        translated = reconstruct(
            "The bug is on line 3.",
            result.encrypted_mapping, result.encryption_key,
        )
        assert "line 3" in translated

    @pytest.mark.parametrize("joiner", [" to ", " through ", " - ", "-"])
    def test_joiner_without_a_second_number_is_preserved(self, joiner):
        """
        "the bug on line 4 to prevent this" is prose, not a range.

        The joiner group matches whether or not a second number follows, so
        the rewriter used to consume ' to ' and emit nothing in its place,
        silently gluing the sentence back together as "line 42prevent this".
        """
        from algorithms.reconstruct import _translate_line_references

        text = f"the bug on line 4{joiner}prevent this"
        translated = _translate_line_references(text, {4: 42})

        assert translated == f"the bug on line 42{joiner}prevent this"

    def test_genuine_range_still_translates_both_ends(self):
        from algorithms.reconstruct import _translate_line_references

        assert _translate_line_references(
            "lines 4 to 6 are wrong", {4: 42, 6: 44},
        ) == "lines 42 to 44 are wrong"

    def test_unmappable_range_end_leaves_citation_untouched(self):
        from algorithms.reconstruct import _translate_line_references

        assert _translate_line_references(
            "lines 4-6 are wrong", {4: 42},
        ) == "lines 4-6 are wrong"


# ═══════════════════════════════════════════════════════════
# Project overrides
# ═══════════════════════════════════════════════════════════

class TestOverrides:
    """.codeabstractignore must be able to recover utility, never privacy."""

    def test_parse_directives(self):
        rules = parse_rules(
            "# comment\n"
            "keep:customer_id\n"
            "secret:tenant_ref\n"
            "module:acme_common\n"
            "bare_name\n"
        )
        assert rules.should_keep("customer_id")
        assert rules.should_keep("bare_name")
        assert rules.is_forced_secret("tenant_ref")
        assert rules.is_safe_module("acme_common.billing")

    def test_keep_preserves_identifier(self):
        source = "def handler(customer_id):\n    return customer_id\n"
        rules = parse_rules("keep:customer_id")
        result = abstract(source, privacy_level="high", overrides=rules)
        assert "customer_id" in result.abstract_code

    def test_glob_keep(self):
        source = "def handle_order(x):\n    return x\n"
        rules = parse_rules("keep:handle_*")
        result = abstract(source, privacy_level="high", overrides=rules)
        assert "handle_order" in result.abstract_code

    def test_force_secret(self):
        source = "tenant_ref = 12345\n"
        rules = parse_rules("secret:tenant_ref")
        result = abstract(source, privacy_level="low", overrides=rules)
        assert "tenant_ref" not in result.abstract_code

    def test_keep_cannot_expose_a_real_secret(self):
        """
        The safety property: a config file must not be able to put a live
        credential on the wire.
        """
        source = 'api_key = "sk_live_51H8xQ2eZvKYlo2C"\n'
        rules = parse_rules("keep:api_key\nkeep:sk_live_51H8xQ2eZvKYlo2C")
        result = abstract(source, privacy_level="high", overrides=rules)
        assert "sk_live_51H8xQ2eZvKYlo2C" not in result.abstract_code

    def test_module_rule_preserves_internal_package(self):
        source = "from acme_common import util\nutil.run()\n"
        rules = parse_rules("module:acme_common")
        result = abstract(source, privacy_level="high", overrides=rules)
        assert "acme_common" in result.abstract_code

    def test_no_rules_is_a_no_op(self):
        source = "def handler(customer_id):\n    return customer_id\n"
        plain = abstract(source, privacy_level="high").abstract_code
        empty = abstract(
            source, privacy_level="high", overrides=OverrideRules()
        ).abstract_code
        assert plain == empty


# ═══════════════════════════════════════════════════════════
# Comment policy
# ═══════════════════════════════════════════════════════════

class TestCommentPolicy:
    """Comments are stripped by default; preservation is screened."""

    SOURCE = '''# Commission is 2.5% per contract.
def compute(amount):
    # ordinary explanatory note
    total_due = amount * 2
    return total_due
'''

    def test_comments_stripped_by_default(self):
        result = abstract(self.SOURCE, privacy_level="high")
        assert "#" not in result.abstract_code

    def test_keep_comments_preserves_safe_comments(self):
        result = abstract(self.SOURCE, privacy_level="high", keep_comments=True)
        assert "ordinary explanatory note" in result.abstract_code

    def test_keep_comments_drops_business_sensitive_comments(self):
        result = abstract(self.SOURCE, privacy_level="high", keep_comments=True)
        assert "Commission" not in result.abstract_code

    def test_keep_comments_redacts_credentials_in_prose(self):
        source = '# key is sk_live_51H8xQ2eZvKYlo2C\nvalue_here = 1\n'
        result = abstract(source, privacy_level="high", keep_comments=True)
        assert "sk_live_51H8xQ2eZvKYlo2C" not in result.abstract_code

    def test_kept_comments_do_not_reintroduce_identifiers(self):
        source = '''def calculate_thing(x):
    return x

# see calculate_thing above
other_value = 1
'''
        result = abstract(source, privacy_level="high", keep_comments=True)
        assert "calculate_thing" not in result.abstract_code

    def test_output_still_parses_with_comments(self):
        result = abstract(self.SOURCE, privacy_level="high", keep_comments=True)
        ast.parse(result.abstract_code)


# ═══════════════════════════════════════════════════════════
# Applying fixes back
# ═══════════════════════════════════════════════════════════

class TestApplyFix:
    """Suggestions must come back de-tokenised, or not at all."""

    SOURCE = '''def calculate_total(amount):
    fee = amount * 2
    return fee
'''

    def test_detokenise_restores_names(self):
        mapping = {'FUNC_0': {'name': 'calculate_total', 'lineno': 1}}
        restored, count, unresolved = detokenise("def FUNC_0(x): pass", mapping)
        assert "calculate_total" in restored
        assert count == 1
        assert not unresolved

    def test_detokenise_is_collision_safe(self):
        mapping = {
            'VAR_1': {'name': 'alpha', 'lineno': 1},
            'VAR_10': {'name': 'omega', 'lineno': 2},
        }
        restored, _, _ = detokenise("VAR_1 + VAR_10", mapping)
        assert restored == "alpha + omega"

    def test_unresolved_tokens_are_reported(self):
        restored, count, unresolved = detokenise("VAR_99 = 1", {})
        assert unresolved == ['VAR_99']
        assert count == 0

    def test_recover_whole_file_suggestion(self):
        result = abstract(self.SOURCE, privacy_level="high")
        mapping = _mapping(result)

        func_token = next(
            t for t, e in mapping.items() if e['name'] == 'calculate_total'
        )
        response = (
            "Here is the fix:\n\n```python\n"
            + result.abstract_code.replace("* NUM_0", "* NUM_0  # fixed")
            + "\n```\n"
        )
        fixes = recover_fixes(
            response, result.encrypted_mapping, result.encryption_key,
            original_source=self.SOURCE,
        )
        assert fixes, "a python block should be recovered"
        assert fixes[0].parses
        assert "calculate_total" in fixes[0].restored_code
        assert func_token not in fixes[0].restored_code

    def test_fragment_is_not_applicable(self):
        result = abstract(self.SOURCE, privacy_level="high")
        response = "```python\nx = 1\n```"
        fixes = recover_fixes(
            response, result.encrypted_mapping, result.encryption_key,
            original_source=self.SOURCE,
        )
        assert fixes and not fixes[0].applicable, (
            "a fragment must never be offered as a whole-file patch"
        )

    def test_non_python_blocks_ignored(self):
        result = abstract(self.SOURCE, privacy_level="high")
        fixes = recover_fixes(
            "```bash\nrm -rf /\n```",
            result.encrypted_mapping, result.encryption_key,
            original_source=self.SOURCE,
        )
        assert fixes == []

    def test_build_diff(self):
        diff = build_diff("a = 1\n", "a = 2\n", "x.py")
        assert "-a = 1" in diff
        assert "+a = 2" in diff

    def test_identical_content_has_empty_diff(self):
        assert build_diff("a = 1\n", "a = 1\n", "x.py") == ""

    # ── No top-level defs: the whole-file heuristic falls back to
    # content similarity, not a bare line count (regression) ──────────

    NO_DEF_SOURCE = '''x = 1
y = 2
print(x + y)
'''

    def test_unrelated_block_not_applicable_when_source_has_no_defs(self):
        """
        A script with no top-level function/class defs has nothing to
        match structurally. A long-enough-but-unrelated code block must
        not be classified as a whole-file rewrite: applying it would
        silently discard the developer's actual file.
        """
        result = abstract(self.NO_DEF_SOURCE, privacy_level="high")
        response = (
            "Here's an unrelated example:\n\n```python\n"
            "def unrelated_helper():\n    pass\n\n"
            "def another_one():\n    pass\n"
            "```\n"
        )
        fixes = recover_fixes(
            response, result.encrypted_mapping, result.encryption_key,
            original_source=self.NO_DEF_SOURCE,
        )
        assert fixes and not fixes[0].applicable, (
            "an unrelated block must never be offered as a whole-file "
            "patch just because it has enough lines"
        )

    def test_genuine_rewrite_still_applicable_when_source_has_no_defs(self):
        """The similarity fallback must not break the legitimate case."""
        result = abstract(self.NO_DEF_SOURCE, privacy_level="high")
        response = (
            "Here is the fix:\n\n```python\n"
            + result.abstract_code.replace("NUM_0", "NUM_0  # fixed")
            + "\n```\n"
        )
        fixes = recover_fixes(
            response, result.encrypted_mapping, result.encryption_key,
            original_source=self.NO_DEF_SOURCE,
        )
        assert fixes and fixes[0].applicable
        assert "x = 1" in fixes[0].restored_code


# ═══════════════════════════════════════════════════════════
# Import bindings that the filters used to drop (ultrareview)
# ═══════════════════════════════════════════════════════════

class TestAbstractedImportBindingsResolve:
    """
    An import Step 5d rewrote must have every use site rewritten too.

    The significance filter used to run before the symbol was resolved, so
    a binding it rejected -- a single-character alias, one shadowing a
    builtin -- had its import turned into ``import MODULE_0`` while the use
    site kept the original name and referred to nothing.
    """

    @pytest.mark.parametrize("alias", ["s", "list", "p"])
    def test_filtered_alias_still_resolves(self, alias):
        source = (
            f"import stripe as {alias}\n"
            "\n"
            "def charge():\n"
            f"    return {alias}.Charge.create(100)\n"
        )
        result = abstract(source, privacy_level="high")

        tree = ast.parse(result.abstract_code)
        bound = {
            a.asname or a.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for a in node.names
        }
        # Literal placeholders (NUM_0, CONST_0) are Load names by design and
        # bind nothing; only module references have to resolve to an import.
        used = {
            n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name)
            and isinstance(n.ctx, ast.Load)
            and n.id.startswith("MODULE_")
        }
        assert used, "expected the module reference to be tokenised"
        assert used <= bound, (
            f"{used - bound} is used but never bound -- the import was "
            f"abstracted while its use site was left behind"
        )
        # Compared as identifiers, not as substrings: "p" occurs inside
        # "import" and would make a substring check fail spuriously.
        identifiers = {
            n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
        } | bound
        assert alias not in identifiers

    def test_keep_rule_cannot_strand_an_abstracted_import(self):
        source = "import stripe as s\n\nresult = s.Charge.create(100)\n"
        rules = parse_rules("keep: s\n")
        result = abstract(source, privacy_level="high", overrides=rules)

        assert "s.Charge" not in result.abstract_code
        ast.parse(result.abstract_code)


class TestModuleMappingEntries:
    """MODULE rows carry the same shape and the import's own line."""

    SOURCE = "import stripe\n\ndef charge():\n    return stripe.Charge.create(1)\n"

    def _module_entries(self):
        result = abstract(self.SOURCE, privacy_level="high")
        mapping = _mapping(result)
        return [e for t, e in mapping.items() if t.startswith("MODULE")]

    def test_entry_has_classifier_fields(self):
        for entry in self._module_entries():
            assert {"confidence", "detector", "evidence"} <= set(entry), (
                "MODULE rows must match the shape every other row has, or "
                "consumers iterating the table raise KeyError"
            )

    def test_definition_line_is_the_import_not_the_first_use(self):
        entries = self._module_entries()
        assert entries, "expected stripe to be abstracted"
        for entry in entries:
            assert entry["lineno"] == 1, (
                "the import statement is the module's definition site; "
                "line 4 is merely where it is first used"
            )
