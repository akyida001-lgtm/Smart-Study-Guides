"""Ryter Pro API client — AI-content detection only.

Confirmed Ryter API response format (tested 2024):
  Detection: {"success": true, "data": {"ai_score": 0.0–1.0, ...}}
             ai_score is on a 0–1 scale (0=human, 1=AI), NOT 0–100.
"""
import os
import time
import requests

BASE_URL     = "https://api.ryter.pro/api/v1"
_MAX_RETRIES = 3
_RETRY_DELAY = 3   # seconds between attempts

def _headers():
    return {
        "x-api-key": os.environ["RYTER_PRO_API_KEY"],
        "Content-Type": "application/json",
    }


def _post_with_retry(url: str, payload: dict, timeout: int = 90):
    """POST to Ryter with up to _MAX_RETRIES attempts on 5xx / connection errors."""
    last_exc = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            r = requests.post(url, headers=_headers(), json=payload, timeout=timeout)
            if r.status_code < 500:
                r.raise_for_status()
                return r
            last_exc = requests.HTTPError(
                f"{r.status_code} Server Error from Ryter (attempt {attempt})", response=r
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
        if attempt < _MAX_RETRIES:
            time.sleep(_RETRY_DELAY * attempt)
    raise last_exc


def _extract_score(data: dict) -> float:
    """Pull a 0–100 AI score from a Ryter detection response.

    Ryter returns ai_score on a 0–1 scale (confirmed from live API).
    We convert to 0–100 for consistency with the rest of the app.
    """
    raw = None
    # Primary path: data.data.ai_score
    inner = data.get("data")
    if isinstance(inner, dict):
        for key in ("ai_score", "aiScore", "score", "ai_percentage"):
            val = inner.get(key)
            if isinstance(val, (int, float)):
                raw = float(val)
                break
    # Fallback: top-level keys
    if raw is None:
        for key in ("ai_score", "aiScore", "score", "ai_percentage", "ai"):
            val = data.get(key)
            if isinstance(val, (int, float)):
                raw = float(val)
                break
    if raw is None:
        return 0.0
    # Convert 0–1 scale → 0–100. Values > 1 are already on 0–100 scale.
    if raw <= 1.0:
        return round(raw * 100, 1)
    return round(min(raw, 100.0), 1)


def _raw_score_01(data: dict) -> float:
    """Return score on 0–1 scale for internal pass/fail decisions."""
    score_100 = _extract_score(data)
    return score_100 / 100.0


# ── Public API ──────────────────────────────────────────────────────────────────

def detect_ai_score(text: str) -> float:
    """Return AI detection score (0–100). 0 = fully human. Falls back to 15 on error."""
    url = f"{BASE_URL}/ai-tools/execute/ai-content-detector"
    try:
        r    = _post_with_retry(url, {"text": text})
        data = r.json()
        if isinstance(data, dict):
            return _extract_score(data)
        return 0.0
    except Exception:
        return 15.0


def detect_ai_full(text: str) -> dict:
    """
    Run AI detection via Ryter Pro and return the real result.
    Returns aggregate AI score (0–100) and human percentage.
    Raises on API error.
    """
    url = f"{BASE_URL}/ai-tools/execute/ai-content-detector"
    r   = _post_with_retry(url, {"text": text})
    raw = r.json()
    aggregate = _extract_score(raw) if isinstance(raw, dict) else 0.0
    aggregate = round(max(0.0, min(100.0, aggregate)), 1)
    human_pct = round(100.0 - aggregate, 1)
    return {
        "aggregate":    aggregate,
        "human_pct":    human_pct,
        "raw_response": raw,
    }
