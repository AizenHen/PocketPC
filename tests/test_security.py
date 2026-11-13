import unittest
from unittest.mock import patch

from aioice import stun

from backend.input_policy import validated_mouse_event
from backend.security import (AttemptLimit, PairingCode, local_sdp, tailscale_ipv4,
                              validated_quality, validated_view)
from backend.server import Manager
from backend.stun import TailnetStunProtocol


class PolicyTests(unittest.TestCase):
    def test_only_tailscale_addresses_accepted(self):
        self.assertEqual(str(tailscale_ipv4("100.64.0.1")), "100.64.0.1")
        self.assertEqual(str(tailscale_ipv4("100.127.255.254")), "100.127.255.254")
        for host in ("100.63.255.255", "100.128.0.1", "192.168.1.10", "8.8.8.8", "::1"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                tailscale_ipv4(host)

    def test_code_expires_and_rotates(self):
        code = PairingCode()
        old = code.value
        self.assertTrue(code.valid(old))
        self.assertFalse(code.valid(None))
        self.assertFalse(code.valid("bad"))
        with patch("backend.security.time.monotonic", return_value=code.expires + 1):
            self.assertFalse(code.valid(old))
        with patch("backend.security.secrets.randbelow", return_value=(int(old) + 1) % 100_000_000):
            code.rotate()
        self.assertFalse(code.valid(old))

    def test_global_rate_limit(self):
        with patch("backend.security.time.monotonic", return_value=100):
            limit = AttemptLimit()
            self.assertTrue(all(limit.allow() for _ in range(6)))
            self.assertFalse(limit.allow())
        with patch("backend.security.time.monotonic", return_value=161):
            self.assertTrue(limit.allow())

    def test_one_peer_cannot_lock_out_another(self):
        manager = Manager(None, "pc.example.ts.net", "100.100.10.20", 8765)
        with patch("backend.security.time.monotonic", return_value=100):
            self.assertTrue(all(manager.allow_attempt("192.168.1.20") for _ in range(6)))
            self.assertFalse(manager.allow_attempt("192.168.1.20"))
            self.assertTrue(manager.allow_attempt("192.168.1.21"))

    def test_resume_credentials_rotate_expire_and_revoke(self):
        manager = Manager(None, "pc.example.ts.net", "100.100.10.20", 8765)
        monitor = {"display": 1, "region": {"width": 100, "height": 100}}
        token, generation = manager.issue_resume_grant(monitor)
        resumed_monitor, rotated, resumed_generation, broker = manager.consume_resume_grant(token)
        self.assertEqual(resumed_monitor, monitor)
        self.assertEqual(resumed_generation, generation)
        self.assertNotEqual(rotated, token)
        self.assertIsNone(broker)
        self.assertIsNone(manager.consume_resume_grant(token))
        with patch("backend.server.time.monotonic", return_value=manager.resume_grant.expires + 1):
            self.assertIsNone(manager.consume_resume_grant(rotated))
        self.assertIsNone(manager.resume_grant)

    def test_only_selected_adapter_advertised(self):
        sdp = "v=0\r\na=candidate:1 1 udp 1 100.100.10.20 5000 typ host\r\na=candidate:2 1 udp 1 192.168.1.5 5001 typ host\r\n"
        result = local_sdp(sdp, "100.100.10.20")
        self.assertIn("100.100.10.20", result)
        self.assertNotIn("192.168.1.5", result)
        with self.assertRaises(ValueError):
            local_sdp(sdp, "100.100.10.21")

    def test_view_updates_stay_inside_approved_display(self):
        self.assertEqual(validated_view({"type": "view", "zoom": 2, "x": .25, "y": .75}), (2.0, .25, .75))
        for message in (
            {"type": "view", "zoom": 0, "x": .5, "y": .5},
            {"type": "view", "zoom": 21, "x": .5, "y": .5},
            {"type": "view", "zoom": 2, "x": .1, "y": .5},
            {"type": "view", "zoom": float("nan"), "x": .5, "y": .5},
            {"type": "view", "zoom": 2, "x": .5, "y": .5, "extra": 1},
        ):
            with self.subTest(message=message), self.assertRaises(ValueError):
                validated_view(message)

    def test_quality_presets_are_allowlisted(self):
        for preset in ("auto", "smooth", "balanced", "sharp"):
            self.assertEqual(validated_quality(preset), preset)
        for preset in ("", "ultra", None, 1):
            with self.subTest(preset=preset), self.assertRaises(ValueError):
                validated_quality(preset)

    def test_mouse_events_are_strictly_allowlisted_and_bounded(self):
        self.assertEqual(validated_mouse_event({"type": "move", "dx": 12.4, "dy": -9}), ("move", 12, -9))
        self.assertEqual(validated_mouse_event({"type": "position", "x": .25, "y": .75}), ("position", .25, .75))
        self.assertEqual(validated_mouse_event({"type": "click", "button": "left"}), ("click", "left"))
        self.assertEqual(validated_mouse_event({"type": "button", "button": "left", "action": "down"}), ("button", "left", "down"))
        self.assertEqual(validated_mouse_event({"type": "button", "button": "left", "action": "up"}), ("button", "left", "up"))
        self.assertEqual(validated_mouse_event({"type": "scroll", "dy": -1}), ("scroll", -1))
        for message in (
            {"type": "move", "dx": 121, "dy": 0},
            {"type": "move", "dx": float("nan"), "dy": 0},
            {"type": "position", "x": -0.01, "y": .5},
            {"type": "position", "x": .5, "y": float("nan")},
            {"type": "click", "button": "middle"},
            {"type": "button", "button": "right", "action": "down"},
            {"type": "button", "button": "left", "action": "hold"},
            {"type": "scroll", "dy": 0},
            {"type": "key", "key": "A"},
            {"type": "click", "button": "left", "extra": True},
        ):
            with self.subTest(message=message), self.assertRaises(ValueError):
                validated_mouse_event(message)


class StunTests(unittest.TestCase):
    def test_binding_response_reports_only_tailnet_source(self):
        class Transport:
            sent = []

            def sendto(self, data, address):
                self.sent.append((data, address))

        protocol = TailnetStunProtocol()
        transport = Transport()
        protocol.connection_made(transport)
        request = stun.Message(stun.Method.BINDING, stun.Class.REQUEST)
        request.add_fingerprint()
        protocol.datagram_received(bytes(request), ("192.168.1.20", 50000))
        self.assertEqual(transport.sent, [])
        protocol.datagram_received(bytes(request), ("100.94.137.92", 50000))
        self.assertEqual(len(transport.sent), 1)
        response = stun.parse_message(transport.sent[0][0])
        self.assertEqual(response.transaction_id, request.transaction_id)
        self.assertEqual(response.attributes["XOR-MAPPED-ADDRESS"], ("100.94.137.92", 50000))


if __name__ == "__main__":
    unittest.main()
