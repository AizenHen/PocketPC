"""Sanitized local-only readiness checks for the Windows Connection Assistant."""
import json
import subprocess

import httpx

from .capture import dxgi_available
from .encoding import encoder_diagnostics
from .runtime_config import CREATE_NO_WINDOW, TAILSCALE


def _tailscale_status(expected_ip):
    if not TAILSCALE.is_file():
        return False, "Tailscale is not installed"
    try:
        result = subprocess.run(
            [str(TAILSCALE), "status", "--json"], capture_output=True, text=True,
            timeout=5, check=True, creationflags=CREATE_NO_WINDOW,
        )
        status = json.loads(result.stdout)
        addresses = (status.get("Self") or {}).get("TailscaleIPs") or []
        ready = status.get("BackendState") == "Running" and expected_ip in addresses
        return ready, "Connected to the private tailnet" if ready else "Tailscale is not connected"
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return False, "Could not read Tailscale status"


def _https_status(origin):
    try:
        response = httpx.get(f"{origin}/health", timeout=4, follow_redirects=False)
        ready = response.status_code == 200 and response.json().get("status") == "ready"
        return ready, "Private HTTPS route is responding" if ready else "Private HTTPS route did not answer"
    except (httpx.HTTPError, ValueError):
        return False, "Private HTTPS route is unavailable"


def collect_diagnostics(manager):
    tailnet_ok, tailnet_detail = _tailscale_status(manager.advertise_ip)
    https_ok, https_detail = _https_status(manager.origin)
    session = manager.session
    pc_state = session.pc.connectionState if session and session.pc else None
    track_info = session.track.diagnostics() if session and session.track else None
    encoder = encoder_diagnostics()
    return {
        "tailscale": {"ok": tailnet_ok, "detail": tailnet_detail},
        "https": {"ok": https_ok, "detail": https_detail},
        "webrtc": {
            "ok": pc_state not in {"failed", "closed"},
            "detail": f"WebRTC session: {pc_state}" if pc_state else "WebRTC is ready; no active viewer",
        },
        "capture": {
            "ok": track_info is not None or dxgi_available(),
            "detail": (
                f"{track_info['backend']} · {track_info['capture_ms']} ms capture"
                if track_info and track_info.get("capture_ms") is not None else
                "DXGI Desktop Duplication is ready" if dxgi_available() else
                "DXGI unavailable; MSS fallback will be used"
            ),
        },
        "encoder": {
            "ok": True,
            "detail": encoder["label"] + (" is ready" if encoder["hardware"] else " is active"),
        },
        "security": {
            "ok": True,
            "detail": "Viewing and optional mouse control require explicit Windows approval",
        },
    }
