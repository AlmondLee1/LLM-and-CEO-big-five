from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def ensure_environment(root=ROOT):
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11 or newer is required")
    import tkinter

    environment = root / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        print("Preparing the project environment...", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    requirements = root / "config" / "requirements.txt"
    expected = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = environment / ".requirements.sha256"
    current = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
    probe = subprocess.run([str(python), "-c", "import tkinter, openai, openpyxl"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if current != expected or probe.returncode:
        print("Installing dependencies (internet access is needed on first launch)...", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(requirements)], check=True)
        marker.write_text(expected + "\n", encoding="utf-8")
    return python


def main():
    try:
        python = ensure_environment()
        runtime = ROOT / ".runtime"
        runtime.mkdir(exist_ok=True)
        environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        if os.name == "nt":
            python = python.with_name("pythonw.exe")
        with (runtime / "launcher.log").open("a", encoding="utf-8") as log:
            subprocess.Popen([str(python), "-m", "app.window"], cwd=ROOT, env=environment,
                             stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=os.name != "nt",
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except Exception as exc:
        print(f"Unable to start: {exc}", file=sys.stderr)
        print("Install Python with Tcl/Tk and pip, and check your internet connection.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
