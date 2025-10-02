# ultron/skills/weather.py
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Tuple

import requests

from ultron.config import DEFAULT_CITY, UNITS  # set these in .env / config.py

# --- Open-Meteo endpoints (no API key required) ---
OPEN_METEO_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"


# ===== Models =====
@dataclass
class WeatherResult:
    location: str
    when_label: str            # "yesterday" | "today" | "tomorrow" | "now"
    temp_c: float | None       # representative temp (avg for daily, current for now)
    temp_f: float | None
    description: str | None
    provider: str              # "open-meteo"


# ===== Helpers =====
def _desc_from_code(code: int) -> str:
    code = int(code)
    return {
        0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
        45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle",
        55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
        61: "light rain", 63: "rain", 65: "heavy rain",
        66: "freezing rain", 67: "freezing rain",
        71: "light snow", 73: "snow", 75: "heavy snow",
        77: "snow grains",
        80: "rain showers", 81: "rain showers", 82: "heavy rain showers",
        85: "snow showers", 86: "heavy snow showers",
        95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
    }.get(code, "typical conditions")


def _geocode_city(city: str) -> Tuple[float, float, str, str]:
    """
    Returns (lat, lon, timezone_name, canonical_location_name).
    Tries a few generic variations so users can say natural phrases like
    "Newark, New Jersey, United States" or "Hyderabad, India".
    """
    def try_query(q: str):
        print(f"[Ultron][Weather][DBG] Geocoding city={q!r}")
        r = requests.get(OPEN_METEO_GEOCODE, params={"name": q, "count": 1}, timeout=10)
        print(f"[Ultron][Weather][DBG] Geocode URL={r.url} status={r.status_code}")
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        return results[0] if results else None

    raw = (city or "").strip().strip('"').strip("'")
    if not raw:
        raise ValueError("Couldn't find location: <empty>")

    # Build normalized candidates (dedup while preserving order)
    candidates: list[str] = []

    # 1) as-is
    candidates.append(raw)

    # 2) Replace common long country names with ISO codes (generic, not city-specific)
    country_norms = {
        "united states": "US",
        "united kingdom": "GB",
        "great britain": "GB",
        "england": "GB",
        "scotland": "GB",
        "wales": "GB",
        "northern ireland": "GB",
        "india": "IN",
        "canada": "CA",
        "australia": "AU",
        "new zealand": "NZ",
        "south africa": "ZA",
        "germany": "DE",
        "france": "FR",
        "spain": "ES",
        "italy": "IT",
        "japan": "JP",
        "china": "CN",
        "brazil": "BR",
        "mexico": "MX",
    }
    lowered = raw.lower()
    for long, iso in country_norms.items():
        if long in lowered:
            # Title-case the whole string after replacement to keep capitalization tidy
            candidates.append(lowered.replace(long, iso).title()
                              .replace(" Us", " US").replace(" Gb", " GB"))

    # 3) Keep only City + last token (e.g., "Newark, US" from "Newark, New Jersey, US")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) >= 2:
        candidates.append(f"{parts[0]}, {parts[-1]}")

    # 4) City only
    candidates.append(parts[0] if parts else raw)

    # Deduplicate while preserving order
    seen = set()
    deduped: list[str] = []
    for c in candidates:
        c2 = c.strip()
        if c2.lower() not in seen:
            deduped.append(c2)
            seen.add(c2.lower())

    # Try each candidate
    hit = None
    for q in deduped:
        try:
            hit = try_query(q)
            if hit:
                break
        except requests.RequestException:
            # network issues → let outer raise after loop
            pass

    if not hit:
        raise ValueError(f"Couldn't find location: {raw}")

    lat = float(hit["latitude"])
    lon = float(hit["longitude"])
    tz_name = hit.get("timezone", "UTC")
    # Canonical label like "Newark, NJ, US" or "Hyderabad, IN" when available
    pieces = [hit.get("name"), hit.get("admin1"), hit.get("country_code")]
    label = ", ".join([p for p in pieces if p])
    return lat, lon, tz_name, label or raw


