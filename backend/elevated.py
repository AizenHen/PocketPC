"""Authenticated, local-only bridge to the temporary elevated input helper."""
import ctypes
import json
import os
from multiprocessing.connection import Listener
from pathlib import Path
import secrets
import subprocess
import sys
import threading


class ElevatedInputBroker:
    def __init__(self, region):
        self.region = {key: int(region[key]) for key in ("left", "top", "width", "height")}
        self.pipe = rf"\\.\pipe\PocketPCInput-{secrets.token_hex(16)}"
        self.key = secrets.token_bytes(32)
        self.listener = Listener(self.pipe, family="AF_PIPE", authkey=self.key)
        self.connection = None
        self.lock = threading.Lock()

    def launch(self):
        if getattr(sys, "frozen", False):
            executable = Path(sys.executable).parent / "PocketPCInput.exe"
            prefix = []
        else:
            executable = Path(sys.executable)
            prefix = [str(Path(__file__).resolve().parents[1] / "pocketpc_input_helper.py")]
        if not executable.is_file():
            self.close()
            raise RuntimeError("Elevated input helper is missing")
        arguments = [
            *prefix, "--pipe", self.pipe, "--key", self.key.hex(),
            "--left", str(self.region["left"]), "--top", str(self.region["top"]),
            "--width", str(self.region["width"]), "--height", str(self.region["height"]),
            "--parent", str(os.getpid()),
        ]
        parameters = subprocess.list2cmdline(arguments)
        shell32 = ctypes.windll.shell32
        shell32.ShellExecuteW.restype = ctypes.c_void_p
        result = shell32.ShellExecuteW(None, "runas", str(executable), parameters, str(executable.parent), 0)
        if not result or int(result) <= 32:
            self.close()
            raise PermissionError("Windows elevation was declined")

    def accept(self):
        connection = self.listener.accept()
        ready = json.loads(connection.recv_bytes(1024).decode("utf-8"))
        if ready != {"type": "ready"}:
            connection.close()
            raise RuntimeError("Elevated helper did not authenticate")
        self.connection = connection
        self.listener.close()
        self.listener = None
        return self

    def send(self, channel, event):
        payload = json.dumps({"channel": channel, "event": event}, separators=(",", ":")).encode("utf-8")
        if len(payload) > 4096:
            raise ValueError("Input message is too large")
        with self.lock:
            if not self.connection:
                raise OSError("Elevated helper is unavailable")
            self.connection.send_bytes(payload)

    def close(self):
        with self.lock:
            if self.connection:
                try:
                    self.connection.send_bytes(b'{"channel":"stop"}')
                except (BrokenPipeError, EOFError, OSError):
                    pass
                self.connection.close()
                self.connection = None
            if self.listener:
                self.listener.close()
                self.listener = None
