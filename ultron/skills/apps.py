import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# Helper to find an executable on PATH or known locations
def _which_any(candidates: list[str]) -> Optional[str]:
    for c in candidates:
        p = shutil.which(c)
        if p:
            return p
        # absolute paths
        if Path(c).exists():
            return str(Path(c))
    return None

def _start(proc: list[str]) -> bool:
    try:
        subprocess.Popen(proc, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def _open_default_browser(blank: bool = True) -> bool:
    try:
        target = "about:blank" if blank else ""
        subprocess.Popen(["cmd", "/c", "start", "", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def open_app(app: str) -> bool:
    """
    Launch a desktop application by common name on Windows.
    Supports browsers and popular apps. Extend as needed.
    """
    a = (app or "").lower().strip()

    # ---- Browsers ----
    if a in ("default", "browser"):
        return _open_default_browser()

    if a in ("chrome", "google chrome"):
        return _start([_which_any([
            "chrome",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        ]) or "chrome"])

    if a in ("edge", "microsoft edge"):
        return _start([_which_any([
            "msedge",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        ]) or "msedge"])

    if a in ("firefox", "mozilla firefox"):
        return _start([_which_any([
            "firefox",
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"
        ]) or "firefox"])

    if a == "brave":
        return _start([_which_any([
            "brave",
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe"
        ]) or "brave"])

    if a == "opera":
        return _start([_which_any([
            "opera",
            r"C:\Users\%USERNAME%\AppData\Local\Programs\Opera\launcher.exe",
            r"C:\Program Files\Opera\launcher.exe",
            r"C:\Program Files (x86)\Opera\launcher.exe"
        ]) or "opera"])

    # ---- Editors / IDEs ----
    if a == "notepad":
        return _start(["notepad"])
    if a == "wordpad":
        return _start(["write"])
    if a in ("vscode", "vs code", "visual studio code"):
        return _start([_which_any([
            "code",
            r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe",
            r"C:\Program Files\Microsoft VS Code\Code.exe"
        ]) or "code"])
    if a == "pycharm":
        return _start([_which_any([
            "pycharm64",
            r"C:\Program Files\JetBrains\PyCharm Community Edition 2024.1\bin\pycharm64.exe",
            r"C:\Program Files\JetBrains\PyCharm\bin\pycharm64.exe"
        ]) or "pycharm64"])
    if a == "visualstudio":
        return _start([_which_any([
            "devenv",
            r"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\devenv.exe"
        ]) or "devenv"])

    # ---- Media / Chat / Gaming ----
    if a == "spotify":
        return _start([_which_any([
            "spotify",
            r"C:\Users\%USERNAME%\AppData\Roaming\Spotify\Spotify.exe",
            r"C:\Users\%USERNAME%\AppData\Local\Microsoft\WindowsApps\Spotify.exe"
        ]) or "spotify"])


    if a == "steam":
        return _start([_which_any([
            "steam",
            r"C:\Program Files (x86)\Steam\Steam.exe"
        ]) or "steam"])

    # ---- Utilities ----
    if a in ("calc", "calculator"):
        return _start(["calc"])
    if a == "mspaint":
        return _start(["mspaint"])
    if a == "snippingtool":
        return _start([_which_any([
            "snippingtool",
            r"C:\Windows\system32\SnippingTool.exe"
        ]) or "snippingtool"])

    # ---- Dynamic Scan (Start Menu) ----
    # If we haven't returned yet, scan the system for installed apps
    try:
        from ultron.skills.app_scanner import get_app_cache
        from difflib import get_close_matches

        installed = get_app_cache()
        # installed is { "google chrome": "path/to/lnk", ... }
        
        # 1. Exact match
        if a in installed:
            return _start_lnk(installed[a])

        # 2. Fuzzy match
        # keys are already lowercased
        candidates = list(installed.keys())
        matches = get_close_matches(a, candidates, n=1, cutoff=0.6)
        
        if matches:
            best_match = matches[0]
            # Optional: Log or print what we found
            # print(f"[Ultron] Found installed app: {best_match}")
            return _start_lnk(installed[best_match])

    except Exception as e:
        print(f"[Ultron][apps] Scan error: {e}")


    # ---- Last resort: try to launch the given token directly (PATH) ----
    path_guess = shutil.which(a)
    if path_guess:
        return _start([path_guess])

    return False

def _start_lnk(lnk_path: str) -> bool:
    """
    Start a shortcut (.lnk) file or Windows Store app URI using os.startfile (Windows only).
    Supports both traditional shortcuts and Store app URIs (shell:AppsFolder\...).
    """
    try:
        os.startfile(lnk_path)
        return True
    except Exception:
        return False
