import tempfile
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.security import PairingCode
from backend.server import Manager, create_app


class FakeDesktop:
    def __init__(self):
        self.code = PairingCode()
        self.requested = threading.Event()
        self.approval = Future()
        self.finished = threading.Event()
        self.session = None

    def valid_code(self, code):
        return self.code.valid(code)

    def request_approval(self, session, peer, mouse_requested=False):
        self.session = session
        self.mouse_requested = mouse_requested
        self.requested.set()
        return self.approval

    def ended(self, session, resumable_seconds=0):
        self.code.rotate()
        self.finished.set()


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.ui = FakeDesktop()
        self.manager = Manager(self.ui, "pc.example.ts.net", "100.100.10.20", 8765)
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        Path(self.temp.name, "index.html").write_text("PocketPC")
        Path(self.temp.name, "assets").mkdir()
        Path(self.temp.name, "assets", "app-safe.js").write_text("safe")
        self.app = create_app(self.manager, Path(self.temp.name))
        self.client = TestClient(self.app, base_url=self.manager.origin, client=("127.0.0.1", 50000))
        self.headers = {"origin": self.manager.origin}
        self.ws_url = "wss://pc.example.ts.net/ws"

    def tearDown(self):
        self.temp.cleanup()

    def test_host_origin_and_loopback_proxy_gate(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/assets/app-safe.js").text, "safe")
        for path in ("/assets/..%5Cserver-key.pem", "/assets/%5C%5Cattacker%5Cshare", "/assets/C:%5Csecret"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get("/", headers={"host": "evil.test"}).status_code, 403)
        with TestClient(self.app, base_url=self.manager.origin, client=("100.100.10.30", 5000)) as outside:
            self.assertEqual(outside.get("/").status_code, 403)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(self.ws_url, headers={"origin": "https://evil.test"}):
                pass

    def test_wrong_code_never_requests_approval_or_captures(self):
        with patch("backend.server.ScreenTrack") as capture, patch("backend.server.RTCPeerConnection") as peer:
            with self.client.websocket_connect(self.ws_url, headers=self.headers) as ws:
                ws.send_json({"type": "pair", "code": "bad", "quality": "auto", "mouseControl": False})
                self.assertEqual(ws.receive_json()["type"], "error")
            self.assertFalse(self.ui.requested.is_set())
            capture.assert_not_called()
            peer.assert_not_called()

    def test_no_capture_while_pending_or_after_denial(self):
        with patch("backend.server.ScreenTrack") as capture, patch("backend.server.RTCPeerConnection") as peer:
            with self.client.websocket_connect(self.ws_url, headers=self.headers) as ws:
                ws.send_json({"type": "pair", "code": self.ui.code.value, "quality": "auto", "mouseControl": False})
                self.assertEqual(ws.receive_json(), {"type": "pending"})
                self.assertTrue(self.ui.requested.wait(2))
                capture.assert_not_called()
                peer.assert_not_called()
                self.ui.approval.set_result(None)
                self.assertEqual(ws.receive_json()["type"], "error")
            capture.assert_not_called()
            peer.assert_not_called()

    def test_local_stop_during_approval_prevents_capture(self):
        with patch("backend.server.ScreenTrack") as capture, patch("backend.server.RTCPeerConnection") as peer:
            with self.client.websocket_connect(self.ws_url, headers=self.headers) as ws:
                ws.send_json({"type": "pair", "code": self.ui.code.value, "quality": "auto", "mouseControl": False})
                self.assertEqual(ws.receive_json()["type"], "pending")
                self.assertTrue(self.ui.requested.wait(2))
                self.ui.session.cancelled.set()
                self.ui.approval.set_result({"left": 0, "top": 0, "width": 100, "height": 100})
                self.assertEqual(ws.receive_json()["type"], "error")
            capture.assert_not_called()
            peer.assert_not_called()

    def test_approval_alone_does_not_capture_and_data_channels_are_refused(self):
        with patch("backend.server.ScreenTrack") as capture:
            with self.client.websocket_connect(self.ws_url, headers=self.headers) as ws:
                ws.send_json({"type": "pair", "code": self.ui.code.value, "quality": "auto", "mouseControl": False})
                self.assertEqual(ws.receive_json()["type"], "pending")
                self.assertTrue(self.ui.requested.wait(2))
                self.ui.approval.set_result({"left": 20, "top": 30, "width": 100, "height": 100})
                approved = ws.receive_json()
                self.assertEqual(approved["type"], "approved")
                self.assertGreaterEqual(len(approved["resumeToken"]), 40)
                capture.assert_not_called()
                ws.send_json({"type": "offer", "sdp": "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n"})
                self.assertEqual(ws.receive_json()["type"], "error")
            capture.assert_not_called()

    def test_approved_session_resumes_without_second_windows_prompt(self):
        monitor = {"region": {"left": 0, "top": 0, "width": 100, "height": 100}, "topology": [], "display": 1}
        with patch("backend.server.ScreenTrack") as capture:
            with self.client.websocket_connect(self.ws_url, headers=self.headers) as ws:
                ws.send_json({"type": "pair", "code": self.ui.code.value, "quality": "auto", "mouseControl": False})
                self.assertEqual(ws.receive_json()["type"], "pending")
                self.assertTrue(self.ui.requested.wait(2))
                self.ui.approval.set_result(monitor)
                approved = ws.receive_json()
                token = approved["resumeToken"]
            self.assertTrue(self.ui.finished.wait(2))
            self.ui.requested.clear()
            with self.client.websocket_connect(self.ws_url, headers=self.headers) as resumed_ws:
                resumed_ws.send_json({"type": "resume", "token": token, "quality": "auto"})
                resumed = resumed_ws.receive_json()
                self.assertEqual(resumed["type"], "resumed")
                self.assertNotEqual(resumed["resumeToken"], token)
                self.assertFalse(self.ui.requested.is_set())
                resumed_ws.send_json({"type": "offer", "sdp": "invalid"})
                self.assertEqual(resumed_ws.receive_json()["type"], "error")
            capture.assert_not_called()

    def test_mouse_control_requires_explicit_request_and_windows_grant(self):
        monitor = {
            "region": {"left": 0, "top": 0, "width": 100, "height": 100},
            "topology": [], "display": 1, "mouse_control": True,
        }
        with patch("backend.server.ScreenTrack") as capture, patch("backend.server.ElevatedInputBroker") as broker_type:
            broker_type.return_value.accept.return_value = broker_type.return_value
            with self.client.websocket_connect(self.ws_url, headers=self.headers) as ws:
                ws.send_json({
                    "type": "pair", "code": self.ui.code.value,
                    "quality": "auto", "mouseControl": True,
                })
                self.assertEqual(ws.receive_json()["type"], "pending")
                self.assertTrue(self.ui.requested.wait(2))
                self.assertTrue(self.ui.mouse_requested)
                self.ui.approval.set_result(monitor)
                approved = ws.receive_json()
                self.assertEqual(approved["type"], "approved")
                self.assertTrue(approved["mouseControl"])
                ws.send_json({"type": "offer", "sdp": "invalid"})
                self.assertEqual(ws.receive_json()["type"], "error")
            capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
