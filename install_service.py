import os
import sys
import os
import sys

# Dependencies will be imported inside functions or after installation check


def create_background_service():
    """
    Sets up Ultron to run in the background on startup.
    1. Creates a VBS script to launch pythonw.exe (hidden).
    2. Creates a shortcut in the Windows Startup folder.
    """
    
    # 1. Identify paths
    base_dir = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(base_dir, "main.py")
    
    # Detect pythonw.exe (windowless python) in the same dir as the current python.exe
    python_exe = sys.executable
    python_dir = os.path.dirname(python_exe)
    pythonw_exe = os.path.join(python_dir, "pythonw.exe")
    
    if not os.path.exists(pythonw_exe):
        print(f"[ERROR] pythonw.exe not found at: {pythonw_exe}")
        print("Ensure you are running this from a standard Python environment or venv.")
        return

    print(f"[INFO] Project Dir: {base_dir}")
    print(f"[INFO] Pythonw:     {pythonw_exe}")
    print(f"[INFO] Script:      {main_script}")

    # 2. Create the VBS launcher
    # We use VBScript to launch the process without a console window popping up momentarily
    vbs_path = os.path.join(base_dir, "ultron_background.vbs")
    
    # Quote paths to handle spaces
    # In VBScript, to pass a string containing quotes, we must escape them by doubling them.
    # We want the final VBS line to look like: WshShell.Run """pythonw""" """main.py""", 0
    
    cmd = f'""{pythonw_exe}"" ""{main_script}""'
    
    vbs_content = f'''Set WshShell = CreateObject("WScript.Shell") 
WshShell.Run "{cmd}", 0
Set WshShell = Nothing
'''
    
    try:
        with open(vbs_path, "w") as f:
            f.write(vbs_content)
        print(f"[OK] Created VBS launcher: {vbs_path}")
    except Exception as e:
        print(f"[ERROR] Failed to create VBS file: {e}")
        return

    # 3. Create Startup Shortcut
    import winshell
    from win32com.client import Dispatch
    
    startup_folder = winshell.startup()
    shortcut_path = os.path.join(startup_folder, "UltronAssistant.lnk")
    
    try:
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = vbs_path
        shortcut.WorkingDirectory = base_dir
        shortcut.IconLocation = python_exe
        shortcut.Description = "Ultron Virtual Assistant (Background)"
        shortcut.save()
        print(f"[OK] Created Startup shortcut: {shortcut_path}")
        print("\nSUCCESS! Ultron is set to run on startup.")
        print("You can double-click 'ultron_background.vbs' to start it now without rebooting.")
        
    except Exception as e:
        print(f"[ERROR] Failed to create startup shortcut: {e}")

if __name__ == "__main__":
    # Check for dependencies
    try:
        import winshell
        import win32com
    except ImportError:
        print("Missing dependencies. Installing needed packages...")
        os.system(f"{sys.executable} -m pip install winshell pypiwin32")
        print("Dependencies installed. Retrying...")
        import winshell
        from win32com.client import Dispatch

    create_background_service()
