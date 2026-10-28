"""Measure sustained rendering resources; USB output is opt-in with --usb."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psutil
from frostvision.core import BackgroundSource, load_settings, render_frame
from frostvision.platform_support import RendererLock
from frostvision.transport import VmaxUsbDisplay


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--output", type=Path, default=Path("verification-local/soak.json"))
    parser.add_argument("--media", type=Path)
    parser.add_argument("--usb", action="store_true", help="Send frames to the supported physical display")
    args = parser.parse_args()
    if args.seconds < 15:
        parser.error("Use at least 15 seconds to collect meaningful warm-up and samples")
    settings = load_settings()
    if args.media:
        settings["media_path"] = str(args.media.resolve())
        settings["media_type"] = "image" if args.media.suffix.lower() in {".gif", ".png", ".jpg", ".webp"} else "video"
    source = BackgroundSource(settings)
    process = psutil.Process()
    process.cpu_percent()
    display = None
    lock = RendererLock()
    frames = 0
    samples = []
    start = time.monotonic()
    next_sample = start + 1
    error = None
    try:
        if args.usb:
            if not lock.acquire():
                raise RuntimeError("Another display renderer already owns the hardware")
            display = VmaxUsbDisplay()
        while time.monotonic() - start < args.seconds:
            tick = time.monotonic()
            frame = render_frame(settings, source.frame())
            if display:
                display.send(frame)
            frames += 1
            if tick >= next_sample:
                handles = process.num_handles() if sys.platform == "win32" else process.num_fds()
                samples.append({"second": round(tick - start, 2),
                                "rss_mb": round(process.memory_info().rss / 2**20, 3),
                                "cpu_percent_one_core": process.cpu_percent(),
                                "handles_or_fds": handles, "threads": process.num_threads()})
                next_sample = tick + 1
            period = 1 / 15 if source.animate else 1.0
            time.sleep(max(0, period - (time.monotonic() - tick)))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        source.close()
        if display:
            display.close()
        lock.release()
    warm = [sample for sample in samples if sample["second"] >= min(10, args.seconds / 3)]
    first = warm[:max(1, len(warm) // 3)]
    last = warm[-max(1, len(warm) // 3):]
    growth = statistics.mean(s["rss_mb"] for s in last) - statistics.mean(s["rss_mb"] for s in first) if warm else 0
    mean_cpu = statistics.mean(s["cpu_percent_one_core"] for s in warm) if warm else 0
    result = {
        "duration_seconds": round(time.monotonic() - start, 2), "usb_output": args.usb,
        "frames": frames, "media_type": settings.get("media_type"), "error": error,
        "media_error": source.error, "warm_mean_cpu_percent_one_core": round(mean_cpu, 2),
        "warm_mean_cpu_percent_machine": round(mean_cpu / (psutil.cpu_count() or 1), 2),
        "warm_rss_growth_mb": round(growth, 3),
        "passed": not error and not source.error and bool(warm) and growth < 24 and mean_cpu < 85,
        "limits": "Short regression probe, not proof of leak freedom. CPU reports one-core percent and whole-machine equivalent.",
        "samples": samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
