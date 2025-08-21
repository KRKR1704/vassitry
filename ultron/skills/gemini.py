# ultron/skills/gemini.py
import os
from typing import List
from google import genai
from google.genai import types

_API_KEY = os.getenv("GOOGLE_API_KEY")
if not _API_KEY:
    raise RuntimeError("GOOGLE_API_KEY is missing in your environment (.env).")

client = genai.Client(api_key=_API_KEY)

# Fast + supports search grounding
MODEL_NAME = "gemini-2.5-flash"

# Google Search grounding tool
GSEARCH_TOOL = types.Tool(google_search=types.GoogleSearch())

def _extract_sources(resp) -> List[str]:
    """Best-effort: pull a few source URLs from grounding metadata (varies by SDK version)."""
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

        # Fallback older field name
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
    Ask Gemini with Google Search grounding enabled.
    Returns plain text; optionally appends a short 'Sources:' section.
    """
    try:
        config = types.GenerateContentConfig(
            tools=[GSEARCH_TOOL],   # safety settings omitted (optional)
        )

        resp = client.models.generate_content(
            model=MODEL_NAME,
            contents=query,
            config=config,
        )

        text = (getattr(resp, "text", "") or "").strip()
        if not text:
            return "I couldn't find a reliable answer."

        if include_sources:
            srcs = _extract_sources(resp)
            if srcs:
                text += "\n\nSources:\n" + "\n".join(f"- {u}" for u in srcs)

        return text

    except Exception as e:
        return f"Error contacting Gemini: {e}"
