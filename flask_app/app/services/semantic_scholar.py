"""Source discovery — AI-powered query extraction + relevance filtering.

Pipeline:
  1. GPT extracts the best academic search query from the raw topic/instructions.
  2. Semantic Scholar (then CrossRef as fallback) fetches candidates.
  3. GPT scores each candidate for relevance and discards weak matches.
  4. Top results returned, ranked by relevance score.
"""
import os, json, logging, re
import requests

log = logging.getLogger(__name__)

_SS_API     = "https://api.semanticscholar.org/graph/v1/paper/search"
_CR_API     = "https://api.crossref.org/works"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"


# ── OpenAI helper ─────────────────────────────────────────────────────────────

def _gpt(messages: list, max_tokens: int = 800, temperature: float = 0.2) -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.post(
            _OPENAI_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "messages": messages,
                  "temperature": temperature, "max_tokens": max_tokens},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("GPT call failed: %s", e)
        return None


# ── Step 1: AI-powered query extraction ──────────────────────────────────────

def _extract_search_queries(topic: str) -> list[str]:
    """
    Use GPT to turn a raw topic / full instructions string into 2–3
    focused academic search queries. Falls back to the raw topic if GPT
    is unavailable.
    """
    prompt = (
        "You are a research librarian. Given the assignment topic / instructions below, "
        "output exactly 3 concise academic search queries (3–6 words each) that will "
        "find the most relevant peer-reviewed papers.\n\n"
        f"TOPIC / INSTRUCTIONS:\n{topic[:1500]}\n\n"
        "Return ONLY a JSON array of 3 strings, e.g. [\"query one\", \"query two\", \"query three\"]. "
        "No markdown, no extra text."
    )
    raw = _gpt([{"role": "user", "content": prompt}], max_tokens=200)
    if raw:
        try:
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
            queries = json.loads(raw)
            if isinstance(queries, list) and queries:
                return [str(q).strip() for q in queries if q][:3]
        except Exception:
            pass
    # Fallback — take first 100 chars of topic as query
    return [topic[:100]]


# ── Step 2: Fetch from academic APIs ─────────────────────────────────────────

def _ss_fetch(query: str, limit: int, offset: int = 0) -> list:
    params = {
        "query": query, "limit": limit, "offset": offset,
        "fields": "title,abstract,url,authors,year,externalIds",
    }
    r = requests.get(_SS_API, params=params, timeout=20)
    if r.status_code == 429:
        raise RuntimeError("rate-limited")
    r.raise_for_status()
    out = []
    for p in r.json().get("data", []) or []:
        url = p.get("url") or ""
        if not url:
            ext = p.get("externalIds") or {}
            if ext.get("DOI"):
                url = f"https://doi.org/{ext['DOI']}"
        out.append({
            "title":   p.get("title") or "Untitled",
            "summary": (p.get("abstract") or "")[:2000],
            "url":     url,
            "authors": ", ".join(
                (a.get("name") or "") for a in (p.get("authors") or [])[:3]
            ),
            "year": p.get("year"),
        })
    return out


def _cr_fetch(query: str, limit: int, offset: int = 0) -> list:
    params = {
        "query": query, "rows": limit, "offset": offset,
        "select": "title,author,published,URL,abstract",
    }
    r = requests.get(
        _CR_API, params=params, timeout=20,
        headers={"User-Agent": "SmartStudyGuides/1.0 (mailto:support@smartstudyguides.com)"},
    )
    r.raise_for_status()
    items = r.json().get("message", {}).get("items", [])
    out = []
    for p in items:
        title   = (p.get("title") or ["Untitled"])[0]
        authors = ", ".join(
            f"{a.get('given','')} {a.get('family','')}".strip()
            for a in (p.get("author") or [])[:3]
        )
        year_parts = (p.get("published") or {}).get("date-parts", [[None]])
        year       = year_parts[0][0] if year_parts and year_parts[0] else None
        abstract   = re.sub(r"<[^>]+>", "", (p.get("abstract") or "").strip())[:2000]
        out.append({
            "title":   title,
            "summary": abstract,
            "url":     p.get("URL") or "",
            "authors": authors,
            "year":    year,
        })
    return out


