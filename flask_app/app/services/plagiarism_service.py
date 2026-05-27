"""Plagiarism detection service using Copyleaks API v3.

Required env vars:
  COPYLEAKS_EMAIL      – the email registered with Copyleaks
  COPYLEAKS_API_KEY    – your Copyleaks API key
"""
import io
import os
import uuid
import base64
import time
import requests

_LOGIN_URL = "https://id.copyleaks.com/v3/account/login/api"
_API_BASE  = "https://api.copyleaks.com"

_POLL_SECONDS = 5
_MAX_POLLS    = 36   # 3 min max for scan


def configured() -> bool:
    return bool(
        os.environ.get("COPYLEAKS_EMAIL") and
        os.environ.get("COPYLEAKS_API_KEY")
    )


def _login() -> str:
    """Return a fresh Bearer token."""
    r = requests.post(
        _LOGIN_URL,
        json={
            "email": os.environ["COPYLEAKS_EMAIL"],
            "key":   os.environ["COPYLEAKS_API_KEY"],
        },
        timeout=30,
    )
    r.raise_for_status()
    data  = r.json()
    token = data.get("access_token") or data.get("token") or ""
    if not token:
        raise RuntimeError(f"Copyleaks login returned no token. Response: {data}")
    return token


def _hdrs(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _webhook_url() -> str:
    domains = os.environ.get("REPLIT_DOMAINS", "localhost")
    base = f"https://{domains.split(',')[0]}"
    return f"{base}/webhooks/copyleaks/noop/{{STATUS}}"


# ── Main scan ──────────────────────────────────────────────────────────────────

def check(text: str) -> dict:
    """
    Submit text to Copyleaks, poll until done, return::

        {
          "similarity": float,
          "words":      int,
          "scan_id":    str,
          "sources": [{"title", "url", "match_pct"}, ...]
        }
    """
    if not configured():
        raise RuntimeError(
            "Copyleaks is not configured. "
            "Set COPYLEAKS_EMAIL and COPYLEAKS_API_KEY."
        )

    scan_id  = str(uuid.uuid4())
    token    = _login()
    hdrs     = _hdrs(token)
    b64_text = base64.b64encode(text.encode("utf-8")).decode()

    # 1 – submit
    r = requests.put(
        f"{_API_BASE}/v3/scans/submit/file/{scan_id}",
        headers=hdrs,
        json={
            "base64":   b64_text,
            "filename": "submission.txt",
            "properties": {
                "webhooks": {"status": _webhook_url()},
                "sensitivity": 1,
                "filters": {
                    "minorChangesEnabled":   True,
                    "relatedMeaningEnabled": True,
                },
            },
        },
        timeout=30,
    )
    r.raise_for_status()

    # 2 – poll result endpoint until data is available
    result_url = f"{_API_BASE}/v3/scans/{scan_id}/result"
    for _ in range(_MAX_POLLS):
        time.sleep(_POLL_SECONDS)
        try:
            rs = requests.get(result_url, headers=hdrs, timeout=30)
            if rs.status_code == 200:
                data = rs.json()
                if data.get("results") is not None:
                    result = _parse(data, text)
                    result["scan_id"] = scan_id
                    return result
        except requests.RequestException:
            pass

    raise RuntimeError(
        "The plagiarism scan is taking longer than expected. "
        "Please try again in a moment."
    )


def _parse(data: dict, text: str) -> dict:
    score_obj  = data.get("results", {}).get("score", {})
    similarity = round(float(score_obj.get("aggregatedScore", 0)), 1)
    words      = len(text.split())

    sources = []
    results = data.get("results", {})
    for section in ("internet", "database", "repositories", "batch"):
        for item in results.get(section, []):
            matched = item.get("matchedWords", 0) or item.get("identicalWords", 0)
            total   = item.get("totalWords", 1) or 1
            match_pct = round((matched / total) * 100, 1)
            if match_pct < 1:
                continue
            sources.append({
                "title":     (item.get("title") or "Untitled source").strip(),
                "url":        item.get("url", ""),
                "match_pct":  match_pct,
            })

    sources.sort(key=lambda s: s["match_pct"], reverse=True)
    return {"similarity": similarity, "words": words, "sources": sources[:25]}


# ── PDF export — falls back to our own PDF if Copyleaks export unavailable ─────

def download_report_pdf(scan_id: str) -> bytes:
    """
    Attempt to download a Copyleaks PDF report.
    Raises RuntimeError if unavailable (caller falls back to our own PDF).
    """
    token   = _login()
    dl_hdrs = {"Authorization": f"Bearer {token}"}
    export_id = str(uuid.uuid4())

    create_body = {
        "completionWebhook": _webhook_url().replace("{STATUS}", "complete"),
        "maxRetries": 1,
        "results": {
            "pdf": {"verb": "generate", "additionalData": ""}
        },
    }

    try:
        ce = requests.post(
            f"{_API_BASE}/v3/{scan_id}/exports/{export_id}/create",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=create_body,
            timeout=30,
        )
        ce.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Copyleaks export creation failed: {exc}") from exc

    for _ in range(20):
        time.sleep(3)
        try:
            es = requests.get(
                f"{_API_BASE}/v3/{scan_id}/exports/{export_id}",
                headers=dl_hdrs, timeout=30,
            )
            if es.status_code == 200:
                st = es.json().get("status", "").lower()
                if st in ("completed", "done"):
                    break
        except requests.RequestException:
            pass

    dl = requests.get(
        f"{_API_BASE}/v3/{scan_id}/exports/{export_id}/download",
        headers=dl_hdrs, timeout=60, stream=True,
    )
    dl.raise_for_status()
    content = dl.content

    import zipfile
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".pdf"):
                    return zf.read(name)

    if b"%PDF" in content[:10]:
        return content

    raise RuntimeError(
        "Could not retrieve the Copyleaks PDF report. "
        "Your account plan may not support direct PDF export."
    )
