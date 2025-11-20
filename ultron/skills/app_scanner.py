import os
import winreg
from pathlib import Path
from typing import Optional

# Global cache
_APP_CACHE: Optional[dict[str, str]] = None

def _scan_start_menu() -> dict[str, str]:
    """Scans Start Menu folders for .lnk files."""
    apps = {}
    # 1. System-wide
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    system_start_menu = Path(program_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    # 2. User-specific
    app_data = os.environ.get("APPDATA", r"C:\Users\Default\AppData\Roaming")
    user_start_menu = Path(app_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs"

    for base_path in [system_start_menu, user_start_menu]:
        if not base_path.exists(): continue
        for root, dirs, files in os.walk(base_path):
            for file in files:
                if file.lower().endswith(".lnk"):
                    name = file[:-4].lower()
                    full_path = os.path.join(root, file)
                    if name not in apps:
                        apps[name] = full_path
    return apps

def _scan_store_apps() -> dict[str, str]:
    """Scans Windows Store (UWP/AppX) apps."""
    apps = {}
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-Command", "Get-AppxPackage | Select-Object Name, PackageFamilyName | ConvertTo-Json"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            import json
            packages = json.loads(result.stdout)
            if not isinstance(packages, list):
                packages = [packages]
            
            for pkg in packages:
                name = pkg.get("Name", "")
                family_name = pkg.get("PackageFamilyName", "")
                if name and family_name:
                    # Extract friendly name (e.g., "OpenAI.ChatGPT-Desktop" -> "chatgpt")
                    friendly = name.lower()
                    # Remove common prefixes
                    friendly = friendly.replace("microsoft.", "").replace("openai.", "")
                    # Remove -desktop, -app suffixes
                    friendly = friendly.replace("-desktop", "").replace("-app", "")
                    # Store with the explorer.exe shell: protocol
                    apps[friendly] = f"shell:AppsFolder\\{family_name}!App"
    except Exception as e:
        print(f"[Ultron][AppScanner] Store app scan failed: {e}")
    return apps


def _scan_registry() -> dict[str, str]:
    """Scans Windows Registry for installed applications with path validation."""
    apps = {}
    roots = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]
    subkeys = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    ]
    
    for root in roots:
        for subkey in subkeys:
            try:
                with winreg.OpenKey(root, subkey) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            sub_key_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, sub_key_name) as sub_key:
                                try:
                                    name = winreg.QueryValueEx(sub_key, "DisplayName")[0]
                                    name = str(name).strip()
                                    if not name: continue
                                    
                                    # Try InstallLocation or DisplayIcon
                                    path = None
                                    try:
                                        path = winreg.QueryValueEx(sub_key, "InstallLocation")[0]
                                    except FileNotFoundError:
                                        pass
                                    
                                    if not path:
                                        try:
                                            icon = winreg.QueryValueEx(sub_key, "DisplayIcon")[0]
                                            path = icon.split(",")[0].strip('"')
                                        except FileNotFoundError:
                                            pass
                                            
                                    # CRITICAL: Validate path exists before adding to cache
                                    if path:
                                        path = str(path).strip()
                                        # Expand environment variables like %ProgramFiles%
                                        path = os.path.expandvars(path)
                                        
                                        # Only add if it's an .exe and the file actually exists
                                        if path.lower().endswith(".exe") and os.path.isfile(path):
                                            apps[name.lower()] = path
                                except FileNotFoundError:
                                    pass
                        except OSError:
                            continue
            except OSError:
                continue
    return apps

def scan_installed_apps() -> dict[str, str]:
    """
    Combines Start Menu, Registry, and Windows Store scans to find all installed apps.
    Only includes apps with valid, existing paths.
    """
    # Start with Registry (often has official names)
    apps = _scan_registry()
    
    # Add Windows Store apps (UWP/AppX packages)
    store_apps = _scan_store_apps()
    apps.update(store_apps)
    
    # Overlay Start Menu (often has user-friendly shortcuts)
    # We prefer Start Menu shortcuts for launching as they handle working dirs etc.
    sm_apps = _scan_start_menu()
    apps.update(sm_apps)
    
    return apps

def initialize_app_cache() -> dict[str, str]:
    """
    Initializes the global app cache by scanning the system.
    Call this once at startup.
    Returns the app dictionary.
    """
    global _APP_CACHE
    print("[Ultron][AppScanner] Indexing installed apps...")
    _APP_CACHE = scan_installed_apps()
    print(f"[Ultron][AppScanner] Found {len(_APP_CACHE)} installed apps.")
    return _APP_CACHE

def get_app_cache() -> dict[str, str]:
    """
    Returns the cached app dictionary.
    If cache is not initialized, initializes it first.
    """
    global _APP_CACHE
    if _APP_CACHE is None:
        initialize_app_cache()
    return _APP_CACHE

def refresh_app_cache() -> dict[str, str]:
    """
    Forces a refresh of the app cache by rescanning the system.
    """
    return initialize_app_cache()
