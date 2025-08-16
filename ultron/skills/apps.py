import shutil
import subprocess
from typing import Optional

def _which_any(names: list[str]) -> Optional[str]:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None

def open_browser_app(app: str) -> bool:
    """
    Launch a browser application by name on Windows.
    Returns True if the process was started.
    """
    app = (app or "").lower().strip()

    if app in ("default", "browser", ""):
        # Open a blank tab in the default browser
        try:
            subprocess.Popen(["cmd", "/c", "start", "", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

    # Chrome
    if app == "chrome":
        path = _which_any(["chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"])
        if path:
            subprocess.Popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True

    # Edge
    if app == "edge":
        path = _which_any(["msedge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                           r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"])
        if path:
            subprocess.Popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True

    # Firefox
    if app == "firefox":
        path = _which_any(["firefox", r"C:\Program Files\Mozilla Firefox\firefox.exe",
                           r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"])
        if path:
            subprocess.Popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True

    # Brave
    if app == "brave":
        path = _which_any(["brave", r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                           r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe"])
        if path:
            subprocess.Popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True

    # Opera
    if app == "opera":
        path = _which_any(["opera", r"C:\Users\%USERNAME%\AppData\Local\Programs\Opera\launcher.exe",
                           r"C:\Program Files\Opera\launcher.exe", r"C:\Program Files (x86)\Opera\launcher.exe"])
        if path:
            subprocess.Popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True

    return False
