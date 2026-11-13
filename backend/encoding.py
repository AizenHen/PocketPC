"""Low-latency H.264 encoder selection with safe software fallback."""
import fractions
import threading

import av
from av import VideoFrame
from av.video.frame import PictureType
import aiortc.codecs as aiortc_codecs
from aiortc.codecs import h264


_lock = threading.Lock()
_selected_codec = "libx264"
_selected_label = "Software H.264"
_fallback_reason = None


ENCODER_CANDIDATES = (
    ("h264_nvenc", "NVIDIA NVENC", {
        "preset": "p1", "tune": "ull", "profile": "baseline",
        "rc": "cbr", "zerolatency": "1", "delay": "0",
    }),
    ("h264_qsv", "Intel Quick Sync", {
        "preset": "veryfast", "profile": "baseline", "look_ahead": "0",
    }),
    ("h264_amf", "AMD AMF", {
        "usage": "ultralowlatency", "profile": "baseline",
    }),
)


def _candidate_options(name):
    return next((dict(options) for codec, _label, options in ENCODER_CANDIDATES if codec == name), {})


def _make_codec(name, width, height, bitrate):
    codec = av.CodecContext.create(name, "w")
    codec.width = width
    codec.height = height
    codec.bit_rate = bitrate
    codec.pix_fmt = "yuv420p"
    codec.framerate = fractions.Fraction(h264.MAX_FRAME_RATE, 1)
    codec.time_base = fractions.Fraction(1, h264.MAX_FRAME_RATE)
    codec.gop_size = h264.MAX_FRAME_RATE * 2
    codec.max_b_frames = 0
    if name == "libx264":
        codec.options = {"level": "31", "tune": "zerolatency"}
        codec.profile = "Baseline"
    else:
        codec.options = _candidate_options(name)
    codec.open()
    return codec


def _self_test(name):
    codec = _make_codec(name, 640, 360, 2_000_000)
    frame = VideoFrame(640, 360, "yuv420p")
    frame.pts = 0
    frame.time_base = fractions.Fraction(1, h264.MAX_FRAME_RATE)
    return bool(codec.encode(frame))


def encoder_diagnostics():
    with _lock:
        return {
            "codec": _selected_codec,
            "label": _selected_label,
            "hardware": _selected_codec != "libx264",
            "fallback_reason": _fallback_reason,
        }


class PocketPCH264Encoder(h264.H264Encoder):
    """aiortc-compatible H.264 encoder that retries safely in software."""
    def __init__(self):
        super().__init__()
        with _lock:
            self.codec_name = _selected_codec

    def _reset_codec(self):
        if self.codec is not None:
            try:
                self.codec.close()
            except Exception:
                pass
        self.buffer_data = b""
        self.buffer_pts = None
        self.codec = None

    def _create_for_frame(self, frame):
        global _selected_codec, _selected_label, _fallback_reason
        try:
            self.codec = _make_codec(
                self.codec_name, frame.width, frame.height, self.target_bitrate
            )
        except Exception as error:
            if self.codec_name == "libx264":
                raise
            with _lock:
                _fallback_reason = type(error).__name__
                _selected_codec = "libx264"
                _selected_label = "Software H.264 fallback"
            self.codec_name = "libx264"
            self.codec = _make_codec(
                self.codec_name, frame.width, frame.height, self.target_bitrate
            )

    def _encode_frame(self, frame, force_keyframe):
        if self.codec and (
            frame.width != self.codec.width
            or frame.height != self.codec.height
            or abs(self.target_bitrate - self.codec.bit_rate) / self.codec.bit_rate > 0.1
        ):
            self._reset_codec()

        frame.pict_type = PictureType.I if force_keyframe else PictureType.NONE
        if self.codec is None:
            self._create_for_frame(frame)

        try:
            packets = self.codec.encode(frame)
        except Exception as error:
            if self.codec_name == "libx264":
                raise
            self._reset_codec()
            global _selected_codec, _selected_label, _fallback_reason
            with _lock:
                _fallback_reason = type(error).__name__
                _selected_codec = "libx264"
                _selected_label = "Software H.264 fallback"
            self.codec_name = "libx264"
            self._create_for_frame(frame)
            packets = self.codec.encode(frame)

        data = b"".join(bytes(packet) for packet in packets)
        if data:
            yield from self._split_bitstream(data)


def configure_h264_encoder():
    """Select a tested hardware encoder, then patch aiortc before sessions start."""
    global _selected_codec, _selected_label, _fallback_reason
    selected = None
    failures = []
    for name, label, _options in ENCODER_CANDIDATES:
        if name not in av.codecs_available:
            continue
        try:
            if _self_test(name):
                selected = (name, label)
                break
            failures.append(f"{name}: no packet")
        except Exception as error:
            failures.append(f"{name}: {type(error).__name__}")
    with _lock:
        if selected:
            _selected_codec, _selected_label = selected
            _fallback_reason = None
        else:
            _selected_codec = "libx264"
            _selected_label = "Software H.264"
            _fallback_reason = ", ".join(failures) or "No hardware encoder exposed"
    aiortc_codecs.H264Encoder = PocketPCH264Encoder
    return encoder_diagnostics()
