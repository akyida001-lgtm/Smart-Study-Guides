"""Past questions: questions that were covered before. Admins upload them; everyone can search and view them.

Files (screenshots, PDFs, Word documents, screen recordings) go from the admin's browser straight to Cloudflare R2
with a presigned URL, because a Vercel function cannot receive a request body bigger than ~4.5 MB.
"""
import base64
import io
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, abort, current_app, jsonify, make_response, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_

from .models import db, PastQuestion

questions_bp = Blueprint("questions", __name__)

PAGE = 24
MAX_FILES = 20
MAX_TEXT = 20000          # longest typed text kept per file
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

_VISION_PROMPT = ("Transcribe all the text in this image exactly as written, in reading order. Keep numbering, bullet points, "
                  "line breaks, equations and symbols. Do not describe the picture, add commentary, or correct mistakes. "
                  "If there is no readable text, reply with exactly NO_TEXT.")

def _clean_text(t):
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(t or "")).replace("\r\n", "\n").strip()
    return t[:MAX_TEXT]

def _vision(jpeg):
    """One picture (or one slice of a tall picture) -> its text, using the same OpenAI key as the rest of the site."""
    from .services import openai_service as oai
    b64 = base64.b64encode(jpeg).decode()
    msg = [{"role": "user", "content": [{"type": "text", "text": _VISION_PROMPT},
                                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}}]}]
    try:
        r = oai.client().chat.completions.create(model="gpt-4o", messages=msg, max_tokens=2500, temperature=0, timeout=45)
    except Exception as e:
        proxy = oai.proxy_client() if "quota" in str(e).lower() else None
        if not proxy:
            raise
        r = proxy.chat.completions.create(model="gpt-4o", messages=msg, max_tokens=2500, temperature=0, timeout=45)
    out = (r.choices[0].message.content or "").strip()
    return "" if out.upper().startswith("NO_TEXT") else out

def _join_slices(parts):
    """Glue the text of overlapping slices together, dropping the lines that were read twice at each seam."""
    out = []
    for part in parts:
        lines = [l for l in part.split("\n")]
        if out:
            for k in range(min(6, len(out), len(lines)), 0, -1):
                if [x.strip() for x in out[-k:]] == [x.strip() for x in lines[:k]]:
                    lines = lines[k:]
                    break
        out.extend(lines)
    return "\n".join(out).strip()

def _transcribe_image(data):
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    w, h = img.size
    if w > 1600:                                    # big enough to read, small enough to be quick
        img = img.resize((1600, round(h * 1600 / w)), Image.LANCZOS)
        w, h = img.size
    pieces = []
    if h > 1.7 * w:                                 # a long chat screenshot: read it in overlapping slices
        seg, step = int(w * 1.5), int(w * 1.5) - int(w * 0.06)
        top = 0
        while top < h and len(pieces) < 8:
            end = min(top + seg, h)
            if h - end < seg * 0.3:                 # don't leave a tiny last slice: stretch this one to the end
                end = h
            pieces.append(img.crop((0, top, w, end)))
            if end >= h:
                break
            top += step
        else:
            if top < h and len(pieces) >= 8:
                raise ValueError("That picture is too long to read in one go. Please split it.")
    else:
        pieces = [img]
    def jpg(im):
        b = io.BytesIO(); im.save(b, "JPEG", quality=88); return b.getvalue()
    with ThreadPoolExecutor(max_workers=4) as ex:
        texts = list(ex.map(lambda im: _vision(jpg(im)), pieces))
    return _join_slices(texts)

def _read_pdf(data):
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(data))
    parts = [(pg.extract_text() or "").strip() for pg in reader.pages[:40]]
    return "\n\n".join(p for p in parts if p)

def _read_docx(data):
    import docx
    d = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in d.paragraphs if p.text.strip())

def _item(q):
    files = json.loads(q.files or "[]")
    first_text = next((f.get("text") for f in files if f.get("text")), "")
    return {"id": q.id, "title": q.title, "subject": q.subject, "body": q.body, "files": files, "snippet": (q.body or first_text or "")[:110],
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
        conds = [PastQuestion.title.ilike(like, escape="\\"), PastQuestion.subject.ilike(like, escape="\\"),
                 PastQuestion.body.ilike(like, escape="\\")]
        if len(q) >= 3:                      # also match the text read from pictures and PDFs
            conds.append(PastQuestion.files.ilike(like, escape="\\"))
        base = base.filter(or_(*conds))
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

@questions_bp.route("/api/questions/read-text", methods=["POST"])
def api_read_text():
    """Type out the text of an uploaded picture, PDF or Word file. The admin can correct it before saving."""
    _admin_api()
    from .services import supabase_storage as st
    key = (request.get_json(silent=True) or {}).get("key")
    if not isinstance(key, str) or not re.fullmatch(_KEY, key):
        return _err("That file isn't valid.")
    ext = key.rsplit(".", 1)[1]
    if ext not in ("jpg", "png", "webp", "pdf", "docx"):
        return _err("Text can only be read from pictures, PDF and Word files.")
    if not st.configured():
        return _err("Uploads aren't set up on the server.", 503)
    try:
        data = st.read_all(key, _CAP[ext] * 1024 * 1024)
    except Exception:
        return _err("We couldn't open that file. Please try again.")
    try:
        if ext == "pdf":
            text, note = _read_pdf(data), "This PDF has no selectable text (it may be a scan). Type it in or upload it as pictures."
        elif ext == "docx":
            text, note = _read_docx(data), "No text found in this document."
        else:
            if not __import__("os").environ.get("OPENAI_API_KEY"):
                return _err("Reading text from pictures needs the OPENAI_API_KEY setting on the server.", 503)
            text, note = _transcribe_image(data), "No readable text was found in this picture."
    except ValueError as e:
        return _err(str(e))
    except Exception:
        current_app.logger.exception("Reading text failed")
        return _err("We couldn't read the text this time. You can type it in or try again.", 502)
    text = _clean_text(text)
    return jsonify(text=text, note=None if text else note)

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
        entry = {"url": st.public_url(key), "key": key, "type": kind, "name": _clean_name(it.get("name")), "size": size}
        text = _clean_text(it.get("text"))
        if text and kind in ("image", "pdf", "doc"):
            entry["text"] = text
        files.append(entry)
    row = PastQuestion(title=title, subject=subject, body=body, files=json.dumps(files, separators=(",", ":"), ensure_ascii=False),
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
