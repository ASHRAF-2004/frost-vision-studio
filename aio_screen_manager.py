#!/usr/bin/env python3
"""Standalone media-and-metrics studio for the 480x480 Frost Vision display."""

import json
import ctypes
import fcntl
import functools
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time

import cairo
import gi
from PIL import Image, ImageDraw, ImageFont, ImageSequence
import vlc

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402


APP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path.home() / ".config" / "aio-screen-manager"
CONFIG_FILE = CONFIG_DIR / "settings.json"
AUTOSTART_FILE = Path.home() / ".config" / "autostart" / "aio-screen-manager.desktop"
DESKTOP_ID = "aio-screen-manager.desktop"
PANEL_SIZE = 480
FRAMEBUFFER = Path("/dev/fb1")
RENDERER_PID = CONFIG_DIR / "renderer.pid"
RENDERER_LOG = CONFIG_DIR / "renderer.log"
FBIOGET_VSCREENINFO = 0x4600
FBIOPUT_VSCREENINFO = 0x4601
FB_ACTIVATE_FORCE = 128
FONT_REGULAR = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"

OVERLAY_DEFAULTS = {
    "cpu_temp": {
        "name": "CPU temperature",
        "x": 120,
        "y": 390,
        "size": 28,
        "color": "#FFFFFF",
        "font": "Noto Sans",
        "bold": True,
        "prefix": "CPU ",
    },
    "gpu_temp": {
        "name": "GPU temperature",
        "x": 360,
        "y": 390,
        "size": 28,
        "color": "#FFFFFF",
        "font": "Noto Sans",
        "bold": True,
        "prefix": "GPU ",
    },
    "cpu_usage": {
        "name": "CPU usage",
        "x": 120,
        "y": 430,
        "size": 22,
        "color": "#7FE8D5",
        "font": "Noto Sans",
        "bold": True,
        "prefix": "CPU ",
    },
    "gpu_usage": {
        "name": "GPU usage",
        "x": 360,
        "y": 430,
        "size": 22,
        "color": "#7FE8D5",
        "font": "Noto Sans",
        "bold": True,
        "prefix": "GPU ",
    },
    "clock": {
        "name": "Clock",
        "x": 240,
        "y": 48,
        "size": 30,
        "color": "#FFFFFF",
        "font": "Noto Sans",
        "bold": True,
        "prefix": "",
    },
}


def load_settings():
    defaults = {
        "media_type": "none",
        "media_path": "",
        "overlays": {
            "cpu_temp": True,
            "gpu_temp": True,
            "cpu_usage": False,
            "gpu_usage": False,
            "clock": True,
        },
        "overlay_position": "bottom",
        "overlay_styles": {
            key: dict(value) for key, value in OVERLAY_DEFAULTS.items()
        },
        "background_transform": {
            "rotation": 0,
            "flip_horizontal": False,
            "flip_vertical": False,
        },
        "autostart": False,
    }
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        defaults.update(saved)
        defaults["overlays"] = {
            **defaults["overlays"],
            **saved.get("overlays", {}),
        }
        saved_styles = saved.get("overlay_styles", {})
        defaults["overlay_styles"] = {
            key: {**value, **saved_styles.get(key, {})}
            for key, value in OVERLAY_DEFAULTS.items()
        }
        defaults["background_transform"] = {
            **defaults["background_transform"],
            **saved.get("background_transform", {}),
        }
        if not defaults["media_path"] and saved.get("image"):
            defaults["media_type"] = "image"
            defaults["media_path"] = saved["image"]
    except (OSError, ValueError, TypeError):
        pass
    return defaults


def save_settings(settings):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def cpu_temperature():
    """Prefer AMD k10temp Tctl, then fall back to any plausible sensor."""
    candidates = []
    for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            chip = (hwmon / "name").read_text().strip()
        except OSError:
            chip = ""
        for source in hwmon.glob("temp*_input"):
            try:
                value = float(source.read_text().strip()) / 1000.0
            except (OSError, ValueError):
                continue
            label_file = source.with_name(source.name.replace("_input", "_label"))
            try:
                label = label_file.read_text().strip()
            except OSError:
                label = ""
            priority = 0 if chip == "k10temp" and label == "Tctl" else 1
            if 0.0 < value < 125.0:
                candidates.append((priority, value))
    return min(candidates)[1] if candidates else None


_last_cpu_times = None


def cpu_usage():
    global _last_cpu_times
    try:
        values = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    except (OSError, ValueError, IndexError):
        return 0.0
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    previous = _last_cpu_times
    _last_cpu_times = (idle, total)
    if not previous or total <= previous[1]:
        count = os.cpu_count() or 1
        return min(100.0, os.getloadavg()[0] * 100.0 / count)
    idle_delta = idle - previous[0]
    total_delta = total - previous[1]
    return max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta)))


def gpu_temperature():
    values = []
    for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            if (hwmon / "name").read_text().strip() != "amdgpu":
                continue
        except OSError:
            continue
        for source in hwmon.glob("temp*_input"):
            label = source.with_name(source.name.replace("_input", "_label"))
            try:
                if label.exists() and label.read_text().strip() != "edge":
                    continue
                value = float(source.read_text().strip()) / 1000.0
            except (OSError, ValueError):
                continue
            if 0.0 < value < 125.0:
                values.append(value)
    return max(values) if values else None


def gpu_usage():
    values = []
    for source in Path("/sys/class/drm").glob("card*/device/gpu_busy_percent"):
        try:
            values.append(float(source.read_text().strip()))
        except (OSError, ValueError):
            pass
    return max(values) if values else 0.0


def usb_display_present():
    for device in Path("/sys/bus/usb/devices").glob("*"):
        try:
            vendor = (device / "idVendor").read_text().strip().lower()
            product = (device / "idProduct").read_text().strip().lower()
        except OSError:
            continue
        if vendor == "345f" and product == "9132":
            return True
    return False