def _fetch_candidates(queries: list[str], limit: int) -> list:
    """Try Semantic Scholar with each query, then CrossRef."""
    per_query = max(limit, 6)
    all_results: list = []
    seen_urls:   set  = set()

    for query in queries:
        try:
            results = _ss_fetch(query, per_query)
            for r in results:
                key = r.get("url") or r.get("title", "")
                if key and key not in seen_urls:
                    seen_urls.add(key)
                    all_results.append(r)
            if all_results:
                log.info("Semantic Scholar: %d unique sources via %d queries",
                         len(all_results), len(queries))
                break
        except Exception as e:
            log.warning("Semantic Scholar failed (%s) for query '%s'", e, query[:40])

    if not all_results:
        for query in queries:
            try:
                results = _cr_fetch(query, per_query)
                for r in results:
                    key = r.get("url") or r.get("title", "")
                    if key and key not in seen_urls:
                        seen_urls.add(key)
                        all_results.append(r)
                if all_results:
                    log.info("CrossRef: %d unique sources", len(all_results))
                    break
            except Exception as e:
                log.warning("CrossRef failed (%s) for query '%s'", e, query[:40])

    return all_results


# ── Step 3: AI relevance filtering ───────────────────────────────────────────

def _ai_filter(sources: list, topic: str, need: int) -> list:
    """
    Ask GPT to score each candidate 0–10 for relevance to the topic.
    Returns sources sorted by score, capped at `need`.
    Gracefully skips scoring if GPT is unavailable.
    """
    if not sources:
        return sources

    candidates_json = json.dumps([
        {"idx": i, "title": s["title"], "summary": (s["summary"] or "")[:300]}
        for i, s in enumerate(sources)
    ], ensure_ascii=False)

    prompt = (
        "You are a research relevance evaluator.\n"
        f"ASSIGNMENT TOPIC:\n{topic[:800]}\n\n"
        f"CANDIDATE SOURCES (JSON):\n{candidates_json}\n\n"
        "For each candidate, give a relevance score 0–10 (10 = perfectly on-topic, "
        "0 = completely unrelated). Discard any with score < 5.\n"
        "Return ONLY a JSON array of objects with keys 'idx' and 'score', "
        "sorted highest score first. No markdown."
    )
    raw = _gpt([{"role": "user", "content": prompt}], max_tokens=500)
    if not raw:
        return sources[:need]

    try:
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        scored = json.loads(raw)
        if not isinstance(scored, list):
            return sources[:need]

        result = []
        for item in scored:
            idx   = item.get("idx")
            score = item.get("score", 0)
            if score >= 5 and idx is not None and 0 <= idx < len(sources):
                entry = dict(sources[idx])
                entry["_relevance"] = score
                result.append(entry)

        if result:
            log.info("AI filter: kept %d/%d sources (needed %d)",
                     len(result), len(sources), need)
            return result[:need]
    except Exception as e:
        log.warning("AI relevance filter failed: %s", e)

    return sources[:need]


# ── OpenAI fallback (when APIs return nothing) ────────────────────────────────

def _openai_fallback(topic: str, limit: int) -> list:
    """Ask GPT to generate realistic academic source metadata as a last resort."""
    prompt = (
        f"List {limit} real peer-reviewed academic papers about: {topic[:600]}\n"
        "Return a JSON array where each item has: title, authors, year, url, summary.\n"
        "Use real papers with real DOI URLs. summary is a 1–2 sentence abstract excerpt.\n"
        "Return ONLY the JSON array, no markdown."
    )
    raw = _gpt([{"role": "user", "content": prompt}], max_tokens=1400)
    if not raw:
        return []
    try:
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        sources = json.loads(raw)
        return [
            {
                "title":   str(s.get("title") or "Untitled"),
                "summary": str(s.get("summary") or "")[:2000],
                "url":     str(s.get("url") or ""),
                "authors": str(s.get("authors") or ""),
                "year":    s.get("year"),
            }
            for s in (sources if isinstance(sources, list) else [])
        ][:limit]
    except Exception as e:
        log.warning("OpenAI fallback failed: %s", e)
        return []


# ── Public API ────────────────────────────────────────────────────────────────

def find_sources(topic: str, limit: int = 8, offset: int = 0) -> list:
    """
    Return a list of relevant academic source dicts.

    Workflow:
      1. AI extracts optimised search queries from the topic/instructions.
      2. Semantic Scholar → CrossRef fetches candidates.
      3. AI filters and ranks results for relevance.
      4. Falls back to GPT-generated sources if APIs return nothing.
    """
    # 1 — Generate focused queries
    queries = _extract_search_queries(topic)
    log.info("Extracted search queries: %s", queries)

    # 2 — Fetch candidates (need extra to allow for filtering)
    fetch_limit = max(limit * 3, 15)
    candidates  = _fetch_candidates(queries, fetch_limit)

    if candidates:
        # 3 — Filter for relevance using AI
        filtered = _ai_filter(candidates, topic, limit)
        if filtered:
            return filtered

    # 4 — Last resort: GPT-generated sources
    log.info("All APIs failed or returned nothing — using OpenAI fallback")
    fallback = _openai_fallback(topic, limit)
    return fallback
