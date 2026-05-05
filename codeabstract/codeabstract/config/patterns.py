"""
Pattern Definitions for CLASSIFY Algorithm

Defines SECRET_PATTERNS and VALUE_PATTERNS used by the
sensitivity classification algorithm (Algorithm 2).
"""

# ═══════════════════════════════════════════════════════════
# SECRET_PATTERNS: Indicators of sensitive credentials/keys
# ═══════════════════════════════════════════════════════════
# Matched against combined name + literal value of AST nodes.
# Case-insensitive matching is applied by the classify module.

SECRET_PATTERNS = [
    r'.*key.*',
    r'.*token.*',
    r'.*secret.*',
    r'.*password.*',
    r'.*credential.*',
    r'.*auth.*',
    r'sk-[a-zA-Z0-9]{32,}',           # Stripe-style API keys
    r'^[A-Za-z0-9+/]{32,}={0,2}$',    # Base64-encoded strings ≥32 chars
    r'.*apikey.*',
    r'.*api_key.*',
    r'.*access_token.*',
    r'.*bearer.*',
    r'.*private.*',
    r'.*passwd.*',
]

# ═══════════════════════════════════════════════════════════
# VALUE_PATTERNS: Business-sensitive values and configuration
# ═══════════════════════════════════════════════════════════
# These identify identifiers/constants that carry business
# logic significance (pricing, endpoints, thresholds, etc.).

VALUE_PATTERNS = [
    r'.*rate.*',
    r'.*price.*',
    r'.*fee.*',
    r'.*commission.*',
    r'.*url.*',
    r'.*endpoint.*',
    r'.*config.*',
    r'.*timeout.*',
    r'.*threshold.*',
    r'.*limit.*',
    r'.*amount.*',
    r'.*total.*',
    r'.*cost.*',
    r'.*margin.*',
    r'.*discount.*',
    r'.*salary.*',
    r'.*revenue.*',
]
