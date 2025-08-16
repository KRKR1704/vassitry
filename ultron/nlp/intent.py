import re
from dataclasses import dataclass
from difflib import get_close_matches
from urllib.parse import urlparse

@dataclass
class IntentResult:
    intent: str          # "open_site" | "open_app" | "unknown"
    entity: str | None   # site domain or app name

# Friendly site aliases (extend as you like)
COMMON_SITES = {
    "google": "google.com",
    "gmail": "mail.google.com",
    "youtube": "youtube.com",
    "you tube": "youtube.com",
    "yt": "youtube.com",
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
    "best buy": "bestbuy.com",
    "open ai": "openai.com",
}

# Common desktop apps (aliases -> canonical token)
APP_ALIASES = {
    # Browsers
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
    # Editors / IDEs
    "notepad": "notepad",
    "wordpad": "wordpad",
    "visual studio code": "vscode",
    "vs code": "vscode",
    "vscode": "vscode",
    "pycharm": "pycharm",
    "visual studio": "visualstudio",
    # Media / chat
    "spotify": "spotify",
    "vlc": "vlc",
    "discord": "discord",
    "slack": "slack",
    "steam": "steam",
    # Utilities
    "calculator": "calc",
    "calc": "calc",
    "paint": "mspaint",
    "snipping tool": "snippingtool",
}

OPEN_TRIGGERS = r"(open|launch|start|run|please open|can you open|open up)"

URL_OR_DOMAIN = re.compile(
    r"(?P<url>(?:https?://)?(?:www\.)?[a-z0-9\-]+(?:\.[a-z0-9\-]+)+(?:/[^\s]*)?)",
    re.IGNORECASE
)

FILLERS = re.compile(r"\b(the|a|an|please|website|site|page|app|application)\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    t = text.lower().strip()
    t = t.replace(" you tube", " youtube")
    t = t.replace(" stack overflow", " stackoverflow")
    t = t.replace(" dot com", ".com")
    t = t.replace(" . com", ".com")
    t = re.sub(r"\s+", " ", t)
    return t


def _site_alias(s: str) -> str | None:
    if s in COMMON_SITES:
        return COMMON_SITES[s]
    keys = list(COMMON_SITES.keys())
    m = get_close_matches(s, keys, n=1, cutoff=0.86)
    if m:
        return COMMON_SITES[m[0]]
    return None


def _app_alias(s: str) -> str | None:
    if s in APP_ALIASES:
        return APP_ALIASES[s]
    keys = list(APP_ALIASES.keys())
    m = get_close_matches(s, keys, n=1, cutoff=0.86)
    if m:
        return APP_ALIASES[m[0]]
    return None


def parse_intent(text: str) -> IntentResult:
    if not text:
        return IntentResult("unknown", None)

    t = _normalize(text)

    # 0) If a URL/domain appears anywhere, treat as open_site
    m = URL_OR_DOMAIN.search(t)
    if m:
        raw = m.group("url").rstrip(".,!?")
        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw
        parsed = urlparse(raw)
        host_or_path = parsed.netloc or parsed.path.lstrip("/")
        if host_or_path:
            site = re.sub(r"^www\.", "", host_or_path)
            alias = _site_alias(site)
            site = alias if alias else site
            return IntentResult("open_site", site)

    # 1) Pure app name without "open" (e.g., "chrome", "notepad")
    app = _app_alias(t)
    if app:
        return IntentResult("open_app", app)

    # 2) "open ..." command
    cmd = re.search(rf"{OPEN_TRIGGERS}\s+(?P<object>.+)$", t)
    if cmd:
        obj = cmd.group("object").strip().rstrip(".,!?")
        # Try app first
        app = _app_alias(obj)
        if app:
            return IntentResult("open_app", app)

        # Else treat as site
        obj = FILLERS.sub(" ", obj)
        obj = re.sub(r"\s+", " ", obj).strip()

        if "." in obj and re.match(r"^[a-z0-9\-\.]+$", obj):
            obj = re.sub(r"^www\.", "", obj)
            return IntentResult("open_site", obj)

        tokens = obj.split()
        if len(tokens) >= 2:
            two = " ".join(tokens[:2])
            alias = _site_alias(two)
            if alias:
                return IntentResult("open_site", alias)

        alias = _site_alias(tokens[0])
        if alias:
            return IntentResult("open_site", alias)

        # fallback: assume it's a site term like "facebook"
        return IntentResult("open_site", obj)

    return IntentResult("unknown", None)
