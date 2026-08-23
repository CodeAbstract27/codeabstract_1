"""
Leak paths found by the end-to-end audit of 19 August 2026.

Each test here reproduces a defect that the 526-test suite did not catch,
and every one is a *leak*: something the privacy guarantee says never
crosses the network, and which did.  They are grouped by the defect ID used
in the audit summary rather than by module, because the point of the file is
to fail with the name of the guarantee that broke.

| ID | Guarantee that broke |
|----|----------------------|
| L1 | A credential is detected by the shape of its value, at every privacy level |
| L2 | Comments are screened before they are sent (Python's stated policy, applied to JavaScript) |
| L3 | Vendor brand references in imports are abstracted, in both languages |
| L4 | A value flowing into a detected credential template is itself a credential |
| L5 | The tool does not print the credentials it stores |
| L6 | ``medium`` abstracts endpoints, as its documentation says it does |

Two threads run through all six.  Four of them (L1, L4, L5, L6) are the same
structural mistake Phase 0 / D1 identified — a value judged on the wrong
node, or on the wrong *type* of node — reappearing on axes D1 did not
cover: ``bytes`` rather than ``str``, the argument rather than the
template, the config file rather than the source file, VALUE rather than
SECRET.  The other two (L2, L3) are the JavaScript adapter not inheriting a
policy Python already enforced.

The corresponding fixes live in ``core.secret_detector``, ``algorithms.classify``,
``algorithms.abstract_source``, ``core.context_features``,
``core.languages.javascript``, ``config.allowlist`` and ``commands.config_cmd``.
"""

import pytest

from algorithms.abstract import abstract
from config.allowlist import is_safe_js_module, is_safe_module
from core.secret_detector import is_endpoint_value, is_secret_value


# The levels at which a *credential* must always be abstracted.  A
# credential is never business-sensitive-but-shareable, so unlike a business
# VALUE it does not get to survive at ``low`` -- see the module docstring of
# ``core.secret_detector``.
ALL_LEVELS = ('low', 'medium', 'high', 'critical')


def abstracted(source, level, language='python', keep_comments=False):
    """Abstract *source* and return only what would be sent to the LLM."""
    if language == 'python':
        return abstract(
            source, privacy_level=level, keep_comments=keep_comments,
        ).abstract_code

    from algorithms.abstract_source import abstract_source
    return abstract_source(
        source, language=language, privacy_level=level,
        keep_comments=keep_comments,
    ).abstract_code


# ═══════════════════════════════════════════════════════════
# L1 — bytes literals bypassed value-shape detection
# ═══════════════════════════════════════════════════════════

class TestL1BytesCredentials:
    """
    ``is_secret_value`` returned False for anything that was not ``str``.

    Every credential format in the detector is a byte-oriented wire format,
    and code that talks to a socket or an HMAC routine holds them as
    ``bytes`` -- ``hmac.new(b"sk_live_...", ...)`` is the idiomatic
    spelling, not the exotic one.  The literal was judged only by the
    accident of what ``str(b"...")`` happens to contain, so ``TOKEN =
    b"ghp_..."`` was caught by its *name* while ``k = b"sk_live_..."`` was
    transmitted verbatim at ``low`` and ``medium``.
    """

    def test_detector_accepts_bytes(self):
        assert is_secret_value(b'sk_live_51H8xQ2eZvKYlo2C') is True

    def test_detector_still_accepts_str(self):
        assert is_secret_value('sk_live_51H8xQ2eZvKYlo2C') is True

    def test_detector_rejects_harmless_bytes(self):
        assert is_secret_value(b'hello world') is False

    def test_undecodable_bytes_do_not_raise(self):
        # A binary blob is not text and must not crash the detector.
        assert is_secret_value(b'\xff\xfe\x00\x01') is False

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_bytes_stripe_key_never_transmitted(self, level):
        out = abstracted("k = b'sk_live_51H8xQ2eZvKYlo2C'\n", level)
        assert 'sk_live_51H8xQ2eZvKYlo2C' not in out

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_bytes_matches_str_behaviour(self, level):
        """The same credential must not depend on the literal's prefix."""
        as_bytes = abstracted("k = b'sk_live_51H8xQ2eZvKYlo2C'\n", level)
        as_text = abstracted("k = 'sk_live_51H8xQ2eZvKYlo2C'\n", level)
        assert ('sk_live' in as_bytes) == ('sk_live' in as_text)

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_bytes_aws_key_never_transmitted(self, level):
        out = abstracted("k = b'AKIAIOSFODNN7EXAMPLE'\n", level)
        assert 'AKIAIOSFODNN7EXAMPLE' not in out

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_bytes_hmac_argument(self, level):
        source = "import hmac\nsig = hmac.new(b'sk_live_51H8xQ2eZvKYlo2C', msg)\n"
        assert 'sk_live_51H8xQ2eZvKYlo2C' not in abstracted(source, level)


