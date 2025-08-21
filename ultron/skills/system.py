# ultron/skills/system.py
# Desktop/system control skills (Windows-first).
#
# Optional deps:
#   comtypes==1.2.0, pycaw==20230407, screen_brightness_control, psutil,
#   pyautogui, pygetwindow, Pillow
#
# All imports are guarded; functions fail gracefully if a dep is missing.

from __future__ import annotations

import ctypes
from ctypes import wintypes  # <-- added for Night Light signatures (safe to include)
import os
import platform
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

IS_WINDOWS = platform.system() == "Windows"

# -------------------------- Optional libraries (guarded) --------------------------

# COM / pycaw for audio volume + endpoints
_PYCAW = False
_PYCAW_UTILS = False
try:
    if IS_WINDOWS:
        from ctypes import POINTER, cast  # type: ignore
        from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize, GUID  # type: ignore
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore
        try:
            from pycaw.utils import AudioUtilities as AU  # type: ignore
            _PYCAW_UTILS = True
        except Exception:
            _PYCAW_UTILS = False
        _PYCAW = True
except Exception:
    _PYCAW = False
    _PYCAW_UTILS = False

def _get_AU():
    return AU if _PYCAW_UTILS else AudioUtilities

# Brightness
_HAS_SBC = False
try:
    import screen_brightness_control as sbc  # type: ignore
    _HAS_SBC = True
except Exception:
    _HAS_SBC = False

# Battery
_HAS_PSUTIL = False
try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except Exception:
    _HAS_PSUTIL = False

# Windows windowing + screenshot fallbacks
_HAS_PYW = False
try:
    import pygetwindow as gw  # type: ignore
    _HAS_PYW = True
except Exception:
    _HAS_PYW = False

_HAS_PYAUTOGUI = False
try:
    import pyautogui  # type: ignore
    _HAS_PYAUTOGUI = True
except Exception:
    _HAS_PYAUTOGUI = False

_HAS_PIL = False
try:
    from PIL import Image  # noqa: F401
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


# -------------------------- Utility helpers --------------------------

def _run(cmd: List[str], timeout: int = 10) -> Tuple[int, str, str]:
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out.decode(errors="ignore"), err.decode(errors="ignore")
    except Exception as e:
        return 1, "", str(e)

def clamp_0_100(v: int) -> int:
    return max(0, min(100, int(v)))


# -------------------------- Wi-Fi controls & status --------------------------

def _get_wlan_interface_name() -> Optional[str]:
    if not IS_WINDOWS:
        return None
    rc, out, _ = _run(["netsh", "wlan", "show", "interfaces"])
    if rc != 0:
        return None
    m = re.search(r"^\s*Name\s*:\s*(.+)$", out, re.I | re.M)
    return m.group(1).strip() if m else "Wi-Fi"

def wifi_status() -> Dict[str, Optional[object]]:
    if not IS_WINDOWS:
        return {"state": "unknown", "ssid": None, "signal": None}
    rc, out, _ = _run(["netsh", "wlan", "show", "interfaces"])
    if rc != 0:
        return {"state": "unknown", "ssid": None, "signal": None}
    if not re.search(r"^\s*State\s*:", out, re.I | re.M):
        return {"state": "off", "ssid": None, "signal": None}
    state = "unknown"; ssid = None; signal = None
    m = re.search(r"^\s*State\s*:\s*(.+)$", out, re.I | re.M)
    if m:
        st = m.group(1).strip().lower()
        if "connected" in st: state = "connected"
        elif "disconnected" in st: state = "disconnected"
        else: state = st
    m = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.I | re.M)
    if m:
        txt = m.group(1).strip()
        ssid = txt or None
    m = re.search(r"^\s*Signal\s*:\s*(\d+)\s*%", out, re.I | re.M)
    if m:
        try: signal = int(m.group(1))
        except Exception: signal = None
    return {"state": state, "ssid": ssid, "signal": signal}

def wifi_disconnect() -> bool:
    if not IS_WINDOWS: return False
    rc, _, _ = _run(["netsh", "wlan", "disconnect"])
    return rc == 0

def wifi_off() -> bool:
    if not IS_WINDOWS: return False
    name = _get_wlan_interface_name() or "Wi-Fi"
    rc, _, _ = _run(["netsh", "interface", "set", "interface", f"name={name}", "admin=disabled"])
    if rc == 0: return True
    return wifi_disconnect()  # fallback if not elevated

def wifi_on() -> bool:
    if not IS_WINDOWS: return False
    name = _get_wlan_interface_name() or "Wi-Fi"
    rc, _, _ = _run(["netsh", "interface", "set", "interface", f"name={name}", "admin=enabled"])
    return rc == 0