def connected_outputs():
    try:
        result = subprocess.run(
            ["xrandr", "--query"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    outputs = []
    pattern = re.compile(
        r"^(?P<name>\S+) connected(?: primary)?"
        r"(?: (?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+))?"
    )
    for line in result.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        values = match.groupdict()
        outputs.append(
            {
                "name": values["name"],
                "width": int(values["w"] or 0),
                "height": int(values["h"] or 0),
                "x": int(values["x"] or 0),
                "y": int(values["y"] or 0),
            }
        )
    return outputs


def aio_output():
    outputs = connected_outputs()
    square = [
        output
        for output in outputs
        if output["width"] == PANEL_SIZE and output["height"] == PANEL_SIZE
    ]
    if square:
        return square[0]
    non_primary = [output for output in outputs if output["width"] <= 800]
    return non_primary[0] if non_primary else None


def font(size, bold=False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def centered_text(draw, xy, value, text_font, fill):
    box = draw.textbbox((0, 0), value, font=text_font)
    width = box[2] - box[0]
    draw.text((xy[0] - width / 2, xy[1]), value, font=text_font, fill=fill)


def gradient_background():
    image = Image.new("RGB", (PANEL_SIZE, PANEL_SIZE))
    pixels = image.load()
    for y in range(PANEL_SIZE):
        for x in range(PANEL_SIZE):
            distance = min(
                1.0,
                math.sqrt((x - 240) ** 2 + (y - 210) ** 2) / 360.0,
            )
            pixels[x, y] = (
                int(12 * (1 - distance) + 2),
                int(32 * (1 - distance) + 5),
                int(49 * (1 - distance) + 9),
            )
    return image


def cover_image(source):
    if source.mode in ("RGBA", "LA") or "transparency" in source.info:
        source = source.convert("RGBA")
        alpha_bounds = source.getchannel("A").getbbox()
        if alpha_bounds:
            source = source.crop(alpha_bounds)
        background = Image.new("RGBA", source.size, (0, 0, 0, 255))
        source = Image.alpha_composite(background, source).convert("RGB")
    else:
        source = source.convert("RGB")
    scale = max(PANEL_SIZE / source.width, PANEL_SIZE / source.height)
    size = (max(PANEL_SIZE, int(source.width * scale)), max(PANEL_SIZE, int(source.height * scale)))
    source = source.resize(size, Image.Resampling.LANCZOS)
    left = (source.width - PANEL_SIZE) // 2
    top = (source.height - PANEL_SIZE) // 2
    return source.crop((left, top, left + PANEL_SIZE, top + PANEL_SIZE))


def overlay_items(settings):
    enabled = settings.get("overlays", {})
    items = []
    if enabled.get("cpu_temp"):
        value = cpu_temperature()
        items.append(("CPU", "--°C" if value is None else f"{value:.0f}°C"))
    if enabled.get("gpu_temp"):
        value = gpu_temperature()
        items.append(("GPU", "--°C" if value is None else f"{value:.0f}°C"))
    if enabled.get("cpu_usage"):
        items.append(("CPU", f"{cpu_usage():.0f}%"))
    else:
        cpu_usage()
    if enabled.get("gpu_usage"):
        items.append(("GPU", f"{gpu_usage():.0f}%"))
    if enabled.get("clock"):
        items.append(("", time.strftime("%I:%M %p")))
    return items


def metric_value(key):
    if key == "cpu_temp":
        value = cpu_temperature()
        return "--°C" if value is None else f"{value:.0f}°C"
    if key == "gpu_temp":
        value = gpu_temperature()
        return "--°C" if value is None else f"{value:.0f}°C"
    if key == "cpu_usage":
        return f"{cpu_usage():.0f}%"
    if key == "gpu_usage":
        return f"{gpu_usage():.0f}%"
    if key == "clock":
        return time.strftime("%I:%M %p")
    return ""


@functools.lru_cache(maxsize=64)
def resolve_font(family, bold):
    pattern = family or "Noto Sans"
    if bold:
        pattern += ":style=Bold"
    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{file}", pattern],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        path = result.stdout.strip()
        if path and Path(path).is_file():
            return path
    except (OSError, subprocess.SubprocessError):
        pass
    return FONT_BOLD if bold else FONT_REGULAR


def parse_color(value):
    value = str(value or "#FFFFFF").lstrip("#")
    try:
        if len(value) == 6:
            return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4)) + (255,)
        if len(value) == 8:
            return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4, 6))
    except ValueError:
        pass
    return (255, 255, 255, 255)


def transform_background(background, settings):
    transform = settings.get("background_transform", {})
    image = background.convert("RGB")
    rotation = int(transform.get("rotation", 0)) % 360
    if rotation:
        image = image.rotate(-rotation, resample=Image.Resampling.BICUBIC, expand=False)
    if transform.get("flip_horizontal"):
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if transform.get("flip_vertical"):
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return image


def add_overlays(background, settings):
    canvas = background.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    enabled = settings.get("overlays", {})
    styles = settings.get("overlay_styles", {})
    for key in OVERLAY_DEFAULTS:
        if not enabled.get(key):
            if key == "cpu_usage":
                cpu_usage()
            continue
        style = {**OVERLAY_DEFAULTS[key], **styles.get(key, {})}
        value = f"{style.get('prefix', '')}{metric_value(key)}"
        size = max(8, min(120, int(style.get("size", 28))))
        text_font = ImageFont.truetype(
            resolve_font(style.get("font", "Noto Sans"), bool(style.get("bold"))),
            size,
        )
        draw.text(
            (
                max(0, min(PANEL_SIZE, int(style.get("x", 240)))),
                max(0, min(PANEL_SIZE, int(style.get("y", 240)))),
            ),
            value,
            font=text_font,
            fill=parse_color(style.get("color")),
            anchor="mm",
        )
    return canvas.convert("RGB")


class VideoBackground:
    """Decode a looping video to a 480x480 in-memory frame with libVLC."""

    def __init__(self, path):
        self.path = path
        self.frame_size = PANEL_SIZE * PANEL_SIZE * 4
        self.buffer = (ctypes.c_ubyte * self.frame_size)()
        self.buffer_lock = threading.Lock()
        self.have_frame = False
        self.instance = vlc.Instance("--no-audio", "--no-video-title-show", "--quiet")
        self.player = self.instance.media_player_new()
        media = self.instance.media_new_path(path)
        media.add_option("input-repeat=65535")
        self.player.set_media(media)

        @vlc.CallbackDecorators.VideoLockCb
        def lock_callback(_opaque, planes):
            self.buffer_lock.acquire()
            planes[0] = ctypes.addressof(self.buffer)
            return None

        @vlc.CallbackDecorators.VideoUnlockCb
        def unlock_callback(_opaque, _picture, _planes):
            self.buffer_lock.release()

        @vlc.CallbackDecorators.VideoDisplayCb
        def display_callback(_opaque, _picture):
            self.have_frame = True

        self.callbacks = (lock_callback, unlock_callback, display_callback)
        self.player.video_set_callbacks(*self.callbacks, None)
        self.player.video_set_format("RV32", PANEL_SIZE, PANEL_SIZE, PANEL_SIZE * 4)
        self.player.play()

    def frame(self):
        state = self.player.get_state()
        if state in (vlc.State.Ended, vlc.State.Error, vlc.State.Stopped):
            self.player.stop()
            self.player.play()
        if not self.have_frame:
            return None
        with self.buffer_lock:
            data = bytes(self.buffer)
        return Image.frombytes("RGB", (PANEL_SIZE, PANEL_SIZE), data, "raw", "BGRX")

    def close(self):
        self.player.stop()
        self.player.release()
        self.instance.release()


