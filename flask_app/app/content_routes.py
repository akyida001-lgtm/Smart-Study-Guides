"""Content management routes — admin posts (results, discounts, videos, pictures)."""
import uuid
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user

from .models import db, Post, PostMedia, PostType
from .native_auth import require_login
from .services import supabase_storage

content_bp = Blueprint("content", __name__)


def _is_admin():
    return current_user.is_authenticated and getattr(current_user, "is_staff", False)


def _save_media_files(post, files):
    for f in files:
        if not f or not f.filename:
            continue
        ext = f.filename.rsplit(".", 1)[-1].lower()
        media_type = "video" if ext in ("mp4", "mov", "avi", "webm", "mkv") else "image"
        filename = f"content/{post.id}/{media_type}s/{uuid.uuid4().hex}.{ext}"
        data = f.read()
        ct = f.content_type or ("video/mp4" if media_type == "video" else "image/jpeg")
        url = supabase_storage.upload_file(filename, data, ct, signed_days=365)
        if url:
            pm = PostMedia(post_id=post.id, url=url, media_type=media_type)
            db.session.add(pm)


@content_bp.route("/admin/content")
@require_login
def admin_content_list():
    if not _is_admin():
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template("admin_content.html", posts=posts)


@content_bp.route("/admin/content/new", methods=["GET", "POST"])
@require_login
def admin_content_new():
    if not _is_admin():
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))
    if request.method == "POST":
        post = Post(
            type=PostType[request.form.get("type", "result")],
            title=request.form.get("title", "").strip(),
            description=request.form.get("description", "").strip(),
            published=request.form.get("published") == "on",
        )
        db.session.add(post)
        db.session.flush()
        files = request.files.getlist("media_files")
        _save_media_files(post, files)
        db.session.commit()
        flash("Post created!", "success")
        return redirect(url_for("content.admin_content_list"))
    return render_template("admin_content_form.html", post=None)


@content_bp.route("/admin/content/<int:post_id>/edit", methods=["GET", "POST"])
@require_login
def admin_content_edit(post_id):
    if not _is_admin():
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))
    post = Post.query.get_or_404(post_id)
    if request.method == "POST":
        post.type        = PostType[request.form.get("type", "result")]
        post.title       = request.form.get("title", "").strip()
        post.description = request.form.get("description", "").strip()
        post.published   = request.form.get("published") == "on"
        post.updated_at  = datetime.utcnow()
        delete_ids = request.form.getlist("delete_media")
        if delete_ids:
            PostMedia.query.filter(
                PostMedia.id.in_([int(x) for x in delete_ids]),
                PostMedia.post_id == post.id,
            ).delete(synchronize_session=False)
        files = request.files.getlist("media_files")
        _save_media_files(post, files)
        db.session.commit()
        flash("Post updated!", "success")
        return redirect(url_for("content.admin_content_list"))
    return render_template("admin_content_form.html", post=post)


@content_bp.route("/admin/content/<int:post_id>/delete", methods=["POST"])
@require_login
def admin_content_delete(post_id):
    if not _is_admin():
        return jsonify({"error": "Access denied"}), 403
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash("Post deleted.", "info")
    return redirect(url_for("content.admin_content_list"))


@content_bp.route("/admin/content/<int:post_id>/toggle", methods=["POST"])
@require_login
def admin_content_toggle(post_id):
    if not _is_admin():
        return jsonify({"error": "Access denied"}), 403
    post = Post.query.get_or_404(post_id)
    post.published = not post.published
    db.session.commit()
    return jsonify({"published": post.published})


@content_bp.route("/updates")
def public_updates():
    results   = Post.query.filter_by(type=PostType.result,   published=True).order_by(Post.created_at.desc()).all()
    discounts = Post.query.filter_by(type=PostType.discount, published=True).order_by(Post.created_at.desc()).all()
    videos    = Post.query.filter_by(type=PostType.video,    published=True).order_by(Post.created_at.desc()).all()
    pictures  = Post.query.filter_by(type=PostType.picture,  published=True).order_by(Post.created_at.desc()).all()
    return render_template(
        "public_updates.html",
        results=results,
        discounts=discounts,
        videos=videos,
        pictures=pictures,
    )
