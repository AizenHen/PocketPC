import asyncio
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

import mss
from aiortc import VideoStreamTrack
from aiortc.mediastreams import MediaStreamError
from av import VideoFrame

try:
    import dxcam
except (ImportError, OSError):
    dxcam = None

diagnostic = logging.getLogger("pocketpc.diagnostic")


def dxgi_available():
    """Report library/device availability without capturing any pixels."""
    if dxcam is None:
        return False
    try:
        return bool(dxcam.output_info().strip())
    except Exception:
        return False


class ScreenTrack(VideoStreamTrack):
    """Capture only the approved monitor, preferring DXGI with a safe MSS fallback."""
    QUALITY = {
        "smooth": (1280, 20),
        "balanced": (1600, 15),
        "sharp": (1920, 12),
    }

    def __init__(self, selection: dict, cancelled: threading.Event, quality="auto"):
        super().__init__()
        self.monitor = dict(selection["region"])
        self.topology = [dict(m) for m in selection["topology"]]
        self.display = selection.get("display")
        self.cancelled = cancelled
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="PocketPC-capture")
        self.view_lock = threading.Lock()
        self.view = (1.0, 0.5, 0.5)
        self.quality = "balanced" if quality == "auto" else quality
        self.next_frame_at = None
        self.started_at = time.monotonic()
        self.closed = False
        self.camera = None
        self.mss_capture = None
        self.mss_context = None
        self.capture_backend = "Starting"
        self.capture_error = None
        self.frames_captured = 0
        self.last_capture_ms = None
        self.last_topology_check = 0.0

    def diagnostics(self):
        return {
            "backend": self.capture_backend,
            "frames": self.frames_captured,
            "capture_ms": self.last_capture_ms,
            "error": self.capture_error,
        }

    def set_view(self, zoom: float, center_x: float, center_y: float):
        with self.view_lock:
            self.view = (zoom, center_x, center_y)

    def set_quality(self, quality: str):
        with self.view_lock:
            self.quality = quality

    def _region(self):
        with self.view_lock:
            zoom, center_x, center_y = self.view
        full_width, full_height = self.monitor["width"], self.monitor["height"]
        width = max(2, int(full_width / zoom) // 2 * 2)
        height = max(2, int(full_height / zoom) // 2 * 2)
        left = round(self.monitor["left"] + center_x * full_width - width / 2)
        top = round(self.monitor["top"] + center_y * full_height - height / 2)
        left = min(self.monitor["left"] + full_width - width, max(self.monitor["left"], left))
        top = min(self.monitor["top"] + full_height - height, max(self.monitor["top"], top))
        return {"left": left, "top": top, "width": width, "height": height}

    def _check_topology(self):
        now = time.monotonic()
        if now - self.last_topology_check < 1.0:
            return
        self.last_topology_check = now
        with mss.mss() as topology_capture:
            if self.topology != topology_capture.monitors[1:]:
                raise MediaStreamError

    def _create_dxgi_camera(self):
        """Return only a DXGI output whose coordinates exactly match approval."""
        if dxcam is None:
            return None
        if not self.display:
            return None
        output_pairs = re.findall(r"Device\[(\d+)] Output\[(\d+)]", dxcam.output_info())
        expected = (
            self.monitor["left"], self.monitor["top"],
            self.monitor["left"] + self.monitor["width"],
            self.monitor["top"] + self.monitor["height"],
        )
        for device_text, output_text in output_pairs:
            camera = None
            try:
                camera = dxcam.create(
                    device_idx=int(device_text), output_idx=int(output_text),
                    output_color="BGRA", backend="dxgi", max_buffer_len=2,
                )
                rect = camera._output.desc.DesktopCoordinates
                actual = (rect.left, rect.top, rect.right, rect.bottom)
                if actual == expected:
                    return camera
            except Exception as error:
                self.capture_error = type(error).__name__
            if camera is not None:
                camera.release()
        return None

    def _initialize_capture(self):
        try:
            self.camera = self._create_dxgi_camera()
        except Exception as error:
            self.capture_error = type(error).__name__
            self.camera = None
        if self.camera is not None:
            self.capture_backend = "DXGI Desktop Duplication"
        else:
            self.mss_context = mss.mss()
            self.mss_capture = self.mss_context.__enter__()
            self.capture_backend = "MSS fallback"

    def _grab(self):
        if self.cancelled.is_set() or self.closed:
            raise MediaStreamError
        started = time.perf_counter()
        self._check_topology()
        if self.camera is None and self.mss_capture is None:
            self._initialize_capture()

        region = self._region()
        if self.camera is not None:
            # Always cache the same full approved output. Dynamic zoom crops
            # are applied below, so a static desktop can reuse this frame
            # without a second capture clock or an extra 50 ms buffer wait.
            full_frame = self.camera.grab(new_frame_only=False)
            if full_frame is None:
                full_frame = self.camera.grab(new_frame_only=True)
            if full_frame is None:
                raise MediaStreamError
            left = region["left"] - self.monitor["left"]
            top = region["top"] - self.monitor["top"]
            right = left + region["width"]
            bottom = top + region["height"]
            # The camera buffers only the approved DXGI output. Cropping that
            # stable full-display frame supports zoom on an otherwise static PC.
            pixels = full_frame[top:bottom, left:right].copy()
            frame = VideoFrame.from_ndarray(pixels, format="bgra")
        else:
            shot = self.mss_capture.grab(region)
            frame = VideoFrame(shot.width, shot.height, "bgra")
            plane = frame.planes[0]
            stride = shot.width * 4
            pixels = shot.raw
            if plane.line_size != stride:
                pixels = b"".join(
                    pixels[row * stride:(row + 1) * stride].ljust(plane.line_size, b"\0")
                    for row in range(shot.height)
                )
            plane.update(pixels)

        with self.view_lock:
            max_width, _ = self.QUALITY[self.quality]
        width = min(max_width, self.monitor["width"]) // 2 * 2
        height = max(2, int(self.monitor["height"] * width / self.monitor["width"]) // 2 * 2)
        self.frames_captured += 1
        self.last_capture_ms = round((time.perf_counter() - started) * 1000, 1)
        return frame.reformat(width=width, height=height, format="yuv420p")

    async def recv(self):
        if self.cancelled.is_set() or self.readyState != "live":
            raise MediaStreamError
        with self.view_lock:
            _, fps = self.QUALITY[self.quality]
        now = time.monotonic()
        if self.next_frame_at is None:
            self.next_frame_at = now
        await asyncio.sleep(max(0, self.next_frame_at - now))
        self.next_frame_at = max(self.next_frame_at + 1 / fps, time.monotonic())
        try:
            frame = await asyncio.get_running_loop().run_in_executor(self.executor, self._grab)
        except Exception as error:
            self.capture_error = type(error).__name__
            diagnostic.info("capture failed with %s", self.capture_error)
            self.cancelled.set()
            raise MediaStreamError
        if self.cancelled.is_set():
            raise MediaStreamError
        frame.pts = int((time.monotonic() - self.started_at) * 90000)
        frame.time_base = Fraction(1, 90000)
        return frame

    def _release_capture(self):
        if self.camera is not None:
            try:
                self.camera.release()
            except Exception:
                pass
            self.camera = None
        if self.mss_capture is not None:
            try:
                if self.mss_context is not None:
                    self.mss_context.__exit__(None, None, None)
                else:
                    self.mss_capture.close()
            except Exception:
                pass
            self.mss_capture = None
            self.mss_context = None

    def stop(self):
        if self.closed:
            return
        self.closed = True
        self.cancelled.set()
        super().stop()
        try:
            self.executor.submit(self._release_capture)
        except RuntimeError:
            pass
        self.executor.shutdown(wait=False)
