"""Expected outputs and constants for test assertions."""

# Tokens that should appear when abstracting SAMPLE_PAYMENT_CODE
EXPECTED_SECRET_TOKENS = ['SECRET_']
EXPECTED_FUNC_TOKENS = ['FUNC_']
EXPECTED_VAR_TOKENS = ['VAR_']

# Identifiers that must NOT appear in abstract output
MUST_BE_ABSTRACTED = [
    'STRIPE_API_KEY',
    'PAYPAL_SECRET',
    'commission_rate',
    'base_url',
    'calculate_commission',
    'process_payment',
]

# Identifiers that SHOULD remain (builtins, single-char, dunder)
MUST_REMAIN = [
    'round',
    'self',
]
