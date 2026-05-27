import os
import logging
import time as _time
from openai import OpenAI

log = logging.getLogger(__name__)

_client = None        # user's own OpenAI key
_proxy_client = None  # Replit AI proxy (no quota limit)


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


def proxy_client() -> OpenAI | None:
    """Replit AI proxy — used when the user's key is rate-limited or quota-exhausted."""
    global _proxy_client
    if _proxy_client is None:
        base_url = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")
        api_key  = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
        if base_url and api_key:
            _proxy_client = OpenAI(api_key=api_key, base_url=base_url)
    return _proxy_client


def _is_quota_error(err: str) -> bool:
    return "insufficient_quota" in err or "quota" in err.lower()

def _is_rate_error(err: str) -> bool:
    return "429" in err or "rate" in err.lower() or _is_quota_error(err)


def _call(cl: OpenAI, model: str, messages: list, max_tokens: int,
          temperature: float = 0.7, json_mode: bool = False) -> str:
    kwargs = dict(model=model, messages=messages,
                  max_tokens=max_tokens, temperature=temperature)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = cl.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def _chat_with_fallback(messages: list, max_tokens: int,
                        temperature: float = 0.7, json_mode: bool = False) -> str:
    """
    Attempt order:
      1. User key  — gpt-4o
      2. User key  — gpt-4o-mini  (on rate-limit)
      3. Replit proxy — gpt-4o-mini (on quota exhaustion or continued rate-limit)
    """
    # ── Tier 1 & 2: user's own key ─────────────────────────────────────────
    own = client()
    for model in ["gpt-4o", "gpt-4o-mini"]:
        for attempt in range(2):
            try:
                return _call(own, model, messages, max_tokens, temperature, json_mode)
            except Exception as e:
                err = str(e)
                log.warning("OpenAI %s attempt %d failed: %s", model, attempt + 1, err[:120])
                if _is_quota_error(err):
                    log.warning("Quota exhausted — switching to Replit AI proxy")
                    break  # jump straight to proxy, don't retry same model
                if _is_rate_error(err):
                    _time.sleep(3 * (attempt + 1))
                    break  # try next model
                if attempt == 0:
                    _time.sleep(1)

    # ── Tier 3: Replit AI proxy ─────────────────────────────────────────────
    proxy = proxy_client()
    if proxy:
        for model in ["gpt-4o-mini", "gpt-4o"]:
            for attempt in range(2):
                try:
                    log.info("Using Replit AI proxy — model %s", model)
                    return _call(proxy, model, messages, max_tokens, temperature, json_mode)
                except Exception as e:
                    err = str(e)
                    log.warning("Proxy %s attempt %d failed: %s", model, attempt + 1, err[:120])
                    if _is_rate_error(err):
                        _time.sleep(3 * (attempt + 1))
                        break
                    if attempt == 0:
                        _time.sleep(1)

    raise RuntimeError(
        "AI generation temporarily unavailable. "
        "Please try again in a few minutes or top up your OpenAI account."
    )


def chat(prompt: str, max_tokens: int = 8000) -> str:
    """Single-prompt chat completion with automatic quota/rate-limit fallback."""
    return _chat_with_fallback(
        [{"role": "user", "content": prompt}], max_tokens
    )


