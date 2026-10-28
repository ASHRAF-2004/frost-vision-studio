"""Portable native editor. A single worker owns media decoding and USB.

The worker publishes one replaceable frame slot, never an unbounded signal
queue. The editor and the physical panel share the same composed pictures.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import sys
import threading
import time
import uuid

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFontComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)

from . import __version__
from .core import (BackgroundSource, OVERLAY_DEFAULTS, PANEL_SIZE, load_settings,
                   metric_value, metrics_snapshot, render_frame, rotated_text_bounds, save_settings, text_font)
from .platform_support import CONFIG_DIR, CONFIG_FILE, RendererLock, set_autostart
from .transport import VmaxUsbDisplay, detect_display

LOG = logging.getLogger(__name__)
ANIMATION_FPS = 10
RENDERER_STATUS = CONFIG_DIR / "renderer-status.json"
RENDERER_CONTROL = CONFIG_DIR / "renderer-control.json"


def _read_control_file(path):
    try:
        if path.stat().st_size > 4096:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_control_file(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def external_renderer_status(own_token=None):
    value = _read_control_file(RENDERER_STATUS)
    try:
        fresh = 0 <= time.time() - float(value.get("updated", 0)) < 4
    except (TypeError, ValueError):
        return {}
    return value if fresh and value.get("token") and value.get("token") != own_token else {}


def resource_path(name):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / name


def preview_boxes(settings, metrics):
    boxes = {}
    for key, default in OVERLAY_DEFAULTS.items():
        if not settings.get("overlays", {}).get(key):
            continue
        style = {**default, **settings.get("overlay_styles", {}).get(key, {})}
        text = f"{style.get('prefix', '')}{metric_value(key, metrics)}"
        size = max(8, min(120, int(style.get("size", 28))))
        font = text_font(style.get("font", "Noto Sans"), bool(style.get("bold")), size)
        left, top, right, bottom = rotated_text_bounds(text, font, style.get("rotation", 0))
        x, y = int(style.get("x", 240)), int(style.get("y", 240))
        boxes[key] = (x + left, y + top, x + right, y + bottom)
    return boxes


@dataclass(frozen=True)
class WorkerState:
    running: bool = False
    status: str = "Preview only — use Apply / Start display to connect."
    error: str = ""
    frames_sent: int = 0


class CompositionWorker(threading.Thread):
    """Synchronous bounded media/USB loop; all inputs are settings snapshots."""
    def __init__(self, settings, *, display_factory=VmaxUsbDisplay, follow_settings=False):
        super().__init__(name="FrostVisionComposition", daemon=True)
        self._guard = threading.Lock()
        self._wake = threading.Event()
        self._shutdown = threading.Event()
        self._settings = copy.deepcopy(settings)
        self._revision = 0
        self._want_display = False
        self._latest = None
        self._sequence = 0
        self._state = WorkerState()
        self._display_factory = display_factory
        self._follow_settings = follow_settings
        self._owner_token = None

    @property
    def owner_token(self):
        with self._guard:
            return self._owner_token

    def _heartbeat(self):
        token = self.owner_token
        if token is not None:
            try:
                _write_control_file(RENDERER_STATUS, {"token": token, "updated": time.time(), "running": True})
            except OSError as error:
                LOG.warning("Cannot publish renderer status: %s", error)

    def _clear_heartbeat(self):
        token = self.owner_token
        if token is not None:
            try:
                if _read_control_file(RENDERER_STATUS).get("token") == token:
                    RENDERER_STATUS.unlink(missing_ok=True)
            except OSError as error:
                LOG.warning("Cannot remove renderer status: %s", error)
            finally:
                with self._guard:
                    self._owner_token = None

    def update_settings(self, settings):
        with self._guard:
            self._settings = copy.deepcopy(settings)
            self._revision += 1
        self._wake.set()

    def start_display(self):
        with self._guard:
            self._want_display = True
        self._wake.set()

    def stop_display(self):
        with self._guard:
            self._want_display = False
        self._wake.set()

    def request_shutdown(self):
        self._shutdown.set()
        self._wake.set()

    def shutdown(self, timeout=10.0):
        self.request_shutdown()
        if self.is_alive():
            self.join(timeout)
        return not self.is_alive()

    def latest_frame(self, after=0):
        with self._guard:
            return self._latest if self._latest is not None and self._latest[0] > after else None

    @property
    def state(self):
        with self._guard:
            return self._state

    def _publish_state(self, **values):
        with self._guard:
            self._state = WorkerState(**{**self._state.__dict__, **values})

    def run(self):
        source = display = renderer_lock = None
        applied_revision = -1
        next_frame = 0.0
        last_frame = 0.0
        frames_sent = 0
        settings_stamp = None
        heartbeat_deadline = 0
        try:
            while not self._shutdown.is_set():
                self._wake.clear()
                if self._follow_settings:
                    try:
                        stamp = CONFIG_FILE.stat().st_mtime_ns
                    except OSError:
                        stamp = None
                    if stamp != settings_stamp:
                        settings_stamp = stamp
                        self.update_settings(load_settings())
                control = _read_control_file(RENDERER_CONTROL)
                if self.owner_token and control.get("token") == self.owner_token and control.get("action") == "stop":
                    with self._guard:
                        self._want_display = False
                    if self._follow_settings:
                        self._shutdown.set()
                if self._shutdown.is_set():
                    break
                if self.owner_token and time.monotonic() >= heartbeat_deadline:
                    self._heartbeat()
                    heartbeat_deadline = time.monotonic() + 1
                with self._guard:
                    settings = copy.deepcopy(self._settings)
                    revision, wanted = self._revision, self._want_display
                if not wanted and display is not None:
                    display.close()
                    display = None
                    self._clear_heartbeat()
                    renderer_lock.release()
                    renderer_lock = None
                    self._publish_state(running=False, error="", status="Display stopped — preview remains available.")
                if wanted and display is None:
                    try:
                        renderer_lock = RendererLock()
                        if renderer_lock.acquire() is False:
                            raise RuntimeError("Another Frost Vision renderer is already using this screen.")
                        display = self._display_factory()
                        with self._guard:
                            self._owner_token = uuid.uuid4().hex
                        self._heartbeat()
                        self._publish_state(running=True, error="", status="Frost Vision connected — live composition is running.")
                        next_frame = last_frame + 1 / ANIMATION_FPS
                    except Exception as error:
                        if renderer_lock is not None:
                            renderer_lock.release()
                            renderer_lock = None
                        with self._guard:
                            self._want_display = False
                        self._publish_state(running=False, error=str(error), status=f"Cannot start display: {error}")
                        LOG.warning("Display startup failed: %s", error)
                try:
                    if source is None:
                        source = BackgroundSource({"media_type": "none", "media_path": ""})
                    if applied_revision != revision:
                        previous_media_error = getattr(source, "error", "")
                        try:
                            source.set_settings(settings)
                        except ValueError as error:
                            self._publish_state(error=str(error), status=f"Media: {error}")
                        else:
                            state = self.state
                            if previous_media_error and not source.error and state.error == previous_media_error:
                                self._publish_state(error="", status=(
                                    "Frost Vision connected — live composition is running." if state.running else
                                    "Preview only — use Apply / Start display to connect."
                                ))
                        applied_revision = revision
                        next_frame = min(next_frame, last_frame + 1 / ANIMATION_FPS)
                    now = time.monotonic()
                    if now < next_frame:
                        self._wake.wait(min(next_frame - now, 1.0))
                        continue
                    metrics = metrics_snapshot()
                    frame = render_frame(settings, source.frame(), metrics=metrics)
                    boxes = preview_boxes(settings, metrics)
                    with self._guard:
                        self._sequence += 1
                        self._latest = (self._sequence, frame, boxes)
                    if getattr(source, "error", ""):
                        self._publish_state(error=source.error, status=f"Media: {source.error}")
                    if display is not None:
                        try:
                            display.send(frame)
                            frames_sent += 1
                            self._publish_state(frames_sent=frames_sent)
                        except Exception as error:
                            display.close()
                            display = None
                            self._clear_heartbeat()
                            renderer_lock.release()
                            renderer_lock = None
                            with self._guard:
                                self._want_display = False
                            self._publish_state(running=False, error=str(error), status=f"Display stopped: {error}. Check USB, then start again.")
                            LOG.warning("USB transfer failed: %s", error)
                    # Schedule from completion; never catch up with a burst.
                    last_frame = time.monotonic()
                    next_frame = last_frame + (1 / ANIMATION_FPS if source.animate else 1)
                except Exception as error:
                    self._publish_state(error=str(error), status=f"Preview error: {error}")
                    LOG.exception("Composition failed")
                    self._wake.wait(1)
        finally:
            if display is not None:
                try:
                    display.close()
                except Exception:
                    LOG.exception("USB cleanup failed")
            if renderer_lock is not None:
                self._clear_heartbeat()
                renderer_lock.release()
            if source is not None:
                source.close()
            with self._guard:
                self._latest = None
            self._publish_state(running=False)


class PreviewEditor(QWidget):
    layer_selected = Signal(str)
    layer_moved = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(280, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Live screen preview. Drag the selected text layer to reposition it.")
        self.image = QImage()
        self.boxes = {}
        self.selected = "cpu_temp"
        self.dragging = False

    def _geometry(self):
        side = max(1, min(self.width(), self.height()) - 4)
        return side / PANEL_SIZE, (self.width() - side) / 2, (self.height() - side) / 2

    def _panel_point(self, position):
        scale, dx, dy = self._geometry()
        return (max(0, min(PANEL_SIZE, round((position.x() - dx) / scale))),
                max(0, min(PANEL_SIZE, round((position.y() - dy) / scale))))

    def set_frame(self, frame, boxes):
        frame = frame.convert("RGB")
        # Detach from temporary Python bytes; exactly one Qt image remains.
        self.image = QImage(frame.tobytes(), frame.width, frame.height, frame.width * 3,
                            QImage.Format.Format_RGB888).copy()
        self.boxes = boxes
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scale, dx, dy = self._geometry()
        target = QRectF(dx, dy, PANEL_SIZE * scale, PANEL_SIZE * scale)
        painter.fillRect(target, QColor("#07111c"))
        if not self.image.isNull():
            painter.drawImage(target, self.image)
        painter.setPen(QPen(QColor("#2e5570"), 1))
        painter.drawRect(target)
        if self.selected in self.boxes:
            left, top, right, bottom = self.boxes[self.selected]
            painter.setPen(QPen(QColor("#22e0c2"), 2, Qt.PenStyle.DashLine))
            painter.drawRect(QRectF(dx + (left - 6) * scale, dy + (top - 5) * scale,
                                    (right - left + 12) * scale, (bottom - top + 10) * scale))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = self._panel_point(event.position())
        for key, box in reversed(list(self.boxes.items())):
            if box[0] - 10 <= x <= box[2] + 10 and box[1] - 10 <= y <= box[3] + 10:
                self.selected = key
                self.layer_selected.emit(key)
                self.dragging = True
                self.update()
                return
        if self.selected in self.boxes:
            self.dragging = True
            self.layer_moved.emit(x, y)

    def mouseMoveEvent(self, event):
        if self.dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.layer_moved.emit(*self._panel_point(event.position()))

    def mouseReleaseEvent(self, _event):
        self.dragging = False


STYLE = """
QMainWindow, QDialog { background: #09131f; color: #e5f1f7; }
QWidget { color: #e5f1f7; font-size: 10pt; }
QLabel#subtitle, QLabel#hint { color: #91adbd; }
QLabel#title { font-size: 23pt; font-weight: 700; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: 0; }
QGroupBox { border: 1px solid #294253; border-radius: 10px; margin-top: 12px; padding: 16px 12px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; color: #a8cfe3; }
QLineEdit, QSpinBox, QComboBox, QTextBrowser { background: #122536; border: 1px solid #36576a; border-radius: 5px; padding: 5px; selection-background-color: #176d73; }
QComboBox QAbstractItemView { background: #122536; color: #e5f1f7; selection-background-color: #176d73; }
QPushButton { background: #173145; border: 1px solid #3b6076; border-radius: 6px; padding: 8px 12px; }
QPushButton:hover { background: #24465b; }
QPushButton:pressed { background: #0f2535; }
QPushButton:disabled { color: #78909f; border-color: #263b49; }
QPushButton#primary { background: #22e0c2; border-color: #22e0c2; color: #061b24; font-weight: 700; }
QPushButton#primary:hover { background: #6beed8; }
QCheckBox { spacing: 8px; font-weight: 400; }
QToolTip { color: #e5f1f7; background: #173145; border: 1px solid #36576a; }
"""


class Manager(QMainWindow):
    def __init__(self, start_panel=False, *, settings=None, worker_factory=CompositionWorker):
        super().__init__()
        self.settings = copy.deepcopy(settings) if settings is not None else load_settings()
        self.selected_overlay = "cpu_temp"
        self._updating_controls = False
        self._sequence = 0
        self._closing = False
        self._last_state = None
        self._external = {}
        self._external_deadline = 0
        self._color = QColor("#ffffff")
        self.setWindowTitle("Frost Vision Studio")
        self.setWindowIcon(QIcon(str(resource_path("aio-screen-manager.svg"))))
        self.resize(1100, 850)
        self.setMinimumSize(800, 620)
        self.setStyleSheet(STYLE)
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(24, 20, 24, 20)
        root_layout.setSpacing(12)
        self.setCentralWidget(root)
        heading = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(self.windowIcon().pixmap(54, 54))
        heading.addWidget(icon)
        names = QVBoxLayout()
        title = QLabel("Frost Vision Studio")
        title.setObjectName("title")
        names.addWidget(title)
        subtitle = QLabel("Design your 480 × 480 cooler screen. Drag text directly on the preview.")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        names.addWidget(subtitle)
        heading.addLayout(names, 1)
        about = QPushButton("About")
        about.clicked.connect(self.show_about)
        heading.addWidget(about)
        root_layout.addLayout(heading)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        controls_scroll.setMinimumWidth(330)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 8, 0)
        controls_layout.setSpacing(10)
        self._build_background_controls(controls_layout)
        self._build_layer_controls(controls_layout)
        self._build_display_controls(controls_layout)
        controls_layout.addStretch()
        controls_scroll.setWidget(controls)
        splitter.addWidget(controls_scroll)
        preview_column = QWidget()
        preview_layout = QVBoxLayout(preview_column)
        preview_layout.setContentsMargins(6, 0, 0, 0)
        preview_title = QLabel("LIVE SCREEN PREVIEW")
        preview_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_title.setObjectName("subtitle")
        preview_layout.addWidget(preview_title)
        self.preview = PreviewEditor()
        self.preview.layer_selected.connect(self.select_overlay)
        self.preview.layer_moved.connect(self.move_selected_overlay)
        preview_layout.addWidget(self.preview, 1)
        hint = QLabel("Click a layer to select it, then drag to position.\nPreview and screen use the same composition.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        preview_layout.addWidget(hint)
        splitter.addWidget(preview_column)
        splitter.setSizes([425, 590])
        splitter.setStretchFactor(1, 1)
        root_layout.addWidget(splitter, 1)
        footer = QHBoxLayout()
        self.status = QLabel("Preview only — use Apply / Start display to connect.")
        self.status.setWordWrap(True)
        self.status.setObjectName("subtitle")
        footer.addWidget(self.status, 1)
        self.stop_button = QPushButton("Stop display")
        self.stop_button.clicked.connect(self.close_panel)
        self.stop_button.setEnabled(False)
        footer.addWidget(self.stop_button)
        self.show_button = QPushButton("Apply / Start display")
        self.show_button.setObjectName("primary")
        self.show_button.clicked.connect(self.show_panel)
        footer.addWidget(self.show_button)
        root_layout.addLayout(footer)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(250)
        self.save_timer.timeout.connect(self._save)
        self.worker = worker_factory(self.settings)
        self.load_selected_controls()
        self.worker.start()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(100)
        self.refresh_timer.timeout.connect(self.update_preview)
        self.refresh_timer.start()
        self.close_timer = QTimer(self)
        self.close_timer.setInterval(50)
        self.close_timer.timeout.connect(self._poll_close)
        if start_panel:
            QTimer.singleShot(0, self.show_panel)

    @staticmethod
    def _box(title, parent):
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setSpacing(10)
        parent.addWidget(group)
        return layout

    @staticmethod
    def _rotation_combo():
        combo = QComboBox()
        for rotation in (0, 90, 180, 270):
            combo.addItem(f"{rotation}°", rotation)
        return combo

    def _build_background_controls(self, parent):
        box = self._box("Background", parent)
        self.media_label = QLabel(self.media_name())
        self.media_label.setWordWrap(True)
        box.addWidget(self.media_label)
        row = QHBoxLayout()
        for label, kind in (("Image / GIF…", "image"), ("Video…", "video")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, kind=kind: self.choose_media(kind))
            row.addWidget(button)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear_media)
        row.addWidget(clear)
        box.addLayout(row)
        form = QFormLayout()
        self.rotation = self._rotation_combo()
        self.rotation.setCurrentIndex(self.rotation.findData(self.settings["background_transform"].get("rotation", 0)))
        self.rotation.currentIndexChanged.connect(self.change_transform)
        form.addRow("Rotation", self.rotation)
        box.addLayout(form)
        self.flip_horizontal = QCheckBox("Flip horizontally")
        self.flip_vertical = QCheckBox("Flip vertically")
        for name, control in (("flip_horizontal", self.flip_horizontal), ("flip_vertical", self.flip_vertical)):
            control.setChecked(bool(self.settings["background_transform"].get(name)))
            control.toggled.connect(self.change_transform)
            box.addWidget(control)

    def _build_layer_controls(self, parent):
        box = self._box("Text layers", parent)
        form = QFormLayout()
        self.layer_selector = QComboBox()
        for key, style in OVERLAY_DEFAULTS.items():
            self.layer_selector.addItem(style["name"], key)
        self.layer_selector.currentIndexChanged.connect(lambda _: self.select_overlay(self.layer_selector.currentData()))
        form.addRow("Edit layer", self.layer_selector)
        box.addLayout(form)
        self.layer_enabled = QCheckBox("Show this text layer")
        self.layer_enabled.toggled.connect(self.layer_control_changed)
        box.addWidget(self.layer_enabled)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.prefix = QLineEdit()
        self.prefix.setMaxLength(200)
        self.prefix.textEdited.connect(self.layer_control_changed)
        form.addRow("Text before value", self.prefix)
        self.font_button = QFontComboBox()
        self.font_button.setFontFilters(QFontComboBox.FontFilter.ScalableFonts)
        self.font_button.currentFontChanged.connect(self.layer_control_changed)
        form.addRow("Font", self.font_button)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 120)
        self.font_size.valueChanged.connect(self.layer_control_changed)
        self.bold = QCheckBox("Bold")
        self.bold.toggled.connect(self.layer_control_changed)
        row = QHBoxLayout()
        row.addWidget(self.font_size)
        row.addWidget(self.bold)
        form.addRow("Size / style", row)
        self.color = QPushButton("Choose color…")
        self.color.clicked.connect(self.choose_color)
        form.addRow("Text color", self.color)
        self.opacity = QSpinBox()
        self.opacity.setRange(0, 100)
        self.opacity.setSuffix(" %")
        self.opacity.valueChanged.connect(self.layer_control_changed)
        form.addRow("Opacity", self.opacity)
        self.position_x, self.position_y = QSpinBox(), QSpinBox()
        row = QHBoxLayout()
        for control in (self.position_x, self.position_y):
            control.setRange(0, PANEL_SIZE)
            control.valueChanged.connect(self.layer_control_changed)
            row.addWidget(control)
        form.addRow("Position X / Y", row)
        self.text_rotation = self._rotation_combo()
        self.text_rotation.currentIndexChanged.connect(self.layer_control_changed)
        form.addRow("Text rotation", self.text_rotation)
        box.addLayout(form)
        reset = QPushButton("Reset selected text")
        reset.clicked.connect(self.reset_selected)
        box.addWidget(reset)

    def _build_display_controls(self, parent):
        box = self._box("Display", parent)
        self.autostart = QCheckBox("Start this composition when I log in")
        self.autostart.setChecked(bool(self.settings.get("autostart")))
        self.autostart.setToolTip("Runs the saved composition at login without opening the editor.")
        self.autostart.toggled.connect(self.toggle_autostart)
        box.addWidget(self.autostart)
        note = QLabel("480 × 480 · USB 345f:9132\nAnimation limited to 10 FPS · metrics once per second\nClosing the editor stops its display session.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        box.addWidget(note)
        diagnostics = QPushButton("Connection details")
        diagnostics.clicked.connect(self.show_diagnostics)
        box.addWidget(diagnostics)

    def media_name(self):
        path = self.settings.get("media_path", "")
        return f"{self.settings.get('media_type', 'image').title()}: {Path(path).name}" if path else "Dark gradient — no background selected"

    def change_transform(self, *_):
        self.settings["background_transform"] = {
            "rotation": self.rotation.currentData() or 0,
            "flip_horizontal": self.flip_horizontal.isChecked(),
            "flip_vertical": self.flip_vertical.isChecked(),
        }
        self.commit_changes()

    def select_overlay(self, key):
        if not key or key not in OVERLAY_DEFAULTS:
            return
        self.selected_overlay = self.preview.selected = key
        self.layer_selector.blockSignals(True)
        self.layer_selector.setCurrentIndex(self.layer_selector.findData(key))
        self.layer_selector.blockSignals(False)
        self.load_selected_controls()
        self.preview.update()

    def load_selected_controls(self):
        self._updating_controls = True
        try:
            style = {**OVERLAY_DEFAULTS[self.selected_overlay], **self.settings["overlay_styles"].get(self.selected_overlay, {})}
            self.layer_enabled.setChecked(bool(self.settings["overlays"].get(self.selected_overlay)))
            self.prefix.setText(str(style.get("prefix", "")))
            self.font_button.setCurrentFont(QFont(style.get("font", "Noto Sans")))
            self.font_size.setValue(int(style.get("size", 28)))
            self.bold.setChecked(bool(style.get("bold")))
            color = str(style.get("color", "#ffffff")).lstrip("#")
            self._color = QColor("#" + color[:6])
            self.opacity.setValue(round(int(color[6:8], 16) * 100 / 255) if len(color) == 8 else 100)
            self._update_color_button()
            self.position_x.setValue(int(style.get("x", 240)))
            self.position_y.setValue(int(style.get("y", 240)))
            self.text_rotation.setCurrentIndex(self.text_rotation.findData(int(style.get("rotation", 0)) % 360))
        finally:
            self._updating_controls = False

    def _update_color_button(self):
        name = self._color.name()
        self.color.setText(name.upper())
        self.color.setStyleSheet(f"QPushButton {{ border-left: 12px solid {name}; }}")

    def choose_color(self):
        color = QColorDialog.getColor(self._color, self, "Text color")
        if color.isValid():
            self._color = color
            self._update_color_button()
            self.layer_control_changed()

    def layer_control_changed(self, *_):
        if self._updating_controls:
            return
        key = self.selected_overlay
        self.settings["overlays"][key] = self.layer_enabled.isChecked()
        self.settings["overlay_styles"][key] = {
            **self.settings["overlay_styles"].get(key, {}),
            "x": self.position_x.value(), "y": self.position_y.value(),
            "size": self.font_size.value(), "font": self.font_button.currentFont().family(),
            "bold": self.bold.isChecked(),
            "color": self._color.name() + f"{round(self.opacity.value() * 255 / 100):02x}",
            "prefix": self.prefix.text(), "rotation": self.text_rotation.currentData() or 0,
        }
        self.commit_changes()

    def move_selected_overlay(self, x, y):
        self.settings["overlay_styles"][self.selected_overlay].update(x=int(x), y=int(y))
        self._updating_controls = True
        self.position_x.setValue(x)
        self.position_y.setValue(y)
        self._updating_controls = False
        self.commit_changes()

    def reset_selected(self):
        self.settings["overlay_styles"][self.selected_overlay] = dict(OVERLAY_DEFAULTS[self.selected_overlay])
        self.load_selected_controls()
        self.commit_changes()

    def commit_changes(self):
        self.worker.update_settings(self.settings)
        self.save_timer.start()

    def _save(self):
        try:
            save_settings(self.settings)
            return True
        except (OSError, ValueError) as error:
            LOG.error("Cannot save settings: %s", error)
            self.status.setText(f"Cannot save settings: {error}")
            return False

    def update_preview(self):
        frame = self.worker.latest_frame(self._sequence)
        if frame is not None:
            self._sequence, image, boxes = frame
            self.preview.set_frame(image, boxes)
        state = self.worker.state
        if time.monotonic() >= self._external_deadline:
            self._external = external_renderer_status(self.worker.owner_token)
            self._external_deadline = time.monotonic() + 1
        if self._external and not state.running:
            self.status.setText("Frost Vision background renderer is running — saved edits are applied automatically.")
            self.stop_button.setEnabled(True)
        elif state != self._last_state or self.stop_button.isEnabled() != state.running:
            self._last_state = state
            self.status.setText(state.status)
            self.stop_button.setEnabled(state.running)

    def choose_media(self, kind):
        filters = "Images and animated GIFs (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff);;All files (*)" if kind == "image" else "Videos (*.mp4 *.mkv *.mov *.avi *.webm *.m4v);;All files (*)"
        path, _ = QFileDialog.getOpenFileName(self, "Choose a background", "", filters)
        if path:
            self.settings.update(media_type=kind, media_path=path)
            self.media_label.setText(self.media_name())
            self.commit_changes()

    def clear_media(self):
        self.settings.update(media_type="none", media_path="")
        self.media_label.setText(self.media_name())
        self.commit_changes()

    def toggle_autostart(self, enabled):
        try:
            set_autostart(enabled)
        except (OSError, RuntimeError, ValueError) as error:
            self.autostart.blockSignals(True)
            self.autostart.setChecked(not enabled)
            self.autostart.blockSignals(False)
            QMessageBox.warning(self, "Startup setting", str(error))
            return
        self.settings["autostart"] = enabled
        self.commit_changes()

    def show_panel(self):
        if self._save():
            self._external = external_renderer_status(self.worker.owner_token)
            if self._external:
                self.status.setText("Saved composition applied to the background renderer.")
                return
            self.worker.update_settings(self.settings)
            self.worker.start_display()
            self.status.setText("Connecting to the Frost Vision screen…")

    def close_panel(self):
        external = external_renderer_status(self.worker.owner_token)
        if external:
            try:
                _write_control_file(RENDERER_CONTROL, {"token": external["token"], "action": "stop"})
            except OSError as error:
                self.status.setText(f"Cannot stop background session: {error}")
                return
        else:
            self.worker.stop_display()
        self.status.setText("Stopping the display session…")

    def show_diagnostics(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Connection details")
        dialog.resize(650, 420)
        layout = QVBoxLayout(dialog)
        text = QTextBrowser()
        text.setPlainText("Reading USB device information…")
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        result = {}
        done = threading.Event()

        def probe():
            try:
                result["value"] = detect_display()
            except Exception as error:
                result["value"] = {"error": str(error)}
            done.set()

        threading.Thread(target=probe, name="FrostVisionDiagnostics", daemon=True).start()
        timer = QTimer(dialog)
        timer.setInterval(100)

        def poll():
            if done.is_set():
                text.setPlainText(json.dumps(result["value"], indent=2, default=str))
                timer.stop()

        timer.timeout.connect(poll)
        timer.start()
        dialog.exec()

    def _show_document(self, path, title):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(680, 520)
        layout = QVBoxLayout(dialog)
        text = QTextBrowser()
        text.setOpenExternalLinks(True)
        text.setMarkdown(path.read_text(encoding="utf-8"))
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def show_about(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("About Frost Vision Studio")
        dialog.resize(620, 460)
        layout = QVBoxLayout(dialog)
        text = QTextBrowser()
        text.setOpenExternalLinks(True)
        text.setHtml(f"<h2>Frost Vision Studio {__version__}</h2>"
                     "<p>An independent editor and direct USB display renderer for the Invasion Frost Vision 480 × 480 AIO screen.</p>"
                     "<p>Created by Ashraf Ali Hussain Al-Saloul.</p><p>Python · Qt for Python · Pillow · PyAV · PyUSB · HIDAPI</p>"
                     "<p><a href='https://github.com/ASHRAF-2004/frost-vision-studio'>Source, documentation and releases</a></p>"
                     "<p>MIT-licensed application. Bundled libraries retain their own licenses; see the third-party notices.</p>")
        layout.addWidget(text)
        for title, name in (("Terms and conditions", "docs/TERMS.md"), ("Privacy", "docs/PRIVACY.md"), ("Third-party notices", "THIRD_PARTY_NOTICES.md")):
            path = resource_path(name)
            if path.is_file():
                button = QPushButton(title)
                button.clicked.connect(lambda _checked=False, path=path, title=title: self._show_document(path, title))
                layout.addWidget(button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def closeEvent(self, event):
        if not self.worker.is_alive():
            self.refresh_timer.stop()
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._closing = True
        self.save_timer.stop()
        self._save()
        self.worker.request_shutdown()
        self.centralWidget().setEnabled(False)
        self.status.setText("Closing media and USB resources…")
        self.close_timer.start()

    def _poll_close(self):
        if not self.worker.is_alive():
            self.close_timer.stop()
            self.close()
