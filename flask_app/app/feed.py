"""Updates feed: an anonymous community feed with photos, videos, likes, comments, saves and reels.

Privacy: every post/comment is shown under a made-up alias (different on every post, so a person
can't be followed across posts). Only admins can see who is behind a post, for moderation.
Admins post as the official "Smart Study Guides" account.
"""
import hashlib
import io
import json
import os
import re
import uuid
from datetime import datetime, timedelta

from flask import (Blueprint, abort, current_app, flash, jsonify, make_response, redirect,
                   render_template, request, send_from_directory, url_for)
from flask_login import current_user
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from .models import (db, User, FeedPost, FeedComment, FeedLike, FeedSave, FeedReport, FeedBan)
from .native_auth import require_login

feed_bp = Blueprint("feed", __name__)

MAX_BODY, MAX_COMMENT, MAX_IMAGES = 2000, 500, 4
# Vercel (and most serverless hosts) reject request bodies over ~4.5 MB, so anything bigger goes straight to storage.
MAX_IMG_BYTES, MAX_VIDEO_BYTES, MAX_REQUEST_BYTES = 10 * 1024 * 1024, 25 * 1024 * 1024, 4_200_000
POSTS_PER_HOUR, POSTS_PER_DAY, COMMENTS_PER_HOUR, REPORTS_TO_HIDE = 5, 20, 30, 3

_ADJ = ["Curious", "Sleepy", "Brave", "Quiet", "Clever", "Cheerful", "Gentle", "Witty", "Calm", "Bold", "Lucky", "Swift",
        "Sunny", "Mellow", "Eager", "Humble", "Jolly", "Nimble", "Polite", "Radiant", "Steady", "Thoughtful", "Vivid", "Zesty"]
_ANIMALS = [("Fox", "🦊"), ("Panda", "🐼"), ("Owl", "🦉"), ("Otter", "🦦"), ("Koala", "🐨"), ("Tiger", "🐯"), ("Dolphin", "🐬"),
            ("Rabbit", "🐰"), ("Penguin", "🐧"), ("Falcon", "🦅"), ("Turtle", "🐢"), ("Lion", "🦁"), ("Giraffe", "🦒"),
            ("Hedgehog", "🦔"), ("Whale", "🐳"), ("Zebra", "🦓"), ("Bee", "🐝"), ("Butterfly", "🦋"), ("Deer", "🦌"),
            ("Elephant", "🐘"), ("Frog", "🐸"), ("Monkey", "🐵"), ("Wolf", "🐺"), ("Seal", "🦭")]
class StorageUnavailable(Exception):
    """Raised when there is nowhere to save an upload (no R2 settings and a read-only disk)."""

REPORT_REASONS = {"spam", "harassment", "inappropriate", "false", "other"}


# ── helpers ───────────────────────────────────────────────────────────────────
def _is_admin():
    return current_user.is_authenticated and bool(getattr(current_user, "is_staff", False))

def _uid():
    return current_user.id if current_user.is_authenticated else None

def _err(msg, code=400):
    return jsonify({"error": msg}), code

def _guard():
    """Reject cross-site requests: our own pages always send this header, other sites cannot."""
    if request.headers.get("X-Requested-With") != "ssg-feed":
        abort(make_response(jsonify({"error": "Bad request."}), 403))
    if request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
        abort(make_response(jsonify({"error": "Bad request."}), 403))

def _banned(uid):
    return bool(uid and db.session.get(FeedBan, uid))

