import os
import os

def remove_background_service():
    """
    Removes the Ultron background service setup.
    1. Deletes the shortcut from the Startup folder.
    2. Deletes the generated VBS launcher.
    """
    
    # 1. Identify paths
    import winshell
    base_dir = os.path.dirname(os.path.abspath(__file__))
    vbs_path = os.path.join(base_dir, "ultron_background.vbs")
    
    startup_folder = winshell.startup()
    shortcut_path = os.path.join(startup_folder, "UltronAssistant.lnk")
    
    print("Removing Ultron background service...")

    # 2. Remove Shortcut
    if os.path.exists(shortcut_path):
        try:
            os.remove(shortcut_path)
            print(f"[OK] Removed Startup shortcut: {shortcut_path}")
        except Exception as e:
            print(f"[ERROR] Could not remove shortcut: {e}")
    else:
        print("[INFO] Startup shortcut not found (already removed?).")

    # 3. Remove VBS Script
    if os.path.exists(vbs_path):
        try:
            os.remove(vbs_path)
            print(f"[OK] Removed VBS launcher: {vbs_path}")
        except Exception as e:
            print(f"[ERROR] Could not remove VBS file: {e}")
    else:
        print("[INFO] VBS launcher not found.")

    print("\nDone. Ultron will no longer start automatically.")
    print("Note: If Ultron is currently running, you may need to stop it manually via Task Manager (look for pythonw.exe).")

if __name__ == "__main__":
    try:
        import winshell
    except ImportError:
        print("winshell not found. Please run 'pip install winshell' first.")
        exit(1)
        
    remove_background_service()
