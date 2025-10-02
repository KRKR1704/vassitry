# ultron/skills/calendar_gcal.py
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional

from dotenv import load_dotenv
load_dotenv()

# --- Time zones & NL datetime parsing ---
from dateutil import tz
import dateparser
from dateparser.search import search_dates

# --- Google Calendar API stack ---
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# ====== Filenames you chose (overridable by env vars) ======
DEFAULT_CLIENT_FILE = "calendar_auth.json"
DEFAULT_TOKEN_FILE  = "token_calendar.json"

# ============================== Helpers ===================================

def _tz_name() -> str:
    # If your system/env TZ is wrong, override with: set TZ=America/New_York
    return os.getenv("TZ", "America/New_York")

def _local_tz():
    return tz.gettz(_tz_name())

def _now_local() -> datetime:
    return datetime.now(_local_tz())

def _iso(dt: datetime) -> str:
    # For messages only; includes offset if present
    return dt.isoformat()

def _load_service():
    """
    Creates/refreshes OAuth creds and returns a Calendar service client.
    Env (optional overrides):
      - GOOGLE_OAUTH_CLIENT_SECRET: path to credentials.json (default calendar_auth.json)
      - GOOGLE_TOKEN_FILE: path to token.json (default token_calendar.json)
    """
    token_file = os.getenv("GOOGLE_TOKEN_FILE", DEFAULT_TOKEN_FILE)
    cred_file  = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", DEFAULT_CLIENT_FILE)

    creds: Optional[Credentials] = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            if not os.path.exists(cred_file):
                raise FileNotFoundError(f"Missing OAuth client file: {cred_file}")
            flow = InstalledAppFlow.from_client_secrets_file(cred_file, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


# ======================= Natural language parsing =========================

def _normalize_ampm(s: str) -> str:
    return re.sub(
        r"\b(a\.?m\.?|p\.?m\.?)\b",
        lambda m: "am" if m.group(0).lower().startswith("a") else "pm",
        s,
        flags=re.IGNORECASE,
    )

_TIME = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b", re.IGNORECASE)
_MONTH = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_MONTH_DAY = re.compile(rf"\b(?:{_MONTH})\s+\d{{1,2}}(?:st|nd|rd|th)?\b", re.IGNORECASE)
_DAY_MONTH = re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH})\b", re.IGNORECASE)

# explicit date tokens (NOT including today/tonight/tomorrow)
_EXPLICIT_DATE_TOKENS = re.compile(
    rf"\b(?:{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}|on\s+\w+\s+\d{{1,2}}|next\s+\w+|this\s+\w+)\b",
    re.IGNORECASE,
)

_GLUE_WORDS = re.compile(
    r"\b(on|at|by|for|from|to|this|next|tomorrow|today|tonight|morning|afternoon|evening|night|"
    r"saying|say|called|named|title|titled|as)\b",
    re.IGNORECASE
)

