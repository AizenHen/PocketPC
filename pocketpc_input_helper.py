"""Temporary elevated PocketPC input helper. It has no network capability."""
import argparse
import ctypes
import json
from multiprocessing.connection import Client
import time

from backend.input_policy import validated_mouse_event
from backend.mouse import MouseController


def parent_alive(process_id):
    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, process_id)
    if not handle:
        return False
    result = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
    ctypes.windll.kernel32.CloseHandle(handle)
    return result == 0x00000102


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--pipe", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--left", required=True, type=int)
    parser.add_argument("--top", required=True, type=int)
    parser.add_argument("--width", required=True, type=int)
    parser.add_argument("--height", required=True, type=int)
    parser.add_argument("--parent", required=True, type=int)
    args = parser.parse_args()
    if not args.pipe.startswith(r"\\.\pipe\PocketPCInput-") or len(args.key) != 64:
        raise ValueError("Invalid helper capability")
    if not 1 <= args.width <= 32768 or not 1 <= args.height <= 32768 or not parent_alive(args.parent):
        raise ValueError("Invalid approved display or parent")
    key = bytes.fromhex(args.key)
    connection = None
    deadline = time.monotonic() + 30
    while connection is None and parent_alive(args.parent) and time.monotonic() < deadline:
        try:
            connection = Client(args.pipe, family="AF_PIPE", authkey=key)
        except FileNotFoundError:
            time.sleep(0.1)
    if connection is None:
        raise TimeoutError("PocketPC input pipe was not available")
    mouse = MouseController({"left": args.left, "top": args.top, "width": args.width, "height": args.height})
    connection.send_bytes(b'{"type":"ready"}')
    try:
        while parent_alive(args.parent):
            if not connection.poll(1):
                continue
            payload = connection.recv_bytes(4096)
            message = json.loads(payload.decode("utf-8"))
            if message == {"channel": "stop"}:
                break
            if not isinstance(message, dict) or set(message) != {"channel", "event"}:
                raise ValueError("Invalid input envelope")
            if message["channel"] == "mouse":
                mouse.apply(validated_mouse_event(message["event"]))
            else:
                raise ValueError("Input permission was not granted")
    except (BrokenPipeError, EOFError, OSError):
        pass
    finally:
        try:
            mouse.release_all()
        except OSError:
            pass
        connection.close()


if __name__ == "__main__":
    main()
