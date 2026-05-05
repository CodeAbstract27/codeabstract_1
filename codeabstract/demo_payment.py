api_key = "user_secret_ABC123"
login_url = "https://auth.example.com/login"

def authenticate_user(username, password):
    token = api_key + username
    return {"url": login_url, "token": token}