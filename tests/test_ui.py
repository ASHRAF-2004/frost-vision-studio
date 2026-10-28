"""No physical screen is opened by these lifecycle and bounded-pipeline tests."""
import copy
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
import pytest
from PySide6.QtWidgets import QApplication

from frostvision import ui
from frostvision.core import load_settings


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeLock:
    def acquire(self):
        return True

    def release(self):
        pass


@pytest.fixture(autouse=True)
def isolated_control_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "RENDERER_STATUS", tmp_path / "renderer-status.json")
    monkeypatch.setattr(ui, "RENDERER_CONTROL", tmp_path / "renderer-control.json")


@pytest.fixture
def settings():
    value = load_settings()
    value.update(media_type="none", media_path="", autostart=False)
    return value


def test_preview_never_opens_usb_and_single_slot_replaces_frames(settings):
    opened = []

    def forbidden_display():
        opened.append(True)
        raise AssertionError("Preview must not open USB")

    worker = ui.CompositionWorker(settings, display_factory=forbidden_display)
    worker.start()
    try:
        assert wait_until(lambda: worker.latest_frame() is not None)
        first = worker.latest_frame()
        settings["overlay_styles"]["clock"]["prefix"] = "Changed "
        worker.update_settings(settings)
        assert wait_until(lambda: worker.latest_frame(first[0]) is not None)
        latest = worker.latest_frame()
        assert latest[0] > first[0]
        assert latest[1].size == (480, 480)
        assert worker.latest_frame(latest[0]) is None
        assert not opened
    finally:
        assert worker.shutdown(3)
    assert worker.latest_frame() is None


def test_worker_releases_device_and_stops_after_failed_transfer(settings, monkeypatch):
    monkeypatch.setattr(ui, "RendererLock", FakeLock)
    actions = []

    class FailingDisplay:
        def __init__(self):
            actions.append("open")

        def send(self, _frame):
            actions.append("send")
            raise OSError("unplugged")

        def close(self):
            actions.append("close")

    worker = ui.CompositionWorker(settings, display_factory=FailingDisplay)
    worker.start_display()
    worker.start()
    try:
        assert wait_until(lambda: "unplugged" in worker.state.error)
        time.sleep(0.2)
        assert actions == ["open", "send", "close"]
        assert not worker.state.running
        assert worker.latest_frame() is not None
    finally:
        assert worker.shutdown(3)


def test_background_renderer_accepts_only_its_token_and_cleans_status(settings, monkeypatch):
    monkeypatch.setattr(ui, "RendererLock", FakeLock)
    actions = []

    class Display:
        def __init__(self):
            actions.append("open")

        def send(self, _frame):
            actions.append("send")

        def close(self):
            actions.append("close")

    worker = ui.CompositionWorker(settings, display_factory=Display, follow_settings=True)
    worker.start_display()
    worker.start()
    try:
        assert wait_until(lambda: bool(worker.owner_token))
        token = worker.owner_token
        ui._write_control_file(ui.RENDERER_CONTROL, {"token": "old-session", "action": "stop"})
        worker.update_settings(settings)
        time.sleep(0.15)
        assert worker.is_alive() and worker.state.running
        ui._write_control_file(ui.RENDERER_CONTROL, {"token": token, "action": "stop"})
        worker.update_settings(settings)
        assert wait_until(lambda: not worker.is_alive())
        assert actions[0] == "open" and actions[-1] == "close"
        assert not ui.RENDERER_STATUS.exists()
    finally:
        assert worker.shutdown(3)


def test_repeated_start_stop_cannot_bypass_frame_cap(settings, monkeypatch):
    monkeypatch.setattr(ui, "RendererLock", FakeLock)
    sends = []

    class Display:
        def send(self, _frame):
            sends.append(time.monotonic())

        def close(self):
            pass

    worker = ui.CompositionWorker(settings, display_factory=Display)
    worker.start()
    try:
        require_first = wait_until(lambda: worker.latest_frame() is not None)
        assert require_first
        started = time.monotonic()
        cycles = 0
        while time.monotonic() - started < 0.75:
            previous = len(sends)
            worker.start_display()
            assert wait_until(lambda: len(sends) > previous)
            worker.stop_display()
            assert wait_until(lambda: not worker.state.running)
            cycles += 1
        elapsed = time.monotonic() - started
        assert cycles >= 3
        assert len(sends) <= int(elapsed * ui.ANIMATION_FPS) + 1
        assert all(b - a >= 0.09 for a, b in zip(sends, sends[1:]))
    finally:
        assert worker.shutdown(3)


