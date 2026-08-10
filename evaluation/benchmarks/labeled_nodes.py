"""
Labeled Node Dataset for CLASSIFY(E) Evaluation

A hand-curated ground-truth dataset of 150+ AST node samples
with correct sensitivity labels. Used to compute Precision,
Recall, F1, and Confusion Matrix for the classification algorithm.

Each entry is a tuple:
    (node_name, node_type, expected_label, domain, notes)

node_name  — the identifier string (as seen by CLASSIFY)
node_type  — AST node type string (Name, Constant, FunctionDef, etc.)
expected   — ground-truth label: 'SECRET', 'VALUE', or 'IDENTIFIER'
domain     — code domain for stratified analysis
notes      — brief justification
"""

from typing import List, Tuple, NamedTuple


class LabeledNode(NamedTuple):
    node_name: str
    node_type: str
    expected_label: str   # 'SECRET', 'VALUE', 'IDENTIFIER'
    domain: str
    notes: str


# ═══════════════════════════════════════════════════════════════════
# SECRET nodes — credentials, API keys, tokens, passwords (50 nodes)
# ═══════════════════════════════════════════════════════════════════

SECRET_NODES: List[LabeledNode] = [
    # API keys
    LabeledNode("STRIPE_API_KEY", "Name", "SECRET", "api_client", "Contains 'api_key'"),
    LabeledNode("api_key", "Name", "SECRET", "api_client", "Contains 'api_key'"),
    LabeledNode("SENDGRID_API_KEY", "Name", "SECRET", "api_client", "Contains 'api_key'"),
    LabeledNode("OPENAI_API_KEY", "Name", "SECRET", "ml", "Contains 'api_key'"),
    LabeledNode("GOOGLE_API_KEY", "Name", "SECRET", "api_client", "Contains 'api_key'"),
    LabeledNode("INTERNAL_API_KEY", "Name", "SECRET", "microservice", "Contains 'api_key'"),
    LabeledNode("api_key_v2", "Name", "SECRET", "api_client", "Contains 'api_key'"),
    LabeledNode("service_api_key", "Name", "SECRET", "microservice", "Contains 'api_key'"),
    # Tokens
    LabeledNode("TWILIO_AUTH_TOKEN", "Name", "SECRET", "api_client", "Contains 'token'"),
    LabeledNode("SLACK_BOT_TOKEN", "Name", "SECRET", "api_client", "Contains 'token'"),
    LabeledNode("JWT_SECRET_KEY", "Name", "SECRET", "auth", "Contains 'secret' and 'key'"),
    LabeledNode("access_token", "Name", "SECRET", "auth", "Contains 'access_token'"),
    LabeledNode("refresh_token", "Name", "SECRET", "auth", "Contains 'token'"),
    LabeledNode("bearer_token", "Name", "SECRET", "auth", "Contains 'bearer' and 'token'"),
    LabeledNode("auth_token", "Name", "SECRET", "auth", "Contains 'auth' and 'token'"),
    LabeledNode("SERVICE_MESH_TOKEN", "Name", "SECRET", "microservice", "Contains 'token'"),
    LabeledNode("MLFLOW_TOKEN", "Name", "SECRET", "ml", "Contains 'token'"),
    LabeledNode("mesh_token_abc123", "Constant", "SECRET", "microservice", "Token literal value"),
    # Secrets
    LabeledNode("PAYPAL_SECRET", "Name", "SECRET", "ecommerce", "Contains 'secret'"),
    LabeledNode("OAUTH_CLIENT_SECRET", "Name", "SECRET", "auth", "Contains 'secret'"),
    LabeledNode("WEBHOOK_SECRET", "Name", "SECRET", "api_client", "Contains 'secret'"),
    LabeledNode("REFRESH_TOKEN_SECRET", "Name", "SECRET", "auth", "Contains 'secret'"),
    LabeledNode("client_secret", "Name", "SECRET", "auth", "Contains 'secret'"),
    LabeledNode("app_secret", "Name", "SECRET", "web", "Contains 'secret'"),
    LabeledNode("signing_secret", "Name", "SECRET", "api_client", "Contains 'secret'"),
    # Passwords
    LabeledNode("DATABASE_PASSWORD", "Name", "SECRET", "database", "Contains 'password'"),
    LabeledNode("DB_PASSWORD", "Name", "SECRET", "database", "Contains 'password'"),
    LabeledNode("admin_password", "Name", "SECRET", "web", "Contains 'password'"),
    LabeledNode("pg_password_super_secret_xyz789", "Constant", "SECRET", "database", "Password literal"),
    LabeledNode("PASSWORD", "Name", "SECRET", "auth", "Contains 'password'"),
    LabeledNode("passwd", "Name", "SECRET", "web", "Contains 'passwd'"),
    LabeledNode("user_passwd", "Name", "SECRET", "auth", "Contains 'passwd'"),
    # Auth / Private
    LabeledNode("SECRET_KEY", "Name", "SECRET", "web", "Contains 'secret' and 'key'"),
    LabeledNode("private_key", "Name", "SECRET", "crypto", "Contains 'private'"),
    LabeledNode("PRIVATE_RSA_KEY", "Name", "SECRET", "crypto", "Contains 'private'"),
    LabeledNode("auth_header", "Name", "SECRET", "api_client", "Contains 'auth'"),
    LabeledNode("AUTH_SERVICE_URL", "Name", "SECRET", "auth", "Contains 'auth'"),
    LabeledNode("ENCRYPTION_KEY", "Name", "SECRET", "database", "Contains 'key'"),
    LabeledNode("aes256_key_abc123", "Constant", "SECRET", "database", "Encryption key literal"),
    LabeledNode("DB_SSL_CERT_PATH", "Name", "SECRET", "database", "Contains 'key' (cert)"),
    # AWS credentials
    LabeledNode("AWS_ACCESS_KEY", "Name", "SECRET", "ml", "Contains 'key'"),
    LabeledNode("AWS_SECRET_KEY", "Name", "SECRET", "ml", "Contains 'secret' and 'key'"),
    LabeledNode("ANALYTICS_API_KEY", "Name", "SECRET", "analytics", "Contains 'api_key'"),
    LabeledNode("REDIS_AUTH_TOKEN", "Name", "SECRET", "web", "Contains 'auth' and 'token'"),
    LabeledNode("TOKEN_VALIDATION_ENDPOINT", "Name", "SECRET", "auth", "Contains 'token'"),
    LabeledNode("REVOCATION_ENDPOINT", "Name", "SECRET", "auth", "Contains 'auth' endpoint"),
    LabeledNode("MODEL_REGISTRY_TOKEN", "Name", "SECRET", "ml", "Contains 'token'"),
    LabeledNode("PASSWORD_HASH_SALT", "Name", "SECRET", "auth", "Contains 'password'"),
    LabeledNode("credentials", "Name", "SECRET", "api_client", "Contains 'credential'"),
    LabeledNode("bearer_header", "Name", "SECRET", "api_client", "Contains 'bearer'"),
]