def wifi_connect(ssid: str) -> bool:
    if not (IS_WINDOWS and ssid): return False
    rc, _, _ = _run(["netsh", "wlan", "connect", f"name={ssid}"])
    return rc == 0


# -------------------------- Display projection (DisplaySwitch) --------------------------

def display_mode(mode: str) -> bool:
    if not IS_WINDOWS: return False
    arg = {"extend": "/extend", "clone": "/clone", "external": "/external", "internal": "/internal"}.get(
        (mode or "").strip().lower()
    )
    if not arg: return False
    rc, _, _ = _run(["DisplaySwitch.exe", arg])
    return rc == 0


# -------------------------- Audio endpoints: list & switch default --------------------------

def audio_list_outputs() -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    if not (_PYCAW and IS_WINDOWS):
        return results
    try:
        CoInitialize()
        try:
            AUref = _get_AU()
            try:
                devices = AUref.GetAllDevices()
            except Exception:
                defaults = [
                    AUref.GetDefaultAudioEndpoint("Render", "Console"),
                    AUref.GetDefaultAudioEndpoint("Render", "Multimedia"),
                    AUref.GetDefaultAudioEndpoint("Render", "Communications"),
                ]
                seen = set()
                devices = []
                for d in defaults:
                    if d and getattr(d, "id", None) and d.id not in seen:
                        seen.add(d.id)
                        devices.append(d)
            default_ids: Dict[str, Optional[str]] = {"console": None, "multimedia": None, "communications": None}
            try:
                default_ids["console"] = AUref.GetDefaultAudioEndpoint("Render", "Console").id
                default_ids["multimedia"] = AUref.GetDefaultAudioEndpoint("Render", "Multimedia").id
                default_ids["communications"] = AUref.GetDefaultAudioEndpoint("Render", "Communications").id
            except Exception:
                pass

            for d in devices:
                try:
                    df = (getattr(d, "data_flow", "") or getattr(d, "DataFlow", "") or "").lower()
                    if df and df != "render": continue
                    dev_id = getattr(d, "id", "") or ""
                    name = getattr(d, "FriendlyName", None) or "Unknown"
                    state_val = getattr(d, "State", None)
                    state_map = {1: "active", 2: "disabled", 4: "not_present", 8: "unplugged"}
                    state_str = state_map.get(state_val, "unknown")
                    roles = [role for role, rid in default_ids.items() if rid and dev_id and rid == dev_id]
                    results.append({"id": dev_id, "name": name, "state": state_str, "default": ",".join(roles) or "none"})
                except Exception:
                    continue
        finally:
            CoUninitialize()
    except Exception:
        return results
    return results