# ═══════════════════════════════════════════════════════════
# L2 — JavaScript comments were never screened
# ═══════════════════════════════════════════════════════════

class TestL2JavaScriptComments:
    """
    ``core.comment_handler`` states the policy: comments are stripped by
    default, and when kept they are screened, because a comment is where
    business context lives most densely.

    The JavaScript adapter rewrites the file in place, so comments were
    never removed to begin with -- and nothing screened them.  A key in a
    ``//`` comment was transmitted verbatim at *every* level, ``critical``
    included, which is worse than the Python path was before Phase 0.
    """

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_line_comment_secret_is_screened(self, level):
        source = '// key is sk_live_51H8xQ2eZvKYlo2C\nconst x = 1;\n'
        assert 'sk_live_51H8xQ2eZvKYlo2C' not in abstracted(
            source, level, language='javascript')

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_block_comment_secret_is_screened(self, level):
        source = '/* token: ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGG12 */\nconst x = 1;\n'
        assert 'ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGG12' not in abstracted(
            source, level, language='javascript')

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_jsdoc_secret_is_screened(self, level):
        source = (
            '/**\n * @param k defaults to sk_live_51H8xQ2eZvKYlo2C\n */\n'
            'function f(k) { return k; }\n'
        )
        assert 'sk_live_51H8xQ2eZvKYlo2C' not in abstracted(
            source, level, language='javascript')

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_business_context_comment_is_screened(self, level):
        """The Python policy drops business VALUE prose too, not just keys."""
        source = '// 2.5% Stripe commission rate, renegotiated Q3\nconst x = 1;\n'
        out = abstracted(source, level, language='javascript')
        assert 'renegotiated' not in out

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_screening_leaves_the_code_intact(self, level):
        """Redacting a comment must not damage the statement beside it."""
        source = 'const x = 1; // key is sk_live_51H8xQ2eZvKYlo2C\nconst y = 2;\n'
        out = abstracted(source, level, language='javascript')
        assert 'sk_live_51H8xQ2eZvKYlo2C' not in out
        assert 'const' in out
        # Both statements survive; only the comment text was removed.
        assert out.count('const') == 2

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_comments_are_stripped_by_default(self, level):
        """The stated policy, now applied to JavaScript as well as Python."""
        source = '// increment the counter\nconst x = 1;\n'
        assert 'increment the counter' not in abstracted(
            source, level, language='javascript')

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_harmless_comment_survives_when_kept(self, level):
        """Screening is not blanket deletion -- ordinary prose is utility."""
        source = '// increment the counter\nconst x = 1;\n'
        assert 'increment the counter' in abstracted(
            source, level, language='javascript', keep_comments=True)

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_kept_comments_are_still_screened(self, level):
        """--keep-comments is not an escape hatch for a credential."""
        source = '// key is sk_live_51H8xQ2eZvKYlo2C\nconst x = 1;\n'
        assert 'sk_live_51H8xQ2eZvKYlo2C' not in abstracted(
            source, level, language='javascript', keep_comments=True)

    def test_kept_comments_have_identifiers_rewritten(self):
        """Prose must not leak a name the code took care to hide."""
        source = (
            '// calculateCommission is called twice here\n'
            'function calculateCommission(amount) { return amount * 0.029; }\n'
        )
        out = abstracted(
            source, 'high', language='javascript', keep_comments=True)
        assert 'calculateCommission' not in out

    def test_comment_marker_inside_a_string_is_not_a_comment(self):
        """``"// not a comment"`` is data, and must not be treated as prose."""
        source = 'const url = "https://example.com/a//b";\n'
        out = abstracted(source, 'low', language='javascript')
        assert 'example.com' in out or 'CONST' in out or 'SECRET' in out


