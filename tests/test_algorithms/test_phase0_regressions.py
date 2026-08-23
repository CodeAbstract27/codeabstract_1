"""
Phase 0 leak-regression suite.

One test class per defect recorded in ``docs/AUDIT.md``.  Each asserts on
the exact input that reproduced the defect, so a regression fails here
rather than in a demo.

These are deliberately written as *behavioural* assertions about what
crosses the network — "this string must not appear in the abstract code" —
rather than assertions about internal structure.  The abstraction strategy
is expected to keep changing; the guarantee is not.
"""

import ast

import pytest

from algorithms.abstract import abstract
from algorithms.encrypt import decrypt_mapping
from algorithms.reconstruct import reconstruct

ALL_LEVELS = ["low", "medium", "high", "critical"]


def _mapping(result):
    return decrypt_mapping(result.encrypted_mapping, result.encryption_key)


# ═══════════════════════════════════════════════════════════
# D1 — secret values must never be transmitted
# ═══════════════════════════════════════════════════════════

class TestD1SecretValueLeakage:
    """Secret literals must be redacted at every privacy level."""

    LEAKY_SOURCE = '''
api_key = "sk_live_51H8xQ2eZvKYlo2C"
db_pass = "hunter2"
conn = f"postgres://admin:{db_pass}@10.2.3.4:5432/prod_billing"
header = f"Bearer sk_live_51H8xQ2eZvKYlo2C"

def login(user):
    return {"Authorization": "Bearer " + api_key}
'''

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_stripe_key_never_leaks(self, level):
        """The live key must not survive at any level, including 'low'."""
        result = abstract(self.LEAKY_SOURCE, privacy_level=level)
        assert "sk_live_51H8xQ2eZvKYlo2C" not in result.abstract_code

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_fstring_secret_never_leaks(self, level):
        """
        f-string fragments were skipped wholesale, making them a reliable
        exfiltration path at every level.
        """
        result = abstract(self.LEAKY_SOURCE, privacy_level=level)
        assert "Bearer sk_live" not in result.abstract_code

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_connection_string_never_leaks(self, level):
        """
        The credential is interpolated, so no single fragment matches --
        only the flattened template does.
        """
        result = abstract(self.LEAKY_SOURCE, privacy_level=level)
        assert "prod_billing" not in result.abstract_code
        assert "10.2.3.4" not in result.abstract_code
        assert "postgres://admin" not in result.abstract_code

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_weak_password_never_leaks(self, level):
        """
        'hunter2' has no credential shape and too little entropy to be
        detected by value.  Only propagation from the 'db_pass' binding
        catches it.
        """
        result = abstract(self.LEAKY_SOURCE, privacy_level=level)
        assert "hunter2" not in result.abstract_code

    @pytest.mark.parametrize("value", [
        "sk_live_51H8xQ2eZvKYlo2C",
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_016C6e8Bf7Aa9De3Bc0Fd2Ee4Ff6Aa8Bb0Cc",
        "xoxb-111111-222222-abc123def456",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9",
        "-----BEGIN RSA PRIVATE KEY-----",
        "mongodb+srv://root:s3cr3t@cluster0.example.net",
    ])
    def test_known_credential_formats_redacted(self, value):
        """Vendor key formats are caught by shape, whatever they are named."""
        source = f'harmless_looking_name = "{value}"\n'
        result = abstract(source, privacy_level="low")
        assert value not in result.abstract_code

    def test_secret_propagates_through_keyword_argument(self):
        """connect(password=...) marks the literal even with a bland name."""
        source = 'conn = connect(host="db", password="p9x2QvB")\n'
        result = abstract(source, privacy_level="low")
        assert "p9x2QvB" not in result.abstract_code

    def test_secret_propagates_through_dict_entry(self):
        """{"api_key": ...} marks the value."""
        source = 'cfg = {"api_key": "abc123xyz"}\n'
        result = abstract(source, privacy_level="low")
        assert "abc123xyz" not in result.abstract_code

    def test_secret_propagates_through_attribute_assignment(self):
        """self.api_key = ... marks the literal."""
        source = '''
class Client:
    def setup(self):
        self.api_key = "zz9pluralZalpha"
'''
        result = abstract(source, privacy_level="low")
        assert "zz9pluralZalpha" not in result.abstract_code

    def test_endpoints_are_not_misfiled_as_secrets(self):
        """
        A bare URL is a business VALUE, not a credential.  Guarding against
        over-redaction matters: false positives cost the LLM utility for
        no privacy gain.
        """
        from core.secret_detector import is_secret_value
        assert not is_secret_value("https://api.payment.com/v2/charges")
        assert not is_secret_value("your-api-key-here")
        assert not is_secret_value("xxxxxxxxxxxxxxxxxxxxxxxxxx")

    def test_abstract_output_stays_valid_python(self):
        """Redacting f-string fragments must not corrupt the f-string."""
        for level in ALL_LEVELS:
            result = abstract(self.LEAKY_SOURCE, privacy_level=level)
            ast.parse(result.abstract_code)  # must not raise