def is_animated_image(path):
    try:
        with Image.open(path) as source:
            return bool(getattr(source, "is_animated", False) and source.n_frames > 1)
    except (OSError, ValueError):
        return False


class AnimatedImageBackground:
    """Decode an animated GIF and preserve its per-frame timing."""

    def __init__(self, path):
        self.frames = []
        self.durations = []
        with Image.open(path) as source:
            if not getattr(source, "is_animated", False) or source.n_frames < 2:
                raise ValueError("The selected image is not animated")
            default_duration = max(20, int(source.info.get("duration", 100)))
            for source_frame in ImageSequence.Iterator(source):
                duration = max(
                    20,
                    int(source_frame.info.get("duration", default_duration)),
                )
                self.frames.append(cover_image(source_frame.convert("RGBA")))
                self.durations.append(duration / 1000.0)
        if not self.frames:
            raise ValueError("The animated image contains no frames")
        self.index = 0
        self.deadline = time.monotonic() + self.durations[0]

    def frame(self):
        now = time.monotonic()
        advanced = 0
        while now >= self.deadline and advanced < len(self.frames):
            self.index = (self.index + 1) % len(self.frames)
            self.deadline += self.durations[self.index]
            advanced += 1
        if advanced == len(self.frames) and now >= self.deadline:
            self.deadline = now + self.durations[self.index]
        return self.frames[self.index]

    def close(self):
        self.frames.clear()
        self.durations.clear()


def static_background(settings):
    path = settings.get("media_path", "")
    if settings.get("media_type") == "image" and path:
        try:
            with Image.open(path) as source:
                return cover_image(source)
        except (OSError, ValueError):
            pass
    return gradient_background()


def render_frame(settings, background=None):
    transformed = transform_background(
        background or static_background(settings),
        settings,
    )
    return add_overlays(transformed, settings)


class VmaxUsbDisplay:
    """Direct userspace implementation of Vmax's MS9132 picture path."""

    VID = 0x345F
    PID = 0x9132
    HID_INTERFACE = 0
    BULK_INTERFACE = 3
    BULK_ENDPOINT = 0x04

    def __init__(self):
        self.usb = ctypes.CDLL("libusb-1.0.so.0")
        self._declare_libusb()
        self.context = ctypes.c_void_p()
        self.handle = ctypes.c_void_p()
        self.frame_index = 0
        self.first_frame = True
        result = self.usb.libusb_init(ctypes.byref(self.context))
        if result:
            raise OSError(f"libusb initialization failed ({result})")
        self.handle = self.usb.libusb_open_device_with_vid_pid(
            self.context, self.VID, self.PID
        )
        if not self.handle:
            self.close()
            raise PermissionError(
                "Cannot open the VMAX USB device. Check its udev permission rule."
            )
        self.usb.libusb_set_auto_detach_kernel_driver(self.handle, 1)
        result = self.usb.libusb_claim_interface(self.handle, self.HID_INTERFACE)
        if result:
            self.close()
            raise OSError(f"Cannot claim VMAX HID interface 0 ({result})")
        result = self.usb.libusb_claim_interface(self.handle, self.BULK_INTERFACE)
        if result:
            self.close()
            raise OSError(f"Cannot claim VMAX USB interface 3 ({result})")
        self.configure()

    def _declare_libusb(self):
        byte_pointer = ctypes.POINTER(ctypes.c_ubyte)
        self.usb.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self.usb.libusb_init.restype = ctypes.c_int
        self.usb.libusb_exit.argtypes = [ctypes.c_void_p]
        self.usb.libusb_open_device_with_vid_pid.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint16,
            ctypes.c_uint16,
        ]
        self.usb.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
        self.usb.libusb_close.argtypes = [ctypes.c_void_p]
        self.usb.libusb_set_auto_detach_kernel_driver.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self.usb.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.usb.libusb_claim_interface.restype = ctypes.c_int
        self.usb.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.usb.libusb_control_transfer.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint8,
            ctypes.c_uint8,
            ctypes.c_uint16,
            ctypes.c_uint16,
            byte_pointer,
            ctypes.c_uint16,
            ctypes.c_uint,
        ]
        self.usb.libusb_control_transfer.restype = ctypes.c_int
        self.usb.libusb_bulk_transfer.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ubyte,
            byte_pointer,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_uint,
        ]
        self.usb.libusb_bulk_transfer.restype = ctypes.c_int

    @staticmethod
    def _buffer(data):
        return (ctypes.c_ubyte * len(data)).from_buffer_copy(data)

    def _hid_write(self, command, subcommand, payload=b""):
        report = bytes((command, subcommand)) + bytes(payload)
        report = report[:8].ljust(8, b"\0")
        buffer = self._buffer(report)
        result = self.usb.libusb_control_transfer(
            self.handle, 0x21, 0x09, 0x0300, 0, buffer, 8, 2000
        )
        if result != 8:
            raise OSError(f"VMAX HID command {command:02x}/{subcommand:02x} failed ({result})")

    def _read_xdata(self, address):
        report = self._buffer(
            bytes((0xB5, (address >> 8) & 0xFF, address & 0xFF, 0, 0, 0, 0, 0))
        )
        result = self.usb.libusb_control_transfer(
            self.handle, 0x21, 0x09, 0x0300, 0, report, 8, 2000
        )
        if result != 8:
            raise OSError(f"VMAX XDATA request failed ({result})")
        result = self.usb.libusb_control_transfer(
            self.handle, 0xA1, 0x01, 0x0300, 0, report, 8, 2000
        )
        if result != 8:
            raise OSError(f"VMAX XDATA response failed ({result})")
        return report[3]

    def _write_xdata(self, address, value):
        report = self._buffer(
            bytes(
                (
                    0xB6,
                    (address >> 8) & 0xFF,
                    address & 0xFF,
                    value & 0xFF,
                    0,
                    0,
                    0,
                    0,
                )
            )
        )
        result = self.usb.libusb_control_transfer(
            self.handle, 0x21, 0x09, 0x0300, 0, report, 8, 2000
        )
        if result != 8:
            raise OSError(f"VMAX XDATA write failed ({result})")

    def _screen(self, enabled):
        value = self._read_xdata(0xFB07)
        value = value & ~0x02 if enabled else value | 0x02
        self._write_xdata(0xFB07, value)

    def configure(self):
        width = PANEL_SIZE
        height = PANEL_SIZE
        size = bytes((width >> 8, width & 0xFF, height >> 8, height & 0xFF))

        self._hid_write(0xA6, 0x04, b"\0")       # transfer off
        self._hid_write(0xA6, 0x05, b"\0")       # video off
        self._screen(False)
        time.sleep(0.05)
        self._hid_write(0xA6, 0x07, b"\x01\x02") # power on
        time.sleep(0.05)
        self._hid_write(0xA6, 0x03, b"\0")       # complete-frame mode
        self._hid_write(0xA6, 0x01, size + b"\x21\0")
        self._hid_write(0xA6, 0x02, b"\x8f\x01" + size)
        self._hid_write(0xA6, 0x04, b"\x01")     # transfer on
        time.sleep(0.05)
        self._hid_write(0xA6, 0x05, b"\0")
        self._screen(False)
        self.frame_index = 1 if self._read_xdata(0xD003) else 0
        self.first_frame = True

    def send(self, image):
        # Vmax supplies an unencoded 32-bit Windows bitmap. The vendor Linux
        # path strips alpha and sends its native B, G, R byte order.
        pixels = image.convert("RGB").tobytes("raw", "BGR")
        buffer = self._buffer(pixels)
        transferred = ctypes.c_int()
        result = self.usb.libusb_bulk_transfer(
            self.handle,
            self.BULK_ENDPOINT,
            buffer,
            len(pixels),
            ctypes.byref(transferred),
            5000,
        )
        if result or transferred.value != len(pixels):
            raise OSError(
                f"VMAX picture transfer failed ({result}, {transferred.value}/{len(pixels)})"
            )

        # The Vmax SDK terminates the transfer with an explicit zero packet.
        empty = (ctypes.c_ubyte * 1)()
        result = self.usb.libusb_bulk_transfer(
            self.handle,
            self.BULK_ENDPOINT,
            empty,
            0,
            ctypes.byref(transferred),
            2000,
        )
        if result:
            raise OSError(f"VMAX frame terminator failed ({result})")

        self.frame_index = 0 if self.frame_index else 1
        self._hid_write(0xA6, 0x00, bytes((self.frame_index, 100)))
        if self.first_frame:
            self._hid_write(0xA6, 0x05, b"\x01")
            self._screen(True)
            self.first_frame = False

    def close(self):
        if getattr(self, "handle", None):
            self.usb.libusb_release_interface(self.handle, self.BULK_INTERFACE)
            self.usb.libusb_release_interface(self.handle, self.HID_INTERFACE)
            self.usb.libusb_close(self.handle)
            self.handle = ctypes.c_void_p()
        if getattr(self, "context", None):
            self.usb.libusb_exit(self.context)
            self.context = ctypes.c_void_p()


