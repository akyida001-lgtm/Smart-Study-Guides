import os
import random
from twilio.rest import Client


def _client():
    return Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])


def send_otp(to: str, code: str) -> tuple[bool, str]:
    """Send a 6-digit OTP to the given E.164 phone number.
    Returns (True, '') on success or (False, reason) on failure."""
    try:
        _client().messages.create(
            body=f"Your Smart Study Guides verification code is: {code}. Valid for 10 minutes.",
            from_=os.environ["TWILIO_PHONE_NUMBER"],
            to=to,
        )
        return True, ""
    except Exception as e:
        code_num = getattr(e, "code", None)
        if code_num == 21608:
            reason = "trial_unverified"
        elif code_num == 21211:
            reason = "invalid_number"
        elif code_num == 21408:
            reason = "region_not_enabled"
        else:
            reason = "unknown"
        print(f"[SMS] Failed to send OTP to {to}: code={code_num} reason={reason} detail={e}")
        return False, reason


def generate_otp() -> str:
    return str(random.randint(100000, 999999))


def send_admin_notification_sms(to: str, body: str) -> bool:
    """Send an admin-composed message to a user via SMS.
    `to` must be in E.164 format (e.g. +254712345678)."""
    if not to:
        return False
    # Ensure E.164 format — add + if missing
    phone = to.strip()
    if not phone.startswith("+"):
        phone = "+" + phone
    try:
        # Truncate to 160 chars for a single SMS segment
        snippet = body[:157] + "…" if len(body) > 160 else body
        _client().messages.create(
            body=f"[Smart Study Guides] {snippet}",
            from_=os.environ["TWILIO_PHONE_NUMBER"],
            to=phone,
        )
        return True
    except Exception as e:
        print(f"[SMS] Admin notification failed to {phone}: {e}")
        return False
