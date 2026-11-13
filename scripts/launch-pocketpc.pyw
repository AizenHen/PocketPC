"""Console-free Windows launcher used by the PocketPC desktop shortcut."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TAILSCALE = Path(r"C:\Program Files\Tailscale\tailscale.exe")
LOCAL_CONFIG = PROJECT_ROOT / "pocketpc.local.json"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
NULL_STREAM = open(os.devnull, "w", encoding="utf-8")
if sys.stdout is None:
    sys.stdout = NULL_STREAM
if sys.stderr is None:
    sys.stderr = NULL_STREAM


def show_error(message):
    ctypes.windll.user32.MessageBoxW(None, message, "PocketPC could not start", 0x10)


def tailscale_connection():
    status = None
    if TAILSCALE.is_file():
        try:
            result = subprocess.run(
                [str(TAILSCALE), "status", "--json"],
                capture_output=True,
                text=True,
                check=True,
                creationflags=CREATE_NO_WINDOW,
            )
            status = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
    if status and status.get("BackendState") == "Running":
        local = status.get("Self") or {}
        address = next((ip for ip in local.get("TailscaleIPs", []) if ip.startswith("100.")), None)
        hostname = (local.get("DNSName") or "").rstrip(".").lower()
    elif LOCAL_CONFIG.is_file():
        local = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
        address = local.get("advertise_ip")
        hostname = (local.get("public_host") or "").rstrip(".").lower()
    else:
        raise RuntimeError("Tailscale details are unavailable. Run scripts\\setup-tailscale.ps1 once as Administrator.")
    if not address or not hostname.endswith(".ts.net"):
        raise RuntimeError("Tailscale did not provide this PC's private IP and MagicDNS name.")
    return address, hostname


def launch():
    address, hostname = tailscale_connection()
    python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise RuntimeError("PocketPC's Python environment is missing. Follow README.md installation first.")
    command = [
        str(python), "-m", "backend.main",
        "--public-host", hostname,
        "--advertise-ip", address,
        "--port", "8765",
        "--stun-port", "3478",
    ]
    result = subprocess.run(command, cwd=PROJECT_ROOT, creationflags=CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("PocketPC stopped unexpectedly. Restart the app and check Tailscale.")


if __name__ == "__main__":
    try:
        launch()
    except SystemExit as error:
        if error.code:
            show_error("PocketPC could not start. Check that the frontend is built and restart the app.")
    except Exception as error:
        show_error(str(error))
