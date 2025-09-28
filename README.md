
# Ultron — Your Personal Voice Assistant

Ultron is a **local**, **modular**, and **voice-first** desktop assistant inspired by J.A.R.V.I.S.  
It runs on your machine, responds to your **voice** (wakeword or hotkey), and can control **apps**, **websites**, and **system settings**, plus fetch **weather** and answer general questions.

> **Highlights**
> - Wakeword **and** Hotkey
> -  Open sites & do **site-specific search** (works on *any* website)
> -  Weather via **Open-Meteo** (no API key)
> -  Volume /  Mute /  Audio output switch
> -  Brightness / Night Light / Display modes
> -  Wi-Fi status/on/off/connect
> -  Battery / Power (sleep, shutdown, restart, lock)
> -  Window controls
> -  Gemini fallback for Q&A

---

## Table of Contents
- [Features](#features)
- [Demo Phrases](#demo-phrases)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Project Structure](#project-structure)

---

## Features

- **Activation**
  - Wakeword via Porcupine/OpenWakeWord
  - Global hotkey (configurable, e.g. `alt+u`)
- **Web & Apps**
  - Open websites (aliases for common sites)
  - Open desktop/browser apps (Chrome, WhatsApp, etc.)
  - **Site Search**: “search \<query\> on \<site\>” (generic, not hardcoded to one site)
- **Weather**
  - “weather today/tomorrow/yesterday/now [in \<city\>]”
  - Robust city parsing and geocoding; default city fallback
- **Audio**
  - Volume set/up/down, mute/unmute
  - List/switch audio outputs (e.g., “switch audio to ‘OnePlus Buds Z2’”)
- **Display**
  - Brightness set/up/down
  - Night Light on/off/toggle
  - Projection modes: extend/clone/internal/external
- **Connectivity**
  - Wi-Fi status/on/off/disconnect/connect “to ‘SSID’”
- **Power & Battery**
  - Sleep / Shutdown / Restart / Lock
  - Battery level
- **Windows & Utility**
  - Minimize/Maximize/Close active window
  - Screenshot
- **AI Fallback**
  - Gemini: general Q&A if no strict intent matches

---

## Demo Phrases

**Web & Search**
- “Open **youtube.com**”
- “Open **Brave**”
- “Search **RTX 5070** on **bestbuy.com**”
- “Search **one direction** on **YouTube**”

**Weather**
- “What’s the weather **today**?”
- “Weather **tomorrow in Newark**”
- “How’s the weather **now**?”
- “Tell me the weather **yesterday in Newark**”

**Audio**
- “Set **volume to 30**”
- “**Increase volume by 10**”
- “**Mute**” / “**Unmute**”
- “**List audio outputs**”
- “**Switch audio to** ‘OnePlus Buds Z2’”

**Display**
- “Set **brightness to 70**”
- “**Turn on Night Light**”
- “**Extend** my display”
- “**PC screen only**”

**Wi-Fi / Power / Windows**
- “**Wi-Fi status**”
- “**Turn off Wi-Fi**”
- “**Connect** to ‘Home Network’”
- “**Sleep now**” / “**Shut down**” / “**Restart**” / “**Lock**”
- “**Minimize this window**” / “**Take a screenshot**”

**Fallback**
- “Who is the CEO of NVIDIA?”
- “Explain quantum entanglement in simple words.”

> Tip: Watch the console logs (if `DEBUG=True`) to see parsed intents, e.g.  
> `Intent=site.search slots={'site': 'bestbuy.com', 'query': 'RTX 4070'}`

---

## Quick Start

> **Platform:** Windows (primary). Other OSes possible with light porting for system controls.

### Clone & create venv
```bash
git clone https://github.com/KRKR1704/vassitry.git
cd vassitry
python -m venv .venv
# PowerShell:
. .\.venv\Scripts\Activate.ps1
# or cmd:
# .venv\Scripts\activate.bat
pip install -r requirements.txt
python ultron/main.py
```
## Configuration
```bash
Create a `.env` file in the repo root:
# ==============================
# Wakeword & Activation
# ==============================
# Porcupine (Picovoice) access key (required if using Porcupine)
PORCUPINE_ACCESS_KEY=

# Wake engine: hotkey-only, wakeword-only, or both
WAKE_ENGINE=both            # hotkey | wakeword | both

# Wakeword model path (Porcupine .ppn) or name for OpenWakeWord
WAKEWORD=<path of the model(ppn file)>

# Global hotkey to trigger listening (if hotkey or both)
ULTRON_HOTKEY=alt+u


# ==============================
# Browser preference
# ==============================
# default = OS default; otherwise choose a browser explicitly
BROWSER=default             # default | chrome | edge | firefox | brave | opera


# ==============================
# Microphone & Audio Beep (optional)
# ==============================
# Microphone device index; -1 uses the system default
MIC_INDEX=-1

# Optional audible beep when waking (if enabled)
BEEP_FREQ=900
BEEP_MS=160


# ==============================
# TTS (Text-to-Speech)
# ==============================
# Voice name (Windows SAPI5 example); see tts_test.py for available voices
TTS_VOICE_NAME=Microsoft David Desktop
TTS_RATE=0                  # -30 slower ... +30 faster
TTS_VOLUME=1.0              # 0.0 .. 1.0
TTS_BACKEND=powershell      # powershell | pyttsx3
TTS_STARTUP_TEST=0          # 1 = speak a test line on startup


# ==============================
# Spoken Feedback
# ==============================
# How Ultron acknowledges wake: voice, beep, both, or off
WAKE_ACK=voice
WAKE_ACK_TEXT=Ultron is listening.
STARTUP_TEXT=Ultron is standing by.
SHUTDOWN_TEXT=Ultron shutting down.

# Amount of spoken narration:
# minimal = only essentials, actions = include actions, debug = verbose
SPEAK_MODE=minimal          # minimal | actions | debug


# ==============================
# Site Search via Playwright (optional)
# ==============================
# Use Playwright to perform on-site searches; 0 = use normal browser only
USE_PLAYWRIGHT_SEARCH=1

# Which Playwright browser to use; blank uses bundled Chromium
PLAYWRIGHT_CHANNEL=chrome   # chrome | msedge | firefox | (blank)


# ==============================
# Realtime Search + LLM (optional)
# ==============================
# Provider for realtime web search (code currently implements duckduckgo; google/serp/bing are placeholders)
REALTIME_SEARCH_PROVIDER=google       # duckduckgo | serpapi | bing | google

# Google Custom Search (if you enable google provider)
GOOGLE_API_KEY=
GOOGLE_CSE_ID=

# Safety limits for realtime search
REALTIME_MAX_RESULTS=6
REALTIME_TIMEOUT_SEC=12


# ==============================
# Weather
# ==============================
# Default city when you say "weather today" without a city
DEFAULT_CITY=<your location>

# Units for temperature:
# metric = °C, imperial = °F, auto = pick °F in US / °C elsewhere
UNITS=metric                 # metric | imperial | auto
```
## Project Structure
```bash
vassitry/
├─ ultron/
│  ├─ main.py                # entrypoint: hotkey/wakeword → listener → intent → skill → TTS
│  ├─ config.py              # loads env, exposes BROWSER, HOTKEY, DEFAULT_CITY, UNITS, etc.
│  ├─ ack.py, hotkey.py, wakeword.py, listener.py, tts.py
│  ├─ nlp/
│  │  └─ intent.py           # Intent parsing (open_site/app, wifi, weather, site.search, etc.)
│  └─ skills/
│     ├─ weather.py          # Open-Meteo geocode + forecast; speak_weather_sync()
│     ├─ site_search.py      # generic site search URL builder + opener
│     ├─ browser.py          # open_url()
│     ├─ apps.py             # open_app/open_browser_app()
│     ├─ system.py           # volume/brightness/wifi/display/power/window/screenshot
│     └─ gemini.py           # ask_gemini() fallback (optional)
├─ requirements.txt
├─ .env (you create this)
└─ README.md
```