def _set_default_endpoint(device_id: str) -> bool:
    if not (_PYCAW and IS_WINDOWS and device_id):
        return False
    try:
        class IPolicyConfig(ctypes.Structure):
            _fields_ = [("lpVtbl", ctypes.c_void_p * 20)]

        IID_IPolicyConfig = GUID("{F8679F50-850A-41CF-9C72-430F290290C8}")
        CLSID_PolicyConfigClient = GUID("{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}")

        CoInitialize()
        try:
            ppv = ctypes.c_void_p()
            hr = ctypes.windll.ole32.CoCreateInstance(
                ctypes.byref(CLSID_PolicyConfigClient),
                None,
                1,  # CLSCTX_INPROC_SERVER
                ctypes.byref(IID_IPolicyConfig),
                ctypes.byref(ppv),
            )
            if hr != 0 or not ppv.value:
                return False

            iface = ctypes.c_void_p(ppv.value)

            def _call(role: int) -> bool:
                for idx in (13, 12, 14, 10):
                    try:
                        vtbl = ctypes.cast(iface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                        func = ctypes.cast(
                            vtbl[idx],
                            ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
                        )
                        hr2 = func(iface, ctypes.c_wchar_p(device_id), ctypes.c_int(role))
                        if hr2 == 0:
                            return True
                    except Exception:
                        continue
                return False

            ok = True
            for role in (0, 1, 2):  # Console, Multimedia, Communications
                ok = _call(role) and ok
            return ok
        finally:
            CoUninitialize()
    except Exception:
        return False

def audio_switch_output(name_or_id: str) -> Tuple[bool, str]:
    target = (name_or_id or "").strip()
    if not target:
        return False, "no_device"
    devices = audio_list_outputs()
    if not devices:
        return False, "no_devices"
    low = target.lower()

    for d in devices:
        if low == d["id"].lower():
            ok = _set_default_endpoint(d["id"])
            return (ok, d["name"] if ok else "set_failed")
    for d in devices:
        if low == d["name"].lower():
            ok = _set_default_endpoint(d["id"])
            return (ok, d["name"] if ok else "set_failed")
    try:
        from difflib import get_close_matches
        names = [d["name"] for d in devices]
        match = get_close_matches(target, names, n=1, cutoff=0.72)
        if match:
            chosen = match[0]
            for d in devices:
                if d["name"] == chosen:
                    ok = _set_default_endpoint(d["id"])
                    return (ok, d["name"] if ok else "set_failed")
    except Exception:
        pass
    alias = low.replace("the ", "").replace("default ", "").strip()
    for d in devices:
        if alias in d["name"].lower():
            ok = _set_default_endpoint(d["id"])
            return (ok, d["name"] if ok else "set_failed")
    return False, "device_not_found"


# -------------------------- Audio master volume (set/up/down/mute) --------------------------

def _get_endpoint_volume():
    if not (_PYCAW and IS_WINDOWS):
        return None
    try:
        CoInitialize()
        speakers = AudioUtilities.GetSpeakers()
        interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(interface, POINTER(IAudioEndpointVolume))
        return vol
    except Exception:
        try:
            CoUninitialize()
        except Exception:
            pass
        return None

def _close_volume():
    try:
        CoUninitialize()
    except Exception:
        pass

def set_volume(pct: int) -> bool:
    vol = _get_endpoint_volume()
    if not vol:
        return False
    try:
        val = clamp_0_100(pct) / 100.0
        vol.SetMasterVolumeLevelScalar(val, None)
        return True
    except Exception:
        return False
    finally:
        _close_volume()

def _adjust_volume(delta_pct: int) -> bool:
    vol = _get_endpoint_volume()
    if not vol:
        return False
    try:
        cur = vol.GetMasterVolumeLevelScalar()
        newv = clamp_0_100(int(round((cur * 100.0) + delta_pct))) / 100.0
        vol.SetMasterVolumeLevelScalar(newv, None)
        return True
    except Exception:
        return False
    finally:
        _close_volume()

def volume_up(step: int = 5) -> bool:
    return _adjust_volume(abs(int(step)))

def volume_down(step: int = 5) -> bool:
    return _adjust_volume(-abs(int(step)))

def mute() -> bool:
    vol = _get_endpoint_volume()
    if not vol:
        return False
    try:
        vol.SetMute(1, None)
        return True
    except Exception:
        return False
    finally:
        _close_volume()

def unmute() -> bool:
    vol = _get_endpoint_volume()
    if not vol:
        return False
    try:
        vol.SetMute(0, None)
        return True
    except Exception:
        return False
    finally:
        _close_volume()


# -------------------------- Brightness --------------------------

def set_brightness(pct: int) -> bool:
    if not (_HAS_SBC and IS_WINDOWS):
        return False
    try:
        sbc.set_brightness(clamp_0_100(pct))
        return True
    except Exception:
        return False

def brightness_up(step: int = 10) -> bool:
    if not (_HAS_SBC and IS_WINDOWS):
        return False
    try:
        curr = sbc.get_brightness(display=0)  # first display
        curv = curr[0] if isinstance(curr, list) else int(curr)
        sbc.set_brightness(clamp_0_100(curv + abs(int(step))))
        return True
    except Exception:
        return False

def brightness_down(step: int = 10) -> bool:
    if not (_HAS_SBC and IS_WINDOWS):
        return False
    try:
        curr = sbc.get_brightness(display=0)
        curv = curr[0] if isinstance(curr, list) else int(curr)
        sbc.set_brightness(clamp_0_100(curv - abs(int(step))))
        return True
    except Exception:
        return False


# -------------------------- Night light (software gamma, per-display) --------------------------
# Applies a warm gamma ramp on every attached display. Restores originals on "off".

_user32 = ctypes.windll.user32 if IS_WINDOWS else None
_gdi32  = ctypes.windll.gdi32  if IS_WINDOWS else None

from ctypes import wintypes

# GDI signatures
if IS_WINDOWS and _gdi32:
    _gdi32.SetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
    _gdi32.SetDeviceGammaRamp.restype  = wintypes.BOOL
    _gdi32.GetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
    _gdi32.GetDeviceGammaRamp.restype  = wintypes.BOOL
    _gdi32.CreateDCW.argtypes          = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
    _gdi32.CreateDCW.restype           = wintypes.HDC
    _gdi32.DeleteDC.argtypes           = [wintypes.HDC]
    _gdi32.DeleteDC.restype            = wintypes.BOOL

# user32 EnumDisplayDevicesW
if IS_WINDOWS and _user32:
    _user32.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    _user32.EnumDisplayDevicesW.restype  = wintypes.BOOL

DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001

class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ('cb',         wintypes.DWORD),
        ('DeviceName', wintypes.WCHAR * 32),    # e.g., '\\.\DISPLAY1'
        ('DeviceString', wintypes.WCHAR * 128),
        ('StateFlags', wintypes.DWORD),
        ('DeviceID',    wintypes.WCHAR * 128),
        ('DeviceKey',   wintypes.WCHAR * 128),
    ]

