"""Cloudflare R2 Storage — S3-compatible object storage (replaces Supabase)."""
import os
import uuid
import boto3
from botocore.client import Config


def _client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _bucket() -> str:
    return os.environ.get("R2_BUCKET", "smart-study-guides")


def _upload(path: str, data: bytes, content_type: str) -> None:
    _client().put_object(
        Bucket=_bucket(),
        Key=path,
        Body=data,
        ContentType=content_type,
    )


def _get_signed_url(path: str, days: int) -> str:
    # Cloudflare R2 maximum is 7 days (604800 seconds)
    expires = min(60 * 60 * 24 * days, 604800)
    url = _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": path},
        ExpiresIn=expires,
    )
    return url


def upload_docx(filename: str, data: bytes) -> str:
    ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    _upload(filename, data, ct)
    return _get_signed_url(filename, 7)


def upload_rubric(assignment_id: int, file_bytes: bytes, content_type: str) -> str:
    ext      = "pdf" if content_type == "application/pdf" else "jpg"
    filename = f"rubrics/{assignment_id}/{uuid.uuid4().hex}.{ext}"
    _upload(filename, file_bytes, content_type)
    return _get_signed_url(filename, 365)


def upload_file(path: str, data: bytes, content_type: str, signed_days: int = 365) -> str:
    _upload(path, data, content_type)
    return _get_signed_url(path, signed_days)


def upload_id_scan(user_id: str, file_bytes: bytes, content_type: str) -> str:
    ext      = "pdf" if content_type == "application/pdf" else "jpg"
    filename = f"id_scans/{user_id}/{uuid.uuid4().hex}.{ext}"
    _upload(filename, file_bytes, content_type)
    return _get_signed_url(filename, 365)
