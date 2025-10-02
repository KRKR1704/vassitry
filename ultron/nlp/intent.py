import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from urllib.parse import urlparse

@dataclass
class IntentResult:
    intent: str                # e.g., "open_site", "open_app", "wifi_on", "unknown", etc.
    entity: str | None         # site/app/target string or None
    name: str | None = None    # optional extra name (e.g., device name)
    slots: dict = field(default_factory=dict)  # optional slots for extra data

# --- Website aliases (spoken names -> canonical targets) ---
# NOTE: "whatsapp" is mapped to a special token for the DESKTOP app.
# If you prefer web, change "app:whatsapp" to "web.whatsapp.com".
COMMON_MAP = {
    "google": "google.com",
    "gmail": "mail.google.com",
    "youtube": "youtube.com",
    "you tube": "youtube.com",
    "chatgpt": "chat.openai.com",
    "linkedin": "linkedin.com",
    "outlook": "outlook.live.com",
    "whatsapp": "app:whatsapp",  # desktop app preference
    "canvas": "canvas.ubuffalo.edu",
    "ublearns": "ublearns.buffalo.edu",
    "reddit": "reddit.com",
    "twitter": "x.com",
    "x": "x.com",
    "stackoverflow": "stackoverflow.com",
    "stack overflow": "stackoverflow.com",
}

# --- Browser/app aliases (spoken names -> app id) ---
APP_BROWSER_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "firefox": "firefox",
    "mozilla": "firefox",
    "brave": "brave",
    "opera": "opera",
}

URL_OR_DOMAIN = re.compile(
    r"(?P<url>(?:https?://)?(?:www\.)?[a-z0-9][a-z0-9\-\.]+\.[a-z]{2,}(?:/[^\s]*)?)",
    re.I
)

# ===== Helpers =====
def _normalize(s: str) -> str:
    t = (s or "").strip()
    t = re.sub(r"[\u2018\u2019]", "'", t)
    t = re.sub(r"[\u201c\u201d]", '"', t)
    t = re.sub(r"[\u2013\u2014]", "-", t)
    t = re.sub(r"\s+", " ", t)
    return t

def _has(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.I) is not None

def _extract_quoted(s: str) -> str | None:
    m = re.search(r'"([^"]+)"', s)
    if m: return m.group(1).strip()
    m = re.search(r"'([^']+)'", s)
    if m: return m.group(1).strip()
    return None

def _extract_after_preposition(s: str) -> str | None:
    m = re.search(r"\b(?:to|into|as|on|onto|at)\s+(.+)$", s, re.I)
    return m.group(1).strip() if m else None

def _extract_first_int(s: str) -> int | None:
    m = re.search(r"\b(\d{1,3})\b", s)
    if not m: return None
    v = max(0, min(100, int(m.group(1))))
    return v

def _alias_lookup(s: str) -> str | None:
    if s in COMMON_MAP: return COMMON_MAP[s]
    match = get_close_matches(s, list(COMMON_MAP.keys()), n=1, cutoff=0.86)
    return COMMON_MAP[match[0]] if match else None

def _browser_app_lookup(s: str) -> str | None:
    if s in APP_BROWSER_ALIASES: return APP_BROWSER_ALIASES[s]
    match = get_close_matches(s, list(APP_BROWSER_ALIASES.keys()), n=1, cutoff=0.86)
    return APP_BROWSER_ALIASES[match[0]] if match else None

def _canonical_device_hint(s: str) -> str | None:
    s = (s or "").strip().lower()
    if not s: return None
    if re.search(r"\b(headset|headphones|buds|airpods)\b", s): return "headphones"
    if re.search(r"\b(speaker|speakers)\b", s): return "speakers"
    if re.search(r"\b(tv|monitor|display)\b", s): return "tv"
    return s

# --- Domain canonicalization (domain -> canonical domain or special token) ---
_DOMAIN_CANON = {
    # Twitter -> X
    "twitter.com": "x.com",
    "www.twitter.com": "x.com",
    "mobile.twitter.com": "x.com",

    # WhatsApp: generic domain -> desktop app token (handled by opener)
    "whatsapp.com": "app:whatsapp",
    "www.whatsapp.com": "app:whatsapp",

    # Keep explicit web.whatsapp.com as web
    "web.whatsapp.com": "web.whatsapp.com",
}