def test_settings_bursts_and_animation_cannot_accumulate_or_exceed_cap(settings, monkeypatch):
    sources = []

    class FastAnimation:
        animate = True
        error = ""

        def __init__(self, _settings):
            self.frames = 0
            self.closed = False
            sources.append(self)

        def set_settings(self, _settings):
            pass

        def frame(self):
            self.frames += 1
            return Image.new("RGB", (480, 480))

        def close(self):
            self.closed = True

    monkeypatch.setattr(ui, "BackgroundSource", FastAnimation)
    worker = ui.CompositionWorker(settings)
    worker.start()
    try:
        started = time.monotonic()
        while time.monotonic() - started < 0.65:
            worker.update_settings(settings)
            time.sleep(0.005)
        # One source/frame slot, with no catch-up burst even when controls change.
        assert len(sources) == 1
        assert 2 <= sources[0].frames <= 8
        assert worker.latest_frame()[0] == sources[0].frames
    finally:
        assert worker.shutdown(3)
    assert sources[0].closed


def test_invalid_media_reports_error_but_keeps_a_preview(settings, tmp_path):
    settings.update(media_type="image", media_path=str(tmp_path / "missing.gif"))
    worker = ui.CompositionWorker(settings)
    worker.start()
    try:
        assert wait_until(lambda: worker.latest_frame() is not None)
        assert "media" in worker.state.status.lower()
        assert worker.latest_frame()[1].size == (480, 480)
    finally:
        assert worker.shutdown(3)


def test_valid_media_clears_prior_media_status_without_clearing_usb_errors(settings, tmp_path):
    settings.update(media_type="image", media_path=str(tmp_path / "missing.gif"))
    worker = ui.CompositionWorker(settings)
    worker.start()
    try:
        assert wait_until(lambda: worker.latest_frame() is not None and bool(worker.state.error))
        failed_sequence = worker.latest_frame()[0]
        settings.update(media_type="none", media_path="")
        worker.update_settings(settings)
        assert wait_until(lambda: worker.latest_frame(failed_sequence) is not None and not worker.state.error)
        assert "Media:" not in worker.state.status
        assert "Preview only" in worker.state.status

        settings.update(media_type="image", media_path=str(tmp_path / "missing-again.gif"))
        worker.update_settings(settings)
        assert wait_until(lambda: bool(worker.state.error))
        # A newer transport error must survive a later successful media change.
        worker._publish_state(error="USB cable disconnected", status="Display stopped: USB cable disconnected")
        settings.update(media_type="none", media_path="")
        before_recovery = worker.latest_frame()[0]
        worker.update_settings(settings)
        assert wait_until(lambda: worker.latest_frame(before_recovery) is not None)
        assert worker.state.error == "USB cable disconnected"
        assert "USB cable disconnected" in worker.state.status
    finally:
        assert worker.shutdown(3)


def test_editor_controls_commit_opacity_position_and_close_cleanly(settings, monkeypatch):
    app = QApplication.instance() or QApplication([])
    saved = []
    monkeypatch.setattr(ui, "save_settings", lambda value: saved.append(copy.deepcopy(value)))
    window = ui.Manager(settings=settings)
    window.show()
    try:
        window.select_overlay("clock")
        window.opacity.setValue(50)
        window.move_selected_overlay(111, 222)
        assert window.settings["overlay_styles"]["clock"]["color"].endswith("80")
        assert window.settings["overlay_styles"]["clock"]["x"] == 111
        assert window.settings["overlay_styles"]["clock"]["y"] == 222
        assert not window.worker.state.running
        deadline = time.monotonic() + 3
        while window.preview.image.isNull() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert not window.preview.image.isNull()
    finally:
        window.close()
        deadline = time.monotonic() + 3
        while window.worker.is_alive() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        assert window.worker.shutdown(3)
        window.close()
    assert saved