# ═══════════════════════════════════════════════════════════════════
# VALUE nodes — business-sensitive rates, prices, endpoints (50 nodes)
# ═══════════════════════════════════════════════════════════════════

VALUE_NODES: List[LabeledNode] = [
    # Rates
    LabeledNode("commission_rate", "Name", "VALUE", "ecommerce", "Contains 'rate'"),
    LabeledNode("PLATFORM_COMMISSION_RATE", "Name", "VALUE", "ecommerce", "Contains 'rate'"),
    LabeledNode("SELLER_FEE_RATE", "Name", "VALUE", "ecommerce", "Contains 'rate'"),
    LabeledNode("VAT_RATE", "Name", "VALUE", "ecommerce", "Contains 'rate'"),
    LabeledNode("LEARNING_RATE", "Name", "VALUE", "ml", "Contains 'rate'"),
    LabeledNode("DROPOUT_RATE", "Name", "VALUE", "ml", "Contains 'rate'"),
    LabeledNode("CORPORATE_TAX_RATE", "Name", "VALUE", "finance", "Contains 'rate'"),
    LabeledNode("CAPITAL_GAINS_RATE", "Name", "VALUE", "finance", "Contains 'rate'"),
    LabeledNode("DIVIDEND_WITHHOLDING_RATE", "Name", "VALUE", "finance", "Contains 'rate'"),
    LabeledNode("ANNUAL_MANAGEMENT_FEE", "Name", "VALUE", "finance", "Contains 'fee'"),
    LabeledNode("PERFORMANCE_FEE_RATE", "Name", "VALUE", "finance", "Contains 'rate'"),
    LabeledNode("CONVERSION_RATE_TARGET", "Name", "VALUE", "analytics", "Contains 'rate'"),
    LabeledNode("CHURN_RATE_LIMIT", "Name", "VALUE", "analytics", "Contains 'rate'"),
    LabeledNode("RISK_FREE_RATE", "Name", "VALUE", "finance", "Contains 'rate'"),
    LabeledNode("LTV_DISCOUNT_RATE", "Name", "VALUE", "analytics", "Contains 'rate'"),
    LabeledNode("MARKET_PREMIUM", "Name", "VALUE", "finance", "Contains 'price' synonym"),
    # Prices and amounts
    LabeledNode("base_price", "Name", "VALUE", "ecommerce", "Contains 'price'"),
    LabeledNode("sale_price", "Name", "VALUE", "ecommerce", "Contains 'price'"),
    LabeledNode("total_amount", "Name", "VALUE", "ecommerce", "Contains 'amount'"),
    LabeledNode("REVENUE_THRESHOLD", "Name", "VALUE", "analytics", "Contains 'revenue'"),
    LabeledNode("BULK_DISCOUNT_THRESHOLD", "Name", "VALUE", "ecommerce", "Contains 'discount'"),
    LabeledNode("FLASH_SALE_DISCOUNT", "Name", "VALUE", "ecommerce", "Contains 'discount'"),
    LabeledNode("MAX_DISCOUNT_RATE", "Name", "VALUE", "ecommerce", "Contains 'discount'"),
    LabeledNode("MINIMUM_MARGIN", "Name", "VALUE", "ecommerce", "Contains 'margin'"),
    LabeledNode("gross_profit", "Name", "VALUE", "finance", "Contains 'cost' synonym"),
    LabeledNode("portfolio_value", "Name", "VALUE", "finance", "Contains 'value'"),
    # Fees
    LabeledNode("transaction_fee", "Name", "VALUE", "ecommerce", "Contains 'fee'"),
    LabeledNode("platform_fee", "Name", "VALUE", "ecommerce", "Contains 'fee'"),
    LabeledNode("service_fee", "Name", "VALUE", "ecommerce", "Contains 'fee'"),
    # URLs and endpoints
    LabeledNode("BASE_URL", "Name", "VALUE", "api_client", "Contains 'url'"),
    LabeledNode("PAYMENT_GATEWAY_URL", "Name", "VALUE", "ecommerce", "Contains 'url'"),
    LabeledNode("FRAUD_CHECK_ENDPOINT", "Name", "VALUE", "ecommerce", "Contains 'endpoint'"),
    LabeledNode("ORDER_SERVICE_URL", "Name", "VALUE", "microservice", "Contains 'url'"),
    LabeledNode("INVENTORY_SERVICE_URL", "Name", "VALUE", "microservice", "Contains 'url'"),
    LabeledNode("DATA_WAREHOUSE_URL", "Name", "VALUE", "analytics", "Contains 'url'"),
    LabeledNode("MLFLOW_TRACKING_URI", "Name", "VALUE", "ml", "Contains 'url' (URI)"),
    LabeledNode("base_endpoint", "Name", "VALUE", "api_client", "Contains 'endpoint'"),
    # Config and thresholds
    LabeledNode("CONNECTION_POOL_SIZE", "Name", "VALUE", "database", "Contains 'limit'"),
    LabeledNode("SESSION_TIMEOUT_SECONDS", "Name", "VALUE", "web", "Contains 'timeout'"),
    LabeledNode("DEFAULT_TIMEOUT_SECONDS", "Name", "VALUE", "microservice", "Contains 'timeout'"),
    LabeledNode("QUERY_TIMEOUT_SECONDS", "Name", "VALUE", "database", "Contains 'timeout'"),
    LabeledNode("RATE_LIMIT_PER_MINUTE", "Name", "VALUE", "web", "Contains 'limit'"),
    LabeledNode("MAX_UPLOAD_SIZE_MB", "Name", "VALUE", "web", "Contains 'limit' synonym"),
    LabeledNode("CHURN_THRESHOLD", "Name", "VALUE", "ml", "Contains 'threshold'"),
    LabeledNode("CIRCUIT_BREAKER_THRESHOLD", "Name", "VALUE", "microservice", "Contains 'threshold'"),
    LabeledNode("SALARY_MULTIPLIER", "Name", "VALUE", "finance", "Contains 'salary'"),
    # Numeric literals classified as VALUE
    LabeledNode("0.029", "Constant", "VALUE", "ecommerce", "Float → numeric constant"),
    LabeledNode("0.025", "Constant", "VALUE", "ecommerce", "Float → numeric constant"),
    LabeledNode("30", "Constant", "VALUE", "web", "Int → numeric constant (timeout)"),
    LabeledNode("0.20", "Constant", "VALUE", "ecommerce", "Float → numeric constant (VAT)"),
]

