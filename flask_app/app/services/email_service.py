import os
import logging
import requests

log = logging.getLogger(__name__)
RESEND_API = "https://api.resend.com/emails"
BRAND_NAME = "Smart Study Guides"
SITE_URL   = "https://smart-study-guides.com"


def _from_addr():
    """Return a display-name formatted sender, e.g. 'Smart Study Guides <pro@…>'."""
    sender = os.environ.get("RESEND_FROM_EMAIL", "")
    if sender:
        return f"{BRAND_NAME} <{sender}>"
    return sender


def _send(to: str, subject: str, html: str):
    api_key = os.environ.get("RESEND_API_KEY")
    sender  = _from_addr()
    if not api_key:
        log.error("EMAIL_SEND_FAILED: RESEND_API_KEY is not set")
        return False
    if not sender:
        log.error("EMAIL_SEND_FAILED: RESEND_FROM_EMAIL is not set")
        return False
    if not to:
        log.error("EMAIL_SEND_FAILED: recipient address is empty")
        return False
    try:
        r = requests.post(
            RESEND_API,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": sender, "to": [to], "subject": subject, "html": html},
            timeout=30,
        )
        if not r.ok:
            log.error("EMAIL_SEND_FAILED to=%s subject=%r status=%s body=%s",
                      to, subject, r.status_code, r.text[:500])
        else:
            log.info("EMAIL_SENT to=%s subject=%r", to, subject)
        return r.ok
    except Exception:
        log.exception("EMAIL_SEND_EXCEPTION to=%s subject=%r", to, subject)
        return False


def _footer():
    return f"""
      <hr style="border:none;border-top:1px solid #1e3a5f;margin:28px 0 20px;">
      <p style="color:#64748b;font-size:12px;margin:0;line-height:1.6;">
        {BRAND_NAME} · <a href="{SITE_URL}" style="color:#64748b;">{SITE_URL}</a><br>
        Questions? Reply to this email or visit our <a href="{SITE_URL}/help" style="color:#64748b;">Help Centre</a>.
      </p>
    """


def send_welcome_email(email: str, name: str):
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;padding:32px;background:#0b1733;color:#ffffff;border-radius:12px;">
      <p style="color:#94a3b8;font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.5px;">{BRAND_NAME}</p>
      <h1 style="color:#ffffff;margin:0 0 16px;">Welcome, {name}.</h1>
      <p style="color:#cbd5e1;line-height:1.6;margin:0 0 16px;">
        Your account is ready. Subscribe to a plan to start generating polished, properly-cited academic assignments in minutes — delivered as a Word document.
      </p>
      <p style="color:#cbd5e1;line-height:1.6;margin:0 0 24px;">
        Plans start at <strong style="color:#ffffff;">$27.99/month</strong> and include unlimited humanization, AI detection, and plagiarism checking.
      </p>
      <p style="margin:0 0 24px;">
        <a href="{SITE_URL}/pricing" style="display:inline-block;background:#00bcd4;color:#0b1733;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:700;">View Plans &amp; Pricing →</a>
      </p>
      {_footer()}
    </div>
    """
    return _send(email, f"Welcome to {BRAND_NAME}", html)


def send_verification_email(email: str, name: str, verify_url: str):
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;padding:32px;background:#0b1733;color:#ffffff;border-radius:12px;">
      <p style="color:#94a3b8;font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.5px;">{BRAND_NAME}</p>
      <h1 style="color:#ffffff;margin:0 0 16px;">Confirm your email</h1>
      <p style="color:#cbd5e1;line-height:1.6;margin:0 0 24px;">
        Hi {name}, click the button below to verify your email address and activate your account.
      </p>
      <p style="margin:0 0 24px;">
        <a href="{verify_url}" style="display:inline-block;background:#00bcd4;color:#0b1733;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:700;">Verify my email →</a>
      </p>
      <p style="color:#94a3b8;font-size:12px;line-height:1.6;margin:0 0 0;">
        Button not working? Copy and paste this link into your browser:<br/>
        <span style="color:#64748b;word-break:break-all;">{verify_url}</span>
      </p>
      {_footer()}
    </div>
    """
    return _send(email, f"Confirm your email — {BRAND_NAME}", html)


def send_password_reset_email(email: str, name: str, reset_url: str):
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;padding:32px;background:#0b1733;color:#ffffff;border-radius:12px;">
      <p style="color:#94a3b8;font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.5px;">{BRAND_NAME}</p>
      <h1 style="color:#ffffff;margin:0 0 16px;">Reset your password</h1>
      <p style="color:#cbd5e1;line-height:1.6;margin:0 0 24px;">
        Hi {name}, click the button below to set a new password. This link expires in <strong style="color:#ffffff;">2 hours</strong>.
      </p>
      <p style="margin:0 0 24px;">
        <a href="{reset_url}" style="display:inline-block;background:#00bcd4;color:#0b1733;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:700;">Set new password →</a>
      </p>
      <p style="color:#94a3b8;font-size:12px;line-height:1.6;margin:0;">
        Didn't request a password reset? You can safely ignore this email — your password won't change.
      </p>
      {_footer()}
    </div>
    """
    return _send(email, f"Reset your {BRAND_NAME} password", html)


def send_admin_notification_email(email: str, name: str, subject: str, body: str):
    """Send an admin-composed message to a user via email."""
    html_body = body.replace("\n", "<br>")
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;padding:32px;background:#0b1733;color:#ffffff;border-radius:12px;">
      <p style="color:#94a3b8;font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.5px;">{BRAND_NAME} — Official Notice</p>
      <h2 style="color:#ffffff;margin:0 0 20px;">{subject}</h2>
      <div style="color:#cbd5e1;line-height:1.8;font-size:15px;">{html_body}</div>
      {_footer()}
    </div>
    """
    return _send(email, subject, html)