def chat_with_image(prompt: str, image_url: str, max_tokens: int = 8000) -> str:
    """Generate text using GPT-4o Vision with an image URL (http/https or data URI)."""
    import base64, urllib.request
    # If it's a remote URL, fetch and convert to base64 data URI
    if image_url.startswith("http"):
        try:
            with urllib.request.urlopen(image_url, timeout=15) as r:
                raw = r.read()
            ct  = r.headers.get_content_type() or "image/jpeg"
            b64 = base64.b64encode(raw).decode()
            image_url = f"data:{ct};base64,{b64}"
        except Exception:
            pass  # fall back to URL directly if fetch fails
    messages = [{
        "role": "user",
        "content": [
            {"type": "text",      "text": prompt},
            {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
        ],
    }]
    # Try own key first, then proxy
    for cl in [client(), proxy_client()]:
        if cl is None:
            continue
        try:
            resp = cl.chat.completions.create(
                model="gpt-4o", messages=messages, max_tokens=max_tokens, temperature=0.7
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            if _is_quota_error(str(e)):
                continue
            raise
    raise RuntimeError("AI vision service unavailable — please try again.")


def stream_chat(prompt: str, max_tokens: int = 8000):
    """Generator that yields text tokens as OpenAI streams them.
    Falls back to Replit proxy on quota exhaustion, gpt-4o-mini on rate-limit.
    Raises RuntimeError if all options are exhausted.
    """
    messages = [{"role": "user", "content": prompt}]

    clients_and_models = [
        (client(), ["gpt-4o", "gpt-4o-mini"]),
    ]
    pc = proxy_client()
    if pc:
        clients_and_models.append((pc, ["gpt-4o-mini", "gpt-4o"]))

    last_err = None
    for cl, models in clients_and_models:
        for model in models:
            try:
                stream = cl.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.7,
                    stream=True,
                )
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    token = (delta.content or "") if delta else ""
                    if token:
                        yield token
                return  # success — done
            except Exception as e:
                last_err = e
                err = str(e)
                log.warning("stream_chat %s failed: %s", model, err[:120])
                if _is_quota_error(err):
                    break  # skip remaining models on this client, try proxy
                if _is_rate_error(err):
                    _time.sleep(3)
                    break  # try next model
                raise  # unexpected error — surface immediately

    raise RuntimeError(
        f"AI generation unavailable. Please try again in a moment. ({last_err})"
    )


def mark_paper_with_rubric(paper_text: str, rubric_bytes: bytes,
                           rubric_content_type: str) -> str:
    """Mark a student paper against an uploaded rubric using GPT-4o."""
    import base64
    import io
    from ..prompts import MARKING_PROMPT

    rubric_content = ""

    if rubric_content_type.startswith("image/"):
        b64 = base64.b64encode(rubric_bytes).decode()
        prompt_text = (
            MARKING_PROMPT
            .replace("[RUBRIC_CONTENT]", "(Rubric is provided as an image — see below)")
            .replace("[PAPER_TEXT]", paper_text[:14000])
        )
        # Image rubric — must use vision; try own key then proxy
        for cl in [client(), proxy_client()]:
            if cl is None:
                continue
            try:
                resp = cl.chat.completions.create(
                    model="gpt-4o",
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {"type": "image_url", "image_url": {
                                "url": f"data:{rubric_content_type};base64,{b64}",
                                "detail": "high",
                            }},
                        ],
                    }],
                    max_tokens=2500,
                    temperature=0.2,
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as e:
                if _is_quota_error(str(e)):
                    continue
                raise
        raise RuntimeError("AI service unavailable — please try again.")
    else:
        # PDF — extract text
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(rubric_bytes))
            rubric_content = "\n".join(
                page.extract_text() or "" for page in reader.pages
            )[:8000]
        except Exception:
            rubric_content = "(Could not extract rubric text — PDF may be scanned. Re-upload as an image.)"

        prompt_text = (
            MARKING_PROMPT
            .replace("[RUBRIC_CONTENT]", rubric_content or "(No rubric text found)")
            .replace("[PAPER_TEXT]", paper_text[:14000])
        )
        return _chat_with_fallback(
            [{"role": "user", "content": prompt_text}],
            max_tokens=2500,
            temperature=0.2,
        )


SUPPORT_SYSTEM = """You are a friendly, warm customer support agent for Smart Study Guides — an AI-powered academic assignment writing platform.
Keep replies concise (2–4 sentences max). Be empathetic and helpful.
Topics you can help with: assignment creation, credits, payments, downloads, rubric marking, account issues.
If you cannot resolve an issue tell the student a human agent will assist shortly.
Never mention that you are an AI unless the student directly asks."""


def generate_support_reply(student_name: str, history: list) -> str:
    """Generate an AI support reply given the full conversation history.
    `history` is a list of dicts: [{sender: 'user'|'ai'|'staff', content: str}]
    """
    messages = [
        {"role": "system", "content": SUPPORT_SYSTEM + f"\nStudent name: {student_name}."}
    ]
    for m in history:
        role = "assistant" if m["sender"] in ("ai", "staff") else "user"
        messages.append({"role": role, "content": m["content"]})
    return _chat_with_fallback(messages, max_tokens=220).strip()


