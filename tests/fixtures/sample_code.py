"""Sample Python code for testing CodeAbstract."""

SAMPLE_PAYMENT_CODE = '''
STRIPE_API_KEY = "sk_live_abc123def456ghi789"
PAYPAL_SECRET = "ppsecret_xyzabc123"
commission_rate = 0.029
base_url = "https://api.payment.com/v2"

def calculate_commission(amount):
    """Calculate commission for a transaction."""
    fee = amount * commission_rate
    return round(fee, 2)

def process_payment(user_id, amount, method="stripe"):
    """Process a payment for a user."""
    if method == "stripe":
        endpoint = base_url + "/charge"
        auth_token = STRIPE_API_KEY
    else:
        endpoint = base_url + "/paypal"
        auth_token = PAYPAL_SECRET

    total = amount + calculate_commission(amount)
    return {"endpoint": endpoint, "total": total, "user": user_id}

class PaymentProcessor:
    def __init__(self, api_key):
        self.api_key = api_key
        self.timeout_seconds = 30

    def charge(self, amount, currency="usd"):
        return {
            "amount": amount,
            "currency": currency,
            "key": self.api_key,
        }
'''

SAMPLE_SIMPLE_CODE = '''
def greet(name):
    return f"Hello, {name}!"

def add(a, b):
    return a + b
'''

SAMPLE_SECRET_HEAVY_CODE = '''
API_KEY = "sk-abc123def456"
SECRET_TOKEN = "token_xyz789"
PASSWORD = "supersecret"
access_token = "Bearer eyJhbGciOiJIUzI1NiJ9"
private_key = "-----BEGIN RSA PRIVATE KEY-----"
'''

# ─── Additional fixtures for gap coverage ───────────────────

SAMPLE_FSTRING_CODE = '''
user_name = "Alice"
greeting = f"Hello, {user_name}! Welcome back."
order_id = 12345
message = f"Your order {order_id} has been processed."
'''

SAMPLE_ASYNC_CODE = '''
import asyncio

async def fetch_payment_data(payment_id):
    """Fetch payment details asynchronously."""
    await asyncio.sleep(0.1)
    return {"id": payment_id, "status": "ok"}

async def process_async_payment(user_id, amount):
    data = await fetch_payment_data(user_id)
    return data
'''

SAMPLE_NESTED_CLASS_CODE = '''
class PaymentService:
    """Outer service class."""

    class StripeAdapter:
        """Inner adapter for Stripe."""
        def charge(self, amount):
            return amount * 1.029

    class PaypalAdapter:
        """Inner adapter for PayPal."""
        def charge(self, amount):
            return amount * 1.035

    def get_adapter(self, provider):
        if provider == "stripe":
            return self.StripeAdapter()
        return self.PaypalAdapter()
'''

SAMPLE_NUMERIC_CODE = '''
commission_rate = 0.029
base_fee = 2.50
max_retry_count = 3
timeout_seconds = 30
discount_rate = 0.15
total_amount = 1000
'''

SAMPLE_CRITICAL_PRIVACY_CODE = '''
for i in range(10):
    x = i * 2
    print(x)

def go(n):
    return n + 1
'''

