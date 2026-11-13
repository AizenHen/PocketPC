"""Pure policy helpers. No capture, control, or networking side effects."""
import ipaddress
import math
import secrets
import time
from collections import deque

from aioice.mdns import create_mdns_protocol
from aiortc.sdp import SessionDescription

TAILSCALE = ipaddress.ip_network("100.64.0.0/10")
QUALITY_PRESETS = {"auto", "smooth", "balanced", "sharp"}


def tailscale_ipv4(value: str) -> ipaddress.IPv4Address:
    address = ipaddress.ip_address(value)
    if address.version != 4 or address not in TAILSCALE:
        raise ValueError("Choose this PC's assigned Tailscale IPv4 address (100.64.0.0/10).")
    return address


class PairingCode:
    def __init__(self):
        self.rotate()

    def rotate(self):
        self.value = f"{secrets.randbelow(100_000_000):08d}"
        self.expires = time.monotonic() + 300

    def valid(self, value):
        return isinstance(value, str) and time.monotonic() < self.expires and secrets.compare_digest(self.value, value)


class AttemptLimit:
    """Global rolling limit also bounds memory and prevents identity rotation bypass."""
    def __init__(self, count=6, window=60):
        self.count, self.window = count, window
        self.attempts = deque()

    def allow(self):
        now = time.monotonic()
        while self.attempts and self.attempts[0] <= now - self.window:
            self.attempts.popleft()
        if len(self.attempts) >= self.count:
            return False
        self.attempts.append(now)
        return True


def validated_quality(value):
    if not isinstance(value, str) or value not in QUALITY_PRESETS:
        raise ValueError("Invalid stream quality")
    return value


def local_sdp(sdp: str, host: str) -> str:
    """Advertise only this Tailscale adapter, never LAN/public/other candidates."""
    lines = []
    for line in sdp.splitlines():
        if line.startswith("a=candidate:") and line.split()[4] != host:
            continue
        lines.append(line)
    if not any(line.startswith("a=candidate:") for line in lines):
        raise ValueError("No ICE candidate on the selected Tailscale adapter")
    return "\r\n".join(lines) + "\r\n"


async def prepare_offer(sdp: str) -> str:
    """Resolve Safari mDNS candidates and retain only Tailscale UDP hosts."""
    protocol = None
    prepared = []
    try:
        for line in sdp.splitlines():
            if not line.startswith("a=candidate:"):
                prepared.append(line)
                continue
            fields = line.split()
            if len(fields) < 8 or fields[2].lower() != "udp" or fields[7] not in ("host", "srflx"):
                continue
            candidate_ip = fields[4]
            if candidate_ip.endswith(".local"):
                if protocol is None:
                    protocol = await create_mdns_protocol()
                candidate_ip = await protocol.resolve(candidate_ip, timeout=2.0)
                if candidate_ip is None:
                    continue
            try:
                address = tailscale_ipv4(candidate_ip)
            except ValueError:
                continue
            fields[4] = str(address)
            prepared.append(" ".join(fields))
    finally:
        if protocol is not None:
            await protocol.close()
    result = "\r\n".join(prepared) + "\r\n"
    validate_offer(result)
    return result


def validate_offer(sdp: str):
    # Receive-only video only. Control uses the separately approved WSS path.
    description = SessionDescription.parse(sdp)
    if len(description.media) != 1:
        raise ValueError("Exactly one video receiver is required")
    video = description.media[0]
    if video.kind != "video" or video.direction != "recvonly":
        raise ValueError("Only receive-only video is supported")
    candidates = [candidate for media in description.media for candidate in media.ice_candidates]
    if not candidates:
        raise ValueError("Wait for ICE gathering before sending the offer")
    for candidate in candidates:
        if candidate.type not in ("host", "srflx") or candidate.protocol.lower() != "udp":
            raise ValueError("Only Tailscale UDP candidates are supported")
        tailscale_ipv4(candidate.ip)


def validated_view(message):
    """Validate a crop update from the approved browser session."""
    if not isinstance(message, dict) or set(message) != {"type", "zoom", "x", "y"} or message.get("type") != "view":
        raise ValueError("Invalid view update")
    values = message["zoom"], message["x"], message["y"]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
        raise ValueError("Invalid view update")
    zoom, center_x, center_y = map(float, values)
    half = 0.5 / zoom if zoom else float("inf")
    if not 1 <= zoom <= 20 or not half <= center_x <= 1 - half or not half <= center_y <= 1 - half:
        raise ValueError("View update is outside the approved display")
    return zoom, center_x, center_y
