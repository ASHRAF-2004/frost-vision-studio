"""Opt-in resource/lifecycle stress lane; uses generated media and fake USB.

Run from the repository root:
    python scripts/stress_worker.py --cycles 72 --output verification-local/worker-stress.json

No real device is enumerated or opened. Temporary settings, control files and
renderer locks are isolated from the owner's app session. This short experiment
checks repeated native decoder disposal; it does not prove long-term leak freedom.
"""
from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
import weakref

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import av
from PIL import Image, ImageDraw
import psutil

from frostvision import __version__, core, platform_support, ui


def require(predicate, message, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError(message)


def snapshot(process, cycle, stage):
    gc.collect()
    return dict(cycle=cycle, stage=stage, elapsed=time.monotonic(),
                rss_bytes=process.memory_info().rss,
                handles=process.num_handles() if sys.platform == "win32" else process.num_fds(),
                threads=process.num_threads())


def make_assets(directory):
    static = directory / "static.png"
    gif = directory / "animation.gif"
    video = directory / "animation.mp4"
    pictures = []
    for index in range(8):
        picture = Image.new("RGB", (320, 240), (15 + index * 20, 80, 130))
        ImageDraw.Draw(picture).rectangle((index * 16, 50, index * 16 + 60, 130), fill="white")
        pictures.append(picture)
    pictures[0].save(static)
    pictures[0].save(gif, save_all=True, append_images=pictures[1:], duration=60, loop=0)
    with av.open(str(video), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 320, 240, "yuv420p"
        for picture in pictures:
            for packet in stream.encode(av.VideoFrame.from_image(picture)):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    for picture in pictures:
        picture.close()
    return [("image", static), ("image", gif), ("video", video)]


def run(cycles):
    process = psutil.Process()
    started = time.monotonic()
    counters = dict(opens=0, sends=0, closes=0, maximum_live_displays=0,
                    live_displays=0, source_instances=0, media_switches=0,
                    native_image_closes=0, native_video_closes=0)
    samples = []
    checks = {}
    errors = []

    class FakeDisplay:
        def __init__(self):
            self.closed = False
            counters["opens"] += 1
            counters["live_displays"] += 1
            counters["maximum_live_displays"] = max(counters["maximum_live_displays"], counters["live_displays"])

        def send(self, frame):
            assert not self.closed and frame.size == (480, 480)
            counters["sends"] += 1

        def close(self):
            if not self.closed:
                counters["closes"] += 1
                counters["live_displays"] -= 1
                self.closed = True

    class TrackedSource(core.BackgroundSource):
        def __init__(self, settings):
            counters["source_instances"] += 1
            super().__init__(settings)

        def set_settings(self, settings):
            changed = super().set_settings(settings)
            if changed:
                counters["media_switches"] += 1
            return changed

        def close(self):
            if getattr(self, "_source", None) is not None:
                counters["native_image_closes"] += 1
            if getattr(self, "_container", None) is not None:
                counters["native_video_closes"] += 1
            super().close()

    with tempfile.TemporaryDirectory(prefix="frost-worker-stress-") as temporary:
        directory = Path(temporary)
        assets = make_assets(directory)
        lock_path = directory / "renderer.lock"
        config_file = directory / "settings.json"
        lock_class = platform_support.RendererLock
        settings = core.default_settings()
        settings["overlays"].update(cpu_temp=False, gpu_temp=False, cpu_usage=True, gpu_usage=False, clock=True)
        # Initialize bounded font/sensor/codec caches before the comparison.
        # A cold process baseline would misclassify retained font handles as a leak.
        for kind, path in assets:
            warm_settings = core.normalize_settings({**settings, "media_type": kind, "media_path": str(path)})
            warm_source = core.BackgroundSource(warm_settings)
            try:
                time.sleep(0.11)
                warm_frame = core.render_frame(warm_settings, warm_source.frame())
                ui.preview_boxes(warm_settings, core.metrics_snapshot())
                warm_frame.close()
            finally:
                warm_source.close()
        del warm_source, warm_frame
        cpu_start = sum(process.cpu_times()[:2])
        baseline = snapshot(process, 0, "before_worker")
        samples.append(baseline)
        worker = None
        with patch.object(ui, "BackgroundSource", TrackedSource), \
             patch.object(ui, "RENDERER_STATUS", directory / "renderer-status.json"), \
             patch.object(ui, "RENDERER_CONTROL", directory / "renderer-control.json"), \
             patch.object(ui, "CONFIG_FILE", config_file), \
             patch.object(ui, "RendererLock", lambda: lock_class(lock_path)):
            try:
                worker = ui.CompositionWorker(settings, display_factory=FakeDisplay)
                worker.start()
                require(lambda: worker.latest_frame() is not None, "initial preview did not appear")
                token_history = set()
                for cycle in range(1, cycles + 1):
                    kind, path = assets[(cycle - 1) % len(assets)]
                    settings.update(media_type=kind, media_path=str(path))
                    settings["overlay_styles"]["clock"].update(prefix=f"Cycle {cycle} ", rotation=(cycle % 4) * 90)
                    settings["background_transform"]["flip_horizontal"] = bool(cycle % 2)
                    old_sequence = worker.latest_frame()[0]
                    previous_sends = counters["sends"]
                    worker.update_settings(settings)
                    worker.start_display()
                    require(lambda: worker.state.running, f"cycle {cycle}: display did not start")
                    require(lambda: counters["sends"] > previous_sends and worker.latest_frame(old_sequence) is not None,
                            f"cycle {cycle}: updated frame was not sent")
                    token = worker.owner_token
                    assert token and token not in token_history, "a stopped renderer token was reused"
                    token_history.add(token)
                    contender = lock_class(lock_path)
                    assert contender.acquire() is False, "second renderer lock succeeded while display owned"
                    contender.release()
                    assert ui.external_renderer_status().get("token") == token
                    # Old tokens must not stop a newly started session.
                    ui._write_control_file(ui.RENDERER_CONTROL, {"token": "stale-token", "action": "stop"})
                    worker.update_settings(settings)
                    if cycle % 6 == 0 or cycle % 12 == 2:
                        # Run across the generated GIF/video loop boundary too.
                        target_frames = 12 if kind == "video" else 10
                        require(lambda: counters["sends"] >= previous_sends + target_frames,
                                f"cycle {cycle}: animated decoder did not advance")
                    assert worker.state.running and not worker.state.error, worker.state
                    worker.stop_display()
                    require(lambda: not worker.state.running, f"cycle {cycle}: display did not stop")
                    require(lambda: worker.owner_token is None, f"cycle {cycle}: owner token retained")
                    assert not ui.RENDERER_STATUS.exists(), "stopped renderer left an active status record"
                    contender = lock_class(lock_path)
                    assert contender.acquire(), "renderer lock was not released on Stop"
                    contender.release()
                    if cycle % 6 == 0:
                        samples.append(snapshot(process, cycle, "warmup" if cycle <= 12 else "steady"))
                checks.update(unique_session_tokens=len(token_history) == cycles,
                              lock_exclusion_and_release=True, stale_stop_ignored=True,
                              same_worker_and_media_owner=counters["source_instances"] == 1,
                              maximum_one_usb_session=counters["maximum_live_displays"] == 1)
            except Exception as error:
                errors.append(f"{type(error).__name__}: {error}")
            finally:
                clean = worker.shutdown(10) if worker else True
                checks["worker_joined"] = clean
                checks["latest_frame_released"] = worker.latest_frame() is None if worker else True
                checks["all_fake_displays_closed"] = counters["opens"] == counters["closes"] and not counters["live_displays"]
                checks["status_released"] = not ui.RENDERER_STATUS.exists()
        owner_reference = weakref.ref(worker) if worker else lambda: None
        worker = None
        gc.collect()
        checks["first_owner_object_released"] = owner_reference() is None
        # Native Windows runtimes can finish destroying worker resources shortly
        # after Python's join returns. Record a settled value, not the exit race.
        time.sleep(0.5)
        after = snapshot(process, cycles, "after_shutdown")
        samples.append(after)
        # A second owner lifetime distinguishes one-time codec/font initialization
        # from resources retained on every start/stop. Keep both raw baselines.
        probe = None
        with patch.object(ui, "BackgroundSource", TrackedSource), \
             patch.object(ui, "RENDERER_STATUS", directory / "renderer-status.json"), \
             patch.object(ui, "RENDERER_CONTROL", directory / "renderer-control.json"), \
             patch.object(ui, "CONFIG_FILE", config_file), \
             patch.object(ui, "RendererLock", lambda: lock_class(lock_path)):
            try:
                probe = ui.CompositionWorker(settings, display_factory=FakeDisplay)
                probe.start()
                require(lambda: probe.latest_frame() is not None, "cleanup probe did not compose")
                for kind, path in assets:
                    settings.update(media_type=kind, media_path=str(path))
                    before = counters["sends"]
                    probe.update_settings(settings)
                    probe.start_display()
                    require(lambda: counters["sends"] > before, "cleanup probe did not send")
                    probe.stop_display()
                    require(lambda: not probe.state.running, "cleanup probe did not release display")
            except Exception as error:
                errors.append(f"Cleanup probe {type(error).__name__}: {error}")
            finally:
                checks["second_worker_joined"] = probe.shutdown(10) if probe else True
        probe_reference = weakref.ref(probe) if probe else lambda: None
        probe = None
        gc.collect()
        checks["second_owner_object_released"] = probe_reference() is None
        time.sleep(0.5)
        after_probe = snapshot(process, cycles + 3, "after_second_owner_shutdown")
        samples.append(after_probe)
        checks["no_thread_growth_across_owner_lifetimes"] = after_probe["threads"] <= after["threads"]
        checks["no_handle_growth_across_owner_lifetimes"] = after_probe["handles"] <= after["handles"] + 1
        steady = [sample for sample in samples if sample["stage"] == "steady"]
        rss_growth = steady[-1]["rss_bytes"] - steady[0]["rss_bytes"] if len(steady) > 1 else None
        checks["steady_rss_growth_under_20_mib"] = rss_growth is not None and rss_growth < 20 * 1024 * 1024
        duration = time.monotonic() - started
        cpu_seconds = sum(process.cpu_times()[:2]) - cpu_start
        for sample in samples:
            sample["elapsed"] = round(sample["elapsed"] - started, 3)
        return dict(app_version=__version__, lane="generated-media worker start/stop stress", usb_writes=False,
                    cycles_requested=cycles, cleanup_probe_cycles=3, elapsed_seconds=round(duration, 3),
                    cpu_seconds=round(cpu_seconds, 3),
                    average_one_core_cpu_percent=round(cpu_seconds / duration * 100, 2),
                    average_machine_cpu_percent=round(cpu_seconds / duration / (psutil.cpu_count() or 1) * 100, 2),
                    steady_rss_growth_bytes=rss_growth, counters=counters, checks=checks,
                    retained_after_first_owner=dict(threads=after["threads"] - baseline["threads"],
                                                    handles=after["handles"] - baseline["handles"]),
                    samples=samples, errors=errors,
                    passed=not errors and all(checks.values()),
                    limits="Short synthetic run on this host; no physical USB throughput, long-runtime guarantee, codec universality, or Linux runtime claim.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=72)
    parser.add_argument("--output", type=Path, default=Path("verification-local/worker-stress.json"))
    args = parser.parse_args()
    if not 24 <= args.cycles <= 120:
        parser.error("--cycles must be between 24 and 120")
    report = run(args.cycles)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "samples"}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