def generate_source_annotations(sources: list, topic: str,
                                style: str = "APA", level: str = "Undergraduate") -> list:
    """For each source dict generate: topic, apa_intext, apa_reference, annotation (200w paragraph).
    Returns a list of dicts in the same order as `sources`.
    """
    import json as _json

    source_blocks = []
    for i, s in enumerate(sources, 1):
        source_blocks.append(
            f"SOURCE {i}:\n"
            f"  Title  : {s.get('title') or 'Unknown'}\n"
            f"  Authors: {s.get('authors') or 'Unknown'}\n"
            f"  Year   : {s.get('year') or 'n.d.'}\n"
            f"  URL    : {s.get('url') or 'N/A'}\n"
            f"  Abstract (excerpt): {(s.get('summary') or 'Not available')[:800]}"
        )

    # Style-specific citation guidance
    style_guides = {
        "APA":     "APA 7th edition",
        "MLA":     "MLA 9th edition",
        "Chicago": "Chicago 17th edition (Author-Date)",
        "Harvard": "Harvard referencing style",
    }
    cite_style = style_guides.get(style, style or "APA 7th edition")

    prompt = f"""You are an expert academic writer. For each source below, generate annotation data for a {level}-level assignment on: "{topic}". Use {cite_style} for all citations and references.

{chr(10).join(source_blocks)}

For EACH source return a JSON object with exactly these keys:
- "topic"     : A concise title/focus of the article (1–2 sentences, not a full sentence starting with "This article").
- "intext"    : In-text citation formatted in {cite_style}, exactly as it would appear inside a paragraph.
- "reference" : Full {cite_style} reference entry. Include the accurate URL or DOI at the end. Ensure the URL fits on one line with no line breaks.
- "paragraph" : Exactly ~200-word formal academic paragraph. Rules:
    • Presentational and formal tone — explain what the article PRESENTS, argues, and emphasises.
    • Cover: core argument/purpose, main ideas/themes/evidence, perspective/position, key contributions.
    • Do NOT write a summary or critique.
    • Do NOT start with "This article...", "This paper...", or "The article...".
    • Use formal academic language appropriate for {level} level.

Return ONLY a valid JSON array of {len(sources)} objects in source order. No markdown, no extra text."""

    # Use plain text mode — json_object response_format is not supported by
    # all proxy endpoints and causes silent failures when falling back.
    raw = _chat_with_fallback(
        [{"role": "user", "content": prompt}],
        max_tokens=420 * len(sources),
        temperature=0.4,
        json_mode=False,
    ).strip()

    # Strip markdown code fences GPT sometimes adds: ```json ... ```
    import re as _re
    fence_match = _re.match(r"^```[a-z]*\n([\s\S]*?)```\s*$", raw, _re.MULTILINE)
    clean = fence_match.group(1).strip() if fence_match else raw.strip()

    parsed = _json.loads(clean)

    # Normalise to a list regardless of how GPT wrapped the data
    annotation_keys = {"intext", "reference", "paragraph", "topic"}
    if isinstance(parsed, list):
        return parsed
    # Wrapped in an object with a list value: {"sources": [...]}
    for v in parsed.values():
        if isinstance(v, list):
            return v
    # Single annotation returned as a plain object (1-source edge case)
    if annotation_keys & set(parsed.keys()):
        return [parsed]
    # Numbered keys: {"1": {…}, "2": {…}}
    candidate = [v for v in parsed.values() if isinstance(v, dict)]
    if candidate:
        return candidate
    return []


def format_source_with_ai(title: str, authors: str, year, url: str, abstract: str,
                          citation_style: str = "APA") -> str:
    """Format a real Semantic Scholar source into the required academic structure."""
    from ..prompts import PER_SOURCE_PROMPT
    prompt = (
        PER_SOURCE_PROMPT
        .replace("[CITATION_STYLE]", citation_style or "APA")
        .replace("[TITLE]", title or "Unknown title")
        .replace("[AUTHORS]", authors or "Unknown authors")
        .replace("[YEAR]", str(year) if year else "n.d.")
        .replace("[URL]", url or "URL not available")
        .replace("[ABSTRACT]", (abstract or "No abstract available.")[:3000])
    )
    return chat(prompt, max_tokens=900)