def _alias(post_id, user_id):
    h = int(hashlib.sha256(f"{current_app.secret_key}:{post_id}:{user_id}".encode()).hexdigest(), 16)
    name, emoji = _ANIMALS[(h // 97) % len(_ANIMALS)]
    return {"name": f"{_ADJ[h % len(_ADJ)]} {name}", "emoji": emoji, "hue": (h // 7919) % 360, "official": False}

def _author(user_id, post_id, official):
    if official:
        return {"name": "Smart Study Guides", "emoji": "", "hue": 174, "official": True}
    return _alias(post_id, user_id)

def _tags_from(body):
    tags = sorted(set(re.findall(r"#([a-z0-9_]{2,30})", (body or "").lower())))
    return (" " + " ".join(tags) + " ") if tags else ""

def _post_json(p, liked, saved, uid, admin):
    return {
        "id": p.id, "author": _author(p.user_id, p.id, p.is_official), "body": p.body, "kind": p.kind,
        "media": json.loads(p.media or "[]"), "tags": p.tags.split(), "pinned": p.is_pinned,
        "created": p.created_at.isoformat() + "Z", "likes": p.like_count, "comments": p.comment_count,
        "views": p.view_count, "liked": p.id in liked, "saved": p.id in saved,
        "mine": bool(uid and uid == p.user_id), "can_remove": admin or bool(uid and uid == p.user_id), "admin": admin,
    }

def _posts_json(posts):
    uid, admin = _uid(), _is_admin()
    ids = [p.id for p in posts]
    liked = saved = set()
    if uid and ids:
        liked = {r.target_id for r in FeedLike.query.filter(FeedLike.user_id == uid, FeedLike.kind == "post", FeedLike.target_id.in_(ids))}
        saved = {r.post_id for r in FeedSave.query.filter(FeedSave.user_id == uid, FeedSave.post_id.in_(ids))}
    return [_post_json(p, liked, saved, uid, admin) for p in posts]

def _visible_post_or_404(pid):
    p = db.session.get(FeedPost, pid)
    if not p or p.status != "visible":
        abort(make_response(jsonify({"error": "This post isn't available."}), 404))
    return p


# ── media ─────────────────────────────────────────────────────────────────────
def _sniff(data):
    if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:6] in (b"GIF87a", b"GIF89a") \
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        return "image"
    if data[4:8] == b"ftyp":
        return "mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return None

def _clean_image(data):
    """Re-encode as WebP: strips EXIF/GPS and other metadata, fixes rotation, caps the size."""
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 30_000_000
    try:
        img = Image.open(io.BytesIO(data))
        if img.format == "JPEG":
            img.draft("RGB", (1800, 1800))
        img = ImageOps.exif_transpose(img)
        img.thumbnail((1600, 1600))
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        out = io.BytesIO()
        img.save(out, "WEBP", quality=80, method=4)
        return out.getvalue(), img.width, img.height
    except Exception:
        raise ValueError("One of those images couldn't be read. Try a JPG, PNG or WebP photo.")

def _media_dir():
    d = os.path.join(current_app.instance_path, "feed_media")
    os.makedirs(d, exist_ok=True)
    return d

def _store(data, ext, ctype):
    name = f"{uuid.uuid4().hex}.{ext}"
    from .services import supabase_storage
    try:
        if supabase_storage.configured():
            return supabase_storage.upload_file(f"feed/{name}", data, ctype)
        with open(os.path.join(_media_dir(), name), "wb") as f:      # local development only
            f.write(data)
        return f"/updates/media/{name}"
    except Exception:
        current_app.logger.exception("Feed upload could not be saved")
        raise StorageUnavailable()

def _direct_video(key):
    """A video the browser uploaded straight to storage: check it before it can be posted."""
    from .services import supabase_storage as st
    if not st.configured() or not re.fullmatch(r"feed/[a-f0-9]{32}\.(mp4|webm)", key or ""):
        raise ValueError("That video upload isn't valid. Please try again.")
    if FeedPost.query.filter(FeedPost.media.like(f"%{key}%")).first():
        raise ValueError("That video was already used in another post.")
    def drop():
        try:
            st.delete(key)
        except Exception:
            pass
    try:
        size = int(st.head(key).get("ContentLength", 0))
        head = st.read_range(key, 16) if 0 < size <= MAX_VIDEO_BYTES else b""
    except Exception:
        raise ValueError("We couldn't find your uploaded video. Please try again.")
    if size <= 0 or size > MAX_VIDEO_BYTES:
        drop()
        raise ValueError("Videos can be up to 25 MB.")
    kind = _sniff(head)
    if kind not in ("mp4", "webm") or (kind == "webm") != key.endswith(".webm"):
        drop()
        raise ValueError("That file isn't a supported video (MP4, MOV or WebM).")
    return "video", [{"url": st.public_url(key), "type": "video", "w": 0, "h": 0}]

def _process_files(files):
    """Validate and store uploads. Returns (kind, media list). Up to 4 photos, or one video."""
    if not files:
        return "text", []
    blobs = []
    for f in files:
        data = f.read(MAX_VIDEO_BYTES + 1)
        kind = _sniff(data)
        if kind is None:
            raise ValueError("Only photos (JPG, PNG, WebP, GIF) and videos (MP4, MOV, WebM) can be uploaded.")
        if kind == "image" and len(data) > MAX_IMG_BYTES:
            raise ValueError("Photos can be up to 10 MB each.")
        if kind != "image" and len(data) > MAX_VIDEO_BYTES:
            raise ValueError("Videos can be up to 25 MB.")
        blobs.append((kind, data))
    videos = [b for b in blobs if b[0] != "image"]
    if videos and len(blobs) > 1:
        raise ValueError("Add either up to 4 photos or one video, not both.")
    if len(blobs) > MAX_IMAGES:
        raise ValueError(f"You can add up to {MAX_IMAGES} photos.")
    if videos:
        kind, data = videos[0]
        ext, ctype = ("webm", "video/webm") if kind == "webm" else ("mp4", "video/mp4")
        return "video", [{"url": _store(data, ext, ctype), "type": "video", "w": 0, "h": 0}]
    media = []
    for _, data in blobs:
        webp, w, h = _clean_image(data)
        media.append({"url": _store(webp, "webp", "image/webp"), "type": "image", "w": w, "h": h})
    return "image", media


# ── pages ─────────────────────────────────────────────────────────────────────
@feed_bp.route("/updates")
def updates_page():
    tag = re.sub(r"[^a-z0-9_]", "", (request.args.get("tag") or "").lower())[:30]
    focus = request.args.get("post", type=int) or 0
    since = datetime.utcnow() - timedelta(days=14)
    counts = {}
    for (t,) in db.session.query(FeedPost.tags).filter(FeedPost.status == "visible", FeedPost.created_at >= since, FeedPost.tags != "").limit(300):
        for x in t.split():
            counts[x] = counts.get(x, 0) + 1
    trending = [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8]]
    uid = _uid()
    return render_template("updates.html", tag=tag, focus_post=focus, trending=trending, is_admin=_is_admin(),
                           can_post=bool(uid) and not _banned(uid))

@feed_bp.route("/updates/media/<name>")
def feed_media(name):
    if not re.fullmatch(r"[a-f0-9]{32}\.(webp|mp4|webm)", name):
        abort(404)
    return send_from_directory(_media_dir(), name, conditional=True, max_age=31536000)


# ── posts ─────────────────────────────────────────────────────────────────────
@feed_bp.route("/api/feed")
def api_feed():
    tab = request.args.get("tab", "feed")
    tag = re.sub(r"[^a-z0-9_]", "", (request.args.get("tag") or "").lower())[:30]
    before = request.args.get("before", type=int) or 0
    limit = max(1, min(request.args.get("limit", 8, type=int), 20))
    uid = _uid()
    if tab == "saved":
        if not uid:
            return _err("Sign in to see your saved posts.", 401)
        q = (db.session.query(FeedSave, FeedPost).join(FeedPost, FeedPost.id == FeedSave.post_id)
             .filter(FeedSave.user_id == uid, FeedPost.status == "visible"))
        if before:
            q = q.filter(FeedSave.id < before)
        rows = q.order_by(FeedSave.id.desc()).limit(limit).all()
        return jsonify(posts=_posts_json([p for _, p in rows]), next=rows[-1][0].id if len(rows) == limit else None)
    q = FeedPost.query.filter(FeedPost.status == "visible")
    if tab == "reels":
        q = q.filter(FeedPost.kind == "video")
    if tag:
        q = q.filter(FeedPost.tags.like(f"% {tag} %"))
    pinned = []
    if tab == "feed" and not before and not tag:
        pinned = q.filter(FeedPost.is_pinned.is_(True)).order_by(FeedPost.created_at.desc()).all()
    q = q.filter(FeedPost.is_pinned.is_(False)) if tab == "feed" and not tag else q
    if before:
        q = q.filter(FeedPost.id < before)
    rows = q.order_by(FeedPost.id.desc()).limit(limit).all()
    return jsonify(posts=_posts_json(pinned + rows), next=rows[-1].id if len(rows) == limit else None)

@feed_bp.route("/api/feed/posts/<int:pid>")
def api_get_post(pid):
    return jsonify(post=_posts_json([_visible_post_or_404(pid)])[0])

@feed_bp.route("/api/feed/posts", methods=["POST"])
@require_login
def api_create_post():
    _guard()
    uid, admin = _uid(), _is_admin()
    if _banned(uid):
        return _err("You can't post right now.", 403)
    if (request.content_length or 0) > MAX_REQUEST_BYTES:
        return _err("That upload is too large.", 413)
    body = (request.form.get("body") or "").strip()
    if len(body) > MAX_BODY:
        return _err(f"Posts can be up to {MAX_BODY:,} characters.")
    if not admin:
        now = datetime.utcnow()
        if FeedPost.query.filter(FeedPost.user_id == uid, FeedPost.created_at >= now - timedelta(hours=1)).count() >= POSTS_PER_HOUR \
                or FeedPost.query.filter(FeedPost.user_id == uid, FeedPost.created_at >= now - timedelta(days=1)).count() >= POSTS_PER_DAY:
            return _err("You're posting too fast. Please try again a bit later.", 429)
    files = [f for f in request.files.getlist("files") if f and f.filename]
    video_key = (request.form.get("video_key") or "").strip()
    try:
        if video_key:
            if files:
                return _err("Add either up to 4 photos or one video, not both.")
            kind, media = _direct_video(video_key)
        else:
            kind, media = _process_files(files)
    except ValueError as e:
        return _err(str(e))
    except StorageUnavailable:
        return _err("Uploads aren't available right now. Please try again later.", 503)
    if not body and not media:
        return _err("Write something or add a photo or video.")
    p = FeedPost(user_id=uid, body=body, kind=kind, media=json.dumps(media, separators=(",", ":")),
                 tags=_tags_from(body), is_official=admin)
    db.session.add(p)
    db.session.commit()
    return jsonify(post=_posts_json([p])[0]), 201

@feed_bp.route("/api/feed/video-upload", methods=["POST"])
@require_login
def api_video_upload():
    """Hand the browser a short-lived link so a video goes straight to storage (it can't pass through the server)."""
    _guard()
    uid = _uid()
    if _banned(uid):
        return _err("You can't post right now.", 403)
    from .services import supabase_storage as st
    if not st.configured():
        return _err("Video uploads aren't set up yet.", 503)
    data = request.get_json(silent=True) or {}
    ext = {"video/mp4": "mp4", "video/quicktime": "mp4", "video/webm": "webm"}.get((data.get("type") or "").lower())
    try:
        size = int(data.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if not ext:
        return _err("Only MP4, MOV or WebM videos can be uploaded.")
    if size <= 0 or size > MAX_VIDEO_BYTES:
        return _err("Videos can be up to 25 MB.")
    ctype = "video/webm" if ext == "webm" else "video/mp4"
    key = f"feed/{uuid.uuid4().hex}.{ext}"
    try:
        url = st.presign_put(key, ctype, size)
    except Exception:
        current_app.logger.exception("Could not create a video upload link")
        return _err("Video uploads aren't available right now.", 503)
    return jsonify(upload_url=url, key=key, content_type=ctype)

@feed_bp.route("/api/feed/posts/<int:pid>", methods=["DELETE"])
@require_login
def api_delete_post(pid):
    _guard()
    p = db.session.get(FeedPost, pid)
    if not p or p.status == "removed":
        return _err("Not found.", 404)
    if not (_is_admin() or p.user_id == _uid()):
        return _err("You can only delete your own posts.", 403)
    p.status = "removed"
    db.session.commit()
    return jsonify(ok=True)

def _toggle(model, **keys):
    row = model.query.filter_by(**keys).first()
    if row:
        db.session.delete(row)
        return False
    db.session.add(model(**keys))
    return True

@feed_bp.route("/api/feed/posts/<int:pid>/like", methods=["POST"])
@require_login
def api_like_post(pid):
    _guard()
    p = _visible_post_or_404(pid)
    on = _toggle(FeedLike, user_id=_uid(), kind="post", target_id=pid)
    p.like_count = max(0, p.like_count + (1 if on else -1))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _err("Try again.", 409)
    return jsonify(liked=on, likes=p.like_count)

@feed_bp.route("/api/feed/posts/<int:pid>/save", methods=["POST"])
@require_login
def api_save_post(pid):
    _guard()
    _visible_post_or_404(pid)
    on = _toggle(FeedSave, user_id=_uid(), post_id=pid)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _err("Try again.", 409)
    return jsonify(saved=on)

@feed_bp.route("/api/feed/posts/<int:pid>/view", methods=["POST"])
def api_view_post(pid):
    _guard()
    p = db.session.get(FeedPost, pid)
    if p and p.status == "visible":
        p.view_count += 1
        db.session.commit()
    return jsonify(ok=True)

@feed_bp.route("/api/feed/posts/<int:pid>/pin", methods=["POST"])
@require_login
def api_pin_post(pid):
    _guard()
    if not _is_admin():
        return _err("Admins only.", 403)
    p = _visible_post_or_404(pid)
    p.is_pinned = not p.is_pinned
    db.session.commit()
    return jsonify(pinned=p.is_pinned)

def _report(kind, target_id, model):
    obj = db.session.get(model, target_id)
    if not obj or obj.status != "visible":
        return _err("Not found.", 404)
    if obj.user_id == _uid():
        return _err("You can't report your own content.", 400)
    reason = ((request.get_json(silent=True) or {}).get("reason") or "other")
    reason = reason if reason in REPORT_REASONS else "other"
    db.session.add(FeedReport(user_id=_uid(), kind=kind, target_id=target_id, reason=reason))
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return jsonify(ok=True, already=True)
    obj.report_count += 1
    if obj.report_count >= REPORTS_TO_HIDE and not getattr(obj, "is_official", False):
        obj.status = "hidden"           # held back until an admin has looked at it
        if kind == "comment":
            _recount(obj.post_id)
    db.session.commit()
    return jsonify(ok=True)

@feed_bp.route("/api/feed/posts/<int:pid>/report", methods=["POST"])
@require_login
def api_report_post(pid):
    _guard()
    return _report("post", pid, FeedPost)


# ── comments ──────────────────────────────────────────────────────────────────
def _recount(post_id):
    p = db.session.get(FeedPost, post_id)
    if p:
        p.comment_count = FeedComment.query.filter_by(post_id=post_id, status="visible").count()

def _comment_json(c, post, liked, uid, admin):
    return {"id": c.id, "parent_id": c.parent_id, "author": _author(c.user_id, post.id, c.is_official), "body": c.body,
            "created": c.created_at.isoformat() + "Z", "likes": c.like_count, "liked": c.id in liked,
            "is_op": c.user_id == post.user_id and not post.is_official and not c.is_official,
            "can_remove": admin or bool(uid and (uid == c.user_id or uid == post.user_id)), "mine": bool(uid and uid == c.user_id), "replies": []}

@feed_bp.route("/api/feed/posts/<int:pid>/comments")
def api_comments(pid):
    post = _visible_post_or_404(pid)
    after = request.args.get("after", type=int) or 0
    uid, admin = _uid(), _is_admin()
    top = (FeedComment.query.filter(FeedComment.post_id == pid, FeedComment.status == "visible", FeedComment.parent_id.is_(None), FeedComment.id > after)
           .order_by(FeedComment.id.asc()).limit(15).all())
    replies = (FeedComment.query.filter(FeedComment.post_id == pid, FeedComment.status == "visible", FeedComment.parent_id.in_([c.id for c in top]))
               .order_by(FeedComment.id.asc()).all()) if top else []
    ids = [c.id for c in top + replies]
    liked = {r.target_id for r in FeedLike.query.filter(FeedLike.user_id == uid, FeedLike.kind == "comment", FeedLike.target_id.in_(ids))} if uid and ids else set()
    out = {c.id: _comment_json(c, post, liked, uid, admin) for c in top}
    for r in replies:
        out[r.parent_id]["replies"].append(_comment_json(r, post, liked, uid, admin))
    return jsonify(comments=[out[c.id] for c in top], next=top[-1].id if len(top) == 15 else None)

@feed_bp.route("/api/feed/posts/<int:pid>/comments", methods=["POST"])
@require_login
def api_add_comment(pid):
    _guard()
    post, uid, admin = _visible_post_or_404(pid), _uid(), _is_admin()
    if _banned(uid):
        return _err("You can't comment right now.", 403)
    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    if not body:
        return _err("Write a comment first.")
    if len(body) > MAX_COMMENT:
        return _err(f"Comments can be up to {MAX_COMMENT} characters.")
    if not admin and FeedComment.query.filter(FeedComment.user_id == uid, FeedComment.created_at >= datetime.utcnow() - timedelta(hours=1)).count() >= COMMENTS_PER_HOUR:
        return _err("You're commenting too fast. Please slow down.", 429)
    parent_id = data.get("parent_id")
    if parent_id:
        parent = db.session.get(FeedComment, int(parent_id)) if str(parent_id).isdigit() else None
        if not parent or parent.post_id != pid or parent.status != "visible":
            return _err("That comment is no longer available.", 404)
        parent_id = parent.parent_id or parent.id         # replies stay one level deep
    c = FeedComment(post_id=pid, user_id=uid, parent_id=parent_id or None, body=body, is_official=admin)
    db.session.add(c)
    db.session.flush()
    _recount(pid)
    db.session.commit()
    return jsonify(comment=_comment_json(c, post, set(), uid, admin), comments=post.comment_count), 201

@feed_bp.route("/api/feed/comments/<int:cid>", methods=["DELETE"])
@require_login
def api_delete_comment(cid):
    _guard()
    c = db.session.get(FeedComment, cid)
    post = db.session.get(FeedPost, c.post_id) if c else None
    if not c or c.status == "removed":
        return _err("Not found.", 404)
    if not (_is_admin() or c.user_id == _uid() or (post and post.user_id == _uid())):
        return _err("You can't delete this comment.", 403)
    c.status = "removed"
    _recount(c.post_id)
    db.session.commit()
    return jsonify(ok=True, comments=post.comment_count)

@feed_bp.route("/api/feed/comments/<int:cid>/like", methods=["POST"])
@require_login
def api_like_comment(cid):
    _guard()
    c = db.session.get(FeedComment, cid)
    if not c or c.status != "visible":
        return _err("Not found.", 404)
    on = _toggle(FeedLike, user_id=_uid(), kind="comment", target_id=cid)
    c.like_count = max(0, c.like_count + (1 if on else -1))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _err("Try again.", 409)
    return jsonify(liked=on, likes=c.like_count)

@feed_bp.route("/api/feed/comments/<int:cid>/report", methods=["POST"])
@require_login
def api_report_comment(cid):
    _guard()
    return _report("comment", cid, FeedComment)


# ── admin moderation ──────────────────────────────────────────────────────────
def _admin_only():
    if not _is_admin():
        abort(403)

@feed_bp.route("/admin/feed")
@require_login
def admin_feed():
    _admin_only()
    flagged_posts = (FeedPost.query.filter(FeedPost.status != "removed", or_(FeedPost.status == "hidden", FeedPost.report_count > 0))
                     .order_by(FeedPost.created_at.desc()).limit(50).all())
    flagged_comments = (FeedComment.query.filter(FeedComment.status != "removed", or_(FeedComment.status == "hidden", FeedComment.report_count > 0))
                        .order_by(FeedComment.created_at.desc()).limit(50).all())
    recent = FeedPost.query.order_by(FeedPost.created_at.desc()).limit(30).all()
    bans = FeedBan.query.order_by(FeedBan.created_at.desc()).all()
    uids = {p.user_id for p in flagged_posts + recent} | {c.user_id for c in flagged_comments} | {b.user_id for b in bans}
    emails = {u.id: u.email for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    reasons = {}
    for r in FeedReport.query.filter(FeedReport.target_id.in_([p.id for p in flagged_posts] + [c.id for c in flagged_comments])).all():
        reasons.setdefault((r.kind, r.target_id), []).append(r.reason)
    return render_template("admin_feed.html", flagged_posts=flagged_posts, flagged_comments=flagged_comments, recent=recent,
                           bans=bans, emails=emails, reasons=reasons, banned={b.user_id for b in bans}, json=json)

@feed_bp.route("/admin/feed/post/<int:pid>/<action>", methods=["POST"])
@require_login
def admin_feed_post(pid, action):
    _admin_only()
    p = db.session.get(FeedPost, pid) or abort(404)
    if action == "restore":
        p.status, p.report_count = "visible", 0
        FeedReport.query.filter_by(kind="post", target_id=pid).delete()
    elif action in ("remove", "hide"):
        p.status = "removed" if action == "remove" else "hidden"
        if request.form.get("ban") and not p.is_official:
            _ban(p.user_id, "Removed post")
    else:
        abort(404)
    db.session.commit()
    return redirect(url_for("feed.admin_feed"))

@feed_bp.route("/admin/feed/comment/<int:cid>/<action>", methods=["POST"])
@require_login
def admin_feed_comment(cid, action):
    _admin_only()
    c = db.session.get(FeedComment, cid) or abort(404)
    if action == "restore":
        c.status, c.report_count = "visible", 0
        FeedReport.query.filter_by(kind="comment", target_id=cid).delete()
    elif action == "remove":
        c.status = "removed"
        if request.form.get("ban") and not c.is_official:
            _ban(c.user_id, "Removed comment")
    else:
        abort(404)
    _recount(c.post_id)
    db.session.commit()
    return redirect(url_for("feed.admin_feed"))

def _ban(user_id, reason):
    if user_id and user_id != "system" and not db.session.get(FeedBan, user_id):
        db.session.add(FeedBan(user_id=user_id, reason=reason[:200]))

@feed_bp.route("/admin/feed/ban", methods=["POST"])
@require_login
def admin_feed_ban():
    _admin_only()
    _ban((request.form.get("user_id") or "").strip(), (request.form.get("reason") or "Banned by admin"))
    db.session.commit()
    return redirect(url_for("feed.admin_feed"))

@feed_bp.route("/admin/feed/unban", methods=["POST"])
@require_login
def admin_feed_unban():
    _admin_only()
    b = db.session.get(FeedBan, (request.form.get("user_id") or "").strip())
    if b:
        db.session.delete(b)
        db.session.commit()
    return redirect(url_for("feed.admin_feed"))


# ── housekeeping ──────────────────────────────────────────────────────────────
def import_legacy_posts():
    """One-time import of the old admin 'Posts' (results, offers, videos, pictures) as official feed posts."""
    from .models import Post
    done = {r[0] for r in db.session.query(FeedPost.legacy_post_id).filter(FeedPost.legacy_post_id.isnot(None))}
    added = 0
    for lp in Post.query.filter_by(published=True).order_by(Post.created_at).all():
        if lp.id in done:
            continue
        media = [{"url": m.url, "type": "video" if m.media_type == "video" else "image", "w": 0, "h": 0}
                 for m in sorted(lp.media, key=lambda m: m.order or 0)]
        kind = "video" if any(m["type"] == "video" for m in media) else ("image" if media else "text")
        media = [m for m in media if m["type"] == "video"][:1] if kind == "video" else media[:MAX_IMAGES]
        body = (lp.title or "").strip() + (("\n\n" + lp.description.strip()) if lp.description else "")
        tag = {"discount": "offers", "result": "results"}.get(lp.type.value)
        if tag:
            body += f"\n\n#{tag}"
        db.session.add(FeedPost(user_id="system", body=body, kind=kind, media=json.dumps(media, separators=(",", ":")),
                                tags=_tags_from(body), is_official=True, legacy_post_id=lp.id, created_at=lp.created_at or datetime.utcnow()))
        added += 1
    if added:
        db.session.commit()
    return added

def delete_user_feed_data(uid):
    """Remove everything a deleted account created in the feed."""
    mine = [p.id for p in FeedPost.query.filter_by(user_id=uid)]
    my_comments = [c.id for c in FeedComment.query.filter_by(user_id=uid)]
    on_my_posts = [c.id for c in FeedComment.query.filter(FeedComment.post_id.in_(mine))] if mine else []
    cids = list(set(my_comments + on_my_posts))
    if cids:
        FeedLike.query.filter(FeedLike.kind == "comment", FeedLike.target_id.in_(cids)).delete(synchronize_session=False)
        FeedReport.query.filter(FeedReport.kind == "comment", FeedReport.target_id.in_(cids)).delete(synchronize_session=False)
        FeedComment.query.filter(FeedComment.id.in_(cids)).delete(synchronize_session=False)
    if mine:
        FeedLike.query.filter(FeedLike.kind == "post", FeedLike.target_id.in_(mine)).delete(synchronize_session=False)
        FeedSave.query.filter(FeedSave.post_id.in_(mine)).delete(synchronize_session=False)
        FeedReport.query.filter(FeedReport.kind == "post", FeedReport.target_id.in_(mine)).delete(synchronize_session=False)
        FeedPost.query.filter(FeedPost.id.in_(mine)).delete(synchronize_session=False)
    for m in (FeedLike, FeedSave, FeedReport, FeedBan):
        m.query.filter_by(user_id=uid).delete(synchronize_session=False)
