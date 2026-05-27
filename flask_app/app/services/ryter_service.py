"""Ryter Pro API client. Handles humanization and AI detection.

Confirmed Ryter API response formats (tested 2024):
  Humanize:  {"success": true, "data": {"beautified_text": "...", ...}}
  Detection: {"success": true, "data": {"ai_score": 0.0–1.0, ...}}
             ai_score is on a 0–1 scale (0=human, 1=AI), NOT 0–100.

Best model combos tested (academic text):
  academic + premium  → 0.0 AI  ✓
  academic + pro      → 0.0 AI  ✓
  academic + standard → 0.0 AI  ✓
  academic + advanced → 1.0 AI  ✗  (DO NOT USE as default)
  natural  + premium  → 0.0 AI  ✓
"""
import os
import time
import requests

BASE_URL     = "https://api.ryter.pro/api/v1"
_MAX_RETRIES = 3
_RETRY_DELAY = 3   # seconds between attempts

# Ordered list of (style, model) combos to try. First that passes AI detection wins.
# Tested and confirmed to produce low AI scores.
_HUMANIZE_ATTEMPTS = [
    ("academic", "premium"),
    ("academic", "pro"),
    ("academic", "standard"),
    ("natural",  "premium"),
    ("natural",  "pro"),
]

# If Ryter AI score is above this threshold (0–1 scale), try the next combo.
_SCORE_THRESHOLD = 0.25   # 25% AI — anything below is acceptable


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


def _extract_text_from_response(data) -> str:
    """Pull humanized text from a Ryter response.
    Ryter returns: {"success": true, "data": {"beautified_text": "...", ...}}
    """
    if not isinstance(data, dict):
        return ""
    # Primary path: data.data.beautified_text  (confirmed Ryter format)
    inner = data.get("data")
    if isinstance(inner, dict):
        for key in ("beautified_text", "humanized_text", "text", "output", "result"):
            val = inner.get(key)
            if isinstance(val, str) and val.strip():
                return val
    # Fallback: flat keys
    for key in ("beautified_text", "humanized_text", "output", "result", "text", "humanized"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return ""


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

def humanize(text: str, style: str = "academic", model: str = "premium") -> str:
    """Humanize text using Ryter Pro.

    Tries multiple (style, model) combinations in order and picks the first
    result that passes AI detection (score ≤ 25%).  Falls back to the best
    result seen if all combos fail.

    Raises ValueError if Ryter returns no usable text at all.
    """
    url_humanize = f"{BASE_URL}/ai-tools/execute/text-humanize"
    url_detect   = f"{BASE_URL}/ai-tools/execute/ai-content-detector"

    # If caller passed explicit non-default args, honour them directly (no loop).
    if (style, model) not in [("academic", "premium"), ("academic", "advanced")]:
        r = _post_with_retry(url_humanize, {"text": text, "style": style, "model": model})
        try:
            data = r.json()
        except Exception:
            raise ValueError(f"Ryter returned non-JSON response (status {r.status_code})")
        result = _extract_text_from_response(data)
        if not result:
            raise ValueError("Ryter returned no humanized text.")
        return result

    # Auto-select best combo by trying each in order.
    best_text  = None
    best_score = 1.0   # worst possible (0–1 scale)

    for s, m in _HUMANIZE_ATTEMPTS:
        try:
            r = _post_with_retry(url_humanize, {"text": text, "style": s, "model": m})
            candidate = _extract_text_from_response(r.json())
        except Exception:
            continue
        if not candidate:
            continue

        # Quick AI detection check
        try:
            rd    = _post_with_retry(url_detect, {"text": candidate}, timeout=60)
            score = _raw_score_01(rd.json())
        except Exception:
            score = 0.5   # unknown — treat neutrally

        if best_text is None or score < best_score:
            best_text  = candidate
            best_score = score

        if score <= _SCORE_THRESHOLD:
            break   # good enough — stop trying

    if not best_text:
        raise ValueError("Ryter returned no humanized text across all attempted model combos.")
    return best_text


def humanize_stream(text: str, style: str = "academic", model: str = "premium"):
    """Humanize via Ryter Pro (best-of-combos), then yield in small chunks
    so the browser renders it letter-by-letter.
    Raises on API error — never silently falls back to the original text.
    """
    full = humanize(text, style, model)

    if not full or not full.strip():
        raise ValueError("Ryter returned empty text — please retry.")

    # Yield in ~12-char chunks with a tiny delay so the browser sees live output
    CHUNK = 12
    for i in range(0, len(full), CHUNK):
        yield full[i:i + CHUNK]
        time.sleep(0.018)   # ~55 chars/s — readable live speed


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
