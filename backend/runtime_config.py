"""Resolve this PC's private Tailscale identity without exposing credentials."""
import json
import os
from pathlib import Path
import subprocess


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
TAILSCALE = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"


def config_paths(project_root: Path):
    paths = [project_root / "pocketpc.local.json"]
    program_data = os.environ.get("PROGRAMDATA")
    if program_data:
        paths.append(Path(program_data) / "PocketPC" / "config.json")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        paths.append(Path(local_app_data) / "PocketPC" / "config.json")
    return paths


def tailscale_connection(project_root: Path):
    status = None
    if TAILSCALE.is_file():
        try:
            result = subprocess.run(
                [str(TAILSCALE), "status", "--json"], capture_output=True, text=True,
                check=True, creationflags=CREATE_NO_WINDOW,
            )
            status = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
    if status and status.get("BackendState") == "Running":
        local = status.get("Self") or {}
        address = next((ip for ip in local.get("TailscaleIPs", []) if ip.startswith("100.")), None)
        hostname = (local.get("DNSName") or "").rstrip(".").lower()
    else:
        saved = next((path for path in config_paths(project_root) if path.is_file()), None)
        if saved is None:
            raise RuntimeError("Tailscale details are unavailable. Run PocketPC setup once as Administrator.")
        local = json.loads(saved.read_text(encoding="utf-8-sig"))
        address = local.get("advertise_ip")
        hostname = (local.get("public_host") or "").rstrip(".").lower()
    if not address or not hostname.endswith(".ts.net"):
        raise RuntimeError("Tailscale did not provide this PC's private IP and MagicDNS name.")
    return address, hostname
