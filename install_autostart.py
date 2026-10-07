"""Fa partire Vokabel-Pop all'avvio di Windows.

    python install_autostart.py           aggiunge il collegamento in Esecuzione automatica
    python install_autostart.py --remove  lo toglie
"""

import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(BASE, "app.py")
STARTUP = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup")
LINK = os.path.join(STARTUP, "Vokabel-Pop.lnk")


def ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def install():
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        sys.exit(f"Non trovo pythonw.exe accanto a {sys.executable}")
    ps = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({ps_quote(LINK)});"
        f"$s.TargetPath = {ps_quote(pythonw)};"
        f"$s.Arguments = {ps_quote(chr(34) + SCRIPT + chr(34) + ' --minimized')};"
        f"$s.WorkingDirectory = {ps_quote(BASE)};"
        f"$s.Description = 'Vokabel-Pop';"
        f"$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    print(f"Fatto! Vokabel-Pop partirà all'avvio di Windows.\nCollegamento: {LINK}")


def remove():
    if os.path.exists(LINK):
        os.remove(LINK)
        print("Avvio automatico rimosso.")
    else:
        print("L'avvio automatico non era attivo.")


if __name__ == "__main__":
    remove() if "--remove" in sys.argv else install()
