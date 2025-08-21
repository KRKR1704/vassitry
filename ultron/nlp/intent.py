import re
from dataclasses import dataclass
from difflib import get_close_matches
from urllib.parse import urlparse

@dataclass
class IntentResult:
    intent: str
    entity: str | None

# --- Website aliases ---
COMMON_MAP = {
    "google": "google.com",
    "gmail": "mail.google.com",
    "youtube": "youtube.com",
    "you tube": "youtube.com",
    "chatgpt": "chat.openai.com",
    "linkedin": "linkedin.com",
    "outlook": "outlook.live.com",
    "whatsapp": "web.whatsapp.com",
    "canvas": "canvas.ubuffalo.edu",
    "ublearns": "ublearns.buffalo.edu",
    "reddit": "reddit.com",
    "twitter": "x.com",
    "x": "x.com",
    "stackoverflow": "stackoverflow.com",
    "stack overflow": "stackoverflow.com",
}

# --- Browser/app aliases ---
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

# ----- Helpers -----
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

# Keys
_AUDIO_DEVICE_KEYS = r"\b(audio|sound|output|device|speaker|speakers|playback)\b"
_SWITCH_TRIGGERS   = r"\b(set|switch|change|make|use|route|default)\b"
_LIST_TRIGGERS     = r"\b(list|show|what(?:'s| is)|available|enumerate|display)\b"

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

        # set to N: "to 70", "set volume 30", "volume 50"
        if _has(s, r"\bto\s+\d{1,3}\b"):
            n = _extract_first_int(s)
            if n is not None: return IntentResult("volume_set", str(n))
        if _has(s, r"\b(set|change|adjust)\b") and _extract_first_int(s) is not None:
            return IntentResult("volume_set", str(_extract_first_int(s)))
        if re.fullmatch(r".*\bvolume\s+\d{1,3}\b.*", s, re.I):
            return IntentResult("volume_set", str(_extract_first_int(s)))

        # up/down (+ optional "by N")
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
        if _has(s, r"\bto\s+\d{1,3}\b") and _has(s, r"\bbright"):
            n = _extract_first_int(s)
            if n is not None: return IntentResult("brightness_set", str(n))
        if _has(s, r"\b(set|change|adjust)\s+(?:the\s+)?brightness\b") and _extract_first_int(s) is not None:
            return IntentResult("brightness_set", str(_extract_first_int(s)))
        if re.fullmatch(r".*\bbrightness\s+\d{1,3}\b.*", s, re.I):
            return IntentResult("brightness_set", str(_extract_first_int(s)))

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
    if _has(t, r"\b(hibernate)\b"): return IntentResult("power_sleep", None)
    if _has(t, r"\b(put\s+(?:the\s+)?(?:pc|computer|system)\s+to\s+sleep|go\s+to\s+sleep|sleep\s+now|^sleep$)\b"):
        return IntentResult("power_sleep", None)
    if re.search(r"\b(shut\s*down|power\s*off|turn\s*off)\b(?!.*\b(wi-?fi|wifi|wireless|wlan)\b)", t, re.I):
        return IntentResult("power_shutdown", None)
    if _has(t, r"\b(restart|reboot)\b"): return IntentResult("power_restart", None)
    if _has(t, r"\b(lock|lock\s+(?:the\s+)?(?:pc|computer|screen))\b"):
        return IntentResult("power_lock", None)

    # ===== URL/domain anywhere → open_site =====
    m = URL_OR_DOMAIN.search(t)
    if m:
        raw = m.group("url").rstrip(".,!?")
        parsed = urlparse(raw if raw.startswith("http") else f"https://{raw}")
        host_or_path = parsed.netloc or parsed.path.strip("/")
        if host_or_path:
            site = re.sub(r"^www\.", "", host_or_path)
            alias = _alias_lookup(site)
            site = alias if alias else site
            return IntentResult("open_site", site)

    # ===== Audio output devices =====
    if _has(s, _LIST_TRIGGERS) and _has(s, _AUDIO_DEVICE_KEYS):
        return IntentResult("audio_list_outputs", None)
    if _has(s, r"\b(outputs|playback devices|audio devices|speakers)\b") and _has(s, r"\b(list|show|available)\b"):
        return IntentResult("audio_list_outputs", None)

    if (_has(s, _SWITCH_TRIGGERS) and _has(s, _AUDIO_DEVICE_KEYS)) or _has(s, r"\b(default output)\b"):
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

        app = _browser_app_lookup(obj.lower())
        if app: return IntentResult("open_app", app)

        alias = _alias_lookup(obj.lower())
        if alias: return IntentResult("open_site", alias)

        m = URL_OR_DOMAIN.search(obj)
        if m:
            raw = m.group("url").rstrip(".,!?")
            parsed = urlparse(raw if raw.startswith("http") else f"https://{raw}")
            host_or_path = parsed.netloc or parsed.path.strip("/")
            if host_or_path:
                site = re.sub(r"^www\.", "", host_or_path)
                return IntentResult("open_site", site)

        return IntentResult("open_site", obj)

    return IntentResult("unknown", None)
