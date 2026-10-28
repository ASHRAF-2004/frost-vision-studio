"""Application entry point and read-only/no-device verification lanes."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import signal
import sys
import time

from . import __version__


def _write_result(value, output=None):
    text = json.dumps(value, indent=2, default=str)
    if output is not None:
        Path(output).write_text(text + "\n", encoding="utf-8")
    if sys.stdout is not None:
        print(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Frost Vision Studio — direct USB AIO display editor")
    parser.add_argument("--version", action="version", version=f"Frost Vision Studio {__version__}")
    parser.add_argument("--render", action="store_true", help="run the saved composition without opening the editor")
    parser.add_argument("--panel", action="store_true", help="open the editor and start its display session")
    parser.add_argument("--diagnose", action="store_true", help="read-only USB diagnostics; no screen writes")
    parser.add_argument("--smoke-test", action="store_true", help="open, render and close the editor without USB writes")
    parser.add_argument("--output", type=Path, help="write diagnostic/smoke-test JSON to this file (useful for the Windows GUI executable)")
    args = parser.parse_args(argv)
    if args.smoke_test and (args.render or args.panel):
        parser.error("--smoke-test cannot be combined with --render or --panel")
    if args.diagnose:
        from .transport import detect_display
        _write_result({"app_version": __version__, **detect_display()}, args.output)
        return 0

    from .platform_support import CONFIG_DIR
    from logging.handlers import RotatingFileHandler
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(CONFIG_DIR / "frost-vision-studio.log", maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.render:
        from .core import load_settings
        from .ui import CompositionWorker
        worker = CompositionWorker(load_settings(), follow_settings=True)
        stopping = False

        def stop(_signal, _frame):
            nonlocal stopping
            stopping = True
            worker.request_shutdown()

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        worker.start_display()
        worker.start()
        started = time.monotonic()
        try:
            while worker.is_alive() and not stopping:
                state = worker.state
                if state.error and not state.running:
                    logging.error("Renderer stopped: %s", state.error)
                    return 1
                if time.monotonic() - started > 15 and not state.running:
                    logging.error("Renderer did not start within 15 seconds")
                    return 1
                time.sleep(0.2)
        finally:
            worker.shutdown(10)
        return 0

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .ui import Manager
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("Frost Vision Studio")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("FrostVisionStudio")
    window = Manager(start_panel=args.panel)
    window.show()
    smoke = {"frame": False, "clean_shutdown": False}
    if args.smoke_test:
        def finish_smoke():
            smoke["frame"] = not window.preview.image.isNull()
            window.close()

        QTimer.singleShot(1500, finish_smoke)
        QTimer.singleShot(12000, app.quit)
    result = app.exec()
    clean = window.worker.shutdown(10)
    if args.smoke_test:
        smoke["clean_shutdown"] = clean
        _write_result({"smoke_test": smoke, "usb_writes": False}, args.output)
        return 0 if smoke["frame"] and clean else 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