# ═══════════════════════════════════════════════════════════
# D2 — token substitution must not collide
# ═══════════════════════════════════════════════════════════

class TestD2TokenCollision:
    """VAR_1 must not substitute itself inside VAR_10."""

    def test_prefix_collision_does_not_corrupt(self):
        source = "\n".join(f"variable_number_{i} = {i}" for i in range(12))
        result = abstract(source, privacy_level="high")

        response = "Bug in VAR_1 and also VAR_10 is wrong."
        translated = reconstruct(
            response, result.encrypted_mapping, result.encryption_key,
        )

        first_line = translated.split("\n")[0]
        assert "variable_number_10" in first_line
        # The signature of the old bug: a truncated name with a stray digit.
        assert "variable_number_1 (line 2)0" not in first_line

    def test_every_token_resolves_to_its_own_name(self):
        """Exhaustive check across a mapping large enough to collide."""
        source = "\n".join(f"identifier_{i} = {i}" for i in range(25))
        result = abstract(source, privacy_level="high")
        mapping = _mapping(result)

        var_tokens = [t for t in mapping if t.startswith("VAR_")]
        assert len(var_tokens) >= 20, "need enough tokens to force collisions"

        response = " ".join(var_tokens)
        translated = reconstruct(
            response, result.encrypted_mapping, result.encryption_key,
        )
        body = translated.split("Source Context")[0]

        for token in var_tokens:
            expected = mapping[token]["name"]
            assert f"{expected} (line" in body, f"{token} lost its name"

    def test_unknown_tokens_are_preserved(self):
        """A token with no mapping entry must pass through untouched."""
        source = "alpha_value = 1\n"
        result = abstract(source, privacy_level="high")
        translated = reconstruct(
            "Check VAR_0 and VAR_9999",
            result.encrypted_mapping, result.encryption_key,
        )
        assert "VAR_9999" in translated


# ═══════════════════════════════════════════════════════════
# D3 — imports must not leak vendor or internal names
# ═══════════════════════════════════════════════════════════

