import os
import logging
from flask import Flask
from .models import db
from .native_auth import init_auth
from .routes import register_routes


def create_app():
    app = Flask(__name__, static_folder="../static", template_folder="../templates")

    from datetime import timedelta
    app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DATABASE_URL"]
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
    # Auto-logout after 6 hours of inactivity
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=6)
    app.config["REMEMBER_COOKIE_DURATION"]   = timedelta(hours=6)
    app.config["SESSION_PERMANENT"]          = True
    # Allow the session cookie to be sent on cross-site redirects (e.g. OAuth
    # callback from Google). Without SameSite=None the browser strips the cookie
    # on the return trip, causing the "mismatching_state" CSRF error.
    app.config["SESSION_COOKIE_SAMESITE"]    = "None"
    app.config["SESSION_COOKIE_SECURE"]      = True
    app.config["SESSION_COOKIE_HTTPONLY"]    = True

    logging.basicConfig(level=logging.INFO)

    db.init_app(app)
    with app.app_context():
        # Import all models so SQLAlchemy metadata is complete before create_all
        from .models import (User, Assignment, Source, Transaction,
                             PipelineLog, UserNotification,
                             ChatSession, ChatMessage,
                             HumanOrder, HumanOrderMessage, HumanOrderFile,
                             JobDocument, OAuth,
                             Subscription, DailyUsage,
                             Post, PostMedia)
        db.create_all()
        # Add identity columns if upgrading from an older schema
        from sqlalchemy import inspect as sa_inspect, text
        inspector = sa_inspect(db.engine)
        existing = [c["name"] for c in inspector.get_columns("users")]
        with db.engine.connect() as conn:
            if "id_hash" not in existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN id_hash VARCHAR(64) UNIQUE"))
                conn.commit()
            if "id_type" not in existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN id_type VARCHAR(20)"))
                conn.commit()
            if "id_scan_url" not in existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN id_scan_url VARCHAR(1000)"))
                conn.commit()
        # Assignment paper/rubric columns
        existing_a2 = [c["name"] for c in inspector.get_columns("assignments")]
        with db.engine.connect() as conn:
            for col, defn in [
                ("paper_text",     "TEXT"),
                ("rubric_url",     "VARCHAR(1000)"),
                ("marking_result", "TEXT"),
            ]:
                if col not in existing_a2:
                    conn.execute(text(f"ALTER TABLE assignments ADD COLUMN {col} {defn}"))
                    conn.commit()
        # Source metadata columns
        existing_s = [c["name"] for c in inspector.get_columns("sources")]
        with db.engine.connect() as conn:
            for col, defn in [
                ("authors",       "VARCHAR(500)"),
                ("year",          "INTEGER"),
                ("apa_intext",    "TEXT"),
                ("apa_reference", "TEXT"),
                ("annotation",    "TEXT"),
            ]:
                if col not in existing_s:
                    conn.execute(text(f"ALTER TABLE sources ADD COLUMN {col} {defn}"))
                    conn.commit()
        # Assignment title-page columns
        existing_a = [c["name"] for c in inspector.get_columns("assignments")]
        with db.engine.connect() as conn:
            for col, defn in [
                ("course_name",     "VARCHAR(255)"),
                ("student_name",    "VARCHAR(255)"),
                ("instructor_name", "VARCHAR(255)"),
                ("school_name",     "VARCHAR(255)"),
                ("due_date",        "VARCHAR(50)"),
            ]:
                if col not in existing_a:
                    conn.execute(text(f"ALTER TABLE assignments ADD COLUMN {col} {defn}"))
                    conn.commit()

        # is_staff column on users
        existing_u2 = [c["name"] for c in inspector.get_columns("users")]
        with db.engine.connect() as conn:
            if "is_staff" not in existing_u2:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_staff BOOLEAN DEFAULT FALSE NOT NULL"))
                conn.commit()

        # Job documents — docx/pdf export columns
        existing_jd = [c["name"] for c in inspector.get_columns("job_documents")]
        with db.engine.connect() as conn:
            for col, defn in [
                ("docx_url",      "VARCHAR(1000)"),
                ("docx_filename", "VARCHAR(255)"),
                ("pdf_url",       "VARCHAR(1000)"),
                ("pdf_filename",  "VARCHAR(255)"),
            ]:
                if col not in existing_jd:
                    conn.execute(text(f"ALTER TABLE job_documents ADD COLUMN {col} {defn}"))
                    conn.commit()

        # User account moderation + phone columns
        existing_u3 = [c["name"] for c in inspector.get_columns("users")]
        # user_notifications table
        if not inspector.has_table("user_notifications"):
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE user_notifications (
                        id SERIAL PRIMARY KEY,
                        user_id VARCHAR NOT NULL REFERENCES users(id),
                        type VARCHAR(30) NOT NULL,
                        title VARCHAR(120) NOT NULL,
                        body TEXT NOT NULL,
                        is_read BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                conn.execute(text("CREATE INDEX ix_user_notifications_user_id ON user_notifications(user_id)"))
                conn.commit()

        # read_by_user column on chat_messages
        existing_cm = [c["name"] for c in inspector.get_columns("chat_messages")]
        with db.engine.connect() as conn:
            if "read_by_user" not in existing_cm:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN read_by_user BOOLEAN NOT NULL DEFAULT FALSE"))
                conn.commit()
            # One-time backfill: mark all messages older than 1 day as read
            # (they existed before this feature was added and were already seen)
            conn.execute(text(
                "UPDATE chat_messages SET read_by_user = TRUE "
                "WHERE read_by_user = FALSE "
                "AND created_at < NOW() - INTERVAL '1 day'"
            ))
            conn.commit()

        with db.engine.connect() as conn:
            if "phone" not in existing_u3:
                conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(30)"))
                conn.commit()
            if "account_status" not in existing_u3:
                conn.execute(text("ALTER TABLE users ADD COLUMN account_status VARCHAR(20) DEFAULT 'active' NOT NULL"))
                conn.commit()
            if "flag_reason" not in existing_u3:
                conn.execute(text("ALTER TABLE users ADD COLUMN flag_reason TEXT"))
                conn.commit()
            if "is_writer" not in existing_u3:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_writer BOOLEAN DEFAULT FALSE NOT NULL"))
                conn.commit()
            if "free_trial_count" not in existing_u3:
                conn.execute(text("ALTER TABLE users ADD COLUMN free_trial_count INTEGER DEFAULT 0 NOT NULL"))
                conn.commit()
            if "review_prompted" not in existing_u3:
                conn.execute(text("ALTER TABLE users ADD COLUMN review_prompted BOOLEAN DEFAULT FALSE NOT NULL"))
                conn.commit()

        # Assignments table migrations
        with db.engine.connect() as conn:
            existing_a = {row[0] for row in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name='assignments'")
            )}
            if "humanize_style" not in existing_a:
                conn.execute(text("ALTER TABLE assignments ADD COLUMN humanize_style VARCHAR(30) DEFAULT 'academic' NOT NULL"))
                conn.commit()
            if "humanize_model" not in existing_a:
                conn.execute(text("ALTER TABLE assignments ADD COLUMN humanize_model VARCHAR(20) DEFAULT 'advanced' NOT NULL"))
                conn.commit()
            if "assignment_type" not in existing_a:
                conn.execute(text("ALTER TABLE assignments ADD COLUMN assignment_type VARCHAR(20) DEFAULT 'standard' NOT NULL"))
                conn.commit()
            if "instruction_image_url" not in existing_a:
                conn.execute(text("ALTER TABLE assignments ADD COLUMN instruction_image_url VARCHAR(1000)"))
                conn.commit()

        # Auto-grant staff access to all owner accounts
        try:
            db.session.execute(
                text(
                    "UPDATE users SET is_staff = TRUE "
                    "WHERE email IN ('aservices767@gmail.com', 'simonedwardj@yahoo.com')"
                )
            )
            db.session.commit()
        except Exception:
            pass

        # Chat tables — created automatically by db.create_all() above,
        # but guard any future column additions here.

    # ── Context processor: pending AI-removal count for admin badge ─────────────
    @app.context_processor
    def _inject_pending_ai_removal_count():
        from flask_login import current_user as cu
        try:
            if cu.is_authenticated and getattr(cu, "is_staff", False):
                from .models import AIRemovalJob
                count = AIRemovalJob.query.filter(
                    AIRemovalJob.status.in_(["pending", "assigned"])
                ).count()
                return {"pending_ai_removal_count": count}
        except Exception:
            pass
        return {"pending_ai_removal_count": 0}

    # ── Context processor: inject active_plan into every template ──────────────
    @app.context_processor
    def _inject_active_plan():
        from flask_login import current_user as cu
        try:
            if cu.is_authenticated and not cu.is_writer:
                email = (getattr(cu, "email", "") or "").lower().strip()
                _owner_emails = {"aservices767@gmail.com", "simonedwardj@yahoo.com"}
                if getattr(cu, "is_staff", False) or email in _owner_emails:
                    return {"active_plan": "admin"}
                from .models import Subscription
                from datetime import datetime as _dt
                sub = (
                    Subscription.query
                    .filter_by(user_id=cu.id, status="active")
                    .filter(Subscription.end_date > _dt.utcnow())
                    .order_by(Subscription.end_date.desc())
                    .first()
                )
                return {"active_plan": sub.plan if sub else None}
        except Exception:
            pass
        return {"active_plan": None}

    init_auth(app)
    register_routes(app)

    @app.after_request
    def _set_response_headers(response):
        from flask_login import current_user
        from flask import request as _req
        try:
            is_auth = current_user.is_authenticated
            is_redirect = response.status_code in (301, 302, 303, 307, 308)
            is_api = _req.path.startswith("/api/")

            # Cache-control: prevent caching of authenticated / redirect responses
            if is_auth or is_redirect:
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"

            # X-Robots-Tag: tell crawlers to index public pages, skip private ones
            if not is_api and not is_redirect:
                if is_auth:
                    # Authenticated pages are private — no need to index
                    response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
                else:
                    # Public pages — explicitly allow indexing (overrides platform defaults)
                    response.headers["X-Robots-Tag"] = "index, follow"
        except Exception:
            pass
        return response

    return app
