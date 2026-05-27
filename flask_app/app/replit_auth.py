"""Replit OIDC integration for Flask using Authlib + Flask-Login."""
import os
import uuid
from functools import wraps
from urllib.parse import urlencode

from flask import g, redirect, request, session, url_for, abort
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user
from authlib.integrations.flask_client import OAuth
from authlib.oidc.core import UserInfo

from .models import db, User
from .services.email_service import send_welcome_email

login_manager = LoginManager()
oauth = OAuth()


class AuthUser(UserMixin):
    def __init__(self, user_record: User):
        self._user = user_record
        self.id = user_record.id

    def __getattr__(self, name):
        return getattr(self._user, name)


@login_manager.user_loader
def load_user(user_id):
    rec = User.query.get(user_id)
    if not rec:
        return None
    return AuthUser(rec)


def init_auth(app):
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    issuer = os.environ.get("ISSUER_URL", "https://replit.com/oidc")
    client_id = os.environ["REPL_ID"]

    oauth.init_app(app)
    oauth.register(
        name="replit",
        client_id=client_id,
        server_metadata_url=f"{issuer}/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid profile email offline_access",
            "code_challenge_method": "S256",
        },
    )

    from flask import Blueprint

    bp = Blueprint("auth", __name__)

    def _redirect_uri():
        # Always match the host the user actually arrived on so it works
        # on both the workspace dev domain and the deployed .replit.app
        host = request.host
        return f"https://{host}/auth/callback"

    @bp.route("/auth/login")
    def login():
        # Force fresh login
        nonce = uuid.uuid4().hex
        session["oidc_nonce"] = nonce
        return oauth.replit.authorize_redirect(
            redirect_uri=_redirect_uri(),
            nonce=nonce,
            prompt="login consent",
        )

    @bp.route("/auth/callback")
    def callback():
        try:
            token = oauth.replit.authorize_access_token()
        except Exception as e:
            return f"Authentication error: {e}", 400

        nonce = session.pop("oidc_nonce", None)
        try:
            userinfo = oauth.replit.parse_id_token(token, nonce=nonce)
        except Exception:
            userinfo = token.get("userinfo") or {}

        sub = userinfo.get("sub")
        if not sub:
            return "Invalid auth response", 400

        is_new = False
        user_rec = User.query.get(sub)
        if not user_rec:
            # Generate a unique short referral code
            ref_code = uuid.uuid4().hex[:8].upper()
            while User.query.filter_by(referral_code=ref_code).first():
                ref_code = uuid.uuid4().hex[:8].upper()
            user_rec = User(
                id=sub,
                email=userinfo.get("email"),
                first_name=userinfo.get("first_name") or userinfo.get("given_name"),
                last_name=userinfo.get("last_name") or userinfo.get("family_name"),
                profile_image_url=userinfo.get("profile_image_url") or userinfo.get("picture"),
                credits=600,  # welcome bonus
                referral_code=ref_code,
            )
            db.session.add(user_rec)
            db.session.flush()

            # Apply referral bonus if this signup came via a referral link
            referrer_code = session.pop("referral_code", None)
            if referrer_code:
                referrer = User.query.filter_by(referral_code=referrer_code).first()
                if referrer and referrer.id != user_rec.id:
                    referrer.credits = (referrer.credits or 0) + 600
                    user_rec.referred_by_id = referrer.id
                    user_rec.referral_bonus_given = True
            is_new = True
        else:
            user_rec.email = userinfo.get("email") or user_rec.email
            user_rec.first_name = userinfo.get("first_name") or userinfo.get("given_name") or user_rec.first_name
            user_rec.last_name = userinfo.get("last_name") or userinfo.get("family_name") or user_rec.last_name
            user_rec.profile_image_url = (
                userinfo.get("profile_image_url") or userinfo.get("picture") or user_rec.profile_image_url
            )
        # Auto-grant staff to all owner accounts on every login
        _owner_emails = {"aservices767@gmail.com", "simonedwardj@yahoo.com"}
        if user_rec.email and user_rec.email.lower() in _owner_emails:
            if not user_rec.is_staff:
                user_rec.is_staff = True
        db.session.commit()

        if is_new and user_rec.email and not user_rec.welcome_email_sent:
            try:
                send_welcome_email(user_rec.email, user_rec.display_name)
                user_rec.welcome_email_sent = True
                db.session.commit()
            except Exception:
                pass

        login_user(AuthUser(user_rec), remember=True)
        return redirect(url_for("main.dashboard"))

    @bp.route("/auth/logout")
    def logout():
        logout_user()
        session.clear()
        issuer_url = os.environ.get("ISSUER_URL", "https://replit.com/oidc")
        domains = os.environ.get("REPLIT_DOMAINS", "")
        host = domains.split(",")[0].strip() if domains else request.host
        return_to = f"https://{host}/"
        params = urlencode({
            "client_id": os.environ["REPL_ID"],
            "post_logout_redirect_uri": return_to,
        })
        return redirect(f"{issuer_url}/session/end?{params}")

    app.register_blueprint(bp)


def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        return fn(*args, **kwargs)
    return wrapper