class TestD3ImportLeakage:
    """Vendor SDKs and internal packages must be abstracted."""

    SOURCE = '''
import stripe
from acme_internal.billing import ledger
ledger.post(1)
'''

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_vendor_module_not_leaked(self, level):
        result = abstract(self.SOURCE, privacy_level=level)
        assert "stripe" not in result.abstract_code

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_internal_package_not_leaked(self, level):
        result = abstract(self.SOURCE, privacy_level=level)
        assert "acme_internal" not in result.abstract_code
        assert "ledger" not in result.abstract_code

    def test_import_binding_matches_use_site(self):
        """
        An import tokenised to MODULE_n while its use site kept the original
        name would emit code that no longer resolves.
        """
        result = abstract(self.SOURCE, privacy_level="high")
        code = result.abstract_code
        ast.parse(code)

        imported = [
            line.split("import")[-1].strip()
            for line in code.splitlines()
            if line.startswith("from ")
        ]
        assert imported, "expected a from-import in the output"
        assert f"{imported[0]}.".lower() in code.lower()

    def test_stdlib_preserved_for_utility(self):
        """Abstracting the standard library would destroy LLM utility."""
        source = "import asyncio\nfrom typing import Optional\n"
        result = abstract(source, privacy_level="high")
        assert "import asyncio" in result.abstract_code
        assert "Optional" in result.abstract_code

    def test_preserved_import_is_consistent_at_use_site(self):
        """
        A name kept in the import block but tokenised at its use site is an
        alignment oracle: an attacker reads the import list and pins the
        token immediately.
        """
        source = '''
from typing import Optional

def handler(value: Optional[str] = None) -> dict:
    return {"v": value}
'''
        result = abstract(source, privacy_level="high")
        assert "Optional" in result.abstract_code
        # It must survive at the annotation, not only in the import line.
        annotation_line = [
            ln for ln in result.abstract_code.splitlines() if "def " in ln
        ]
        assert annotation_line and "Optional" in annotation_line[0]

    def test_relative_imports_treated_as_internal(self):
        source = "from .billing import ledger\nledger.post(1)\n"
        result = abstract(source, privacy_level="high")
        assert "billing" not in result.abstract_code
        assert "ledger" not in result.abstract_code


# ═══════════════════════════════════════════════════════════
# D5 — privacy levels must be distinct
# ═══════════════════════════════════════════════════════════

class TestD5PrivacyLevels:
    """Each documented level must produce distinct behaviour."""

    SOURCE = '''
API_KEY = "sk_live_51H8xQ2eZvKYlo2C"
commission_rate = 0.029

def calculate(x):
    total_amount = x * commission_rate
    return total_amount
'''

    def test_four_levels_produce_four_outputs(self):
        outputs = {
            level: abstract(self.SOURCE, privacy_level=level).abstract_code
            for level in ALL_LEVELS
        }
        assert len(set(outputs.values())) == 4, (
            "each privacy level must be distinguishable:\n"
            + "\n\n".join(f"--- {k} ---\n{v}" for k, v in outputs.items())
        )

    def test_critical_abstracts_short_names(self):
        """The 'abstract_short_names' flag must actually do something."""
        high = abstract(self.SOURCE, privacy_level="high").abstract_code
        critical = abstract(self.SOURCE, privacy_level="critical").abstract_code
        assert "(x)" in high
        assert "(x)" not in critical

    def test_low_leaves_ordinary_identifiers_alone(self):
        code = abstract(self.SOURCE, privacy_level="low").abstract_code
        assert "calculate" in code

    def test_medium_abstracts_business_values(self):
        code = abstract(self.SOURCE, privacy_level="medium").abstract_code
        assert "commission_rate" not in code

    def test_secrets_abstracted_at_every_level(self):
        for level in ALL_LEVELS:
            code = abstract(self.SOURCE, privacy_level=level).abstract_code
            assert "API_KEY" not in code, f"leaked at {level}"


# ═══════════════════════════════════════════════════════════
# D6 — packaging and entry-point defects
# ═══════════════════════════════════════════════════════════

class TestD6Housekeeping:
    """Small defects that broke the CLI or misreported results."""

    def test_version_is_importable(self):
        """`--version` raised ImportError via a bad relative import."""
        from config.settings import __version__
        assert __version__

    def test_version_callback_does_not_raise(self):
        import typer
        from cli import version_callback

        with pytest.raises(typer.Exit):
            version_callback(True)

    def test_utf8_helper_is_idempotent(self):
        from ui.console import ensure_utf8_stdout
        ensure_utf8_stdout()
        ensure_utf8_stdout()
