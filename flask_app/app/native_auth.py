"""Native email/password + Google OAuth authentication for Flask."""
import os
import uuid
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlencode

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, current_app,
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, current_user,
)
from authlib.integrations.flask_client import OAuth
import bcrypt as _bcrypt


class _BcryptCompat:
    @staticmethod
    def hash(password: str) -> str:
        pw = password.encode("utf-8")[:72]
        return _bcrypt.hashpw(pw, _bcrypt.gensalt(rounds=12)).decode("utf-8")

    @staticmethod
    def verify(password: str, hashed: str) -> bool:
        if not hashed:
            return False
        try:
            return _bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
        except Exception:
            return False


bcrypt = _BcryptCompat

import hashlib
from .models import db, User
from .services.email_service import send_welcome_email, send_verification_email, send_password_reset_email


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


def _new_id() -> str:
    return uuid.uuid4().hex


def _new_token() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex


def _new_referral_code() -> str:
    code = uuid.uuid4().hex[:8].upper()
    while User.query.filter_by(referral_code=code).first():
        code = uuid.uuid4().hex[:8].upper()
    return code


def _apply_referral(user_rec: User):
    """If a referral code is in session, credit both referrer and new user."""
    if user_rec.referral_bonus_given:
        return
    referrer_code = session.pop("referral_code", None)
    if not referrer_code:
        return
    referrer = User.query.filter_by(referral_code=referrer_code).first()
    if referrer and referrer.id != user_rec.id:
        referrer.credits = (referrer.credits or 0) + 600
        user_rec.referred_by_id = referrer.id
        user_rec.referral_bonus_given = True


def _hash_id(id_number: str) -> str:
    """One-way hash of a normalised ID/passport number."""
    normalised = id_number.strip().upper().replace(" ", "").replace("-", "").replace(".", "")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _absolute_url(path: str) -> str:
    """Build an absolute URL — APP_DOMAIN overrides REPLIT_DOMAINS."""
    custom = os.environ.get("APP_DOMAIN", "").strip()
    if custom:
        return f"https://{custom}{path}"
    domains = os.environ.get("REPLIT_DOMAINS", "")
    host = domains.split(",")[0].strip() if domains else request.host
    return f"https://{host}{path}"


def google_enabled() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID")) and bool(os.environ.get("GOOGLE_CLIENT_SECRET"))