# ═══════════════════════════════════════════════════════════
# L3 — vendor brand references leaked from JS imports
# ═══════════════════════════════════════════════════════════

class TestL3VendorImports:
    """
    The proposal names "brand references" as a protected category and its
    worked example is literally Stripe.  ``config.allowlist`` enforces that
    for Python -- ``is_safe_module('stripe')`` is False -- but the
    JavaScript list shipped ``stripe``, ``twilio`` and ``openai`` as public
    vocabulary, so the same brand was hidden in one language and sent in
    the other.
    """

    @pytest.mark.parametrize('vendor', ['stripe', 'twilio', 'openai'])
    def test_python_and_javascript_agree(self, vendor):
        assert is_safe_module(vendor) == is_safe_js_module(vendor)

    @pytest.mark.parametrize('vendor', ['stripe', 'twilio', 'openai'])
    def test_vendor_sdk_is_not_allowlisted(self, vendor):
        assert is_safe_js_module(vendor) is False

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_default_import_of_a_vendor_is_abstracted(self, level):
        out = abstracted('import stripe from "stripe";\n',
                         level, language='javascript')
        assert 'stripe' not in out.lower()

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_require_of_a_vendor_is_abstracted(self, level):
        out = abstracted('const stripe = require("stripe");\n',
                         level, language='javascript')
        assert 'stripe' not in out.lower()

    def test_genuinely_public_packages_still_survive(self):
        """Failing closed on everything would cost the utility the
        allowlist exists to preserve."""
        for module in ('react', 'express', 'lodash', 'fs', 'axios'):
            assert is_safe_js_module(module) is True

    def test_public_framework_import_is_kept(self):
        out = abstracted('import express from "express";\n',
                         'high', language='javascript')
        assert 'express' in out


# ═══════════════════════════════════════════════════════════
# L4 — values flowing into a detected credential template
# ═══════════════════════════════════════════════════════════

