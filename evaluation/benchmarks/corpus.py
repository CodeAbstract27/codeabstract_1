"""
Benchmark Corpus for CodeAbstract Evaluation

10 synthetic Python code files of varying complexity, domain,
and sensitivity level. Used consistently across all metric pillars.

Each entry is a dict:
    name        — short label used in reports
    domain      — code domain (api_client, ecommerce, ml, etc.)
    sensitivity — expected dominant classification (low/medium/high)
    loc         — approximate lines of code
    code        — the Python source string
"""

# ═══════════════════════════════════════════════════════════════════
# File 1: API Client — HIGH sensitivity (many secrets)
# ═══════════════════════════════════════════════════════════════════

FILE_API_CLIENT = {
    "name": "api_client",
    "domain": "api_client",
    "sensitivity": "high",
    "loc": 55,
    "code": '''
import requests

STRIPE_API_KEY = "sk_live_abc123def456ghi789jkl012mno345pqr"
SENDGRID_API_KEY = "SG.abc123def456ghi789jkl012mno345"
TWILIO_AUTH_TOKEN = "auth_token_xyz789abc123def456"
SLACK_BOT_TOKEN = "xoxb-111111-222222-abc123def456"
BASE_URL = "https://api.stripe.com/v1"
WEBHOOK_SECRET = "whsec_abc123def456ghi789"

class StripeClient:
    def __init__(self, api_key, timeout_seconds=30):
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.base_endpoint = BASE_URL

    def create_charge(self, amount, currency, customer_id):
        """Create a charge via the Stripe API."""
        endpoint = self.base_endpoint + "/charges"
        payload = {
            "amount": amount,
            "currency": currency,
            "customer": customer_id,
        }
        response = requests.post(
            endpoint,
            data=payload,
            auth=(self.api_key, ""),
            timeout=self.timeout_seconds,
        )
        return response.json()

    def refund_charge(self, charge_id, refund_amount=None):
        """Refund a previous charge."""
        endpoint = self.base_endpoint + "/refunds"
        payload = {"charge": charge_id}
        if refund_amount:
            payload["amount"] = refund_amount
        response = requests.post(endpoint, data=payload, auth=(self.api_key, ""))
        return response.json()

    def verify_webhook(self, payload, sig_header):
        """Verify incoming webhook authenticity."""
        import hmac, hashlib
        expected = hmac.new(
            WEBHOOK_SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig_header)
''',
}

# ═══════════════════════════════════════════════════════════════════
# File 2: E-Commerce Pricing — HIGH sensitivity (business values)
# ═══════════════════════════════════════════════════════════════════

FILE_ECOMMERCE = {
    "name": "ecommerce_pricing",
    "domain": "ecommerce",
    "sensitivity": "high",
    "loc": 60,
    "code": '''
"""E-commerce pricing engine with commission and discount logic."""

PLATFORM_COMMISSION_RATE = 0.025
SELLER_FEE_RATE = 0.015
VAT_RATE = 0.20
PREMIUM_DISCOUNT_RATE = 0.10
BULK_DISCOUNT_THRESHOLD = 1000.00
FLASH_SALE_DISCOUNT = 0.30
MINIMUM_MARGIN = 0.05
MAX_DISCOUNT_RATE = 0.50

PAYMENT_GATEWAY_URL = "https://payments.internal.example.com/v3"
FRAUD_CHECK_ENDPOINT = "https://risk.internal.example.com/score"

def calculate_commission(sale_price, seller_tier="standard"):
    """Calculate platform commission for a sale."""
    if seller_tier == "premium":
        rate = PLATFORM_COMMISSION_RATE - 0.005
    else:
        rate = PLATFORM_COMMISSION_RATE
    return round(sale_price * rate, 2)

def apply_discount(price, customer_tier, cart_total):
    """Apply tiered discounts to a cart item."""
    discount = 0.0
    if customer_tier == "premium":
        discount += PREMIUM_DISCOUNT_RATE
    if cart_total >= BULK_DISCOUNT_THRESHOLD:
        discount += 0.05
    discount = min(discount, MAX_DISCOUNT_RATE)
    return round(price * (1 - discount), 2)

def compute_final_price(base_price, customer_tier, cart_total, include_vat=True):
    """Compute final price after all fees, discounts, and taxes."""
    discounted = apply_discount(base_price, customer_tier, cart_total)
    commission = calculate_commission(discounted)
    fee = discounted * SELLER_FEE_RATE
    subtotal = discounted + commission + fee
    if include_vat:
        subtotal = subtotal * (1 + VAT_RATE)
    margin = (subtotal - base_price) / subtotal
    if margin < MINIMUM_MARGIN:
        raise ValueError(f"Margin {margin:.1%} below minimum {MINIMUM_MARGIN:.1%}")
    return round(subtotal, 2)
''',
}