class GAMMARAMP(ctypes.Structure):
    _fields_ = [
        ("Red",   ctypes.c_ushort * 256),
        ("Green", ctypes.c_ushort * 256),
        ("Blue",  ctypes.c_ushort * 256),
    ]

# Store original ramp per display key (e.g., '\\.\DISPLAY1')
_GAMMA_ORIG_MAP: dict[str, GAMMARAMP] = {}
_GAMMA_ACTIVE: bool = False
_GAMMA_STRENGTH: int = 60  # default warmth percent

def _enum_display_devices() -> list[str]:
    """Return list of device names like '\\\\.\\DISPLAY1' that are attached to desktop."""
    names: list[str] = []
    if not (IS_WINDOWS and _user32):
        return names
    i = 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not _user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            break
        if dd.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
            name = dd.DeviceName
            if name:
                names.append(name)
        i += 1
    return names

def _open_hdcs_for_all() -> list[tuple[wintypes.HDC, str]]:
    """Open HDCs for each display device + a generic screen DC fallback."""
    hdcs: list[tuple[wintypes.HDC, str]] = []
    if not (IS_WINDOWS and _gdi32 and _user32):
        return hdcs
    # Per-display DCs
    for dev in _enum_display_devices():
        try:
            hdc = _gdi32.CreateDCW("DISPLAY", dev, None, None)
            if hdc:
                hdcs.append((hdc, dev))
        except Exception:
            continue
    # Generic screen DC as last resort
    try:
        hscr = _user32.GetDC(None)
        if hscr:
            hdcs.append((hscr, "screen"))
    except Exception:
        pass
    return hdcs

def _close_hdc(hdc: wintypes.HDC, key: str):
    try:
        if key == "screen" and _user32:
            _user32.ReleaseDC(None, hdc)
        elif _gdi32:
            _gdi32.DeleteDC(hdc)
    except Exception:
        pass

def _gamma_linear_ramp() -> GAMMARAMP:
    r = GAMMARAMP()
    for i in range(256):
        v = min(65535, i * 257)
        r.Red[i] = v; r.Green[i] = v; r.Blue[i] = v
    return r

def _gamma_warm_ramp(strength_pct: int) -> GAMMARAMP:
    s = clamp_0_100(strength_pct) / 100.0
    r_factor = 1.0
    g_factor = max(0.0, 1.0 - 0.25 * s)
    b_factor = max(0.0, 1.0 - 0.60 * s)
    r = GAMMARAMP()
    for i in range(256):
        base = i * 257
        r.Red[i]   = min(65535, int(base * r_factor))
        r.Green[i] = min(65535, int(base * g_factor))
        r.Blue[i]  = min(65535, int(base * b_factor))
    return r

def _read_current_for(hdc: wintypes.HDC) -> GAMMARAMP | None:
    buf = GAMMARAMP()
    ok = bool(_gdi32.GetDeviceGammaRamp(hdc, ctypes.byref(buf)))
    return buf if ok else None

def _apply_for_all(ramp_for_key: dict[str, GAMMARAMP] | GAMMARAMP) -> bool:
    """Apply ramp(s). If dict provided, use per-key; else use same ramp for all."""
    ok_any = False
    hdcs = _open_hdcs_for_all()
    try:
        for hdc, key in hdcs:
            try:
                ramp = ramp_for_key[key] if isinstance(ramp_for_key, dict) and key in ramp_for_key else (
                    ramp_for_key if not isinstance(ramp_for_key, dict) else _gamma_linear_ramp()
                )
                ok = bool(_gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp)))
                ok_any = ok_any or ok
            except Exception:
                continue
    finally:
        for hdc, key in hdcs:
            _close_hdc(hdc, key)
    return ok_any

