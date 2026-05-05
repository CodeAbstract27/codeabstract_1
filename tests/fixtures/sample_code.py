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
