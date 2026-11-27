"""Past questions: questions that were covered before. Admins upload them; everyone can search and view them.

Files (screenshots, PDFs, Word documents, screen recordings) go from the admin's browser straight to Cloudflare R2
with a presigned URL, because a Vercel function cannot receive a request body bigger than ~4.5 MB.
"""
import json
import re
import uuid

from flask import Blueprint, abort, current_app, jsonify, make_response, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_

from .models import db, PastQuestion

questions_bp = Blueprint("questions", __name__)

PAGE = 24
MAX_FILES = 20
# content type -> (file extension, kind, size cap in MB)
TYPES = {
    "image/jpeg": ("jpg", "image", 25), "image/png": ("png", "image", 25), "image/webp": ("webp", "image", 25),
    "application/pdf": ("pdf", "pdf", 50),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ("docx", "doc", 50),
    "video/mp4": ("mp4", "video", 200), "video/quicktime": ("mp4", "video", 200), "video/webm": ("webm", "video", 200),
}
_KEY = r"questions/[a-f0-9]{32}\.(jpg|png|webp|pdf|docx|mp4|webm)"
_CAP = {"jpg": 25, "png": 25, "webp": 25, "pdf": 50, "docx": 50, "mp4": 200, "webm": 200}


def _is_admin():
    return current_user.is_authenticated and bool(getattr(current_user, "is_staff", False))

def _err(msg, code=400):
    return jsonify({"error": msg}), code

def _admin_api():
    """Admins only, and only from our own pages (other sites cannot send this header)."""
    if not _is_admin():
        abort(make_response(jsonify({"error": "Admins only."}), 403))
    if request.headers.get("X-Requested-With") != "ssg-q":
        abort(make_response(jsonify({"error": "Bad request."}), 403))
    if request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
        abort(make_response(jsonify({"error": "Bad request."}), 403))

def _sniff(head, ext):
    """True when the first bytes of the stored file really are what the extension says."""
    if ext in ("jpg", "png", "webp"):
        from .feed import _sniff as feed_sniff
        return feed_sniff(head) == "image"
    if ext == "pdf":
        return head[:4] == b"%PDF"
    if ext == "docx":
        return head[:4] == b"PK\x03\x04"
    if ext == "mp4":
        return head[4:8] == b"ftyp"
    if ext == "webm":
        return head[:4] == b"\x1a\x45\xdf\xa3"
    return False

def _clean_name(name):
    name = re.sub(r"[\x00-\x1f\x7f/\\]", "", (name or "").strip())
    return name[:120] or "file"

def _item(q):
    files = json.loads(q.files or "[]")
    return {"id": q.id, "title": q.title, "subject": q.subject, "body": q.body, "files": files,
            "published": q.is_published, "created": q.created_at,
            "thumb": next((f["url"] for f in files if f["type"] == "image"), None)}