def night_light_on(strength: int = 60) -> bool:
    """Enable warm tint via gamma ramp on all displays. strength: 0–100 (default 60)."""
    if not (IS_WINDOWS and _gdi32 and _user32):
        return False
    global _GAMMA_ACTIVE, _GAMMA_STRENGTH, _GAMMA_ORIG_MAP
    # Capture originals per display (once)
    if not _GAMMA_ORIG_MAP:
        hdcs = _open_hdcs_for_all()
        try:
            for hdc, key in hdcs:
                try:
                    cur = _read_current_for(hdc)
                    if cur is not None:
                        _GAMMA_ORIG_MAP[key] = cur
                except Exception:
                    continue
        finally:
            for hdc, key in hdcs:
                _close_hdc(hdc, key)
    warm = _gamma_warm_ramp(strength)
    ok = _apply_for_all(warm)
    if ok:
        _GAMMA_ACTIVE = True
        _GAMMA_STRENGTH = clamp_0_100(strength)
    return ok

def night_light_off() -> bool:
    """Restore the original gamma ramp per display (linear if unknown)."""
    if not (IS_WINDOWS and _gdi32 and _user32):
        return False
    # Build a per-key ramp map; fall back to linear for keys without saved originals
    ramp_map: dict[str, GAMMARAMP] = {}
    # Use current attached displays as keys we try to restore
    keys = _enum_display_devices()
    if not keys:
        keys = ["screen"]  # fallback
    for k in keys:
        ramp_map[k] = _GAMMA_ORIG_MAP.get(k, _gamma_linear_ramp())
    ok = _apply_for_all(ramp_map)
    if ok:
        # Keep originals cached for future toggles; just mark inactive
        global _GAMMA_ACTIVE
        _GAMMA_ACTIVE = False
    return ok

def night_light_toggle(strength: Optional[int] = None) -> bool:
    if _GAMMA_ACTIVE:
        return night_light_off()
    return night_light_on(_GAMMA_STRENGTH if strength is None else strength)

# Back-compat alias (existing code may call this)
def toggle_night_light() -> bool:
    return night_light_toggle()




# -------------------------- Power --------------------------

def sleep() -> bool:
    if not IS_WINDOWS: return False
    try:
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return True
    except Exception:
        return False

def shutdown() -> bool:
    if not IS_WINDOWS: return False
    try:
        subprocess.Popen(["shutdown", "/s", "/t", "0"])
        return True
    except Exception:
        return False

def restart() -> bool:
    if not IS_WINDOWS: return False
    try:
        subprocess.Popen(["shutdown", "/r", "/t", "0"])
        return True
    except Exception:
        return False

def lock() -> bool:
    if not IS_WINDOWS: return False
    try:
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        return True
    except Exception:
        return False


# -------------------------- Battery --------------------------

def battery_percent() -> Optional[int]:
    if not _HAS_PSUTIL:
        return None
    try:
        b = psutil.sensors_battery()
        if not b: return None
        return int(round(b.percent))
    except Exception:
        return None


# -------------------------- Window controls --------------------------

def minimize_active_window() -> bool:
    if _HAS_PYW:
        try:
            win = gw.getActiveWindow()
            if win:
                win.minimize()
                return True
        except Exception:
            pass
    if _HAS_PYAUTOGUI and IS_WINDOWS:
        try:
            pyautogui.hotkey("win", "down"); pyautogui.hotkey("win", "down")
            return True
        except Exception:
            return False
    return False

def maximize_active_window() -> bool:
    if _HAS_PYW:
        try:
            win = gw.getActiveWindow()
            if win:
                win.maximize()
                return True
        except Exception:
            pass
    if _HAS_PYAUTOGUI and IS_WINDOWS:
        try:
            pyautogui.hotkey("win", "up")
            return True
        except Exception:
            return False
    return False

def close_active_window() -> bool:
    if _HAS_PYW:
        try:
            win = gw.getActiveWindow()
            if win:
                win.close()
                return True
        except Exception:
            pass
    if _HAS_PYAUTOGUI and IS_WINDOWS:
        try:
            pyautogui.hotkey("alt", "f4")
            return True
        except Exception:
            return False
    return False


# -------------------------- Screenshot + reveal --------------------------

def screenshot(save_dir: Optional[str] = None) -> Optional[str]:
    if not (_HAS_PYAUTOGUI or _HAS_PIL):
        return None
    try:
        if _HAS_PYAUTOGUI:
            img = pyautogui.screenshot()
        else:
            return None
        base = Path(save_dir) if save_dir else Path.home() / "Pictures" / "Screenshots"
        base.mkdir(parents=True, exist_ok=True)
        fname = base / f"Screenshot_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.png"
        img.save(str(fname))
        return str(fname)
    except Exception:
        return None

def reveal_in_explorer(path: str) -> bool:
    if not (IS_WINDOWS and path):
        return False
    try:
        subprocess.Popen(["explorer", "/select,", path])
        return True
    except Exception:
        return False