# ═══════════════════════════════════════════════════════════════════
# File 3: ML Pipeline — MEDIUM sensitivity (mixed)
# ═══════════════════════════════════════════════════════════════════

FILE_ML_PIPELINE = {
    "name": "ml_pipeline",
    "domain": "machine_learning",
    "sensitivity": "medium",
    "loc": 65,
    "code": '''
"""Proprietary ML training pipeline for churn prediction."""

import random

MLFLOW_TRACKING_URI = "https://mlflow.internal.company.com"
MLFLOW_EXPERIMENT_NAME = "churn_prediction_v3"
MODEL_REGISTRY_TOKEN = "mlflow_token_abc123def456"
S3_BUCKET_NAME = "company-ml-models-prod"
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

LEARNING_RATE = 0.001
BATCH_SIZE = 256
NUM_EPOCHS = 100
DROPOUT_RATE = 0.3
L2_REGULARIZATION = 0.0001
VALIDATION_SPLIT = 0.2
EARLY_STOPPING_PATIENCE = 10
CHURN_THRESHOLD = 0.65

class ChurnPredictor:
    def __init__(self, model_path, tracking_uri=MLFLOW_TRACKING_URI):
        self.model_path = model_path
        self.tracking_uri = tracking_uri
        self.churn_threshold = CHURN_THRESHOLD
        self.is_trained = False

    def train(self, features, labels):
        """Train the churn prediction model."""
        n_samples = len(features)
        split_idx = int(n_samples * (1 - VALIDATION_SPLIT))
        train_features = features[:split_idx]
        val_features = features[split_idx:]
        best_val_loss = float("inf")
        patience_counter = 0
        for epoch in range(NUM_EPOCHS):
            loss = self._compute_loss(train_features)
            val_loss = self._compute_loss(val_features)
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
            else:
                patience_counter += 1
            if patience_counter >= EARLY_STOPPING_PATIENCE:
                break
        self.is_trained = True
        return {"best_val_loss": best_val_loss, "epochs_trained": epoch + 1}

    def _compute_loss(self, features):
        return random.uniform(0.1, 0.9)

    def predict_churn_probability(self, customer_features):
        """Return churn probability for a customer."""
        score = random.uniform(0.0, 1.0)
        return {"churn_probability": score, "will_churn": score > self.churn_threshold}
''',
}

# ═══════════════════════════════════════════════════════════════════
# File 4: Web Server Config — HIGH sensitivity (secrets + endpoints)
# ═══════════════════════════════════════════════════════════════════

FILE_WEB_CONFIG = {
    "name": "web_server_config",
    "domain": "web_server",
    "sensitivity": "high",
    "loc": 50,
    "code": '''
"""Web server configuration and middleware."""

import os

SECRET_KEY = "django-insecure-abc123def456ghi789jkl012mno345pqr678stu901"
DATABASE_PASSWORD = "pg_password_super_secret_xyz789"
REDIS_AUTH_TOKEN = "redis_auth_abc123"
JWT_SECRET = "jwt_secret_key_very_long_and_random_abc123def456"

DB_HOST = "postgres.internal.company.com"
DB_PORT = 5432
DB_NAME = "production_db"
REDIS_URL = "redis://redis.internal.company.com:6379/0"
ALLOWED_HOSTS = ["api.company.com", "www.company.com"]

SESSION_TIMEOUT_SECONDS = 3600
MAX_UPLOAD_SIZE_MB = 10
RATE_LIMIT_PER_MINUTE = 100
CORS_MAX_AGE = 86400

class AppConfig:
    def __init__(self):
        self.secret_key = SECRET_KEY
        self.db_password = DATABASE_PASSWORD
        self.redis_token = REDIS_AUTH_TOKEN
        self.jwt_secret = JWT_SECRET
        self.session_timeout = SESSION_TIMEOUT_SECONDS
        self.rate_limit = RATE_LIMIT_PER_MINUTE

    def get_db_url(self):
        return f"postgresql://admin:{self.db_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    def get_redis_url(self):
        return REDIS_URL

    def is_rate_limited(self, request_count):
        return request_count > self.rate_limit

    def validate_upload(self, file_size_mb):
        return file_size_mb <= MAX_UPLOAD_SIZE_MB
''',
}

