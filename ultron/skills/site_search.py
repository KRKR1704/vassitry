# ultron/skills/site_search.py
from __future__ import annotations

"""
Generic site-search helper for Ultron.

Usage in main.py (already wired):
    ok, url = site_search.open_site_search(
        open_url, site, query, browser_pref=BROWSER,
        prefer_direct=True, probe=False
    )

Behavior:
- If `site` is None → Google search for the query.
- If `site` is given → try a site-specific search URL if known (e.g., BestBuy, Amazon, YouTube),
  else fall back to common patterns (/search?q=, ?s=, etc.).
- If those fail or `prefer_direct=False` → Google "site:<host> <query>".
- Optional `probe=True` (requires requests) will HEAD/GET candidates to pick the first working one.
"""

import re
from typing import Iterable
from urllib.parse import urlparse, quote_plus

try:
    import requests  # optional; only used if probe=True
except Exception:
    requests = None


# Known, reliable search paths for popular sites.
# These are tried BEFORE generic patterns if the host matches (suffix match).
SITE_SEARCH_TEMPLATES = {
    # Retail / marketplaces
    "bestbuy.com": "https://www.bestbuy.com/site/searchpage.jsp?st={q}",
    "amazon.com": "https://www.amazon.com/s?k={q}",
    "walmart.com": "https://www.walmart.com/search?q={q}",
    "ebay.com": "https://www.ebay.com/sch/i.html?_nkw={q}",

    # Video / social / community
    "youtube.com": "https://www.youtube.com/results?search_query={q}",
    "youtu.be": "https://www.youtube.com/results?search_query={q}",
    "x.com": "https://x.com/search?q={q}&src=typed_query",
    "twitter.com": "https://x.com/search?q={q}&src=typed_query",
    "reddit.com": "https://www.reddit.com/search/?q={q}",
    "tiktok.com": "https://www.tiktok.com/search?q={q}",
    "instagram.com": "https://www.instagram.com/explore/search/keyword/?q={q}",

    # Code / docs / knowledge
    "github.com": "https://github.com/search?q={q}",
    "gitlab.com": "https://gitlab.com/search?search={q}",
    "wikipedia.org": "https://en.wikipedia.org/w/index.php?search={q}",
    "medium.com": "https://medium.com/search?q={q}",
    "stackexchange.com": "https://stackexchange.com/search?q={q}",
    "stackoverflow.com": "https://stackoverflow.com/search?q={q}",

    # Fallback for Google Docs/Sheets links (no native full-site search UI)
    "docs.google.com": "https://www.google.com/search?q=site%3A{host}+{q}",
}


def _canonical_host(site: str) -> tuple[str, str | None]:
    """
    Normalize input like "bestbuy", "www.bestbuy.com", "https://bestbuy.com"
    to a (host, path) pair. Also canonicalizes twitter -> x.com.
    """
    s = (site or "").strip()
    if not s:
        return "", None

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", s):
        s = "https://" + s
    p = urlparse(s)

    host = (p.netloc or "").lower()
    host = re.sub(r"^www\.", "", host)
    path = p.path or None

    # twitter -> x
    if host in ("twitter.com", "mobile.twitter.com", "www.twitter.com"):
        host = "x.com"
    return host, path


def _sanitize_query(q: str) -> str:
    """
    Keep it simple: trim and collapse whitespace. We do not try to 'fix' numbers
    (to avoid over-correcting speech-to-text). If ASR mangles "4070" -> "47070",
    it should be fixed at the ASR layer, or by quoting/spelling out digits.
    """
    q = (q or "").strip()
    q = re.sub(r"\s+", " ", q)
    return q


def _candidate_search_urls(host: str, query: str) -> Iterable[str]:
    """
    Generate candidate search URLs:
    1) A site-specific template (if known)
    2) A set of generic patterns
    """
    q = quote_plus(query)

    # First: site-specific template if we have one (suffix match)
    for key, tpl in SITE_SEARCH_TEMPLATES.items():
        if host == key or host.endswith("." + key):
            url = tpl.format(q=q, host=host)
            yield url
            break  # only use the first matching template

    # Generic patterns as fallbacks
    patterns = [
        f"https://{host}/search?q={q}",
        f"https://{host}/?s={q}",
        f"https://{host}/?q={q}",
        f"https://{host}/search/{q}",
        f"http://{host}/search?q={q}",
        f"http://{host}/?s={q}",
        f"http://{host}/?q={q}",
        f"http://{host}/search/{q}",
    ]
    for url in patterns:
        yield url


