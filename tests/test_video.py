"""Synthetic-only capture and WebRTC checks. Never read the real desktop."""
import asyncio
import socket
import tempfile
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.mediastreams import MediaStreamError
from av import VideoFrame
from fastapi.testclient import TestClient

from backend.capture import ScreenTrack
from backend.security import PairingCode, local_sdp, tailscale_ipv4
from backend.server import Manager, create_app


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_zoom_crop_remains_inside_selected_display(self):
        region = {"left": 0, "top": 0, "width": 1920, "height": 1080}
        track = ScreenTrack({"region": region, "topology": [region]}, threading.Event())
        try:
            track.set_view(2, .75, .25)
            self.assertEqual(track._region(), {"left": 960, "top": 0, "width": 960, "height": 540})
            track.set_view(20, .975, .975)
            crop = track._region()
            self.assertGreaterEqual(crop["left"], region["left"])
            self.assertGreaterEqual(crop["top"], region["top"])
            self.assertLessEqual(crop["left"] + crop["width"], region["left"] + region["width"])
            self.assertLessEqual(crop["top"] + crop["height"], region["top"] + region["height"])
        finally:
            track.stop()

    async def test_exact_selected_rectangle_and_non_aligned_width(self):
        region = {"left": -1366, "top": 0, "width": 1366, "height": 768}
        other = {"left": 0, "top": 0, "width": 1920, "height": 1080}
        topology = [region, other]
        capture = MagicMock()
        capture.monitors = [{}, *topology]
        shot = MagicMock(width=1366, height=768, raw=bytes(1366 * 768 * 4))
        capture.grab.return_value = shot
        context = MagicMock()
        context.__enter__.return_value = capture
        track = ScreenTrack({"region": region, "topology": topology}, threading.Event())
        try:
            with patch("backend.capture.mss.mss", return_value=context):
                frame = await track.recv()
            capture.grab.assert_called_once_with(region)
            self.assertEqual((frame.width, frame.height), (1366, 768))
        finally:
            track.stop()

    async def test_topology_change_and_cancellation_never_grab(self):
        region = {"left": 0, "top": 0, "width": 100, "height": 100}
        capture = MagicMock()
        capture.monitors = [{}, {**region, "width": 200}]
        context = MagicMock()
        context.__enter__.return_value = capture
        track = ScreenTrack({"region": region, "topology": [region]}, threading.Event())
        try:
            with patch("backend.capture.mss.mss", return_value=context):
                with self.assertRaises(MediaStreamError):
                    await track.recv()
            capture.grab.assert_not_called()
            self.assertTrue(track.cancelled.is_set())
        finally:
            track.stop()


class SyntheticVideo(VideoStreamTrack):
    selections = []

    def __init__(self, selection, cancelled, quality="auto"):
        super().__init__()
        self.selections.append(selection)
        self.views = []

    def set_view(self, zoom, center_x, center_y):
        self.views.append((zoom, center_x, center_y))

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        frame = VideoFrame(320, 180, "yuv420p")
        for plane in frame.planes:
            plane.update(bytes([100]) * plane.buffer_size)
        frame.pts, frame.time_base = pts, time_base
        return frame


class VideoRoundTrip(unittest.IsolatedAsyncioTestCase):
    async def test_approved_h264_stream_decodes_and_stop_closes_peer(self):
        host = None
        for addresses in psutil.net_if_addrs().values():
            for address in addresses:
                if address.family == socket.AF_INET and address.netmask:
                    try:
                        tailscale_ipv4(address.address)
                    except ValueError:
                        continue
                    host = address.address
                    break
            if host:
                break
        if not host:
            self.skipTest("No Tailscale adapter for synthetic WebRTC round trip")

        class ApprovedDesktop:
            code = PairingCode()
            finished = threading.Event()

            def valid_code(self, value):
                return self.code.valid(value)

            def request_approval(self, session, peer, mouse_requested=False):
                result = Future()
                result.set_result({"synthetic": True})
                return result

            def ended(self, session, resumable_seconds=0):
                self.finished.set()

        ui = ApprovedDesktop()
        manager = Manager(ui, "pc.example.ts.net", host, 8765)
        client_pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        client_pc.addTransceiver("video", direction="recvonly")
        received = asyncio.get_running_loop().create_future()

        @client_pc.on("track")
        def on_track(track):
            received.set_result(track)

        try:
            await client_pc.setLocalDescription(await client_pc.createOffer())
            offer = local_sdp(client_pc.localDescription.sdp, host)
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
                Path(folder, "index.html").write_text("Synthetic test")
                app = create_app(manager, Path(folder))
                client = TestClient(app, base_url=manager.origin, client=("127.0.0.1", 50000))
                with patch("backend.server.ScreenTrack", SyntheticVideo):
                    with client.websocket_connect("wss://pc.example.ts.net/ws", headers={"origin": manager.origin}) as ws:
                        ws.send_json({"type": "pair", "code": ui.code.value, "quality": "auto", "mouseControl": False})
                        self.assertEqual(ws.receive_json()["type"], "pending")
                        self.assertEqual(ws.receive_json()["type"], "approved")
                        ws.send_json({"type": "offer", "sdp": offer})
                        answer = ws.receive_json()
                        self.assertEqual(answer["type"], "answer")
                        self.assertIn("H264", answer["sdp"])
                        await client_pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type="answer"))
                        track = await asyncio.wait_for(received, 10)
                        frame = await asyncio.wait_for(track.recv(), 10)
                        self.assertEqual((frame.width, frame.height), (320, 180))
                        session = manager.session
                        ws.send_json({"type": "view", "zoom": 2, "x": .25, "y": .75})
                        ws.send_json({"type": "ping"})
                        self.assertEqual(ws.receive_json(), {"type": "pong"})
                        self.assertEqual(session.track.views, [(2.0, .25, .75)])
                        ws.send_json({"type": "stop"})
                        self.assertTrue(await asyncio.to_thread(ui.finished.wait, 5))
                        self.assertTrue(session.cancelled.is_set())
                        self.assertEqual(session.pc.connectionState, "closed")
        finally:
            await client_pc.close()
