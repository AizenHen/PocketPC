import asyncio
import ipaddress
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from aiortc import RTCConfiguration, RTCPeerConnection, RTCRtpSender, RTCSessionDescription
from aiortc.codecs import h264 as h264_codec
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .capture import ScreenTrack
from .diagnostics import collect_diagnostics
from .elevated import ElevatedInputBroker
from .input_policy import validated_mouse_event
from .security import AttemptLimit, local_sdp, prepare_offer, validated_quality, validated_view

SESSION_GRACE_SECONDS = 300
# The dependency is pinned. This sharp-desktop profile prioritizes text clarity
# over motion while receiver REMB feedback can still lower it when required.
h264_codec.MIN_BITRATE = 2_000_000
h264_codec.MAX_BITRATE = 8_000_000
h264_codec.DEFAULT_BITRATE = 8_000_000

DIAGNOSTIC_LOG = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PocketPC" / "pocketpc-diagnostic.log"
DIAGNOSTIC_LOG.parent.mkdir(parents=True, exist_ok=True)
diagnostic = logging.getLogger("pocketpc.diagnostic")
if not diagnostic.handlers:
    handler = RotatingFileHandler(DIAGNOSTIC_LOG, maxBytes=64_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    diagnostic.addHandler(handler)
    diagnostic.setLevel(logging.INFO)
    diagnostic.propagate = False


@dataclass
class Session:
    ws: WebSocket
    quality: str = "auto"
    cancelled: threading.Event = field(default_factory=threading.Event)
    pc: RTCPeerConnection | None = None
    track: ScreenTrack | None = None
    closed: bool = False
    last_view_update: float = 0
    grant_generation: int | None = None
    mouse_control: bool = False
    input_broker: ElevatedInputBroker | None = None
    input_disabled: bool = False
    mouse_limit: AttemptLimit = field(default_factory=lambda: AttemptLimit(count=180, window=1))


@dataclass
class ResumeGrant:
    token: str
    monitor: dict
    expires: float
    generation: int
    input_broker: ElevatedInputBroker | None = None


class Manager:
    def __init__(self, ui, public_host, advertise_ip, port):
        self.ui = ui
        self.public_host = public_host.rstrip(".").lower()
        self.advertise_ip = advertise_ip
        self.port = port
        self.origin = f"https://{self.public_host}"
        self.session = None
        self.global_limit = AttemptLimit(count=60)
        self.peer_limits = {}
        self.resume_grant: ResumeGrant | None = None
        self.grant_generation = 0
        self.resume_expiry_handle = None

    def allow_attempt(self, peer):
        # A single noisy device cannot lock out the owner's iPhone. The global
        # ceiling still prevents identity rotation from brute forcing.
        if not self.global_limit.allow():
            return False
        if peer not in self.peer_limits:
            if len(self.peer_limits) >= 256:
                return False
            self.peer_limits[peer] = AttemptLimit(count=6)
        return self.peer_limits[peer].allow()

    def diagnostics(self):
        return collect_diagnostics(self)

    def allowed(self, scope, headers, websocket=False):
        try:
            peer = ipaddress.ip_address(scope["client"][0])
            if not peer.is_loopback:
                return False
        except (ValueError, KeyError, TypeError):
            return False
        allowed_hosts = {self.public_host, f"{self.public_host}:443", f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        if headers.get("host", "").lower() not in allowed_hosts:
            return False
        return not websocket or headers.get("origin") == self.origin

    @staticmethod
    def client_label(headers):
        # Tailscale Serve removes spoofed incoming identity headers before adding
        # its authenticated values. The loopback-only backend trusts that proxy.
        return headers.get("tailscale-user-login") or "Tailscale device"

    def issue_resume_grant(self, monitor, input_broker=None):
        self.grant_generation += 1
        token = secrets.token_urlsafe(32)
        self.resume_grant = ResumeGrant(
            token, monitor, time.monotonic() + SESSION_GRACE_SECONDS,
            self.grant_generation, input_broker,
        )
        self._schedule_resume_expiry()
        return token, self.grant_generation

    def _schedule_resume_expiry(self):
        if self.resume_expiry_handle:
            self.resume_expiry_handle.cancel()
        grant = self.resume_grant
        if not grant:
            self.resume_expiry_handle = None
            return
        generation = grant.generation
        delay = max(0, grant.expires - time.monotonic())
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Pure policy tests may exercise token rotation without a server loop.
            self.resume_expiry_handle = None
            return
        self.resume_expiry_handle = loop.call_later(delay, self._expire_resume_grant, generation)

    def _expire_resume_grant(self, generation):
        grant = self.resume_grant
        if grant and grant.generation == generation and time.monotonic() >= grant.expires:
            self.revoke_resume_grant()

    def consume_resume_grant(self, token):
        grant = self.resume_grant
        if not grant or not isinstance(token, str) or time.monotonic() >= grant.expires:
            if grant and grant.input_broker:
                grant.input_broker.close()
            self.resume_grant = None
            if self.resume_expiry_handle:
                self.resume_expiry_handle.cancel()
                self.resume_expiry_handle = None
            return None
        if not secrets.compare_digest(grant.token, token):
            return None
        # Rotate after every successful resume so an intercepted old value
        # cannot be replayed. The lease never extends without live activity.
        grant.token = secrets.token_urlsafe(32)
        grant.expires = time.monotonic() + SESSION_GRACE_SECONDS
        self._schedule_resume_expiry()
        return grant.monitor, grant.token, grant.generation, grant.input_broker

    def touch_resume_grant(self, session):
        grant = self.resume_grant
        if grant and grant.generation == session.grant_generation:
            grant.expires = time.monotonic() + SESSION_GRACE_SECONDS
            self._schedule_resume_expiry()

    def revoke_resume_grant(self, session=None):
        if session is None or (self.resume_grant and self.resume_grant.generation == session.grant_generation):
            if self.resume_expiry_handle:
                self.resume_expiry_handle.cancel()
                self.resume_expiry_handle = None
            if self.resume_grant and self.resume_grant.input_broker:
                self.resume_grant.input_broker.close()
            self.resume_grant = None

    async def close(self, session, keep_resume=False):
        if session.closed:
            return
        session.closed = True
        session.cancelled.set()
        broker_is_resumable = bool(
            self.resume_grant and self.resume_grant.generation == session.grant_generation
            and self.resume_grant.input_broker is session.input_broker
        )
        if session.input_broker and not (keep_resume and broker_is_resumable):
            session.input_broker.close()
        if session.track:
            session.track.stop()
        if session.pc:
            await session.pc.close()
        try:
            await session.ws.close(code=1000)
        except (RuntimeError, WebSocketDisconnect):
            pass
        if self.session is session:
            self.session = None
            if not keep_resume:
                self.revoke_resume_grant(session)
            remaining = 0
            if keep_resume and self.resume_grant and self.resume_grant.generation == session.grant_generation:
                remaining = max(0, int(self.resume_grant.expires - time.monotonic()))
            self.ui.ended(session, remaining)

    async def stop(self):
        self.revoke_resume_grant()
        if self.session:
            await self.close(self.session, keep_resume=False)


def create_app(manager: Manager, dist: Path):
    @asynccontextmanager
    async def lifespan(app):
        yield
        await manager.stop()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    index_file = dist / "index.html"
    assets_dir = dist / "assets"
    current_bundles = {
        Path(name).suffix: name
        for name in re.findall(r'/assets/([A-Za-z0-9][A-Za-z0-9._-]+)', index_file.read_text(encoding="utf-8"))
        if Path(name).suffix in {".js", ".css"}
    }

    @app.middleware("http")
    async def lan_only(request: Request, call_next):
        if not manager.allowed(request.scope, request.headers):
            return JSONResponse({"error": "LAN host only"}, status_code=403)
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
        })
        return response

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def viewer():
        return FileResponse(index_file, media_type="text/html")

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ready", "viewer": "view-with-optional-mouse", "session": "busy" if manager.session else "available"}

    @app.api_route("/assets/{filename}", methods=["GET", "HEAD"], include_in_schema=False)
    async def asset(filename: str):
        # Vite emits flat, hashed asset names. An allowlist avoids Windows path
        # resolution entirely for UNC paths, drive paths, traversal and ADS.
        if filename in (".", "..") or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", filename):
            return JSONResponse({"error": "Not found"}, status_code=404)
        suffix = Path(filename).suffix
        current = current_bundles.get(suffix)
        if current and filename.startswith("index-") and filename != current:
            # A Home Screen app can retain an older index document. Always
            # move that request to the matching bundle from this installation.
            return RedirectResponse(f"/assets/{current}", status_code=307)
        target = assets_dir / filename
        if not target.is_file():
            return JSONResponse({"error": "Not found"}, status_code=404)
        return FileResponse(target)

    @app.api_route("/{filename}", methods=["GET", "HEAD"], include_in_schema=False)
    async def web_app_file(filename: str):
        # Only the explicit install metadata emitted by Vite is exposed from
        # the distribution root; arbitrary backend paths remain unreachable.
        allowed = {
            "apple-touch-icon.png",
            "pocketpc-app-192.png",
            "pocketpc-app-512.png",
            "manifest.webmanifest",
        }
        if filename not in allowed:
            return JSONResponse({"error": "Not found"}, status_code=404)
        target = dist / filename
        if not target.is_file():
            return JSONResponse({"error": "Not found"}, status_code=404)
        media_type = "application/manifest+json" if filename == "manifest.webmanifest" else "image/png"
        return FileResponse(target, media_type=media_type)

    @app.websocket("/ws")
    async def signaling(ws: WebSocket):
        stage = "policy"
        if not manager.allowed(ws.scope, ws.headers, websocket=True):
            diagnostic.info("pairing rejected at policy")
            await ws.close(code=1008)
            return
        await ws.accept()
        diagnostic.info("pairing socket accepted")
        session = None
        keep_resume = False
        resumed_session = False
        try:
            # At most six new attempts/minute across the LAN, including idle sockets.
            if not manager.allow_attempt(ws.client.host):
                await ws.send_json({"type": "error", "message": "Too many attempts. Wait one minute."})
                return
            data = await asyncio.wait_for(ws.receive_json(), timeout=10)
            if manager.session:
                await ws.send_json({"type": "error", "message": "Windows is busy. Stop the existing request or session first."})
                return
            quality = validated_quality(data.get("quality", "auto")) if isinstance(data, dict) else "auto"
            if isinstance(data, dict) and data.get("type") == "resume" and set(data) == {"type", "token", "quality"}:
                stage = "resume-credential"
                resumed = manager.consume_resume_grant(data.get("token"))
                if not resumed:
                    diagnostic.info("resume credential rejected or expired")
                    await ws.send_json({"type": "resume-expired", "message": "The five-minute reconnect period ended. Pair again."})
                    return
                monitor, resume_token, generation, input_broker = resumed
                session = Session(
                    ws, quality=quality, grant_generation=generation,
                    mouse_control=bool(monitor.get("mouse_control", False)),
                    input_broker=input_broker,
                )
                manager.session = session
                keep_resume = True
                resumed_session = True
                await ws.send_json({
                    "type": "resumed", "resumeToken": resume_token,
                    "mouseControl": session.mouse_control,
                })
                diagnostic.info("approved session resume accepted")
            else:
                stage = "pairing-code"
                if (
                    not isinstance(data, dict) or set(data) != {"type", "code", "quality", "mouseControl"}
                    or data.get("type") != "pair" or not isinstance(data.get("mouseControl"), bool)
                    or not manager.ui.valid_code(data.get("code"))
                ):
                    diagnostic.info("pairing code rejected")
                    await ws.send_json({"type": "error", "message": "Incorrect or expired pairing code."})
                    return
                session = Session(ws, quality=quality, mouse_control=data["mouseControl"])
                manager.session = session
                stage = "windows-approval"
                diagnostic.info("pairing code accepted; waiting for Windows approval")
                await ws.send_json({"type": "pending"})
                approval = manager.ui.request_approval(
                    session, manager.client_label(ws.headers), session.mouse_control,
                )
                monitor = await asyncio.wait_for(asyncio.wrap_future(approval), timeout=45)
                if monitor is None or session.cancelled.is_set():
                    diagnostic.info("Windows approval declined or cancelled")
                    await ws.send_json({"type": "error", "message": "Sharing was declined or stopped on Windows."})
                    return
                # Neither a PeerConnection nor a capture track exists before this point.
                session.mouse_control = bool(monitor.get("mouse_control", False))
                if session.mouse_control:
                    stage = "elevated-input-approval"
                    broker = ElevatedInputBroker(
                        monitor["region"]
                    )
                    try:
                        broker.launch()
                        session.input_broker = await asyncio.wait_for(
                            asyncio.to_thread(broker.accept), timeout=45
                        )
                        diagnostic.info("temporary elevated input helper approved")
                    except (PermissionError, RuntimeError, OSError, asyncio.TimeoutError):
                        broker.close()
                        session.input_broker = None
                        session.mouse_control = False
                        monitor["mouse_control"] = False
                        diagnostic.info("temporary elevated input helper declined or unavailable")
                        manager.ui.input_unavailable(session)
                resume_token, session.grant_generation = manager.issue_resume_grant(
                    monitor, session.input_broker
                )
                keep_resume = True
                await ws.send_json({
                    "type": "approved", "resumeToken": resume_token,
                    "mouseControl": session.mouse_control,
                })
            stage = "iphone-offer"
            diagnostic.info("Windows approved; waiting for iPhone video offer")
            offer = await asyncio.wait_for(ws.receive_json(), timeout=30)
            if not isinstance(offer, dict) or offer.get("type") != "offer" or not isinstance(offer.get("sdp"), str):
                raise ValueError("Expected a video offer")
            if session.cancelled.is_set():
                return
            stage = "offer-validation"
            safe_offer = await prepare_offer(offer["sdp"])
            diagnostic.info("iPhone video offer validated")
            pc = session.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))

            @pc.on("connectionstatechange")
            async def connection_state():
                diagnostic.info("WebRTC state %s", pc.connectionState)
                if pc.connectionState == "failed":
                    await manager.close(session, keep_resume=True)

            stage = "remote-description"
            await pc.setRemoteDescription(RTCSessionDescription(sdp=safe_offer, type="offer"))
            if session.cancelled.is_set():
                return
            session.track = ScreenTrack(monitor, session.cancelled, session.quality)
            pc.addTrack(session.track)
            if resumed_session and hasattr(manager.ui, "resumed"):
                manager.ui.resumed(
                    session, monitor.get("display", 1), session.mouse_control,
                )
            h264 = [codec for codec in RTCRtpSender.getCapabilities("video").codecs if codec.mimeType.lower() == "video/h264"]
            pc.getTransceivers()[0].setCodecPreferences(h264)
            answer = await pc.createAnswer()
            stage = "windows-answer"
            await asyncio.wait_for(pc.setLocalDescription(answer), timeout=20)
            if session.cancelled.is_set():
                return
            await ws.send_json({"type": "answer", "sdp": local_sdp(pc.localDescription.sdp, manager.advertise_ip)})
            stage = "connected-session"
            diagnostic.info("Windows video answer sent")
            # A backgrounded Safari tab may pause JavaScript and heartbeats. Keep
            # the approved lease for at most five minutes, then stop capture.
            while not session.cancelled.is_set():
                message = await asyncio.wait_for(ws.receive_json(), timeout=SESSION_GRACE_SECONDS)
                if message == {"type": "stop"}:
                    keep_resume = False
                    manager.revoke_resume_grant(session)
                    break
                manager.touch_resume_grant(session)
                if message == {"type": "ping"}:
                    await ws.send_json({"type": "pong"})
                    continue
                if isinstance(message, dict) and message.get("type") == "view":
                    view = validated_view(message)
                    now = time.monotonic()
                    if now - session.last_view_update >= 1 / 30 and session.track:
                        session.track.set_view(*view)
                        session.last_view_update = now
                    continue
                if isinstance(message, dict) and set(message) == {"type", "event"} and message.get("type") == "mouse":
                    # Windows may reject SendInput on an elevated/secure desktop.
                    # Ignore already-queued touches after notifying the phone so
                    # view-only video remains alive instead of failing the session.
                    if session.input_disabled:
                        continue
                    if not session.mouse_control or not session.input_broker:
                        raise ValueError("Mouse control was not approved")
                    if not session.mouse_limit.allow():
                        continue
                    try:
                        validated_mouse_event(message["event"])
                        session.input_broker.send("mouse", message["event"])
                    except OSError:
                        session.input_broker.close()
                        session.input_broker = None
                        session.mouse_control = False
                        session.input_disabled = True
                        diagnostic.info("Windows elevated input helper became unavailable")
                        manager.ui.input_unavailable(session)
                        await ws.send_json({
                            "type": "input-disabled",
                            "message": "Windows input control ended. Video remains connected.",
                        })
                    continue
                if isinstance(message, dict) and set(message) == {"type", "preset"} and message.get("type") == "quality":
                    preset = validated_quality(message["preset"])
                    if preset == "auto":
                        preset = "balanced"
                    if session.track:
                        session.track.set_quality(preset)
                    diagnostic.info("stream quality changed to %s", preset)
                    continue
                else:
                    raise ValueError("Unsupported message")
        except WebSocketDisconnect:
            diagnostic.info("session disconnected at %s", stage)
        except asyncio.TimeoutError:
            diagnostic.info("session timed out at %s", stage)
            if stage == "connected-session":
                keep_resume = False
                manager.revoke_resume_grant(session)
            try:
                await ws.send_json({"type": "error", "message": "Request timed out. Pair again from the beginning."})
            except (RuntimeError, WebSocketDisconnect):
                pass
        except Exception as error:
            keep_resume = False
            if session:
                manager.revoke_resume_grant(session)
            # Never log SDP, codes, or pixels. End the session on any protocol/capture error.
            safe_validation_reasons = {
                "Exactly one video receiver is required",
                "Only receive-only video is supported",
                "Wait for ICE gathering before sending the offer",
                "Only Tailscale UDP candidates are supported",
                "ICE address is outside the approved private networks",
                "Expected a video offer",
                "Mouse control was not approved",
            }
            reason = str(error) if str(error) in safe_validation_reasons else type(error).__name__
            diagnostic.info("session failed at %s with %s", stage, reason)
            try:
                await ws.send_json({"type": "error", "message": "Connection failed. Check Windows and pair again."})
            except (RuntimeError, WebSocketDisconnect):
                pass
        finally:
            if session:
                await manager.close(session, keep_resume=keep_resume)
            else:
                try:
                    await ws.close()
                except (RuntimeError, WebSocketDisconnect):
                    pass

    return app
