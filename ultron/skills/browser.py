import webbrowser
import shutil
import subprocess
from typing import Optional

def _edge_path() -> Optional[str]:
    candidate = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    return candidate if shutil.which(candidate) or (shutil.which("msedge") is not None) else None

def _chrome_path() -> Optional[str]:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        if shutil.which(c) or (shutil.which("chrome") is not None):
            return c
    return None

def open_url(url: str, browser_pref: str = "default"):
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url

    if browser_pref == "chrome":
        path = _chrome_path()
        if path:
            subprocess.Popen([path, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    elif browser_pref == "edge":
        path = _edge_path()
        if path:
            subprocess.Popen([path, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True

    webbrowser.open(url, new=2)
    return True