def _strip_triggers(s: str) -> str:
    s = re.sub(r"^\s*(hey\s+)?(ultron[, ]+)?", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(create|schedule|add|make|put|set)\s+(?:an?\s+)?", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:an?\s+)?(event|meeting|appointment|calendar|reminder)\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(to|on|into)\s+calendar\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip(" ,.-")
    return s

def _extract_explicit_title(text_clean: str) -> Tuple[Optional[str], str]:
    m = re.search(
        r"\b("
        r"titled\s+as|titled|title|"
        r"called|named|"
        r"name(?:\s+(?:it|this))?|"
        r"call(?:\s+(?:it|this))?|"
        r"label(?:\s+(?:it|this))?|"
        r"saying|say"
        r")\s*[:\-]?\s*(.+)$",
        text_clean,
        re.IGNORECASE,
    )
    if not m:
        return None, text_clean
    title = (m.group(2) or "").strip(" .,'\"-")
    if not title:
        return None, text_clean[: m.start()].strip()
    remainder = text_clean[: m.start()].strip()
    return title, remainder

def _cleanup_title(text: str) -> str:
    t = text
    t = _TIME.sub(" ", t)
    t = _MONTH_DAY.sub(" ", t)
    t = _DAY_MONTH.sub(" ", t)
    t = _GLUE_WORDS.sub(" ", t)
    t = re.sub(r"^(?:an?|the)\s+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip(" ,.-")
    return t

_FALLBACK_TITLE_ORDER = ["meeting", "appointment", "reminder", "event"]

def _pick_fallback_title(raw_text: str) -> Optional[str]:
    low = raw_text.lower()
    for w in _FALLBACK_TITLE_ORDER:
        if re.search(rf"\b{w}\b", low):
            return w.title()
    return None

def _parse_event_from_text(utterance: str, tz_name: str | None = None) -> Optional[Dict[str, Any]]:
    tz_name = tz_name or _tz_name()
    zone = tz.gettz(tz_name)
    now = datetime.now(zone)

    raw = utterance or ""
    text = _normalize_ampm(raw)
    text_clean = _strip_triggers(text)

    explicit_title, dt_text = _extract_explicit_title(text_clean)

    settings = {
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": now,
        "TIMEZONE": tz_name,
        "TO_TIMEZONE": tz_name,
        "RETURN_AS_TIMEZONE_AWARE": True,
    }

    dt: Optional[datetime] = None
    matched_span = ""
    try:
        found = search_dates(dt_text, settings=settings, languages=["en"])
    except Exception:
        found = None

    if found:
        def has_time(frag: str) -> bool:
            return bool(_TIME.search(frag))
        scored = sorted(found, key=lambda x: (has_time(x[0]), len(x[0])), reverse=True)
        matched_span, dt = scored[0]

    if dt is None:
        m = re.search(
            r"\b(tomorrow|today|tonight|next\s+\w+|this\s+\w+|on\s+[a-z]+\s+\d{1,2}|[a-z]+\s+\d{1,2}(?:st|nd|rd|th)?)\b.*?\bat\s+([0-9]{1,2}(:\d{2})?\s*(am|pm))\b",
            dt_text, re.IGNORECASE
        )
        if m:
            phrase = f"{m.group(1)} at {m.group(2)}"
            dt = dateparser.parse(phrase, settings=settings)
            matched_span = m.group(0)

    if dt is None:
        m = re.search(
            r"\bat\s+([0-9]{1,2}(:\d{2})?\s*(am|pm))\b.*?\b(tomorrow|today|tonight|next\s+\w+|this\s+\w+|on\s+[a-z]+\s+\d{1,2}|[a-z]+\s+\d{1,2}(?:st|nd|rd|th)?)\b",
            dt_text, re.IGNORECASE
        )
        if m:
            phrase = f"{m.group(4)} at {m.group(1)}"
            dt = dateparser.parse(phrase, settings=settings)
            matched_span = m.group(0)

    if dt is None:
        mt = re.search(r"\bat\s+([0-9]{1,2}(:\d{2})?\s*(am|pm))\b", dt_text, re.IGNORECASE)
        if mt:
            t_only = dateparser.parse(mt.group(1), settings=settings)
            if t_only:
                dt = t_only
                matched_span = mt.group(0)

    if dt is None:
        dt_try = dateparser.parse(dt_text, settings=settings)
        if dt_try:
            dt = dt_try
            if dt.hour == 0 and dt.minute == 0:
                dt = dt.replace(hour=9, minute=0, second=0, microsecond=0)
            matched_span = ""

    if dt is None:
        return None

    # If user did NOT give an explicit calendar date and time is already past today,
    # roll forward by 1 day. This fixes "today night at 7:30 p.m." spoken after 7:30 PM.
    has_explicit_date = bool(_EXPLICIT_DATE_TOKENS.search(dt_text))
    if not has_explicit_date:
        now_local = datetime.now(zone)
        if dt <= now_local and dt.date() == now_local.date():
            dt = dt + timedelta(days=1)

    # Normalize the parsed time to the target timezone explicitly
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
    else:
        dt = dt.astimezone(zone)

    if explicit_title:
        title = _cleanup_title(explicit_title)
    else:
        title_source = dt_text
        if matched_span:
            title_source = title_source.replace(matched_span, " ")
        title = _cleanup_title(title_source)
        if not title:
            fallback = _pick_fallback_title(raw)
            title = fallback if fallback else "New event"

    end_dt = dt + timedelta(minutes=30)
    return {"title": title, "start": dt, "end": end_dt}


# ======================== Public functions =================================

def _rfc3339_local_naive(dt: datetime) -> str:
    """
    Return 'YYYY-MM-DDTHH:MM:SS' *without* offset.
    Google will use the provided 'timeZone' field to interpret this local time.
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%S")

def create_event(summary: str, start_dt: datetime, end_dt: datetime,
                 description: str = "", location: str = "") -> Dict[str, Any]:
    """
    Create an event in Google Calendar and return the created event object.
    We send local times *without* an offset and specify 'timeZone' so Google
    doesn't double-convert.
    """
    cal_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    tz_name = _tz_name()
    service = _load_service()

    body = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": {"dateTime": _rfc3339_local_naive(start_dt), "timeZone": tz_name},
        "end":   {"dateTime": _rfc3339_local_naive(end_dt),   "timeZone": tz_name},
    }

    try:
        evt = service.events().insert(calendarId=cal_id, body=body).execute()
        return evt
    except HttpError as e:
        raise RuntimeError(f"Google Calendar API error: {e}")

def create_event_from_text(utterance: str) -> Dict[str, Any]:
    """
    Parse title + time from the user's command and create the event.
    Returns a dict with ok/message/id/link/etc. for TTS and logging.
    """
    try:
        parsed = _parse_event_from_text(utterance)
        if not parsed:
            return {
                "ok": False,
                "message": ("Sorry, I couldn't parse a date/time in that. "
                            "Try: ‘create an event project sync tomorrow at 8:30 am’, "
                            "or ‘create an event on Oct 18 at 7:30 pm titled as Trip’.")
            }

        title = parsed["title"]
        start = parsed["start"]
        end   = parsed["end"]

        # Reject past times (after roll-forward rule). Don’t silently schedule in the past.
        now = _now_local()
        if start <= now:
            pretty = start.strftime("%b %d, %I:%M %p").lstrip("0")
            return {
                "ok": False,
                "message": (f"That time ({pretty}) has already passed. "
                            "Say something like ‘tomorrow at 8:30 pm’ or give a future date/time.")
            }

        evt = create_event(title, start, end, description="Created by Ultron")
        link = evt.get("htmlLink")

        pretty_when = start.strftime("%b %d, %I:%M %p").lstrip("0")
        return {
            "ok": True,
            "message": f"Added “{title}” on {pretty_when}.",
            "id": evt.get("id"),
            "link": link,
            "title": title,
            "start": _iso(start),
            "end": _iso(end),
        }
    except Exception as e:
        return {"ok": False, "message": f"Couldn't create the event: {e}"}
