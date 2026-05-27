"""Supabase Storage — direct REST API calls (bypasses supabase-py routing bugs)."""
import os
import uuid
import requests as _req


def _base() -> str:
    url = os.environ["SUPABASE_URL"].rstrip("/")
    # Strip any PostgREST suffix so we hit the storage API root correctly
    for suffix in ("/rest/v1", "/rest"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return f"{url}/storage/v1"


def _supabase_root() -> str:
    url = os.environ["SUPABASE_URL"].rstrip("/")
    for suffix in ("/rest/v1", "/rest"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url


def _headers(content_type: str | None = None) -> dict:
    h = {
        "apikey":         os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization":  f"Bearer {os.environ['SUPABASE_SERVICE_ROLE_KEY']}",
    }
    if content_type:
        h["Content-Type"] = content_type
    return h


def _upload_with_fallback(path: str, data: bytes, content_type: str) -> None:
    bucket  = os.environ["SUPABASE_BUCKET"]
    base    = _base()
    obj_url = f"{base}/object/{bucket}/{path}"

    # Try POST (new file)
    r = _req.post(obj_url, data=data, headers=_headers(content_type), timeout=60)
    if r.status_code in (200, 201):
        return

    # File exists (409) → try PUT (update)
    if r.status_code == 409:
        r2 = _req.put(obj_url, data=data, headers=_headers(content_type), timeout=60)
        if r2.status_code in (200, 201):
            return
        raise RuntimeError(f"PUT failed {r2.status_code}: {r2.text[:200]}")

    raise RuntimeError(f"POST failed {r.status_code}: {r.text[:200]}")


def _get_signed_url(path: str, days: int) -> str:
    bucket   = os.environ["SUPABASE_BUCKET"]
    base     = _base()
    sign_url = f"{base}/object/sign/{bucket}/{path}"
    r = _req.post(
        sign_url,
        json={"expiresIn": 60 * 60 * 24 * days},
        headers=_headers("application/json"),
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Sign URL failed {r.status_code}: {r.text[:200]}")
    data = r.json()
    signed_path = data.get("signedURL") or data.get("signedUrl") or data.get("signed_url") or ""
    if signed_path.startswith("/"):
        return f"{_supabase_root()}{signed_path}"
    return signed_path


def upload_docx(filename: str, data: bytes) -> str:
    ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    _upload_with_fallback(filename, data, ct)
    return _get_signed_url(filename, 7)


def upload_rubric(assignment_id: int, file_bytes: bytes, content_type: str) -> str:
    ext      = "pdf" if content_type == "application/pdf" else "jpg"
    filename = f"rubrics/{assignment_id}/{uuid.uuid4().hex}.{ext}"
    _upload_with_fallback(filename, file_bytes, content_type)
    return _get_signed_url(filename, 365)


def upload_file(path: str, data: bytes, content_type: str, signed_days: int = 365) -> str:
    _upload_with_fallback(path, data, content_type)
    return _get_signed_url(path, signed_days)


def upload_id_scan(user_id: str, file_bytes: bytes, content_type: str) -> str:
    ext      = "pdf" if content_type == "application/pdf" else "jpg"
    filename = f"id_scans/{user_id}/{uuid.uuid4().hex}.{ext}"
    _upload_with_fallback(filename, file_bytes, content_type)
    return _get_signed_url(filename, 365)
