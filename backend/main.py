import argparse
import asyncio
import ctypes
from pathlib import Path
import socket
import subprocess
import sys
import threading
import tkinter as tk

import psutil
import uvicorn

from .desktop import Desktop
from .encoding import configure_h264_encoder
from .runtime_config import tailscale_connection
from .security import tailscale_ipv4
from .server import Manager, create_app
from .stun import TailnetStunProtocol

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
ERROR_ALREADY_EXISTS = 183
SINGLE_INSTANCE_MUTEX = "Local\\PocketPC.ScreenViewer.SingleInstance"


def acquire_single_instance():
    """Keep one installed PocketPC window and one pairing-code authority."""
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        ctypes.windll.user32.MessageBoxW(
            0,
            "PocketPC is already open. Use the existing window from the taskbar or system tray.",
            "PocketPC",
            0x40,
        )
        return False
    return handle


def release_single_instance(handle):
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)


def configure_windows_app_identity():
    """Give the Python-hosted window its own Windows taskbar identity."""
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PocketPC.ScreenViewer")


def assigned_tailscale_ip(host):
    tailscale_ipv4(host)
    for addresses in psutil.net_if_addrs().values():
        for address in addresses:
            if address.family == socket.AF_INET and address.address == host:
                return host
    raise ValueError("--advertise-ip must be the Tailscale IPv4 assigned to this Windows computer")


def main():
    instance_handle = acquire_single_instance()
    if instance_handle is False:
        return
    configure_windows_app_identity()
    configure_h264_encoder()
    parser = argparse.ArgumentParser(description="PocketPC Tailscale-only Windows screen viewer")
    parser.add_argument("--public-host", help="This PC's MagicDNS name, such as pc.example.ts.net")
    parser.add_argument("--advertise-ip", help="This PC's Tailscale IPv4 address")
    parser.add_argument("--port", type=int, default=8765, help="Loopback port used behind Tailscale Serve")
    parser.add_argument("--stun-port", type=int, default=3478, help="Tailnet-only STUN discovery port")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("PocketPC v1 capture requires an interactive Windows desktop")
    if bool(args.public_host) != bool(args.advertise_ip):
        parser.error("Provide both --public-host and --advertise-ip, or neither")
    if not args.public_host:
        try:
            args.advertise_ip, args.public_host = tailscale_connection(ROOT)
        except RuntimeError as error:
            parser.error(str(error))
    try:
        assigned_tailscale_ip(args.advertise_ip)
    except ValueError as error:
        parser.error(str(error))
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port from 1024 to 65535")
    if not 1024 <= args.stun_port <= 65535 or args.stun_port == args.port:
        parser.error("Choose a distinct STUN port from 1024 to 65535")
    dist = ROOT / "frontend/dist"
    if not (dist / "index.html").is_file():
        parser.error("Build the frontend first; see README.md")
    root = tk.Tk()
    public_host = args.public_host.rstrip(".").lower()
    if not public_host.endswith(".ts.net") or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-." for char in public_host):
        parser.error("--public-host must be this PC's Tailscale .ts.net MagicDNS name")
    ui = Desktop(root, f"https://{public_host}")
    manager = Manager(ui, public_host, args.advertise_ip, args.port)
    ui.diagnostics_provider = manager.diagnostics
    loop = asyncio.new_event_loop()
    config = uvicorn.Config(create_app(manager, dist), host="127.0.0.1", port=args.port,
                            ws_max_size=65536, ws_max_queue=4, access_log=False,
                            proxy_headers=False, server_header=False, log_level="warning",
                            log_config=None)
    server = uvicorn.Server(config)

    async def serve_all():
        transport, _ = await loop.create_datagram_endpoint(
            TailnetStunProtocol, local_addr=(args.advertise_ip, args.stun_port)
        )
        try:
            await server.serve()
        finally:
            transport.close()

    def serve():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(serve_all())
        except (Exception, SystemExit):
            ui.events.put(("error", "Server stopped or failed to bind. Check Tailscale Serve and restart PocketPC."))
        finally:
            loop.run_until_complete(manager.stop())
            loop.close()

    def stop():
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.stop(), loop)

    restart_requested = False

    def restart():
        nonlocal restart_requested
        if restart_requested:
            return
        restart_requested = True
        ui.quit()

    ui.on_stop = stop
    ui.on_restart = restart
    thread = threading.Thread(target=serve, name="PocketPC-Loopback", daemon=True)
    thread.start()
    try:
        root.mainloop()
    finally:
        if manager.session:
            manager.session.cancelled.set()
        server.should_exit = True
        thread.join(timeout=8)
    if restart_requested:
        # Release before starting the replacement process. This keeps language
        # changes automatic without briefly creating two pairing-code owners.
        release_single_instance(instance_handle)
        instance_handle = None
        if getattr(sys, "frozen", False):
            command = [sys.executable, *sys.argv[1:]]
            working_directory = Path(sys.executable).parent
        else:
            command = [sys.executable, "-m", "backend.main", *sys.argv[1:]]
            working_directory = ROOT
        subprocess.Popen(
            command,
            cwd=working_directory,
            close_fds=True,
            creationflags=(
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                if sys.platform == "win32" else 0
            ),
        )
    release_single_instance(instance_handle)


if __name__ == "__main__":
    main()