def init_auth(app):
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = None  # we render our own pages

    oauth.init_app(app)
    if google_enabled():
        oauth.register(
            name="google",
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    bp = Blueprint("auth", __name__)

    # ----------------- helpers -----------------
    def _login(user_rec: User, remember: bool = True):
        session.permanent = True   # honour PERMANENT_SESSION_LIFETIME (6 h)
        login_user(AuthUser(user_rec), remember=remember)

    # ----------------- views -----------------
    def _safe_next(fallback="main.dashboard"):
        """Return a safe redirect URL — only allow relative paths on this host."""
        nxt = request.form.get("next") or request.args.get("next") or ""
        if nxt and nxt.startswith("/") and not nxt.startswith("//"):
            return nxt
        return url_for(fallback)

    @bp.route("/auth/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("main.dashboard"), 303)
        next_url = request.args.get("next", "")
        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            next_url = request.form.get("next", "")
            if not email or not password:
                flash("Enter your email and password.", "error")
                return redirect(url_for("auth.login", next=next_url) if next_url else url_for("auth.login"), 303)
            user_rec = User.query.filter_by(email=email).first()
            if not user_rec or not user_rec.password_hash or not bcrypt.verify(password, user_rec.password_hash):
                flash("Wrong email or password.", "error")
                return redirect(url_for("auth.login", next=next_url) if next_url else url_for("auth.login"), 303)
            # If email not verified, send them to check-email page (don't log in)
            if not user_rec.email_verified:
                # Refresh token so they can resend from that page
                if not user_rec.verification_token:
                    user_rec.verification_token = _new_token()
                    db.session.commit()
                    verify_url = _absolute_url(url_for("auth.verify_email", token=user_rec.verification_token))
                    try:
                        send_verification_email(user_rec.email, user_rec.display_name, verify_url)
                    except Exception:
                        current_app.logger.exception("Failed to send verification email")
                flash("Please verify your email before signing in. Check your inbox.", "error")
                return redirect(url_for("auth.check_email", email=user_rec.email), 303)
            _login(user_rec)
            return redirect(_safe_next(), 303)
        return render_template("login.html", mode="signin", google_enabled=google_enabled(), next_url=next_url)

    @bp.route("/auth/signup", methods=["GET", "POST"])
    def signup():
        if current_user.is_authenticated:
            return redirect(url_for("main.dashboard"), 303)
        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            first_name = (request.form.get("first_name") or "").strip()
            last_name = (request.form.get("last_name") or "").strip()
            if not email or "@" not in email:
                flash("Enter a valid email address.", "error")
                return redirect(url_for("auth.signup"), 303)
            if len(password) < 8:
                flash("Password must be at least 8 characters.", "error")
                return redirect(url_for("auth.signup"), 303)

            existing = User.query.filter_by(email=email).first()
            if existing:
                flash("An account with that email already exists. Please sign in.", "error")
                return redirect(url_for("auth.login"), 303)

            # ID verification happens after email confirmation (same as Google OAuth flow).
            # require_login redirects users with no id_hash to /auth/complete-id automatically.
            token = _new_token()
            user_rec = User(
                id=_new_id(),
                email=email,
                first_name=first_name or None,
                last_name=last_name or None,
                password_hash=bcrypt.hash(password),
                credits=600,  # welcome bonus — unlocked after verification
                referral_code=_new_referral_code(),
                email_verified=False,        # must click link in email
                verification_token=token,
                auth_provider="email",
            )
            db.session.add(user_rec)
            db.session.flush()
            _apply_referral(user_rec)
            db.session.commit()

            verify_url = _absolute_url(url_for("auth.verify_email", token=token))
            try:
                send_verification_email(email, user_rec.display_name, verify_url)
            except Exception:
                current_app.logger.exception("Failed to send verification email")

            return redirect(url_for("auth.check_email", email=email), 303)
        return render_template("login.html", mode="signup", google_enabled=google_enabled())

    @bp.route("/auth/check-email")
    def check_email():
        email = request.args.get("email", "")
        return render_template("check_email.html", email=email)

    @bp.route("/auth/resend-verification", methods=["POST"])
    def resend_verification():
        email = (request.form.get("email") or "").strip().lower()
        user_rec = User.query.filter_by(email=email).first()
        if user_rec and not user_rec.email_verified:
            token = _new_token()
            user_rec.verification_token = token
            db.session.commit()
            verify_url = _absolute_url(url_for("auth.verify_email", token=token))
            try:
                send_verification_email(email, user_rec.display_name, verify_url)
            except Exception:
                current_app.logger.exception("Failed to resend verification email")
        flash("If that account exists, a new verification link has been sent.", "info")
        return redirect(url_for("auth.check_email", email=email))

    @bp.route("/auth/verify/<token>")
    def verify_email(token):
        user_rec = User.query.filter_by(verification_token=token).first()
        if not user_rec:
            flash("This verification link is invalid or already used.", "error")
            return redirect(url_for("auth.login"))
        user_rec.email_verified = True
        user_rec.verification_token = None
        db.session.commit()
        if user_rec.email and not user_rec.welcome_email_sent:
            try:
                send_welcome_email(user_rec.email, user_rec.display_name)
                user_rec.welcome_email_sent = True
                db.session.commit()
            except Exception:
                pass
        _login(user_rec)
        flash("Email verified — welcome!", "info")
        return redirect(url_for("main.dashboard"))

    @bp.route("/auth/forgot", methods=["GET", "POST"])
    def forgot():
        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            user_rec = User.query.filter_by(email=email).first()
            if user_rec and user_rec.password_hash:
                token = _new_token()
                user_rec.password_reset_token = token
                user_rec.password_reset_expires = datetime.utcnow() + timedelta(hours=2)
                db.session.commit()
                reset_url = _absolute_url(url_for("auth.reset_password", token=token))
                try:
                    send_password_reset_email(email, user_rec.display_name, reset_url)
                except Exception:
                    current_app.logger.exception("Failed to send reset email")
            flash("If that account exists, a reset link has been sent to the email.", "info")
            return redirect(url_for("auth.login"))
        return render_template("forgot.html")

    @bp.route("/auth/reset/<token>", methods=["GET", "POST"])
    def reset_password(token):
        user_rec = User.query.filter_by(password_reset_token=token).first()
        if not user_rec or not user_rec.password_reset_expires or user_rec.password_reset_expires < datetime.utcnow():
            flash("This reset link is invalid or expired.", "error")
            return redirect(url_for("auth.forgot"))
        if request.method == "POST":
            password = request.form.get("password") or ""
            if len(password) < 8:
                flash("Password must be at least 8 characters.", "error")
                return redirect(url_for("auth.reset_password", token=token))
            user_rec.password_hash = bcrypt.hash(password)
            user_rec.password_reset_token = None
            user_rec.password_reset_expires = None
            db.session.commit()
            _login(user_rec)
            flash("Password updated.", "info")
            return redirect(url_for("main.dashboard"))
        return render_template("reset.html", token=token)

    # ----------------- Google OAuth -----------------
    @bp.route("/auth/google")
    def google_login():
        if not google_enabled():
            flash("Google sign-in is not configured yet.", "error")
            return redirect(url_for("auth.login"))
        import secrets as _secrets
        from itsdangerous import URLSafeTimedSerializer as _USTS
        state = _secrets.token_urlsafe(32)
        redirect_uri = _absolute_url(url_for("auth.google_callback"))
        # authorize_redirect will store state in Flask session AND we back it
        # up in a separate small cookie so the callback survives if the session
        # cookie drops on the Google redirect round-trip (common on custom domains).
        resp = oauth.google.authorize_redirect(redirect_uri, state=state)
        _s = _USTS(current_app.secret_key)
        resp.set_cookie(
            "_gostate",
            _s.dumps(state),
            secure=True,
            httponly=True,
            samesite="None",
            max_age=600,
        )
        return resp

    @bp.route("/auth/google/callback")
    def google_callback():
        if not google_enabled():
            return redirect(url_for("auth.login"))
        # If the Flask session lost the Authlib state key during the Google
        # redirect, restore it from our backup cookie before Authlib checks it.
        _state_key = "_google_authlib_state_"
        if _state_key not in session:
            from itsdangerous import URLSafeTimedSerializer as _USTS, BadSignature
            _s = _USTS(current_app.secret_key)
            _cookie = request.cookies.get("_gostate", "")
            if _cookie:
                try:
                    _recovered = _s.loads(_cookie, max_age=600)
                    session[_state_key] = _recovered
                except (BadSignature, Exception):
                    pass
        try:
            token = oauth.google.authorize_access_token()
        except Exception as e:
            err = str(e)
            if "mismatching_state" in err or "CSRF" in err:
                flash("Sign-in failed — please try again.", "error")
                return redirect(url_for("auth.login"))
            return f"Authentication error: {e}", 400
        userinfo = token.get("userinfo") or {}
        email = (userinfo.get("email") or "").lower()
        if not email:
            flash("Google account did not return an email.", "error")
            return redirect(url_for("auth.login"))

        user_rec = User.query.filter_by(email=email).first()
        is_new = False
        if not user_rec:
            user_rec = User(
                id=_new_id(),
                email=email,
                first_name=userinfo.get("given_name"),
                last_name=userinfo.get("family_name"),
                profile_image_url=userinfo.get("picture"),
                credits=600,
                referral_code=_new_referral_code(),
                email_verified=True,
                auth_provider="google",
            )
            db.session.add(user_rec)
            db.session.flush()
            _apply_referral(user_rec)
            is_new = True
        else:
            user_rec.email_verified = True
            user_rec.first_name = user_rec.first_name or userinfo.get("given_name")
            user_rec.last_name = user_rec.last_name or userinfo.get("family_name")
            user_rec.profile_image_url = user_rec.profile_image_url or userinfo.get("picture")
        db.session.commit()

        _login(user_rec)

        # New Google users must verify ID before accessing the app
        if not user_rec.id_hash:
            if is_new and not user_rec.welcome_email_sent:
                try:
                    send_welcome_email(email, user_rec.display_name)
                    user_rec.welcome_email_sent = True
                    db.session.commit()
                except Exception:
                    pass
            return redirect(url_for("auth.complete_id"), 303)

        return redirect(url_for("main.dashboard"), 303)

    # ----------------- ID / Passport verification -----------------
    @bp.route("/auth/complete-id", methods=["GET", "POST"])
    def complete_id():
        from flask_login import current_user as cu
        if not cu.is_authenticated:
            return redirect(url_for("auth.login"))
        if getattr(cu, "id_hash", None):
            return redirect(url_for("main.dashboard"), 303)

        if request.method == "POST":
            id_type = (request.form.get("id_type") or "").strip()
            id_number = (request.form.get("id_number") or "").strip()

            if not id_type or not id_number:
                flash("Please select your document type and enter the number.", "error")
                return redirect(url_for("auth.complete_id"))
            if len(id_number) < 5:
                flash("Document number looks too short — please enter your full number.", "error")
                return redirect(url_for("auth.complete_id"))

            id_h = _hash_id(id_number)
            conflict = User.query.filter_by(id_hash=id_h).first()
            if conflict and conflict.id != cu.id:
                flash("An account is already registered with that document number. Each person may only create one account.", "error")
                return redirect(url_for("auth.complete_id"))

            user_rec = User.query.get(cu.id)
            user_rec.id_hash = id_h
            user_rec.id_type = id_type
            db.session.commit()
            flash("Identity verified — welcome!", "success")
            return redirect(url_for("main.dashboard"), 303)

        return render_template("complete_id.html")

    # ----------------- logout -----------------
    @bp.route("/auth/logout", methods=["GET", "POST"])
    def logout():
        logout_user()
        session.clear()
        resp = redirect(url_for("main.index"))
        # Aggressively clear any auth cookies on every known path
        for cookie in ("session", "remember_token"):
            resp.delete_cookie(cookie, path="/")
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
        flash("You've been logged out.", "info")
        return resp

    app.register_blueprint(bp)


def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        is_api = request.path.startswith("/api/")
        if not current_user.is_authenticated:
            if is_api:
                from flask import jsonify
                return jsonify({"error": "Session expired — please refresh the page and log in again."}), 401
            return redirect(url_for("auth.login", next=request.path))
        # Block unverified email/password accounts
        if not getattr(current_user, "email_verified", True):
            if is_api:
                from flask import jsonify
                return jsonify({"error": "Please verify your email before uploading files."}), 403
            return redirect(url_for("auth.check_email", email=getattr(current_user, "email", "")))
        # Block accounts that haven't submitted their ID yet
        if not getattr(current_user, "id_hash", None):
            if is_api:
                from flask import jsonify
                return jsonify({"error": "Please complete your profile setup before uploading files."}), 403
            return redirect(url_for("auth.complete_id"))
        return fn(*args, **kwargs)
    return wrapper