def _site_alias(key: str) -> str | None:
    """
    Map a domain-ish key or a common-name key to a canonical target.
    Returns a domain (e.g., 'x.com'), a full URL, a special token like 'app:whatsapp',
    or None if no mapping applies.
    """
    if not key:
        return None
    k = key.strip().lower()
    k = re.sub(r"^www\.", "", k)

    # 1) Domain-level canonicalization
    if k in _DOMAIN_CANON:
        return _DOMAIN_CANON[k]

    # 2) Common-name aliasing
    if k in COMMON_MAP:
        return COMMON_MAP[k]

    return None

def _normalize_url_or_domain(raw: str) -> str:
    """
    Preserve path/query/fragment, normalize host, and apply domain canonicalization.
    If the result is a special app token (e.g., 'app:whatsapp'), return that token.
    """
    val = raw.strip().rstrip(".,!?")
    url = val if re.match(r"^https?://", val, re.I) else f"https://{val}"
    p = urlparse(url)

    host = p.netloc.lower()
    host = re.sub(r"^www\.", "", host)

    mapped = _site_alias(host)
    if mapped and mapped.startswith("app:"):
        return mapped
    if mapped and re.search(r"\.[a-z]{2,}$", mapped):
        host = mapped

    path = p.path or ""
    qs = f"?{p.query}" if p.query else ""
    frag = f"#{p.fragment}" if p.fragment else ""
    return f"https://{host}{path}{qs}{frag}" if host else val

# ===== Weather helpers =====
_WEATHER_PATTERNS = [
    # "weather", "temperature", "forecast" optionally followed by "in <city>"
    re.compile(r"\b(weather|temperature|forecast)\b(?:\s+(?:for|in|at)\s+(?P<city>.+))?", re.I),
    # "how's the weather in <city>"
    re.compile(r"\bhow\s*(?:is|’s|s)\s*the\s*weather(?:\s+(?:for|in|at)\s+(?P<city>.+))?", re.I),
    # direct requests like "tell me weather in <city>"
    re.compile(r"\b(tell|say)\s+(?:me\s+)?(?:about\s+)?(?:the\s+)?weather(?:\s+(?:for|in|at)\s+(?P<city>.+))?", re.I),
]

def _detect_when(text: str) -> str:
    tl = text.lower()
    if "yesterday" in tl: return "yesterday"
    if "tomorrow" in tl:  return "tomorrow"
    if "now" in tl or "right now" in tl or "currently" in tl: return "now"
    if re.search(r"\btoday\b", tl): return "today"
    return "today"

def _extract_city(text: str) -> str | None:
    # priority to quoted city
    q = _extract_quoted(text)
    if q: return q.strip()

    # after prepositions like "in/at/for"
    m = re.search(r"\b(?:in|at|for)\s+([A-Za-z0-9 ,.'\-]+)$", text, re.I)
    if m:
        return m.group(1).strip(" .!?")
    return None

# ===== Site-search helpers =====
def _extract_site_and_query(text: str) -> tuple[str | None, str | None]:
    """
    Handles:
      - search <query> on <site>
      - search <site> for <query>
      - find <query> in <site>
      - open <site> and search/find <query>
      - search for "<query>" on <site>
      - search "<query>"  (no site)
    Returns (site, query) where either can be None.
    """
    s = _normalize(text)
    quoted = _extract_quoted(s)

    patterns = [
        r"(?:^|\b)(?:search|find)\s+(?P<q>.+?)\s+(?:on|in)\s+(?P<site>[^\s,]+)\b",
        r"(?:^|\b)(?:search|find)\s+(?P<site>[^\s,]+)\s+(?:for|about)\s+(?P<q>.+)$",
        r"(?:^|\b)(?:open|visit|go to)\s+(?P<site>[^\s,]+).*?(?:search|find)\s+(?:for\s+)?(?P<q>.+)$",
    ]
    for pat in patterns:
        m = re.search(pat, s, re.I)
        if m:
            site = (m.group("site") or "").strip(" .,'\"")
            q = quoted or (m.group("q") or "").strip(" .,'\"")
            return (site or None), (q or None)

    m = re.search(r"(?:^|\b)search(?:\s+for)?\s+(.+)$", s, re.I)
    if m:
        q = quoted or m.group(1).strip(" .,'\"")
        return None, (q or None)

    m = re.search(r"(?:^|\b)find\s+(.+)$", s, re.I)
    if m:
        q = quoted or m.group(1).strip(" .,'\"")
        return None, (q or None)

    return None, None