def _fetch_openmeteo_daily(
    lat: float, lon: float, tz_name: str, target: str
) -> Tuple[float, float, str]:
    """
    target: 'yesterday' | 'today' | 'tomorrow'
    Returns (tmin_c, tmax_c, description)
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": tz_name,
        "daily": "weathercode,temperature_2m_max,temperature_2m_min",
        # Request a 3-day window around today so all targets exist:
        "past_days": 1,      # yields yesterday
        "forecast_days": 2,  # yields today + tomorrow
    }
    r = requests.get(OPEN_METEO_FORECAST, params=params, timeout=10)
    r.raise_for_status()
    j = r.json()
    daily = j.get("daily") or {}
    dates = daily.get("time") or []
    tmin = daily.get("temperature_2m_min") or []
    tmax = daily.get("temperature_2m_max") or []
    codes = daily.get("weathercode") or []

    if not dates:
        raise RuntimeError("No daily data returned")

    today = date.today()
    target_date = {
        "yesterday": today - timedelta(days=1),
        "today": today,
        "tomorrow": today + timedelta(days=1),
    }[target]
    want = target_date.isoformat()

    # Prefer exact match; fallback to a sensible index if API shifts order
    if want in dates:
        idx = dates.index(want)
    else:
        fallback = {"yesterday": 0, "today": 1, "tomorrow": 2}.get(target, 1)
        idx = max(0, min(len(dates) - 1, fallback))

    code = int(codes[idx]) if idx < len(codes) and codes[idx] is not None else -1
    desc = _desc_from_code(code)
    tmin_c = float(tmin[idx]) if idx < len(tmin) and tmin[idx] is not None else math.nan
    tmax_c = float(tmax[idx]) if idx < len(tmax) and tmax[idx] is not None else math.nan
    return tmin_c, tmax_c, desc


# ===== Public API =====
def get_weather_sync(city: str | None, when: str | None = "today") -> WeatherResult:
    """
    - 'yesterday'/'today'/'tomorrow' → Open-Meteo daily (min/max → speak avg)
    - 'now' (or anything else)       → Open-Meteo current conditions
    """
    # Clean up accidental quotes/spaces from .env/user speech
    default_city = (DEFAULT_CITY or "").strip().strip('"').strip("'")

    # Start from the explicit city (if any); don't fall back yet
    city_in = (city or "").strip().strip('"').strip("'")

    # If the "city" is actually a time-word (e.g., "tomorrow", "s tomorrow"), ignore it
    if city_in:
        # strip leading "'s " or "s " (from "what's", "how's")
        city_in = re.sub(r"^\s*'?s\s+", "", city_in, flags=re.I)
        # drop if it contains only time words / no real letters
        if re.search(r"\b(today|tomorrow|yesterday|now)\b", city_in, re.I):
            city_in = ""

    # Fall back to DEFAULT_CITY if needed
    city_in = city_in or default_city
    if not city_in:
        raise ValueError("No city set. Set DEFAULT_CITY in .env or say a city name.")

    when_norm = (when or "today").lower()
    print(f"[Ultron][Weather][DBG] get_weather_sync city_in={city_in!r} when={when_norm!r}")

    # Geocode once, reuse for all branches
    lat, lon, tz_name, loc_label = _geocode_city(city_in)

    if when_norm in ("today", "tomorrow", "yesterday"):
        tmin_c, tmax_c, desc = _fetch_openmeteo_daily(lat, lon, tz_name, when_norm)
        if (tmin_c is None or math.isnan(tmin_c)) and (tmax_c is None or math.isnan(tmax_c)):
            avg_c = None
        elif tmin_c is None or math.isnan(tmin_c):
            avg_c = tmax_c
        elif tmax_c is None or math.isnan(tmax_c):
            avg_c = tmin_c
        else:
            avg_c = (tmin_c + tmax_c) / 2.0

        temp_f = (avg_c * 9 / 5 + 32) if (isinstance(avg_c, (int, float)) and avg_c is not None and not math.isnan(avg_c)) else None
        return WeatherResult(
            location=loc_label,
            when_label=when_norm,
            temp_c=avg_c,
            temp_f=temp_f,
            description=desc,
            provider="open-meteo",
        )

    # 'now' (and any other) → current conditions
    params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": True,
        "timezone": tz_name,
    }
    r = requests.get(OPEN_METEO_FORECAST, params=params, timeout=10)
    r.raise_for_status()
    j = r.json()
    cw = j.get("current_weather") or {}
    if "temperature" not in cw:
        raise RuntimeError("No current weather in response")

    temp_c = float(cw["temperature"])
    code = int(cw.get("weathercode", -1))
    desc = _desc_from_code(code)
    temp_f = temp_c * 9 / 5 + 32
    label = "now" if when_norm == "now" else "today"

    return WeatherResult(
        location=loc_label,
        when_label=label,
        temp_c=temp_c,
        temp_f=temp_f,
        description=desc,
        provider="open-meteo",
    )


def speak_weather_sync(tts, city: str | None, when: str | None):
    """
    Speaks a concise weather line based on UNITS:
      - UNITS=metric  → Celsius
      - UNITS=imperial→ Fahrenheit
      - UNITS=auto    → choose F if location label ends with 'US' or contains 'United States'
    """
    try:
        w = get_weather_sync(city, when)

        # Unit selection
        use_f = (UNITS == "imperial") or (
            UNITS == "auto" and (w.location.endswith(", US") or "United States" in w.location)
        )

        unit = "degrees Fahrenheit" if use_f else "degrees Celsius"
        temp_val = None
        if isinstance(w.temp_c, (int, float)) and w.temp_c is not None and not math.isnan(w.temp_c):
            temp_val = round(w.temp_f) if use_f else round(w.temp_c)

        when_spoken = w.when_label  # "today" | "tomorrow" | "yesterday" | "now"

        if when_spoken in ("today", "tomorrow", "yesterday"):
            if temp_val is not None:
                tts.speak(f"In {w.location}, {when_spoken}, around {temp_val} {unit} with {w.description}.")
            else:
                tts.speak(f"In {w.location}, {when_spoken}, conditions are {w.description}.")
        else:  # now
            if temp_val is not None:
                tts.speak(f"In {w.location} right now, it's {temp_val} {unit} with {w.description}.")
            else:
                tts.speak(f"Sorry, I couldn't get the weather for {w.location} right now.")

    except requests.RequestException as e:
        print(f"[Ultron][Weather] Network error: {e!r}")
        tts.speak("Weather ran into a network issue. Please check your internet connection.")
    except Exception as e:
        print(f"[Ultron][Weather] Error: {e!r}")
        msg = str(e)
        if "Couldn't find location" in msg:
            tts.speak("I couldn't find that location. Please say the city name, like ‘weather in Hyderabad’.")
        elif "No city set" in msg:
            tts.speak("Please set a default city in your dot env or say a city name.")
        else:
            tts.speak("Weather ran into an issue. Please try again.")
