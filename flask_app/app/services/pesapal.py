"""PesaPal v3 API client for credit purchases."""
import os
import time
import requests

LIVE_BASE = "https://pay.pesapal.com/v3/api"
SANDBOX_BASE = "https://cybqa.pesapal.com/pesapalv3/api"


def base_url():
    return SANDBOX_BASE if os.environ.get("PESAPAL_ENV", "sandbox") == "sandbox" else LIVE_BASE


_token_cache = {"token": None, "expires_at": 0}


def _auth_token() -> str:
    if _token_cache["token"] and _token_cache["expires_at"] > time.time() + 30:
        return _token_cache["token"]
    r = requests.post(
        f"{base_url()}/Auth/RequestToken",
        json={
            "consumer_key": os.environ["PESAPAL_CONSUMER_KEY"],
            "consumer_secret": os.environ["PESAPAL_CONSUMER_SECRET"],
        },
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("token")
    if not token:
        raise RuntimeError(f"PesaPal auth failed: {data}")
    _token_cache["token"] = token
    _token_cache["expires_at"] = time.time() + 4 * 60
    return token


def submit_order(merchant_ref: str, amount_usd: float, description: str,
                 callback_url: str, notification_id: str, email: str, name: str):
    token = _auth_token()
    payload = {
        "id": merchant_ref,
        "currency": "USD",
        "amount": float(amount_usd),
        "description": description,
        "callback_url": callback_url,
        "notification_id": notification_id,
        "billing_address": {
            "email_address": email or "student@example.com",
            "first_name": (name or "Student").split(" ")[0],
            "last_name": " ".join((name or "Student").split(" ")[1:]) or "User",
        },
    }
    r = requests.post(
        f"{base_url()}/Transactions/SubmitOrderRequest",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_transaction_status(order_tracking_id: str):
    token = _auth_token()
    r = requests.get(
        f"{base_url()}/Transactions/GetTransactionStatus",
        params={"orderTrackingId": order_tracking_id},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def register_ipn(url: str):
    """Register an IPN URL. Call this once. Returns notification_id."""
    token = _auth_token()
    r = requests.post(
        f"{base_url()}/URLSetup/RegisterIPN",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={"url": url, "ipn_notification_type": "GET"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