class TestL4TemplateTaint:
    """
    Phase 0 taught the detector to flatten an f-string and recognise
    ``postgres://admin:{}@host/db`` as a connection string.  It redacted the
    *literal fragments* of that template and stopped there -- so the system
    identified the placeholder as a password position and then transmitted
    the password that filled it.

    The password only survived before because its own binding happened to
    be named ``db_pass``.  Rename it to ``p`` and every signal disappears,
    which is precisely the case the flattening was introduced to handle.
    """

    SOURCE = (
        "p = 'hunter2'\n"
        "conn = f'postgres://admin:{p}@10.2.3.4:5432/prod_billing'\n"
    )

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_interpolated_password_is_not_transmitted(self, level):
        assert 'hunter2' not in abstracted(self.SOURCE, level)

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_template_itself_still_redacted(self, level):
        """The Phase 0 guarantee must not regress while fixing this."""
        out = abstracted(self.SOURCE, level)
        assert 'prod_billing' not in out
        assert '10.2.3.4' not in out

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_mongodb_srv_credentials(self, level):
        source = (
            "q = 'hunter2'\n"
            "c = f'mongodb+srv://root:{q}@cluster0.mongodb.net/prod'\n"
        )
        assert 'hunter2' not in abstracted(source, level)

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_bearer_header_interpolation(self, level):
        source = "t = 'abc123def456'\nh = f'Bearer {t}'\n"
        assert "'abc123def456'" not in abstracted(source, level)

    @pytest.mark.parametrize('level', ('low', 'medium', 'high', 'critical'))
    def test_str_format_arguments_are_tainted(self, level):
        """``.format`` is the pre-f-string spelling of the same construct."""
        source = "t = 'db://{}:{}@h'.format(user, 'hunter2pass')\n"
        assert 'hunter2pass' not in abstracted(source, level)

    @pytest.mark.parametrize('level', ('low', 'medium', 'high', 'critical'))
    def test_percent_operator_arguments_are_tainted(self, level):
        source = "t = 'db://%s:%s@h' % (user, 'hunter2pass')\n"
        assert 'hunter2pass' not in abstracted(source, level)

    def test_format_on_a_harmless_template_is_untouched(self):
        source = "t = 'hello {}'.format('world')\n"
        assert 'world' in abstracted(source, 'low')

    def test_format_on_a_variable_template_marks_nothing(self):
        """Only a literal template is judged; a variable one is unknown."""
        source = "tpl = get_template()\nt = tpl.format('plain-value-here')\n"
        assert 'plain-value-here' in abstracted(source, 'low')

    @pytest.mark.parametrize('level', ALL_LEVELS)
    def test_javascript_template_literal_taint(self, level):
        source = (
            'const p = "hunter2";\n'
            'const c = `postgres://admin:${p}@10.2.3.4:5432/prod_billing`;\n'
        )
        assert 'hunter2' not in abstracted(source, level, language='javascript')

    def test_ordinary_interpolation_is_untouched(self):
        """Taint follows credential templates, not every f-string --
        over-marking would abstract half the file at ``low``."""
        source = "name = 'world'\ngreeting = f'hello {name}'\n"
        out = abstracted(source, 'low')
        assert 'world' in out

    def test_taint_does_not_walk_backwards_through_arbitrary_calls(self):
        """``token = build(user_id)`` must not drag ``user_id`` in --
        the same shallow-marking rule ``_mark_secret`` already documents."""
        source = (
            "user_id = 'public-identifier-42'\n"
            "conn = f'postgres://admin:{build(user_id)}@h/db'\n"
        )
        out = abstracted(source, 'low')
        assert 'public-identifier-42' in out

    def test_bearer_placeholder_is_a_recognised_credential(self):
        """``_handle_template``'s docstring cites ``Bearer ${token}`` as the
        case flattening exists to catch. It did not match: the pattern
        needed 8+ literal characters and the placeholder supplies none."""
        assert is_secret_value('Bearer {}') is True

    def test_prose_about_bearers_is_not_a_credential(self):
        """Widening the pattern must not cost precision on ordinary text."""
        assert is_secret_value('bearer of this note') is False
        assert is_secret_value('the token is missing') is False


# ═══════════════════════════════════════════════════════════
# L6 — endpoint literals were never classified VALUE
# ═══════════════════════════════════════════════════════════