def send_ai_removal_admin_alert(admin_email: str, student_name: str, topic: str,
                                ai_score: float, deadline_str: str, job_url: str):
    """Alert admins that a student has submitted a job for AI removal."""
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:580px;margin:0 auto;padding:32px;background:#0b1733;color:#ffffff;border-radius:12px;">
      <p style="color:#94a3b8;font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.5px;">{BRAND_NAME} — AI Removal Request</p>
      <h2 style="color:#ff6b6b;margin:0 0 20px;">⚠️ New AI Removal Job</h2>
      <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
        <tr><td style="color:#94a3b8;padding:6px 0;font-size:13px;width:90px;">Student</td><td style="color:#ffffff;font-size:13px;">{student_name}</td></tr>
        <tr><td style="color:#94a3b8;padding:6px 0;font-size:13px;">Topic</td><td style="color:#ffffff;font-size:13px;">{topic}</td></tr>
        <tr><td style="color:#94a3b8;padding:6px 0;font-size:13px;">AI Score</td><td style="color:#ff6b6b;font-size:13px;font-weight:700;">{ai_score}% AI detected</td></tr>
        <tr><td style="color:#94a3b8;padding:6px 0;font-size:13px;">Deadline</td><td style="color:#ffd166;font-size:13px;font-weight:700;">{deadline_str}</td></tr>
      </table>
      <p style="margin:0 0 24px;">
        <a href="{job_url}" style="display:inline-block;background:#ff6b6b;color:#ffffff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:700;">View &amp; Assign Job →</a>
      </p>
      {_footer()}
    </div>
    """
    return _send(admin_email, f"[Action Required] AI Removal Job — {topic[:50]}", html)


def send_ai_removal_completed_student(email: str, name: str, topic: str,
                                      final_ai_score: float, status_url: str):
    """Notify student that their AI removal job is complete and ready to download."""
    score_color = "#5ad48a" if final_ai_score <= 5 else "#ffd166"
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:580px;margin:0 auto;padding:32px;background:#0b1733;color:#ffffff;border-radius:12px;">
      <p style="color:#94a3b8;font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.5px;">{BRAND_NAME}</p>
      <h2 style="color:#5ad48a;margin:0 0 16px;">✅ Your Paper is Ready</h2>
      <p style="color:#cbd5e1;line-height:1.6;margin:0 0 16px;">
        Hi {name}, your paper on <strong>"{topic}"</strong> has been rewritten and is ready to download.
      </p>
      <div style="background:#1e3a5f;border-radius:10px;padding:16px 20px;margin:0 0 24px;display:inline-block;">
        <span style="color:#94a3b8;font-size:13px;">Final AI Detection Score</span><br>
        <span style="color:{score_color};font-size:32px;font-weight:800;line-height:1.2;">{final_ai_score}% AI</span>
        <span style="color:#94a3b8;font-size:13px;margin-left:8px;">/ {round(100 - final_ai_score, 1)}% Human</span>
      </div>
      <p style="margin:0 0 24px;">
        <a href="{status_url}" style="display:inline-block;background:#5ad48a;color:#0b1733;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:700;">Download Your Paper →</a>
      </p>
      {_footer()}
    </div>
    """
    return _send(email, f"Your AI-removed paper is ready — {topic[:50]}", html)


def send_assignment_ready_email(email: str, name: str, topic: str, download_url: str):
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;padding:32px;background:#0b1733;color:#ffffff;border-radius:12px;">
      <p style="color:#94a3b8;font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.5px;">{BRAND_NAME}</p>
      <h1 style="color:#ffffff;margin:0 0 16px;">Your assignment is ready.</h1>
      <p style="color:#cbd5e1;line-height:1.6;margin:0 0 24px;">
        Hi {name}, your paper on <strong>"{topic}"</strong> has finished generating and passed all humanization checks.
      </p>
      <p style="margin:0 0 24px;">
        <a href="{download_url}" style="display:inline-block;background:#00bcd4;color:#0b1733;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:700;">Download .docx →</a>
      </p>
      {_footer()}
    </div>
    """
    return _send(email, f"Your assignment is ready — {BRAND_NAME}", html)


def send_admin_activity_email(admin_email: str, event_title: str, details: dict):
    """Generic admin activity alert — used for signups, payments, assignments, chats, logins."""
    rows = "".join(
        f'<tr><td style="color:#94a3b8;padding:6px 12px 6px 0;font-size:13px;white-space:nowrap;">{k}</td>'
        f'<td style="color:#ffffff;font-size:13px;">{v}</td></tr>'
        for k, v in details.items()
    )
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;padding:32px;background:#0b1733;color:#ffffff;border-radius:12px;">
      <p style="color:#94a3b8;font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.5px;">{BRAND_NAME} — Activity Alert</p>
      <h2 style="color:#00bcd4;margin:0 0 20px;">{event_title}</h2>
      <table style="width:100%;border-collapse:collapse;margin-bottom:10px;">{rows}</table>
      {_footer()}
    </div>
    """
    return _send(admin_email, f"[{BRAND_NAME}] {event_title}", html)
