"""
One-command setup and launch.

Run:  python setup.py
"""

import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent
os.chdir(ROOT)

def run(cmd: list[str]) -> int:
    return subprocess.call(cmd)

def main():
    print("=" * 52)
    print("  Gold Signal Bot  —  Setup")
    print("=" * 52)

    # 1. Upgrade pip silently
    print("\n[1/3]  Upgrading pip...")
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip", "-q"])

    # 2. Install requirements
    req = ROOT / "requirements.txt"
    print("[2/3]  Installing packages...")
    result = run([sys.executable, "-m", "pip", "install", "-r", str(req)])
    if result != 0:
        print("\n  ERROR: package install failed.")
        print("  Try running as Administrator or check your internet connection.")
        input("\nPress Enter to exit.")
        sys.exit(1)

    # 3. Desktop shortcut (Windows only)
    if sys.platform == "win32":
        print("[3/3]  Creating desktop shortcut...")
        app_path = ROOT / "app.py"
        ps_cmd = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$lnk = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\\\\Gold Signal Bot.lnk'); "
            f"$lnk.TargetPath = 'pythonw.exe'; "
            f"$lnk.Arguments = '\"{app_path}\"'; "
            f"$lnk.WorkingDirectory = '{ROOT}'; "
            f"$lnk.Description = 'Gold Signal Bot'; "
            f"$lnk.Save()"
        )
        r = subprocess.call(["powershell", "-NoProfile", "-Command", ps_cmd])
        if r == 0:
            print("       Shortcut created: 'Gold Signal Bot' on Desktop")
        else:
            print("       Could not create shortcut — launch via START_BOT.bat instead")
    else:
        print("[3/3]  Skipping shortcut (not Windows)")

    print("\n" + "=" * 52)
    print("  Setup complete!")
    print("  Launch: double-click 'Gold Signal Bot' on Desktop")
    print("       or run:  pythonw app.py")
    print("=" * 52)

    # Auto-launch
    ans = input("\nLaunch the app now? [Y/n]: ").strip().lower()
    if ans in ("", "y", "yes"):
        # Use pythonw on Windows to avoid console window
        launcher = "pythonw" if sys.platform == "win32" else sys.executable
        subprocess.Popen([launcher, str(ROOT / "app.py")], cwd=str(ROOT))
        print("App launched.")

if __name__ == "__main__":
    main()
