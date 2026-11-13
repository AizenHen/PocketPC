"""Minimal tailnet-only STUN binding responder for browser ICE discovery."""
import asyncio
import ipaddress
import logging

from aioice import stun

from .security import TAILSCALE

diagnostic = logging.getLogger("pocketpc.diagnostic")


class TailnetStunProtocol(asyncio.DatagramProtocol):
    """Return a peer's Tailscale address; ignore all other traffic."""

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        try:
            source = ipaddress.ip_address(addr[0])
            if source.version != 4 or source not in TAILSCALE or len(data) > 1024:
                return
            request = stun.parse_message(data)
            if request.message_method != stun.Method.BINDING or request.message_class != stun.Class.REQUEST:
                return
        except (ValueError, TypeError):
            return
        diagnostic.info("iPhone STUN request accepted")
        response = stun.Message(
            message_method=stun.Method.BINDING,
            message_class=stun.Class.RESPONSE,
            transaction_id=request.transaction_id,
            attributes={"XOR-MAPPED-ADDRESS": addr, "SOFTWARE": "PocketPC"},
        )
        response.add_fingerprint()
        self.transport.sendto(bytes(response), addr)
        diagnostic.info("iPhone STUN response sent")