# ===== Calendar intent cues =====
_CAL_VERBS = r"(create|schedule|add|make|put|set)"
_CAL_OBJECTS = r"(event|meeting|appointment|calendar|reminder)"
# date/time cues: am/pm time, relative words, weekdays, or month names
_CAL_TIME = r"\bat\s+\d{1,2}(:\d{2})?\s*(am|pm)\b"
_CAL_REL = r"\b(today|tomorrow|tonight|this\s+\w+|next\s+\w+)\b"
_CAL_ON_DAY = r"\bon\s+(mon|tue|tues|weds|wed|thu|thur|thurs|fri|sat|saturday|sun|sunday)\b"
_CAL_MONTH = r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"

def parse_intent(text: str) -> IntentResult:
    if not text:
        return IntentResult("unknown", None)

    t = _normalize(text)
    s = " ".join(t.split())
    tl = t.lower()

    # 0) Pure app name ("chrome") without "open"
    app = _browser_app_lookup(tl)
    if app:
        return IntentResult("open_app", app)

    # ===== CALENDAR: create event =====
    # Strong signal: verb + explicit object word
    if _has(tl, rf"\b{_CAL_VERBS}\b") and _has(tl, rf"\b{_CAL_OBJECTS}\b"):
        return IntentResult("calendar.create", t)

    # Also allow: add/put .. to/into calendar
    if _has(tl, r"\b(add|put)\b") and _has(tl, r"\b(to|into)\s+calendar\b"):
        return IntentResult("calendar.create", t)

    # Soft signal: scheduling verb + clear date/time cue
    if _has(tl, rf"\b{_CAL_VERBS}\b") and (
        _has(tl, _CAL_TIME) or _has(tl, _CAL_REL) or _has(tl, _CAL_ON_DAY) or _has(tl, _CAL_MONTH)
    ):
        return IntentResult("calendar.create", t)

    # ===== Connectivity (Wi-Fi) — must be BEFORE power =====
    if _has(s, r"\b(wi[-\s]?fi|wifi|wireless|wlan)\b"):
        if _has(s, r"\b(status|connected|which\s+(?:network|wi[-\s]?fi)|what(?:'s| is)\s+(?:my\s+)?wi[-\s]?fi)\b"):
            return IntentResult("wifi_status", None)
        if _has(s, r"\b(turn\s*on|enable|switch\s*on|activate)\b"):
            return IntentResult("wifi_on", None)
        if _has(s, r"\b(turn\s*off|disable|switch\s*off|deactivate)\b"):
            return IntentResult("wifi_off", None)
        if _has(s, r"\b(disconnect)\b"):
            return IntentResult("wifi_disconnect", None)
        quoted = _extract_quoted(s)
        if quoted:
            return IntentResult("wifi_connect", quoted)
        m = re.search(r"\b(?:connect|join)\s+(?:to\s+)?(?:network\s+)?([^\.,;]+)$", s, re.I)
        if m:
            return IntentResult("wifi_connect", m.group(1).strip())

    # ===== Display projection =====
    if _has(s, r"\b(extend|duplicate|mirror|second\s+screen\s+only|pc\s+screen\s+only|project|projection)\b"):
        if _has(s, r"\b(extend|extended)\b"):               return IntentResult("display_mode", "extend")
        if _has(s, r"\b(duplicate|mirror|clone)\b"):        return IntentResult("display_mode", "clone")
        if _has(s, r"\b(second\s+screen\s+only|external|projector|monitor\s+only)\b"):
            return IntentResult("display_mode", "external")
        if _has(s, r"\b(pc\s+screen\s+only|internal|laptop\s+screen|this\s+screen|computer\s+screen)\b"):
            return IntentResult("display_mode", "internal")

    # ===== Volume =====
    if _has(s, r"\b(volume|sound)\b"):
        if _has(s, r"\b(mute)\b"):      return IntentResult("volume_mute", None)
        if _has(s, r"\b(unmute)\b"):    return IntentResult("volume_unmute", None)

        n = _extract_first_int(s)
        if _has(s, r"\bto\s+\d{1,3}\b") and n is not None:
            return IntentResult("volume_set", str(n))
        if _has(s, r"\b(set|change|adjust)\b") and n is not None:
            return IntentResult("volume_set", str(n))
        if re.fullmatch(r".*\bvolume\s+\d{1,3}\b.*", s, re.I) and n is not None:
            return IntentResult("volume_set", str(n))

        if _has(s, r"\b(increase|raise|turn\s*up)\b"):
            m = re.search(r"\bby\s+(\d{1,3})\b", s, re.I)
            return IntentResult("volume_up", m.group(1) if m else None)
        if _has(s, r"\b(decrease|lower|reduce|turn\s*down)\b"):
            m = re.search(r"\bby\s+(\d{1,3})\b", s, re.I)
            return IntentResult("volume_down", m.group(1) if m else None)
        if _has(s, r"\bvolume\s+up\b"):   return IntentResult("volume_up", None)
        if _has(s, r"\bvolume\s+down\b"): return IntentResult("volume_down", None)

    # ===== Brightness =====
    if _has(s, r"\b(bright|brightness|screen)\b"):
        n = _extract_first_int(s)
        if _has(s, r"\bto\s+\d{1,3}\b") and _has(s, r"\bbright") and n is not None:
            return IntentResult("brightness_set", str(n))
        if _has(s, r"\b(set|change|adjust)\s+(?:the\s+)?brightness\b") and n is not None:
            return IntentResult("brightness_set", str(n))
        if re.fullmatch(r".*\bbrightness\s+\d{1,3}\b.*", s, re.I) and n is not None:
            return IntentResult("brightness_set", str(n))

        if _has(s, r"\b(increase|raise|brighten|turn\s*up)\b"):
            m = re.search(r"\bby\s+(\d{1,3})\b", s, re.I)
            return IntentResult("brightness_up", m.group(1) if m else None)
        if _has(s, r"\b(decrease|lower|reduce|dim|turn\s*down)\b"):
            m = re.search(r"\bby\s+(\d{1,3})\b", s, re.I)
            return IntentResult("brightness_down", m.group(1) if m else None)
        if _has(s, r"\b(make\s+(it\s+)?brighter)\b"): return IntentResult("brightness_up", None)
        if _has(s, r"\b(make\s+(it\s+)?darker)\b"):   return IntentResult("brightness_down", None)

    # Night light
    if _has(s, r"\b(night\s*light|blue\s*light\s*filter)\b"):
        if _has(s, r"\b(toggle|switch)\b"):                 return IntentResult("night_light_toggle", None)
        if _has(s, r"\bturn\s*on|enable|activate\b"):       return IntentResult("night_light_on", None)
        if _has(s, r"\bturn\s*off|disable|deactivate\b"):   return IntentResult("night_light_off", None)
        return IntentResult("night_light_toggle", None)

    # ===== Window controls =====
    if _has(s, r"\b(minimi[sz]e|shrink)\b") and _has(s, r"\b(window|this)\b"):
        return IntentResult("window_minimize", None)
    if _has(s, r"\b(maximi[sz]e|make.*full\s*screen|larger)\b") and _has(s, r"\b(window|this)\b"):
        return IntentResult("window_maximize", None)
    if _has(s, r"\b(close|exit)\b") and _has(s, r"\b(window|this)\b"):
        return IntentResult("window_close", None)

    # ===== Screenshot =====
    if _has(s, r"\b(screenshot|capture\s+(?:the\s+)?screen|take\s+(?:a\s+)?screenshot)\b"):
        return IntentResult("screenshot", None)

    # ===== Battery =====
    if _has(s, r"\b(battery|charge)\b") and _has(s, r"\b(level|percent|percentage|how\s+much)\b"):
        return IntentResult("battery_query", None)

    # ===== Power =====
    if _has(tl, r"\b(hibernate)\b"): return IntentResult("power_sleep", None)
    if _has(tl, r"\b(put\s+(?:the\s+)?(?:pc|computer|system)\s+to\s+sleep|go\s+to\s+sleep|sleep\s+now|^sleep$)\b"):
        return IntentResult("power_sleep", None)
    if re.search(r"\b(shut\s*down|power\s*off|turn\s*off)\b(?!.*\b(wi-?fi|wifi|wireless|wlan)\b)", tl, re.I):
        return IntentResult("power_shutdown", None)
    if _has(tl, r"\b(restart|reboot)\b"): return IntentResult("power_restart", None)
    if _has(tl, r"\b(lock|lock\s+(?:the\s+)?(?:pc|computer|screen))\b"):
        return IntentResult("power_lock", None)

    # ===== WEATHER =====
    for pat in _WEATHER_PATTERNS:
        m = pat.search(s)
        if m:
            city = m.groupdict().get("city") or _extract_city(s)
            when = _detect_when(s)

            # --- sanitize city: strip artifacts and ignore time words ---
            if city:
                city = city.strip(" ?.,'\"")
                city = re.sub(r"^\s*'?s\s+", "", city, flags=re.I)
                if re.search(r"\b(today|tomorrow|yesterday|now)\b", city, re.I):
                    city = None

            return IntentResult("weather.get", None, slots={"city": city, "when": when})

    # ===== Site search (generic) =====
    if _has(s, r"\b(search|find)\b"):
        site, query = _extract_site_and_query(s)
        if site or query:
            site_mapped = None
            if site:
                raw = site.strip().lower()
                mapped = _site_alias(raw) or _alias_lookup(raw)
                site_mapped = mapped if (mapped and not str(mapped).startswith("app:")) else site
            return IntentResult("site.search", None, slots={"site": site_mapped or site, "query": query})

    # ===== URL/domain anywhere → open_site (preserve path/query/fragment) =====
    m = URL_OR_DOMAIN.search(t)
    if m:
        raw = m.group("url")
        target = _normalize_url_or_domain(raw)
        return IntentResult("open_site", target)

    # ===== Audio output devices =====
    if _has(s, r"\b(list|show|what(?:'s| is)|available|enumerate|display)\b") and _has(s, r"\b(audio|sound|output|device|speaker|speakers|playback)\b"):
        return IntentResult("audio_list_outputs", None)
    if _has(s, r"\b(outputs|playback devices|audio devices|speakers)\b") and _has(s, r"\b(list|show|available)\b"):
        return IntentResult("audio_list_outputs", None)

    if (_has(s, r"\b(set|switch|change|make|use|route|default)\b") and _has(s, r"\b(audio|sound|output|device|speaker|speakers|playback)\b")) or _has(s, r"\b(default output)\b"):
        target = _extract_quoted(s) or _extract_after_preposition(s)
        if target:
            return IntentResult("audio_switch_output", _canonical_device_hint(target))
        if _has(s, r"\b(headphones|headset|buds|airpods)\b"): return IntentResult("audio_switch_output", "headphones")
        if _has(s, r"\b(speaker|speakers)\b"):                return IntentResult("audio_switch_output", "speakers")
        if _has(s, r"\b(tv|monitor|display)\b"):              return IntentResult("audio_switch_output", "tv")

    # ===== Open app/site by name =====
    if _has(s, r"\b(open|launch|start|go to|goto|visit)\b"):
        obj = _extract_quoted(s) or re.sub(r"\b(open|launch|start|go to|goto|visit)\b", "", s, flags=re.I).strip()
        obj = re.sub(r"^(the|a|an)\s+", "", obj, flags=re.I).strip()

        # Browser app?
        app = _browser_app_lookup(obj.lower())
        if app:
            return IntentResult("open_app", app)

        # Known alias (common name)
        alias = _alias_lookup(obj.lower())
        if alias:
            if alias.startswith("app:"):
                return IntentResult("open_site", alias)
            return IntentResult("open_site", _normalize_url_or_domain(alias))

        # Explicit URL or domain in the object
        m = URL_OR_DOMAIN.search(obj)
        if m:
            raw = m.group("url")
            return IntentResult("open_site", _normalize_url_or_domain(raw))

        # Domain canonicalization on raw token (e.g., "whatsapp", "twitter")
        mapped = _site_alias(obj)
        if mapped:
            if mapped.startswith("app:"):
                return IntentResult("open_site", mapped)
            return IntentResult("open_site", _normalize_url_or_domain(mapped))

        # Last resort: treat it like a site keyword; opener can decide scheme
        return IntentResult("open_site", obj)

    return IntentResult("unknown", None)