# ═══════════════════════════════════════════════════════════════════
# File 5: Simple Utility — LOW sensitivity (no secrets)
# ═══════════════════════════════════════════════════════════════════

FILE_SIMPLE_UTIL = {
    "name": "simple_utility",
    "domain": "utility",
    "sensitivity": "low",
    "loc": 40,
    "code": '''
"""General-purpose utility functions."""

def format_currency(amount, symbol="$", decimals=2):
    """Format a number as a currency string."""
    return f"{symbol}{amount:.{decimals}f}"

def clamp(value, minimum, maximum):
    """Clamp a value between minimum and maximum."""
    return max(minimum, min(value, maximum))

def chunk_list(items, chunk_size):
    """Split a list into chunks of a given size."""
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

def flatten(nested):
    """Flatten a nested list one level deep."""
    result = []
    for item in nested:
        if isinstance(item, list):
            result.extend(item)
        else:
            result.append(item)
    return result

def safe_divide(numerator, denominator, default=0.0):
    """Divide safely, returning default on division by zero."""
    if denominator == 0:
        return default
    return numerator / denominator

def truncate_string(text, max_length, suffix="..."):
    """Truncate a string to max_length with a suffix."""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix

class RollingAverage:
    def __init__(self, window_size=10):
        self.window_size = window_size
        self.values = []

    def add(self, value):
        self.values.append(value)
        if len(self.values) > self.window_size:
            self.values.pop(0)

    def average(self):
        if not self.values:
            return 0.0
        return sum(self.values) / len(self.values)
''',
}

# ═══════════════════════════════════════════════════════════════════
# File 6: Auth Service — HIGH sensitivity (tokens + auth)
# ═══════════════════════════════════════════════════════════════════

FILE_AUTH_SERVICE = {
    "name": "auth_service",
    "domain": "authentication",
    "sensitivity": "high",
    "loc": 55,
    "code": '''
"""Authentication and token management service."""

import hashlib
import hmac

JWT_SECRET_KEY = "jwt_super_secret_abc123def456ghi789jkl012"
OAUTH_CLIENT_SECRET = "oauth_client_secret_xyz789"
REFRESH_TOKEN_SECRET = "refresh_secret_mno345pqr678"
PASSWORD_HASH_SALT = "bcrypt_salt_rounds_12_static"

TOKEN_EXPIRY_SECONDS = 3600
REFRESH_TOKEN_EXPIRY_SECONDS = 604800
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 900

AUTH_SERVICE_URL = "https://auth.internal.company.com/v2"
TOKEN_VALIDATION_ENDPOINT = AUTH_SERVICE_URL + "/validate"
REVOCATION_ENDPOINT = AUTH_SERVICE_URL + "/revoke"

class AuthManager:
    def __init__(self):
        self.jwt_secret = JWT_SECRET_KEY
        self.oauth_secret = OAUTH_CLIENT_SECRET
        self.refresh_secret = REFRESH_TOKEN_SECRET
        self.failed_attempts = {}

    def generate_token(self, user_id, roles):
        """Generate a signed JWT-style access token."""
        payload = f"{user_id}:{','.join(roles)}"
        signature = hmac.new(
            self.jwt_secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return f"{payload}.{signature}"

    def validate_token(self, token):
        """Validate token signature and expiry."""
        parts = token.rsplit(".", 1)
        if len(parts) != 2:
            return False
        payload, sig = parts
        expected = hmac.new(
            self.jwt_secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig)

    def record_failed_attempt(self, user_id):
        """Track failed login attempts for lockout."""
        count = self.failed_attempts.get(user_id, 0) + 1
        self.failed_attempts[user_id] = count
        return count >= MAX_LOGIN_ATTEMPTS
''',
}

# ═══════════════════════════════════════════════════════════════════
# File 7: Financial Calculator — MEDIUM sensitivity (business values)
# ═══════════════════════════════════════════════════════════════════