def _looks_like_result(url: str, status: int, final_url: str | None, content_snippet: str | None) -> bool:
    """
    Heuristic to decide if a probed URL likely shows a results page.
    """
    if status not in (200, 301, 302, 303):
        return False

    # If we got redirected to the bare homepage with no query, it's probably a dud.
    if final_url:
        parsed = urlparse(final_url)
        if parsed.path in ("", "/") and not parsed.query:
            return False

    if content_snippet:
        snippet = content_snippet.lower()
        if any(w in snippet for w in ("search", "results", "result", "query", "found", "showing")):
            return True

    return True


def _probe_first_working(candidates: Iterable[str], timeout: float = 2.0) -> str | None:
    """
    Optionally send HEAD/GET requests (fast) to choose the best candidate.
    Requires 'requests'. If unavailable, returns None.
    """
    if requests is None:
        return None

    headers = {"User-Agent": "UltronSiteSearch/1.0"}
    for url in candidates:
        try:
            r = requests.head(url, allow_redirects=True, timeout=timeout, headers=headers)
            if _looks_like_result(url, r.status_code, getattr(r, "url", None), None):
                return getattr(r, "url", url)

            r = requests.get(url, allow_redirects=True, timeout=timeout, headers=headers)
            snippet = r.text[:2048] if isinstance(r.text, str) else None
            if _looks_like_result(url, r.status_code, getattr(r, "url", None), snippet):
                return getattr(r, "url", url)
        except Exception:
            # swallow and try next candidate
            pass

    return None


def build_site_search_url(
    site: str | None,
    query: str | None,
    *,
    prefer_direct: bool = True,
    probe: bool = False,
) -> str:
    """
    Build the best-guess URL to perform a site search.

    - If site is None: Google search for the query.
    - If site is given:
        - If prefer_direct=True and query provided:
            - Try site-specific template (if known) then generic patterns.
            - If probe=True and 'requests' present, pick the first working candidate.
        - Else fall back to Google site: search.
    """
    q_raw = (query or "")
    q = _sanitize_query(q_raw)

    # No site and no query -> just open Google
    if not site and not q:
        return "https://www.google.com"

    # No site -> generic Google search
    if not site:
        return f"https://www.google.com/search?q={quote_plus(q)}" if q else "https://www.google.com"

    # Normalize site -> host
    host, _ = _canonical_host(site)
    if not host:
        return f"https://www.google.com/search?q={quote_plus(q)}" if q else "https://www.google.com"

    # Prefer direct on-site search if we have a query
    if prefer_direct and q:
        candidates = list(_candidate_search_urls(host, q))
        if probe:
            found = _probe_first_working(candidates)
            return found or candidates[0]
        return candidates[0]

    # Fallback: Google site: search
    return (
        f"https://www.google.com/search?q=site%3A{quote_plus(host)}+{quote_plus(q)}"
        if q else f"https://{host}"
    )


def open_site_search(
    open_url_func,
    site: str | None,
    query: str | None,
    *,
    browser_pref: str | None = None,
    prefer_direct: bool = True,
    probe: bool = False,
) -> tuple[bool, str]:
    """
    Build and open the search URL using your existing open_url() skill.
    Returns (ok, final_url).
    """
    url = build_site_search_url(site, query, prefer_direct=prefer_direct, probe=probe)
    # Helpful debug prints; comment out if too chatty:
    print(f"[Ultron][SiteSearch] site={site!r} query={query!r} -> {url}")

    try:
        ok = open_url_func(url, browser_pref=browser_pref)
    except TypeError:
        # older open_url signature without browser_pref
        ok = open_url_func(url)

    return ok, url