# ── pages ─────────────────────────────────────────────────────────────────────
@questions_bp.route("/questions")
def list_page():
    admin = _is_admin()
    q = (request.args.get("q") or "").strip()[:80]
    subject = (request.args.get("subject") or "").strip()[:80]
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    base = PastQuestion.query
    if not admin:
        base = base.filter(PastQuestion.is_published.is_(True))
    subjects = [(s, n) for s, n in db.session.query(PastQuestion.subject, db.func.count(PastQuestion.id))
                .filter(PastQuestion.subject != "", *( [] if admin else [PastQuestion.is_published.is_(True)] ))
                .group_by(PastQuestion.subject).order_by(db.func.count(PastQuestion.id).desc()).limit(24)]
    if subject:
        base = base.filter(PastQuestion.subject == subject)
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        base = base.filter(or_(PastQuestion.title.ilike(like, escape="\\"), PastQuestion.subject.ilike(like, escape="\\"),
                               PastQuestion.body.ilike(like, escape="\\")))
    total = base.count()
    rows = base.order_by(PastQuestion.created_at.desc()).offset((page - 1) * PAGE).limit(PAGE).all()
    return render_template("questions.html", items=[_item(r) for r in rows], q=q, subject=subject, subjects=subjects,
                           page=page, pages=max((total + PAGE - 1) // PAGE, 1), total=total, is_admin=admin)

@questions_bp.route("/questions/<int:qid>")
def detail(qid):
    row = db.session.get(PastQuestion, qid)
    if not row or (not row.is_published and not _is_admin()):
        abort(404)
    return render_template("question_detail.html", item=_item(row), is_admin=_is_admin())


# ── admin API ─────────────────────────────────────────────────────────────────
@questions_bp.route("/api/questions/upload-url", methods=["POST"])
def api_upload_url():
    """Hand the browser a short-lived link so one file goes straight to storage."""
    _admin_api()
    from .services import supabase_storage as st
    if not st.configured():
        return _err("Uploads aren't set up: these settings are missing on the server: " + ", ".join(st.missing_settings()) + ".", 503)
    data = request.get_json(silent=True) or {}
    info = TYPES.get((data.get("type") or "").lower())
    try:
        size = int(data.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if not info:
        return _err("Only photos (JPG, PNG, WebP), PDF, Word (.docx) and videos (MP4, MOV, WebM) can be uploaded.")
    ext, kind, cap = info
    if size <= 0 or size > cap * 1024 * 1024:
        return _err(f"That file is too large. The limit for this type is {cap} MB.")
    ctype = {"mp4": "video/mp4", "webm": "video/webm"}.get(ext) or (data.get("type") or "").lower()
    key = f"questions/{uuid.uuid4().hex}.{ext}"
    try:
        url = st.presign_put(key, ctype, size)
    except Exception:
        current_app.logger.exception("Could not create an upload link")
        return _err("Uploads aren't available right now.", 503)
    return jsonify(upload_url=url, key=key, content_type=ctype)

@questions_bp.route("/api/questions", methods=["POST"])
def api_create():
    _admin_api()
    from .services import supabase_storage as st
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()[:200]
    subject = re.sub(r"\s+", " ", (data.get("subject") or "").strip())[:80]
    body = (data.get("body") or "").strip()[:5000]
    items = data.get("files") or []
    if not title:
        return _err("Add a title.")
    if not isinstance(items, list) or not items and not body:
        return _err("Add at least one file or some notes.")
    if len(items) > MAX_FILES:
        return _err(f"Up to {MAX_FILES} files per question.")
    files, seen = [], set()
    for it in items:
        key = it.get("key") if isinstance(it, dict) else None
        if not isinstance(key, str) or not re.fullmatch(_KEY, key) or key in seen:
            return _err("One of the uploads isn't valid. Please try again.")
        seen.add(key)
        if PastQuestion.query.filter(PastQuestion.files.like(f"%{key}%")).first():
            return _err("One of those files was already used.")
        ext = key.rsplit(".", 1)[1]
        try:
            size = int(st.head(key).get("ContentLength", 0))
            head = st.read_range(key, 16) if 0 < size <= _CAP[ext] * 1024 * 1024 else b""
        except Exception:
            return _err("We couldn't find an uploaded file. Please try again.")
        if size <= 0 or size > _CAP[ext] * 1024 * 1024 or not _sniff(head, ext):
            try:
                st.delete(key)
            except Exception:
                pass
            return _err("One of those files isn't a supported file, or it is too large.")
        kind = {"jpg": "image", "png": "image", "webp": "image", "pdf": "pdf", "docx": "doc", "mp4": "video", "webm": "video"}[ext]
        files.append({"url": st.public_url(key), "key": key, "type": kind, "name": _clean_name(it.get("name")), "size": size})
    row = PastQuestion(title=title, subject=subject, body=body, files=json.dumps(files, separators=(",", ":")),
                       is_published=bool(data.get("published", True)), created_by=current_user.id)
    db.session.add(row)
    db.session.commit()
    return jsonify(id=row.id, url=url_for("questions.detail", qid=row.id)), 201

@questions_bp.route("/api/questions/<int:qid>/publish", methods=["POST"])
def api_publish(qid):
    _admin_api()
    row = db.session.get(PastQuestion, qid) or abort(404)
    row.is_published = not row.is_published
    db.session.commit()
    return jsonify(published=row.is_published)

@questions_bp.route("/api/questions/<int:qid>/delete", methods=["POST"])
def api_delete(qid):
    _admin_api()
    row = db.session.get(PastQuestion, qid) or abort(404)
    from .services import supabase_storage as st
    for f in json.loads(row.files or "[]"):
        try:
            st.delete(f["key"])
        except Exception:
            pass
    db.session.delete(row)
    db.session.commit()
    return jsonify(ok=True)