FILE_FINANCE = {
    "name": "financial_calculator",
    "domain": "finance",
    "sensitivity": "medium",
    "loc": 50,
    "code": '''
"""Proprietary financial calculation engine."""

CORPORATE_TAX_RATE = 0.21
CAPITAL_GAINS_RATE = 0.15
DIVIDEND_WITHHOLDING_RATE = 0.10
ANNUAL_MANAGEMENT_FEE = 0.02
PERFORMANCE_FEE_RATE = 0.20
HIGH_WATER_MARK_RESET_YEARS = 3

RISK_FREE_RATE = 0.045
MARKET_PREMIUM = 0.065
INFLATION_TARGET = 0.02

def calculate_after_tax_return(gross_return, is_capital_gain=False):
    """Calculate after-tax return on investment."""
    rate = CAPITAL_GAINS_RATE if is_capital_gain else CORPORATE_TAX_RATE
    return gross_return * (1 - rate)

def compute_management_fees(portfolio_value, years):
    """Compute total management fees over a period."""
    total_fees = 0.0
    remaining_value = portfolio_value
    for year in range(years):
        fee = remaining_value * ANNUAL_MANAGEMENT_FEE
        total_fees += fee
        remaining_value -= fee
    return round(total_fees, 2)

def sharpe_ratio(portfolio_return, volatility):
    """Compute the Sharpe ratio for a portfolio."""
    excess_return = portfolio_return - RISK_FREE_RATE
    if volatility == 0:
        return 0.0
    return round(excess_return / volatility, 4)

def performance_fee(gross_profit, high_water_mark):
    """Calculate performance fee above high water mark."""
    excess = max(0, gross_profit - high_water_mark)
    return round(excess * PERFORMANCE_FEE_RATE, 2)
''',
}

# ═══════════════════════════════════════════════════════════════════
# File 8: Database Layer — HIGH sensitivity (credentials + queries)
# ═══════════════════════════════════════════════════════════════════

FILE_DATABASE = {
    "name": "database_layer",
    "domain": "database",
    "sensitivity": "high",
    "loc": 55,
    "code": '''
"""Proprietary database access layer."""

DB_HOST = "db-prod-001.internal.company.com"
DB_PORT = 5432
DB_NAME = "customer_data"
DB_USER = "app_service_user"
DB_PASSWORD = "pg_secret_password_abc123def456"
DB_SSL_CERT_PATH = "/etc/ssl/certs/db-client.crt"

CONNECTION_POOL_SIZE = 20
CONNECTION_TIMEOUT_SECONDS = 10
QUERY_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3

ENCRYPTION_KEY = "aes256_key_abc123def456ghi789jkl012mno345"

class DatabaseClient:
    def __init__(self):
        self.host = DB_HOST
        self.port = DB_PORT
        self.database = DB_NAME
        self.user = DB_USER
        self.password = DB_PASSWORD
        self.pool_size = CONNECTION_POOL_SIZE
        self.query_timeout = QUERY_TIMEOUT_SECONDS
        self.encryption_key = ENCRYPTION_KEY

    def get_connection_string(self):
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )

    def execute_query(self, query, params=None):
        """Execute a parameterized query."""
        conn_str = self.get_connection_string()
        return {"conn": conn_str, "query": query, "params": params}

    def fetch_customer(self, customer_id):
        """Fetch a customer record by ID."""
        query = "SELECT * FROM customers WHERE id = %s AND deleted_at IS NULL"
        return self.execute_query(query, (customer_id,))

    def bulk_insert(self, table, records):
        """Bulk insert records into a table."""
        if not records:
            return 0
        query = f"INSERT INTO {table} VALUES %s"
        return self.execute_query(query, records)
''',
}

# ═══════════════════════════════════════════════════════════════════
# File 9: Microservice Router — MEDIUM sensitivity
# ═══════════════════════════════════════════════════════════════════

