import re
from dataclasses import dataclass
from difflib import get_close_matches
from urllib.parse import urlparse

@dataclass
class IntentResult:
    intent: str
    entity: str | None

# --- Website aliases (unchanged/expand as you like) ---
COMMON_MAP = {
    "google": "google.com",
    "gmail": "mail.google.com",
    "youtube": "youtube.com",
    "you tube": "youtube.com",
    "yt": "youtube.com",
    "youtube music": "music.youtube.com",
    "github": "github.com",
    "stack overflow": "stackoverflow.com",
    "stackoverflow": "stackoverflow.com",
    "reddit": "reddit.com",
    "twitter": "x.com",
    "x": "x.com",
    "facebook": "facebook.com",
    "instagram": "instagram.com",
    "netflix": "netflix.com",
    "maps": "maps.google.com",
    "drive": "drive.google.com",
    "docs": "docs.google.com",
}

# --- Browser app aliases (NEW) ---
APP_BROWSER_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "edge",
    "microsoft edge": "edge",
    "firefox": "firefox",
    "mozilla firefox": "firefox",
    "brave": "brave",
    "opera": "opera",
    "default browser": "default",
    "browser": "default",
}

OPEN_TRIGGERS = r"(open|go to|launch|start|navigate to|please open|can you open|open up)"

URL_OR_DOMAIN = re.compile(
    r"(?P<url>(?:https?://)?(?:www\.)?[a-z0-9\-]+(?:\.[a-z0-9\-]+)+(?:/[^\s]*)?)",
    re.IGNORECASE
)

FILLERS = re.compile(r"\b(the|a|an|please|website|site|page|app|application)\b", re.IGNORECASE)

def _normalize(text: str) -> str:
    t = text.lower().strip()
    t = t.replace(" you tube", " youtube")
    t = t.replace(" dot com", ".com")
    t = t.replace(" . com", ".com")
    t = re.sub(r"\s+", " ", t)
    return t

def _alias_lookup(s: str) -> str | None:
    if s in COMMON_MAP:
        return COMMON_MAP[s]
    keys = list(COMMON_MAP.keys())
    match = get_close_matches(s, keys, n=1, cutoff=0.86)
    if match:
        return COMMON_MAP[match[0]]
    return None

def _browser_app_lookup(s: str) -> str | None:
    # exact
    if s in APP_BROWSER_ALIASES:
        return APP_BROWSER_ALIASES[s]
    # try two-word forms (e.g., "google chrome")
    for k, v in APP_BROWSER_ALIASES.items():
        if s == k:
            return v
    # fuzzy-ish
    keys = list(APP_BROWSER_ALIASES.keys())
    m = get_close_matches(s, keys, n=1, cutoff=0.86)
    if m:
        return APP_BROWSER_ALIASES[m[0]]
    return None

def parse_intent(text: str) -> IntentResult:
    if not text:
        return IntentResult("unknown", None)

    t = _normalize(text)

    # 0) Pure app open phrases without explicit "open" (e.g., "chrome")
    if t in APP_BROWSER_ALIASES:
        return IntentResult("open_app", APP_BROWSER_ALIASES[t])

    # 1) If a URL/domain appears anywhere, treat as website
    m = URL_OR_DOMAIN.search(t)
    if m:
        raw = m.group("url").rstrip(".,!?")
        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw
        parsed = urlparse(raw)
        host_or_path = parsed.netloc or parsed.path.lstrip("/")
        if host_or_path:
            site = re.sub(r"^www\.", "", host_or_path)
            alias = _alias_lookup(site)
            site = alias if alias else site
            return IntentResult("open_site", site)

    # 2) Look for "open ... <object>"
    cmd = re.search(rf"{OPEN_TRIGGERS}\s+(?P<object>.+)$", t)
    if cmd:
        obj = cmd.group("object").strip().rstrip(".,!?")
        # Check if they meant a browser app first
        app = _browser_app_lookup(obj)
        if app:
            return IntentResult("open_app", app)

        # Website cleanup
        obj = FILLERS.sub(" ", obj)
        obj = re.sub(r"\s+", " ", obj).strip()

        if "." in obj and re.match(r"^[a-z0-9\-\.]+$", obj):
            obj = re.sub(r"^www\.", "", obj)
            return IntentResult("open_site", obj)

        tokens = obj.split()
        if len(tokens) >= 2:
            two = " ".join(tokens[:2])
            alias = _alias_lookup(two)
            if alias:
                return IntentResult("open_site", alias)

        alias = _alias_lookup(tokens[0])
        if alias:
            return IntentResult("open_site", alias)

        return IntentResult("open_site", obj)

    return IntentResult("unknown", None)
