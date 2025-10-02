# ultron/skills/gemini.py
import os
from typing import List

# ---- Dependencies ----
# pip install google-genai
try:
    from google import genai
    from google.genai import types
except Exception as e:
    raise ImportError(
        "google-genai package not installed or import failed.\n"
        "Install it with: pip install google-genai\n"
        f"Details: {e}"
    )

# Fast model that supports Google Search grounding (SDK v2)
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Optional: Google Search grounding tool (safe to keep enabled)
GSEARCH_TOOL = types.Tool(google_search=types.GoogleSearch())


def _get_client() -> "genai.Client":
    """
    Lazy-initialize the Gemini client so .env can be loaded BEFORE this is called.
    Looks for GOOGLE_API_KEY first, then GEMINI_API_KEY.
    """
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing GOOGLE_API_KEY (or GEMINI_API_KEY). "
            "Ensure your .env is loaded before calling ask_gemini()."
        )
    return genai.Client(api_key=api_key)


def _extract_sources(resp) -> List[str]:
    """
    Best-effort: pull a few source URLs from grounding metadata.
    Structure can vary by SDK release, so be defensive.
    """
    out, seen = [], set()
    try:
        cands = getattr(resp, "candidates", None) or []
        if not cands:
            return out
        gm = getattr(cands[0], "grounding_metadata", None)
        if not gm:
            return out

        # Newer field
        chunks = getattr(gm, "grounding_chunks", []) or []
        for ch in chunks:
            web = getattr(ch, "web", None)
            if web:
                url = getattr(web, "display_url", None) or getattr(web, "uri", None)
                if url and url not in seen:
                    seen.add(url)
                    out.append(url)

        # Older fallback field
        if not out:
            refs = getattr(gm, "supporting_references", []) or []
            for r in refs:
                url = getattr(r, "uri", None) or getattr(r, "display_url", None)
                if url and url not in seen:
                    seen.add(url)
                    out.append(url)
    except Exception:
        pass
    return out[:3]


def ask_gemini(query: str, include_sources: bool = False) -> str:
    """
    Ask Gemini with optional Google Search grounding.
    Returns plain text; optionally appends a short 'Sources:' section.
    """
    try:
        client = _get_client()
        config = types.GenerateContentConfig(
            tools=[GSEARCH_TOOL],  # comment out if you don't want grounding
        )
        resp = client.models.generate_content(
            model=MODEL_NAME,
            contents=query,
            config=config,
        )

        # Preferred convenience field
        text = (getattr(resp, "text", "") or "").strip()

        # Fallback parse if needed
        if not text:
            try:
                parts = getattr(resp, "candidates", [])[0].content.parts
                text = " ".join(
                    getattr(p, "text", "")
                    for p in parts
                    if getattr(p, "text", "")
                ).strip()
            except Exception:
                text = ""

        if not text:
            text = "I couldn't find a reliable answer."

        if include_sources:
            srcs = _extract_sources(resp)
            if srcs:
                text += "\n\nSources:\n" + "\n".join(f"- {u}" for u in srcs)

        return text

    except Exception as e:
        return f"Error contacting Gemini: {e}"