class TestL6EndpointLiterals:
    """
    ``medium`` is documented — in the README's privacy table and in
    ``PRIVACY_LEVELS`` — as abstracting business VALUEs, "rates, fees,
    endpoints".  It abstracted an endpoint only when the *identifier* was
    named like one, and the literal was a separate node judged on its own
    text, so::

        endpoint_url = "https://api.payment.com/v2"

    tokenised the name to ``VAR_0`` and transmitted the URL beside it.
    That is the Phase 0 / D1 split between a binding and the value it
    binds, on the axis D1 did not cover.
    """

    def test_url_literal_is_a_value(self):
        assert is_endpoint_value('https://api.payment.com/v2') is True

    def test_ipv4_literal_is_a_value(self):
        assert is_endpoint_value('10.9.9.9') is True

    def test_a_version_string_is_not_an_endpoint(self):
        """The reason the dotted-quad pattern checks octet ranges."""
        assert is_endpoint_value('1.0') is False
        assert is_endpoint_value('v1.2.3') is False

    def test_an_impossible_address_is_not_an_endpoint(self):
        assert is_endpoint_value('999.1.1.1') is False

    def test_a_relative_path_is_not_an_endpoint(self):
        assert is_endpoint_value('/charge') is False

    def test_a_bare_hostname_is_not_an_endpoint(self):
        """Deliberately excluded: ``a.b.c`` is as likely a module path."""
        assert is_endpoint_value('internal.corp.local') is False

    def test_named_endpoint_no_longer_leaks_its_url(self):
        out = abstracted(
            "endpoint_url = 'https://api.payment.com/v2'\n", 'medium')
        assert 'api.payment.com' not in out

    def test_unnamed_endpoint_is_abstracted_at_medium(self):
        out = abstracted("u = 'https://api.payment.com/v2'\n", 'medium')
        assert 'api.payment.com' not in out

    def test_internal_host_is_abstracted_at_medium(self):
        out = abstracted("connect(host='10.9.9.9')\n", 'medium')
        assert '10.9.9.9' not in out

    def test_endpoints_survive_at_low(self):
        """An endpoint is a business VALUE, not a credential, and ``low``
        is defined as secrets only. Abstracting it there would make the
        level mean something other than what it says."""
        assert '10.9.9.9' in abstracted("h = '10.9.9.9'\n", 'low')

    def test_a_connection_string_is_still_a_secret_not_an_endpoint(self):
        """Credentials are judged first, so an inline password does not get
        downgraded to a mere endpoint."""
        out = abstracted("c = 'postgres://admin:hunter2@h/db'\n", 'low')
        assert 'hunter2' not in out


# ═══════════════════════════════════════════════════════════
# L5 — the CLI printed stored API keys
# ═══════════════════════════════════════════════════════════

class TestL5ConfigExposure:
    """
    ``config show`` rendered every value with ``str(value)``, so a stored
    provider key was printed in full -- and ``config set`` echoed the key
    back into shell history as it saved it.

    That is the one output a user is most likely to share: ``config show``
    is what you run when something is wrong and paste into an issue.
    """

    def test_key_names_are_recognised(self):
        from commands.config_cmd import is_secret_key

        for key in ('gemini_api_key', 'openai_api_key', 'anthropic_api_key'):
            assert is_secret_key(key) is True

    def test_a_provider_added_later_is_covered(self):
        """Substring matching, so a new provider is masked on the day it
        is added rather than the day someone updates a list."""
        from commands.config_cmd import is_secret_key

        assert is_secret_key('mistral_api_key') is True

    def test_preferences_are_not_masked(self):
        from commands.config_cmd import is_secret_key

        for key in ('default_privacy', 'theme', 'db_path', 'audit_log'):
            assert is_secret_key(key) is False

    def test_value_is_masked_by_default(self):
        from commands.config_cmd import display_value

        secret = 'AIzaSyREALKEY1234567890'
        rendered = display_value('gemini_api_key', secret)
        assert secret not in rendered
        assert f'{len(secret)} chars' in rendered

    def test_reveal_prints_in_full(self):
        from commands.config_cmd import display_value

        rendered = display_value(
            'gemini_api_key', 'AIzaSyREALKEY1234567890', reveal=True)
        assert rendered == 'AIzaSyREALKEY1234567890'

    def test_empty_key_is_not_masked_into_noise(self):
        """An unset key should read as unset, not as ``…(0 chars)``."""
        from commands.config_cmd import display_value

        assert display_value('gemini_api_key', '') == ''

    def test_non_secret_value_passes_through(self):
        from commands.config_cmd import display_value

        assert display_value('default_privacy', 'high') == 'high'