def renderer_running():
    try:
        pid = int(RENDERER_PID.read_text().strip())
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        return str(APP_DIR / "aio_screen_manager.py").encode() in command
    except (OSError, ValueError):
        return False


def start_renderer():
    if renderer_running():
        return True
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    log = RENDERER_LOG.open("ab")
    process = subprocess.Popen(
        ["python3", str(APP_DIR / "aio_screen_manager.py"), "--render"],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
    RENDERER_PID.write_text(str(process.pid), encoding="utf-8")
    time.sleep(0.25)
    return renderer_running()


def stop_renderer():
    if not renderer_running():
        return
    try:
        pid = int(RENDERER_PID.read_text().strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass


def detach_aio_from_desktop():
    """Keep Xorg from treating the cooler panel as an extended desktop."""
    try:
        result = subprocess.run(
            ["xrandr", "--listproviders"],
            check=False,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if "name:modesetting" not in line:
                continue
            match = re.search(r"id:\s*(0x[0-9a-fA-F]+)", line)
            if match:
                subprocess.run(
                    ["xrandr", "--setprovideroutputsource", match.group(1), "0x0"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
    except OSError:
        pass


def refresh_framebuffer(framebuffer):
    """Force the MS9132 fbdev client to submit the newly written frame."""
    variable_info = bytearray(160)
    fcntl.ioctl(framebuffer.fileno(), FBIOGET_VSCREENINFO, variable_info, True)
    variable_info[84:88] = FB_ACTIVATE_FORCE.to_bytes(4, "little")
    fcntl.ioctl(framebuffer.fileno(), FBIOPUT_VSCREENINFO, variable_info, True)


def run_renderer():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    RENDERER_PID.write_text(str(os.getpid()), encoding="utf-8")
    detach_aio_from_desktop()
    video = None
    animation = None
    display = None
    media_key = None
    static = None
    try:
        display = VmaxUsbDisplay()
        while True:
            settings = load_settings()
            new_key = (settings.get("media_type"), settings.get("media_path"))
            if new_key != media_key:
                if video:
                    video.close()
                    video = None
                if animation:
                    animation.close()
                    animation = None
                media_key = new_key
                static = static_background(settings)
                if new_key[0] == "video" and new_key[1] and Path(new_key[1]).is_file():
                    try:
                        video = VideoBackground(new_key[1])
                    except Exception as error:
                        RENDERER_LOG.write_text(
                            f"Video initialization error: {error}\n",
                            encoding="utf-8",
                        )
                elif (
                    new_key[0] == "image"
                    and new_key[1]
                    and Path(new_key[1]).is_file()
                    and is_animated_image(new_key[1])
                ):
                    try:
                        animation = AnimatedImageBackground(new_key[1])
                    except Exception as error:
                        RENDERER_LOG.write_text(
                            f"GIF initialization error: {error}\n",
                            encoding="utf-8",
                        )
            background = (
                video.frame()
                if video
                else animation.frame()
                if animation
                else static
            )
            if background is None:
                background = static or gradient_background()
            frame = render_frame(settings, background)
            try:
                display.send(frame)
            except PermissionError:
                RENDERER_LOG.write_text(
                    "Permission denied opening the VMAX USB device. Reinstall the udev rule.\n",
                    encoding="utf-8",
                )
                return 1
            except OSError as error:
                RENDERER_LOG.write_text(f"Framebuffer error: {error}\n", encoding="utf-8")
                return 1
            time.sleep(1 / 30 if animation else 1 / 15 if video else 1)
    finally:
        if video:
            video.close()
        if animation:
            animation.close()
        if display:
            display.close()


class PanelWindow(Gtk.Window):
    def __init__(self, settings, on_closed):
        super().__init__(title="AIO Panel")
        self.settings = settings
        self.on_closed = on_closed
        self.temperature = None
        self.load = 0.0
        self.pixbuf = None
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_resizable(False)
        self.set_default_size(PANEL_SIZE, PANEL_SIZE)
        self.set_size_request(PANEL_SIZE, PANEL_SIZE)
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(PANEL_SIZE, PANEL_SIZE)
        self.area.connect("draw", self.on_draw)
        self.add(self.area)
        self.connect("delete-event", self.handle_close)
        self.connect("realize", self.place_on_panel)
        self.refresh_image()
        self.refresh()
        GLib.timeout_add_seconds(1, self.refresh)

    def handle_close(self, *_args):
        self.on_closed()
        return False

    def place_on_panel(self, *_args):
        output = aio_output()
        if output:
            self.move(output["x"], output["y"])
        else:
            screen = self.get_screen()
            self.move(max(0, screen.get_width() - PANEL_SIZE - 24), 24)
        self.resize(PANEL_SIZE, PANEL_SIZE)

    def refresh_image(self):
        self.pixbuf = None
        image = self.settings.get("image", "")
        if not image:
            return
        try:
            source = GdkPixbuf.Pixbuf.new_from_file(image)
            width, height = source.get_width(), source.get_height()
            scale = max(PANEL_SIZE / width, PANEL_SIZE / height)
            scaled_w, scaled_h = int(width * scale), int(height * scale)
            scaled = source.scale_simple(
                scaled_w, scaled_h, GdkPixbuf.InterpType.BILINEAR
            )
            self.pixbuf = scaled.new_subpixbuf(
                (scaled_w - PANEL_SIZE) // 2,
                (scaled_h - PANEL_SIZE) // 2,
                PANEL_SIZE,
                PANEL_SIZE,
            )
        except (GLib.Error, ValueError):
            self.pixbuf = None

    def refresh(self):
        self.temperature = cpu_temperature()
        self.load = cpu_load()
        self.area.queue_draw()
        return True

    @staticmethod
    def text(ctx, value, size, x, y, color=(1, 1, 1), weight=0, align="center"):
        ctx.select_font_face(
            "Sans",
            0,
            1 if weight else 0,
        )
        ctx.set_font_size(size)
        extents = ctx.text_extents(value)
        if align == "center":
            draw_x = x - extents.width / 2 - extents.x_bearing
        else:
            draw_x = x
        ctx.set_source_rgb(*color)
        ctx.move_to(draw_x, y)
        ctx.show_text(value)

    def draw_background(self, ctx):
        gradient = cairo.RadialGradient(240, 210, 20, 240, 240, 360)
        gradient.add_color_stop_rgb(0, 0.08, 0.16, 0.25)
        gradient.add_color_stop_rgb(0.55, 0.025, 0.055, 0.10)
        gradient.add_color_stop_rgb(1, 0.005, 0.012, 0.025)
        ctx.set_source(gradient)
        ctx.paint()

    def draw_dashboard(self, ctx):
        self.draw_background(ctx)
        temp = self.temperature or 0.0
        fraction = max(0.0, min(1.0, temp / 100.0))
        ctx.set_line_width(18)
        ctx.set_line_cap(1)
        ctx.set_source_rgba(0.2, 0.32, 0.42, 0.55)
        ctx.arc(240, 220, 142, math.radians(145), math.radians(395))
        ctx.stroke()
        ctx.set_source_rgb(0.05, 0.85, 0.75 if temp < 75 else 0.25)
        ctx.arc(
            240,
            220,
            142,
            math.radians(145),
            math.radians(145 + 250 * fraction),
        )
        ctx.stroke()
        self.text(ctx, "CPU", 26, 240, 150, (0.5, 0.72, 0.84), weight=1)
        temperature_text = f"{temp:.0f}°" if self.temperature is not None else "--°"
        self.text(ctx, temperature_text, 104, 240, 260, weight=1)
        self.text(ctx, "CELSIUS", 19, 240, 297, (0.43, 0.64, 0.74))
        self.text(
            ctx,
            f"LOAD  {self.load:.0f}%",
            25,
            240,
            375,
            (0.90, 0.95, 1.0),
            weight=1,
        )
        self.text(
            ctx,
            time.strftime("%I:%M %p"),
            21,
            240,
            418,
            (0.42, 0.67, 0.78),
        )

    def draw_clock(self, ctx):
        self.draw_background(ctx)
        now = time.localtime()
        self.text(ctx, time.strftime("%I:%M", now), 112, 240, 226, weight=1)
        self.text(ctx, time.strftime("%p", now), 35, 240, 278, (0.1, 0.86, 0.75))
        self.text(ctx, time.strftime("%A", now).upper(), 24, 240, 345, (0.5, 0.7, 0.8))
        self.text(ctx, time.strftime("%d %B %Y", now), 24, 240, 383)
        temp = "--" if self.temperature is None else f"{self.temperature:.0f}°C"
        self.text(ctx, f"CPU {temp}", 18, 240, 435, (0.44, 0.63, 0.72))

    def draw_image(self, ctx):
        if self.pixbuf:
            Gdk.cairo_set_source_pixbuf(ctx, self.pixbuf, 0, 0)
            ctx.paint()
        else:
            self.draw_background(ctx)
            self.text(ctx, "Choose an image", 31, 240, 230, weight=1)
            self.text(ctx, "in AIO Screen Manager", 20, 240, 267, (0.5, 0.7, 0.8))

    def on_draw(self, _widget, ctx):
        mode = self.settings.get("mode", "dashboard")
        if mode == "clock":
            self.draw_clock(ctx)
        elif mode == "image":
            self.draw_image(ctx)
        else:
            self.draw_dashboard(ctx)
        return False


class PreviewEditor(Gtk.DrawingArea):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.dragging = False
        self.set_size_request(PANEL_SIZE, PANEL_SIZE)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_press)
        self.connect("button-release-event", self.on_release)
        self.connect("motion-notify-event", self.on_motion)

    def geometry(self):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        scale = min(width / PANEL_SIZE, height / PANEL_SIZE)
        return scale, (width - PANEL_SIZE * scale) / 2, (height - PANEL_SIZE * scale) / 2

    def panel_point(self, event):
        scale, offset_x, offset_y = self.geometry()
        return (
            max(0, min(PANEL_SIZE, int((event.x - offset_x) / scale))),
            max(0, min(PANEL_SIZE, int((event.y - offset_y) / scale))),
        )

    def on_draw(self, _widget, context):
        scale, offset_x, offset_y = self.geometry()
        context.save()
        context.translate(offset_x, offset_y)
        context.scale(scale, scale)
        if self.manager.preview_pixbuf:
            Gdk.cairo_set_source_pixbuf(context, self.manager.preview_pixbuf, 0, 0)
            context.paint()
        context.set_source_rgb(0.15, 0.18, 0.22)
        context.set_line_width(2 / scale)
        context.rectangle(0, 0, PANEL_SIZE, PANEL_SIZE)
        context.stroke()
        box = self.manager.preview_boxes.get(self.manager.selected_overlay)
        if box and self.manager.settings["overlays"].get(self.manager.selected_overlay):
            context.set_source_rgba(0.1, 0.9, 0.75, 0.95)
            context.set_line_width(2 / scale)
            context.set_dash([7 / scale, 5 / scale])
            context.rectangle(box[0] - 6, box[1] - 5, box[2] - box[0] + 12, box[3] - box[1] + 10)
            context.stroke()
        context.restore()
        return False

    def on_press(self, _widget, event):
        if event.button != 1:
            return False
        x, y = self.panel_point(event)
        for key, box in reversed(list(self.manager.preview_boxes.items())):
            if box[0] - 10 <= x <= box[2] + 10 and box[1] - 10 <= y <= box[3] + 10:
                self.manager.select_overlay(key)
                self.dragging = True
                return True
        self.dragging = bool(self.manager.selected_overlay)
        if self.dragging:
            self.manager.move_selected_overlay(x, y)
        return self.dragging

    def on_motion(self, _widget, event):
        if self.dragging and event.state & Gdk.ModifierType.BUTTON1_MASK:
            self.manager.move_selected_overlay(*self.panel_point(event))
            return True
        return False

    def on_release(self, _widget, event):
        self.dragging = False
        return event.button == 1


class Manager(Gtk.Window):
    def __init__(self, start_panel=False):
        super().__init__(title="Frost Vision Studio")
        self.settings = load_settings()
        self.selected_overlay = "cpu_temp"
        self.preview_pixbuf = None
        self.preview_bytes = None
        self.preview_boxes = {}
        self.preview_video = None
        self.preview_animation = None
        self.preview_media_key = None
        self._updating_controls = False
        self.set_default_size(1080, 780)
        self.set_border_width(18)
        self.connect("destroy", self.on_destroy)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(root)
        title = Gtk.Label()
        title.set_markup("<span size='xx-large' weight='bold'>Frost Vision Studio</span>")
        title.set_xalign(0)
        root.pack_start(title, False, False, 0)
        subtitle = Gtk.Label(
            label="Design the 480×480 cooler screen, then drag text directly on the preview."
        )
        subtitle.set_xalign(0)
        root.pack_start(subtitle, False, False, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        root.pack_start(body, True, True, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_size_request(455, -1)
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        controls.set_border_width(4)
        scroller.add(controls)
        body.pack_start(scroller, False, False, 0)

        self._build_background_controls(controls)
        self._build_layer_controls(controls)
        self._build_startup_controls(controls)

        preview_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.pack_start(preview_column, True, True, 0)
        preview_title = Gtk.Label()
        preview_title.set_markup("<b>Live screen preview</b>")
        preview_title.set_xalign(0.5)
        preview_column.pack_start(preview_title, False, False, 0)
        self.preview = PreviewEditor(self)
        preview_column.pack_start(self.preview, True, True, 0)
        hint = Gtk.Label(
            label="Click a text layer to select it. Drag it anywhere on the screen."
        )
        hint.get_style_context().add_class("dim-label")
        preview_column.pack_start(hint, False, False, 0)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.pack_start(footer, False, False, 0)
        self.status = Gtk.Label()
        self.status.set_xalign(0)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        footer.pack_start(self.status, True, True, 0)
        self.stop_button = Gtk.Button(label="Stop display")
        self.stop_button.connect("clicked", self.close_panel)
        self.show_button = Gtk.Button(label="Apply / Start display")
        self.show_button.get_style_context().add_class("suggested-action")
        self.show_button.connect("clicked", self.show_panel)
        footer.pack_end(self.show_button, False, False, 0)
        footer.pack_end(self.stop_button, False, False, 0)

        self.load_selected_controls()
        self.refresh_status()
        self.update_preview()
        GLib.timeout_add(500, self.update_preview)
        GLib.timeout_add_seconds(2, self.refresh_status)
        if start_panel:
            GLib.idle_add(self.show_panel)

    def _frame_box(self, title):
        frame = Gtk.Frame(label=title)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        box.set_border_width(12)
        frame.add(box)
        return frame, box

    def _build_background_controls(self, parent):
        frame, box = self._frame_box("Background")
        parent.pack_start(frame, False, False, 0)
        self.media_label = Gtk.Label(label=self.media_name())
        self.media_label.set_xalign(0)
        self.media_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        box.pack_start(self.media_label, False, False, 0)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, kind in (("Choose image…", "image"), ("Choose video…", "video")):
            button = Gtk.Button(label=label)
            button.connect("clicked", self.choose_media, kind)
            buttons.pack_start(button, True, True, 0)
        clear = Gtk.Button(label="Clear")
        clear.connect("clicked", self.clear_media)
        buttons.pack_start(clear, False, False, 0)
        box.pack_start(buttons, False, False, 0)

        orientation = Gtk.Grid(column_spacing=8, row_spacing=8)
        orientation.attach(Gtk.Label(label="Rotation:", xalign=0), 0, 0, 1, 1)
        self.rotation = Gtk.ComboBoxText()
        for value in (0, 90, 180, 270):
            self.rotation.append(str(value), f"{value}°")
        self.rotation.set_active_id(str(self.settings["background_transform"]["rotation"]))
        self.rotation.connect("changed", self.change_transform)
        orientation.attach(self.rotation, 1, 0, 1, 1)
        self.flip_horizontal = Gtk.CheckButton(label="Flip horizontally")
        self.flip_horizontal.set_active(
            bool(self.settings["background_transform"]["flip_horizontal"])
        )
        self.flip_horizontal.connect("toggled", self.change_transform)
        orientation.attach(self.flip_horizontal, 0, 1, 2, 1)
        self.flip_vertical = Gtk.CheckButton(label="Flip vertically")
        self.flip_vertical.set_active(
            bool(self.settings["background_transform"]["flip_vertical"])
        )
        self.flip_vertical.connect("toggled", self.change_transform)
        orientation.attach(self.flip_vertical, 0, 2, 2, 1)
        box.pack_start(orientation, False, False, 0)

    def _build_layer_controls(self, parent):
        frame, box = self._frame_box("Text layers")
        parent.pack_start(frame, False, False, 0)
        selector_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        selector_row.pack_start(Gtk.Label(label="Edit:"), False, False, 0)
        self.layer_selector = Gtk.ComboBoxText()
        for key, style in OVERLAY_DEFAULTS.items():
            self.layer_selector.append(key, style["name"])
        self.layer_selector.set_active_id(self.selected_overlay)
        self.layer_selector.connect("changed", self.layer_changed)
        selector_row.pack_start(self.layer_selector, True, True, 0)
        box.pack_start(selector_row, False, False, 0)

        self.layer_enabled = Gtk.CheckButton(label="Show this text layer")
        self.layer_enabled.connect("toggled", self.layer_control_changed)
        box.pack_start(self.layer_enabled, False, False, 0)

        grid = Gtk.Grid(column_spacing=10, row_spacing=9)
        box.pack_start(grid, False, False, 0)
        self.prefix = Gtk.Entry()
        self.prefix.connect("changed", self.layer_control_changed)
        grid.attach(Gtk.Label(label="Text before value:", xalign=0), 0, 0, 1, 1)
        grid.attach(self.prefix, 1, 0, 2, 1)

        self.font_button = Gtk.FontButton()
        self.font_button.set_use_size(False)
        self.font_button.set_show_style(False)
        self.font_button.connect("font-set", self.layer_control_changed)
        grid.attach(Gtk.Label(label="Font:", xalign=0), 0, 1, 1, 1)
        grid.attach(self.font_button, 1, 1, 2, 1)

        self.font_size = Gtk.SpinButton.new_with_range(8, 120, 1)
        self.font_size.connect("value-changed", self.layer_control_changed)
        self.bold = Gtk.CheckButton(label="Bold")
        self.bold.connect("toggled", self.layer_control_changed)
        grid.attach(Gtk.Label(label="Size:", xalign=0), 0, 2, 1, 1)
        grid.attach(self.font_size, 1, 2, 1, 1)
        grid.attach(self.bold, 2, 2, 1, 1)

        self.color = Gtk.ColorButton()
        self.color.set_use_alpha(True)
        self.color.connect("color-set", self.layer_control_changed)
        grid.attach(Gtk.Label(label="Color:", xalign=0), 0, 3, 1, 1)
        grid.attach(self.color, 1, 3, 2, 1)

        self.position_x = Gtk.SpinButton.new_with_range(0, PANEL_SIZE, 1)
        self.position_y = Gtk.SpinButton.new_with_range(0, PANEL_SIZE, 1)
        self.position_x.connect("value-changed", self.layer_control_changed)
        self.position_y.connect("value-changed", self.layer_control_changed)
        grid.attach(Gtk.Label(label="Position X / Y:", xalign=0), 0, 4, 1, 1)
        grid.attach(self.position_x, 1, 4, 1, 1)
        grid.attach(self.position_y, 2, 4, 1, 1)

        reset = Gtk.Button(label="Reset selected text")
        reset.connect("clicked", self.reset_selected)
        box.pack_start(reset, False, False, 0)

    def _build_startup_controls(self, parent):
        frame, box = self._frame_box("Display")
        parent.pack_start(frame, False, False, 0)
        self.autostart = Gtk.CheckButton(
            label="Start this composition automatically when I log in"
        )
        self.autostart.set_active(bool(self.settings.get("autostart")))
        self.autostart.connect("toggled", self.toggle_autostart)
        box.pack_start(self.autostart, False, False, 0)

    def media_name(self):
        path = self.settings.get("media_path", "")
        kind = self.settings.get("media_type", "none")
        if not path:
            return "No background selected — a dark gradient will be used"
        return f"{kind.title()}: {Path(path).name}"

    def refresh_status(self):
        usb = usb_display_present()
        running = renderer_running()
        if usb and running:
            text = "● Frost Vision connected — live composition is running"
        elif usb:
            text = "● Frost Vision connected — ready to start"
        else:
            text = "● AIO USB screen is not currently detected."
        self.status.set_text(text)
        self.stop_button.set_sensitive(running)
        return False

    def change_transform(self, *_args):
        self.settings["background_transform"] = {
            "rotation": int(self.rotation.get_active_id() or 0),
            "flip_horizontal": self.flip_horizontal.get_active(),
            "flip_vertical": self.flip_vertical.get_active(),
        }
        self.commit_changes()

    def layer_changed(self, combo):
        key = combo.get_active_id()
        if key:
            self.selected_overlay = key
            self.load_selected_controls()
            self.preview.queue_draw()

    def select_overlay(self, key):
        if key not in OVERLAY_DEFAULTS:
            return
        self.selected_overlay = key
        self.layer_selector.set_active_id(key)
        self.load_selected_controls()

    def load_selected_controls(self):
        self._updating_controls = True
        key = self.selected_overlay
        style = {
            **OVERLAY_DEFAULTS[key],
            **self.settings["overlay_styles"].get(key, {}),
        }
        self.layer_enabled.set_active(bool(self.settings["overlays"].get(key)))
        self.prefix.set_text(str(style.get("prefix", "")))
        self.font_button.set_font_name(str(style.get("font", "Noto Sans")))
        self.font_size.set_value(float(style.get("size", 28)))
        self.bold.set_active(bool(style.get("bold")))
        rgba = Gdk.RGBA()
        if not rgba.parse(str(style.get("color", "#FFFFFF"))):
            rgba.parse("#FFFFFF")
        self.color.set_rgba(rgba)
        self.position_x.set_value(float(style.get("x", 240)))
        self.position_y.set_value(float(style.get("y", 240)))
        self._updating_controls = False

    def layer_control_changed(self, *_args):
        if self._updating_controls:
            return
        description = Pango.FontDescription.from_string(self.font_button.get_font_name())
        rgba = self.color.get_rgba()
        color = "#{:02X}{:02X}{:02X}{:02X}".format(
            round(rgba.red * 255),
            round(rgba.green * 255),
            round(rgba.blue * 255),
            round(rgba.alpha * 255),
        )
        key = self.selected_overlay
        self.settings["overlays"][key] = self.layer_enabled.get_active()
        self.settings["overlay_styles"][key] = {
            **self.settings["overlay_styles"].get(key, {}),
            "x": self.position_x.get_value_as_int(),
            "y": self.position_y.get_value_as_int(),
            "size": self.font_size.get_value_as_int(),
            "font": description.get_family() or "Noto Sans",
            "bold": self.bold.get_active(),
            "color": color,
            "prefix": self.prefix.get_text(),
        }
        resolve_font.cache_clear()
        self.commit_changes()

    def move_selected_overlay(self, x, y):
        style = self.settings["overlay_styles"][self.selected_overlay]
        style["x"] = int(x)
        style["y"] = int(y)
        self._updating_controls = True
        self.position_x.set_value(x)
        self.position_y.set_value(y)
        self._updating_controls = False
        self.commit_changes()

    def reset_selected(self, *_args):
        key = self.selected_overlay
        self.settings["overlay_styles"][key] = dict(OVERLAY_DEFAULTS[key])
        self.load_selected_controls()
        self.commit_changes()

    def commit_changes(self):
        save_settings(self.settings)
        self.update_preview()

    def preview_background(self):
        key = (self.settings.get("media_type"), self.settings.get("media_path"))
        if key != self.preview_media_key:
            if self.preview_video:
                self.preview_video.close()
                self.preview_video = None
            if self.preview_animation:
                self.preview_animation.close()
                self.preview_animation = None
            self.preview_media_key = key
            if key[0] == "video" and key[1] and Path(key[1]).is_file():
                try:
                    self.preview_video = VideoBackground(key[1])
                except Exception:
                    self.preview_video = None
            elif (
                key[0] == "image"
                and key[1]
                and Path(key[1]).is_file()
                and is_animated_image(key[1])
            ):
                try:
                    self.preview_animation = AnimatedImageBackground(key[1])
                except Exception:
                    self.preview_animation = None
        if self.preview_video:
            frame = self.preview_video.frame()
            if frame is not None:
                return frame
        if self.preview_animation:
            return self.preview_animation.frame()
        return static_background(self.settings)

    def update_preview(self):
        try:
            image = render_frame(self.settings, self.preview_background())
            self.preview_bytes = GLib.Bytes.new(image.tobytes())
            self.preview_pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
                self.preview_bytes,
                GdkPixbuf.Colorspace.RGB,
                False,
                8,
                PANEL_SIZE,
                PANEL_SIZE,
                PANEL_SIZE * 3,
            )
            self.preview_boxes = self.calculate_preview_boxes()
            self.preview.queue_draw()
        except Exception as error:
            self.status.set_text(f"Preview error: {error}")
        return True

    def calculate_preview_boxes(self):
        boxes = {}
        for key, default in OVERLAY_DEFAULTS.items():
            if not self.settings["overlays"].get(key):
                continue
            style = {**default, **self.settings["overlay_styles"].get(key, {})}
            text = f"{style.get('prefix', '')}{metric_value(key)}"
            text_font = ImageFont.truetype(
                resolve_font(style.get("font", "Noto Sans"), bool(style.get("bold"))),
                int(style.get("size", 28)),
            )
            left, top, right, bottom = text_font.getbbox(text, anchor="mm")
            x, y = int(style.get("x", 240)), int(style.get("y", 240))
            boxes[key] = (x + left, y + top, x + right, y + bottom)
        return boxes

    def choose_media(self, _button, media_type):
        dialog = Gtk.FileChooserDialog(
            title=f"Choose a {media_type} for the AIO screen",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,
            Gtk.ResponseType.OK,
        )
        media_filter = Gtk.FileFilter()
        if media_type == "image":
            media_filter.set_name("Images and animated GIFs")
            media_filter.add_pixbuf_formats()
            media_filter.add_pattern("*.gif")
            media_filter.add_pattern("*.GIF")
        else:
            media_filter.set_name("Videos")
            media_filter.add_mime_type("video/*")
            for pattern in ("*.mp4", "*.mkv", "*.mov", "*.avi", "*.webm", "*.m4v"):
                media_filter.add_pattern(pattern)
        dialog.add_filter(media_filter)
        if dialog.run() == Gtk.ResponseType.OK:
            self.settings["media_type"] = media_type
            self.settings["media_path"] = dialog.get_filename()
            save_settings(self.settings)
            self.media_label.set_text(self.media_name())
            self.update_preview()
        dialog.destroy()

    def clear_media(self, *_args):
        self.settings["media_type"] = "none"
        self.settings["media_path"] = ""
        save_settings(self.settings)
        self.media_label.set_text(self.media_name())
        self.update_preview()

    def toggle_autostart(self, button):
        enabled = button.get_active()
        self.settings["autostart"] = enabled
        save_settings(self.settings)
        if enabled:
            AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART_FILE.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Frost Vision Composition\n"
                f"Exec=python3 {APP_DIR / 'aio_screen_manager.py'} --render\n"
                f"Icon={APP_DIR / 'aio-screen-manager.svg'}\n"
                "Terminal=false\n"
                "X-GNOME-Autostart-enabled=true\n",
                encoding="utf-8",
            )
        else:
            try:
                AUTOSTART_FILE.unlink()
            except FileNotFoundError:
                pass

    def show_panel(self, *_args):
        save_settings(self.settings)
        start_renderer()
        self.refresh_status()
        return False

    def close_panel(self, *_args):
        stop_renderer()
        self.refresh_status()

    def on_destroy(self, *_args):
        if self.preview_video:
            self.preview_video.close()
            self.preview_video = None
        if self.preview_animation:
            self.preview_animation.close()
            self.preview_animation = None
        Gtk.main_quit()


def main():
    if "--render" in os.sys.argv:
        raise SystemExit(run_renderer())
    start_panel = "--panel" in os.sys.argv
    window = Manager(start_panel=start_panel)
    window.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