FILE_MICROSERVICE = {
    "name": "microservice_router",
    "domain": "microservice",
    "sensitivity": "medium",
    "loc": 50,
    "code": '''
"""Internal microservice routing layer."""

SERVICE_REGISTRY_URL = "https://registry.internal.company.com"
LOAD_BALANCER_URL = "https://lb.internal.company.com"
SERVICE_MESH_TOKEN = "mesh_token_abc123def456"

ORDER_SERVICE_URL = "http://order-svc:8080"
INVENTORY_SERVICE_URL = "http://inventory-svc:8081"
NOTIFICATION_SERVICE_URL = "http://notification-svc:8082"
PAYMENT_SERVICE_URL = "http://payment-svc:8083"

DEFAULT_TIMEOUT_SECONDS = 5
RETRY_BACKOFF_FACTOR = 1.5
MAX_RETRY_ATTEMPTS = 3
CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_BREAKER_TIMEOUT_SECONDS = 60

class ServiceRouter:
    def __init__(self):
        self.registry_url = SERVICE_REGISTRY_URL
        self.mesh_token = SERVICE_MESH_TOKEN
        self.timeout = DEFAULT_TIMEOUT_SECONDS
        self.retry_attempts = MAX_RETRY_ATTEMPTS
        self.failure_counts = {}

    def route_request(self, service_name, path, payload):
        """Route a request to the appropriate microservice."""
        service_urls = {
            "order": ORDER_SERVICE_URL,
            "inventory": INVENTORY_SERVICE_URL,
            "notification": NOTIFICATION_SERVICE_URL,
            "payment": PAYMENT_SERVICE_URL,
        }
        base_url = service_urls.get(service_name)
        if not base_url:
            raise ValueError(f"Unknown service: {service_name}")
        return {"url": base_url + path, "payload": payload}

    def is_circuit_open(self, service_name):
        """Check if circuit breaker is tripped for a service."""
        failures = self.failure_counts.get(service_name, 0)
        return failures >= CIRCUIT_BREAKER_THRESHOLD
''',
}

# ═══════════════════════════════════════════════════════════════════
# File 10: Analytics Engine — MEDIUM sensitivity
# ═══════════════════════════════════════════════════════════════════

FILE_ANALYTICS = {
    "name": "analytics_engine",
    "domain": "analytics",
    "sensitivity": "medium",
    "loc": 50,
    "code": '''
"""Proprietary analytics and reporting engine."""

ANALYTICS_API_KEY = "analytics_key_abc123def456"
BIGQUERY_PROJECT_ID = "company-analytics-prod"
BIGQUERY_DATASET = "user_events"
DATA_WAREHOUSE_URL = "https://dw.internal.company.com/query"

REVENUE_THRESHOLD = 10000.0
CONVERSION_RATE_TARGET = 0.035
CHURN_RATE_LIMIT = 0.05
RETENTION_TARGET = 0.85
LTV_DISCOUNT_RATE = 0.12

class AnalyticsEngine:
    def __init__(self, api_key=ANALYTICS_API_KEY):
        self.api_key = api_key
        self.project_id = BIGQUERY_PROJECT_ID
        self.revenue_threshold = REVENUE_THRESHOLD
        self.conversion_target = CONVERSION_RATE_TARGET

    def compute_ltv(self, avg_order_value, purchase_frequency, customer_lifespan):
        """Compute Customer Lifetime Value."""
        annual_value = avg_order_value * purchase_frequency
        ltv = annual_value * customer_lifespan / (1 + LTV_DISCOUNT_RATE)
        return round(ltv, 2)

    def compute_conversion_rate(self, visitors, conversions):
        """Compute conversion rate and compare to target."""
        if visitors == 0:
            return 0.0
        rate = conversions / visitors
        gap = rate - self.conversion_target
        return {"rate": round(rate, 4), "gap_vs_target": round(gap, 4)}

    def is_revenue_milestone(self, period_revenue):
        """Check if revenue exceeds the milestone threshold."""
        return period_revenue >= self.revenue_threshold

    def compute_retention(self, cohort_start, cohort_end):
        """Compute retention rate between two cohort sizes."""
        if cohort_start == 0:
            return 0.0
        rate = cohort_end / cohort_start
        return {"retention_rate": round(rate, 4), "meets_target": rate >= RETENTION_TARGET}
''',
}

# ═══════════════════════════════════════════════════════════════════
# Corpus registry
# ═══════════════════════════════════════════════════════════════════

ALL_FILES = [
    FILE_API_CLIENT,
    FILE_ECOMMERCE,
    FILE_ML_PIPELINE,
    FILE_WEB_CONFIG,
    FILE_SIMPLE_UTIL,
    FILE_AUTH_SERVICE,
    FILE_FINANCE,
    FILE_DATABASE,
    FILE_MICROSERVICE,
    FILE_ANALYTICS,
]

CORPUS_SUMMARY = {
    "total_files": len(ALL_FILES),
    "total_loc": sum(f["loc"] for f in ALL_FILES),
    "domains": [f["domain"] for f in ALL_FILES],
    "sensitivity_distribution": {
        "high": sum(1 for f in ALL_FILES if f["sensitivity"] == "high"),
        "medium": sum(1 for f in ALL_FILES if f["sensitivity"] == "medium"),
        "low": sum(1 for f in ALL_FILES if f["sensitivity"] == "low"),
    },
}
