"""Portable, bounded-memory media composition without a GUI dependency."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .platform_support import CONFIG_DIR, CONFIG_FILE, IS_WINDOWS

PANEL_SIZE = 480
MAX_IMAGE_PIXELS = 16_777_216
MAX_ANIMATION_FRAMES = 10_000
MAX_MEDIA_BYTES = 1_073_741_824
MAX_VIDEO_PIXELS = 8_294_400
OVERLAY_DEFAULTS = {
    "cpu_temp": dict(name="CPU temperature", x=120, y=390, size=28, color="#FFFFFF", font="Noto Sans", bold=True, prefix="CPU ", rotation=0),
    "gpu_temp": dict(name="GPU temperature", x=360, y=390, size=28, color="#FFFFFF", font="Noto Sans", bold=True, prefix="GPU ", rotation=0),
    "cpu_usage": dict(name="CPU usage", x=120, y=430, size=22, color="#7FE8D5", font="Noto Sans", bold=True, prefix="CPU ", rotation=0),
    "gpu_usage": dict(name="GPU usage", x=360, y=430, size=22, color="#7FE8D5", font="Noto Sans", bold=True, prefix="GPU ", rotation=0),
    "clock": dict(name="Clock", x=240, y=48, size=30, color="#FFFFFF", font="Noto Sans", bold=True, prefix="", rotation=0),
}


def default_settings():
    return dict(media_type="none", media_path="", overlays=dict(cpu_temp=True, gpu_temp=True, cpu_usage=False, gpu_usage=False, clock=True),
                overlay_position="bottom", overlay_styles=deepcopy(OVERLAY_DEFAULTS),
                background_transform=dict(rotation=0, flip_horizontal=False, flip_vertical=False), autostart=False, max_fps=15)


def normalize_settings(saved):
    defaults = default_settings()
    if not isinstance(saved, dict):
        return defaults
    defaults.update(saved)
    defaults["overlays"] = {**default_settings()["overlays"], **(saved.get("overlays") if isinstance(saved.get("overlays"), dict) else {})}
    styles = saved.get("overlay_styles") if isinstance(saved.get("overlay_styles"), dict) else {}
    defaults["overlay_styles"] = {key: {**value, **(styles.get(key) if isinstance(styles.get(key), dict) else {})} for key, value in OVERLAY_DEFAULTS.items()}
    defaults["background_transform"] = {**default_settings()["background_transform"], **(saved.get("background_transform") if isinstance(saved.get("background_transform"), dict) else {})}
    for key, style in defaults["overlay_styles"].items():
        for name, lower, upper in (("x", 0, PANEL_SIZE), ("y", 0, PANEL_SIZE), ("size", 8, 120), ("rotation", -360, 360)):
            try:
                style[name] = max(lower, min(upper, int(style[name])))
            except (TypeError, ValueError, OverflowError):
                style[name] = OVERLAY_DEFAULTS[key][name]
        style["prefix"] = str(style.get("prefix", ""))[:256]
        style["font"] = str(style.get("font") or "Noto Sans")[:128]
    try:
        defaults["background_transform"]["rotation"] = int(defaults["background_transform"].get("rotation", 0)) % 360
    except (ValueError, TypeError, OverflowError):
        defaults["background_transform"]["rotation"] = 0
    if not defaults.get("media_path") and isinstance(saved.get("image"), str):
        defaults.update(media_type="image", media_path=saved["image"])
    if defaults.get("media_type") not in ("none", "image", "video"):
        defaults["media_type"] = "none"
    if not isinstance(defaults.get("media_path"), str):
        defaults["media_path"] = ""
    try:
        defaults["max_fps"] = max(1, min(30, int(defaults.get("max_fps", 15))))
    except (ValueError, TypeError, OverflowError):
        defaults["max_fps"] = 15
    return defaults


def load_settings():
    # Keep the original Linux path; migrate an older Windows home config once.
    source = CONFIG_FILE
    legacy = Path.home() / ".config" / "aio-screen-manager" / "settings.json"
    if IS_WINDOWS and not source.exists() and legacy.is_file():
        source = legacy
    try:
        if source.stat().st_size > 1_048_576:
            return default_settings()
        result = normalize_settings(json.loads(source.read_text(encoding="utf-8")))
        if source != CONFIG_FILE:
            save_settings(result)
        return result
    except (OSError, ValueError, TypeError):
        return default_settings()


def save_settings(settings):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = json.dumps(normalize_settings(settings), indent=2, ensure_ascii=False, allow_nan=False)
    if len(data.encode("utf-8")) > 1_048_576:
        raise ValueError("Settings exceed the 1 MiB safety limit.")
    descriptor, path = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=CONFIG_DIR)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(path, CONFIG_FILE)
    finally:
        Path(path).unlink(missing_ok=True)


@lru_cache(maxsize=1)
def _gradient():
    image = Image.new("RGB", (PANEL_SIZE, PANEL_SIZE))
    image.putdata([(int(12 * (1 - d) + 2), int(32 * (1 - d) + 5), int(49 * (1 - d) + 9))
                   for y in range(PANEL_SIZE) for x in range(PANEL_SIZE)
                   for d in [min(1.0, math.hypot(x - 240, y - 210) / 360.0)]])
    return image


def gradient_background():
    return _gradient().copy()


def cover_image(source):
    if source.width < 1 or source.height < 1 or source.width * source.height > MAX_IMAGE_PIXELS:
        raise ValueError("Image exceeds the 16 megapixel safety limit.")
    source = ImageOps.exif_transpose(source)
    if source.mode in ("RGBA", "LA") or "transparency" in source.info:
        rgba = source.convert("RGBA")
        bounds = rgba.getchannel("A").getbbox()
        if bounds:
            rgba = rgba.crop(bounds)
        base = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
        source = Image.alpha_composite(base, rgba).convert("RGB")
    else:
        source = source.convert("RGB")
    return ImageOps.fit(source, (PANEL_SIZE, PANEL_SIZE), method=Image.Resampling.LANCZOS)


@lru_cache(maxsize=64)
def resolve_font(family="Noto Sans", bold=False):
    family = str(family or "Noto Sans")[:128]
    if IS_WINDOWS:
        import winreg
        directories = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
        candidates = []
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as key:
                    for index in range(winreg.QueryInfoKey(key)[1]):
                        name, value, _kind = winreg.EnumValue(key, index)
                        if (family.casefold() in name.casefold() and isinstance(value, str)
                                and Path(value).suffix.casefold() in (".ttf", ".otf", ".ttc", ".otc")):
                            candidates.append((int(("bold" in name.casefold()) != bool(bold)), value))
            except OSError:
                pass
        for _score, value in sorted(candidates):
            for directory in directories:
                path = directory / value
                if path.is_file():
                    return str(path)
        for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
            path = directories[0] / name
            if path.is_file():
                return str(path)
    else:
        try:
            pattern = family + (":style=Bold" if bold else "")
            result = subprocess.run(["fc-match", "-f", "%{file}", pattern], check=True, capture_output=True, text=True, timeout=2)
            if Path(result.stdout.strip()).is_file():
                return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        for path in ("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            if Path(path).is_file():
                return path
    # Pillow wheels normally include access to DejaVu through the font search path.
    return "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"


@lru_cache(maxsize=128)
def _font(family, bold, size):
    try:
        return ImageFont.truetype(resolve_font(family, bold), size)
    except OSError:
        return ImageFont.load_default(size=size)


def text_font(family="Noto Sans", bold=False, size=28):
    """Use the same bounded cached font/fallback for composition and hit boxes."""
    return _font(str(family or "Noto Sans")[:128], bool(bold), max(8, min(120, int(size))))


_metric_lock = threading.Lock()
_metric_deadline = 0.0
_metrics = {}


def _sensor_snapshot():
    import psutil
    values = {"cpu_temp": None, "gpu_temp": None, "cpu_usage": psutil.cpu_percent(interval=None), "gpu_usage": None}
    if hasattr(psutil, "sensors_temperatures"):
        try:
            sensors = psutil.sensors_temperatures()
            cpu = [(0 if chip == "k10temp" and item.label == "Tctl" else 1, item.current)
                   for chip, items in sensors.items() for item in items
                   if chip in ("k10temp", "coretemp", "zenpower", "cpu_thermal") and 0 < item.current < 125]
            gpu = [item.current for chip, items in sensors.items() for item in items if chip in ("amdgpu", "nouveau") and 0 < item.current < 125]
            values["cpu_temp"] = min(cpu)[1] if cpu else None
            values["gpu_temp"] = max(gpu) if gpu else None
        except (OSError, RuntimeError, AttributeError):
            pass
    if not IS_WINDOWS:
        busy = []
        for path in Path("/sys/class/drm").glob("card*/device/gpu_busy_percent"):
            try:
                busy.append(float(path.read_text().strip()))
            except (OSError, ValueError):
                pass
        values["gpu_usage"] = max(busy) if busy else None
    return values


def metrics_snapshot():
    global _metric_deadline, _metrics
    with _metric_lock:
        now = time.monotonic()
        if now >= _metric_deadline:
            _metrics = _sensor_snapshot()
            _metrics["clock"] = time.strftime("%I:%M %p")
            _metric_deadline = now + 1.0
        return dict(_metrics)


def metric_value(key, metrics=None):
    values = metrics_snapshot() if metrics is None else metrics
    value = values.get(key)
    if isinstance(value, str):
        return value[:256]
    if key == "clock":
        return time.strftime("%I:%M %p") if value is None else str(value)
    if key in ("cpu_temp", "gpu_temp"):
        return "--°C" if value is None else f"{value:.0f}°C"
    if key in ("cpu_usage", "gpu_usage"):
        return "--%" if value is None else f"{value:.0f}%"
    return ""


def rotated_text_bounds(value, text_font, rotation):
    left, top, right, bottom = text_font.getbbox(value, anchor="mm")
    angle = math.radians(int(rotation) % 360)
    c, s = math.cos(angle), math.sin(angle)
    points = [(x * c - y * s, x * s + y * c) for x, y in ((left, top), (right, top), (right, bottom), (left, bottom))]
    return (math.floor(min(p[0] for p in points)), math.floor(min(p[1] for p in points)),
            math.ceil(max(p[0] for p in points)), math.ceil(max(p[1] for p in points)))


def parse_color(value):
    value = str(value or "#FFFFFF").lstrip("#")
    try:
        if len(value) in (6, 8):
            result = tuple(int(value[index:index + 2], 16) for index in range(0, len(value), 2))
            return result + (255,) if len(result) == 3 else result
    except ValueError:
        pass
    return 255, 255, 255, 255


def render_frame(settings, background=None, metrics=None):
    settings = normalize_settings(settings)
    image = (background if background is not None else _gradient()).convert("RGB")
    if image.size != (PANEL_SIZE, PANEL_SIZE):
        image = cover_image(image)
    transform = settings["background_transform"]
    rotation = int(transform.get("rotation", 0)) % 360
    if rotation:
        image = image.rotate(-rotation, resample=Image.Resampling.BICUBIC)
    if transform.get("flip_horizontal"):
        image = ImageOps.mirror(image)
    if transform.get("flip_vertical"):
        image = ImageOps.flip(image)
    canvas = image.convert("RGBA")
    values = metrics_snapshot() if metrics is None else metrics
    for key, style in settings["overlay_styles"].items():
        if not settings["overlays"].get(key):
            continue
        size = max(8, min(120, int(style.get("size", 28))))
        family = str(style.get("font") or "Noto Sans")[:128]
        text_font = _font(family, bool(style.get("bold")), size)
        value = str(style.get("prefix", ""))[:256] + metric_value(key, values)
        fill = parse_color(style.get("color"))
        position = (max(0, min(PANEL_SIZE, int(style.get("x", 240)))), max(0, min(PANEL_SIZE, int(style.get("y", 240)))))
        rotation = int(style.get("rotation", 0)) % 360
        # Keep malicious or accidental giant text from allocating an unbounded surface.
        if not rotation:
            layer = Image.new("RGBA", (PANEL_SIZE, PANEL_SIZE))
            ImageDraw.Draw(layer).text(position, value, font=text_font, fill=fill, anchor="mm")
            canvas.alpha_composite(layer)
        else:
            layer = Image.new("RGBA", (PANEL_SIZE * 2, PANEL_SIZE * 2))
            ImageDraw.Draw(layer).text((PANEL_SIZE, PANEL_SIZE), value, font=text_font, fill=fill, anchor="mm")
            layer = layer.rotate(-rotation, resample=Image.Resampling.BICUBIC)
            canvas.alpha_composite(layer, (position[0] - PANEL_SIZE, position[1] - PANEL_SIZE))
    return canvas.convert("RGB")


class BackgroundSource:
    """Own one decoder and one output frame; never preload an animation."""

    def __init__(self, settings):
        self._key = None
        self._source = None
        self._container = None
        self._decoder = None
        self._stream = None
        self._image = None
        self._deadline = 0.0
        self._index = 0
        self.animate = False
        self.error = ""
        self.set_settings(settings)

    @property
    def animated(self):
        return self.animate

    def set_settings(self, settings):
        key = (settings.get("media_type", "none"), settings.get("media_path", ""))
        if key == self._key:
            return False
        self.close()
        self._key = key
        self.error = ""
        self._image = _gradient()
        try:
            kind, path = key
            if kind not in ("image", "video") or not path:
                return True
            if Path(path).stat().st_size > MAX_MEDIA_BYTES:
                raise ValueError("Media exceeds the 1 GiB safety limit.")
            if kind == "video":
                import av
                self._container = av.open(path)
                streams = list(self._container.streams.video)
                if not streams:
                    raise ValueError("No video stream was found in this file.")
                self._stream = streams[0]
                if self._stream.width * self._stream.height > MAX_VIDEO_PIXELS:
                    raise ValueError("Video exceeds the 3840×2160 pixel safety limit.")
                self._stream.thread_type = "SLICE"
                self._stream.codec_context.thread_count = 1
                self._decoder = iter(self._container.decode(self._stream))
                self._period = 1 / max(1.0, min(60.0, float(self._stream.average_rate or 25)))
                self.animate = True
            else:
                self._source = Image.open(path)
                if self._source.width * self._source.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image exceeds the 16 megapixel safety limit.")
                # n_frames scans an entire GIF. is_animated checks only whether
                # a second frame exists; enforce the count as frames are played.
                self.animate = bool(getattr(self._source, "is_animated", False))
                self._image = cover_image(self._source)
                self._deadline = time.monotonic() + max(0.02, float(self._source.info.get("duration", 100)) / 1000)
                if not self.animate:
                    self._source.close()
                    self._source = None
        except Exception as error:
            self.close()
            self._image = _gradient()
            self.error = f"Cannot load media: {error}"
            raise ValueError(self.error) from error
        return True

    def frame(self):
        now = time.monotonic()
        if not self.animate or now < self._deadline:
            return self._image
        try:
            if self._container is not None:
                advanced = 0
                while now >= self._deadline and advanced < 4:
                    try:
                        decoded = next(self._decoder)
                    except StopIteration:
                        self._container.seek(0, stream=self._stream)
                        self._decoder = iter(self._container.decode(self._stream))
                        decoded = next(self._decoder)
                    if decoded.width * decoded.height > MAX_VIDEO_PIXELS:
                        raise ValueError("Decoded video exceeds the pixel safety limit.")
                    self._deadline = (self._deadline or now) + self._period
                    advanced += 1
                # Native image size is checked above. ImageOps.fit avoids allocating
                # a huge intermediate for extreme aspect ratios.
                self._image = cover_image(decoded.to_image())
                if now >= self._deadline:
                    self._deadline = now + self._period
            else:
                advanced = 0
                while now >= self._deadline and advanced < 4:
                    self._index += 1
                    try:
                        self._source.seek(self._index)
                    except EOFError:
                        self._index = 0
                        self._source.seek(0)
                    if self._index >= MAX_ANIMATION_FRAMES:
                        raise ValueError("Animation exceeds the 10,000-frame safety limit.")
                    duration = max(0.02, float(self._source.info.get("duration", 100)) / 1000)
                    self._deadline = (self._deadline or now) + duration
                    advanced += 1
                self._image = cover_image(self._source)
                if now >= self._deadline:
                    self._deadline = now + duration
        except Exception as error:
            self.error = f"Media playback stopped: {error}"
            self.close()
            raise ValueError(self.error) from error
        return self._image

    def close(self):
        if self._source is not None:
            self._source.close()
        if self._container is not None:
            self._container.close()
        self._source = self._container = self._decoder = self._stream = None
        self.animate = False
        self._index = 0
        self._deadline = 0.0