# ═══════════════════════════════════════════════════════════════════
# IDENTIFIER nodes — non-sensitive identifiers (50 nodes)
# ═══════════════════════════════════════════════════════════════════

IDENTIFIER_NODES: List[LabeledNode] = [
    # Functions
    LabeledNode("calculate_commission", "FunctionDef", "IDENTIFIER", "ecommerce", "Business function name"),
    LabeledNode("process_payment", "FunctionDef", "IDENTIFIER", "ecommerce", "Business function name"),
    LabeledNode("create_charge", "FunctionDef", "IDENTIFIER", "api_client", "Method name"),
    LabeledNode("refund_charge", "FunctionDef", "IDENTIFIER", "api_client", "Method name"),
    LabeledNode("train", "FunctionDef", "IDENTIFIER", "ml", "Method name"),
    LabeledNode("predict_churn_probability", "FunctionDef", "IDENTIFIER", "ml", "Method name"),
    LabeledNode("sharpe_ratio", "FunctionDef", "IDENTIFIER", "finance", "Function name"),
    LabeledNode("compute_ltv", "FunctionDef", "IDENTIFIER", "analytics", "Function name"),
    LabeledNode("fetch_customer", "FunctionDef", "IDENTIFIER", "database", "Method name"),
    LabeledNode("bulk_insert", "FunctionDef", "IDENTIFIER", "database", "Method name"),
    LabeledNode("route_request", "FunctionDef", "IDENTIFIER", "microservice", "Method name"),
    LabeledNode("apply_discount", "FunctionDef", "IDENTIFIER", "ecommerce", "Function name"),
    LabeledNode("format_currency", "FunctionDef", "IDENTIFIER", "utility", "Function name"),
    LabeledNode("chunk_list", "FunctionDef", "IDENTIFIER", "utility", "Function name"),
    LabeledNode("safe_divide", "FunctionDef", "IDENTIFIER", "utility", "Function name"),
    # Classes
    LabeledNode("StripeClient", "ClassDef", "IDENTIFIER", "api_client", "Class name"),
    LabeledNode("ChurnPredictor", "ClassDef", "IDENTIFIER", "ml", "Class name"),
    LabeledNode("AppConfig", "ClassDef", "IDENTIFIER", "web", "Class name"),
    LabeledNode("AuthManager", "ClassDef", "IDENTIFIER", "auth", "Class name"),
    LabeledNode("DatabaseClient", "ClassDef", "IDENTIFIER", "database", "Class name"),
    LabeledNode("ServiceRouter", "ClassDef", "IDENTIFIER", "microservice", "Class name"),
    LabeledNode("AnalyticsEngine", "ClassDef", "IDENTIFIER", "analytics", "Class name"),
    LabeledNode("RollingAverage", "ClassDef", "IDENTIFIER", "utility", "Class name"),
    # Parameters and variables
    LabeledNode("customer_id", "arg", "IDENTIFIER", "ecommerce", "Parameter name"),
    LabeledNode("user_id", "arg", "IDENTIFIER", "ecommerce", "Parameter name"),
    LabeledNode("amount", "arg", "IDENTIFIER", "ecommerce", "Parameter name"),
    LabeledNode("currency", "arg", "IDENTIFIER", "ecommerce", "Parameter name"),
    LabeledNode("features", "arg", "IDENTIFIER", "ml", "Parameter name"),
    LabeledNode("labels", "arg", "IDENTIFIER", "ml", "Parameter name"),
    LabeledNode("query", "arg", "IDENTIFIER", "database", "Parameter name"),
    LabeledNode("service_name", "arg", "IDENTIFIER", "microservice", "Parameter name"),
    LabeledNode("portfolio_return", "arg", "IDENTIFIER", "finance", "Parameter name"),
    LabeledNode("volatility", "arg", "IDENTIFIER", "finance", "Parameter name"),
    LabeledNode("customer_tier", "arg", "IDENTIFIER", "ecommerce", "Parameter name"),
    LabeledNode("cart_total", "arg", "IDENTIFIER", "ecommerce", "Parameter name"),
    # Local variables
    LabeledNode("discounted", "Name", "IDENTIFIER", "ecommerce", "Local variable"),
    LabeledNode("subtotal", "Name", "IDENTIFIER", "ecommerce", "Local variable"),
    LabeledNode("n_samples", "Name", "IDENTIFIER", "ml", "Local variable"),
    LabeledNode("split_idx", "Name", "IDENTIFIER", "ml", "Local variable"),
    LabeledNode("best_val_loss", "Name", "IDENTIFIER", "ml", "Local variable"),
    LabeledNode("patience_counter", "Name", "IDENTIFIER", "ml", "Local variable"),
    LabeledNode("excess_return", "Name", "IDENTIFIER", "finance", "Local variable"),
    LabeledNode("expected", "Name", "IDENTIFIER", "auth", "Local variable"),
    LabeledNode("parts", "Name", "IDENTIFIER", "auth", "Local variable"),
    LabeledNode("failure_counts", "Name", "IDENTIFIER", "microservice", "Local variable"),
    # String literals (non-sensitive)
    LabeledNode("stripe", "Constant", "IDENTIFIER", "ecommerce", "String literal (method name)"),
    LabeledNode("usd", "Constant", "IDENTIFIER", "ecommerce", "Currency code literal"),
    LabeledNode("standard", "Constant", "IDENTIFIER", "ecommerce", "Tier name literal"),
    LabeledNode("premium", "Constant", "IDENTIFIER", "ecommerce", "Tier name literal"),
    LabeledNode("order", "Constant", "IDENTIFIER", "microservice", "Service name literal"),
]

# ═══════════════════════════════════════════════════════════════════
# Combined dataset
# ═══════════════════════════════════════════════════════════════════

ALL_LABELED_NODES: List[LabeledNode] = SECRET_NODES + VALUE_NODES + IDENTIFIER_NODES

DATASET_SUMMARY = {
    "total": len(ALL_LABELED_NODES),
    "secret_count": len(SECRET_NODES),
    "value_count": len(VALUE_NODES),
    "identifier_count": len(IDENTIFIER_NODES),
    "domains": list({n.domain for n in ALL_LABELED_NODES}),
}
