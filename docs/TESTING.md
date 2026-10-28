# Verification lanes

Tests answer different questions. Keep unit/UI checks, sustained resource measurements, package checks, and physical-device validation separate. Ordinary CI must not configure a real screen or write USB frames.

## Fast lane

Use the development environment from [INSTALLATION.md](INSTALLATION.md#from-source). From the repository root:

```text
python -m pytest -q
python aio_screen_manager.py --smoke-test
python aio_screen_manager.py --diagnose
```

For a headless test host, set Qt to offscreen before running the unit/UI smoke checks:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest -q
python aio_screen_manager.py --smoke-test
```

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
QT_QPA_PLATFORM=offscreen python aio_screen_manager.py --smoke-test
```

The smoke test opens the preview, waits for a frame, closes the editor, and reports frame/shutdown results. It does not start physical output. `--diagnose` reports device/backend availability without configuring the panel. These commands do not establish correct real-screen output or visual acceptance.

Unit tests cover selected settings validation/persistence, rendering, media lifecycle, transport framing, and UI behavior using isolated or mocked dependencies. Review the actual files under [tests](../tests/) for current coverage; a test count is not a statement of complete coverage.

## Soak lane

Run sustained measurements for changes to media, frame handling, sensors, worker lifetime, or cleanup:

```text
python scripts/soak.py --seconds 120 --output verification-local/soak.json
```

The default test uses the saved composition without physical output. Select a representative local media file explicitly when checking animation/video:

```text
python scripts/soak.py --seconds 600 --media path/to/sample.gif --output verification-local/gif-soak.json
python scripts/soak.py --seconds 600 --media path/to/sample.mp4 --output verification-local/video-soak.json
```

The direct composition probe runs animated media at up to **15 fps** as a stress lane; the interactive editor/renderer uses its separate **10 fps** cap. Static probe frames use a 1 Hz cadence. The script samples process RSS, CPU, handles/file descriptors, and threads once per second, then compares warm-period measurements. Its JSON includes errors, media errors, frame count, raw samples, and an explicit `passed` result.

Current regression gates require warm RSS growth below 24 MiB and mean CPU below 85% of one logical core, with usable warm samples and no media/runtime error. CPU is reported both as a one-core percentage and as an equivalent whole-machine percentage. These are regression thresholds for this probe, not guaranteed real-world resource ceilings.

A 20-second CI probe catches gross regressions. A two-minute local run is still a short regression test. For a leak investigation, use longer runs, multiple media types, repeated media replacement, start/stop cycles, and unplug/reconnect scenarios. Inspect trends rather than treating one passing exit code as proof of leak freedom. A direct composition probe does not measure the full Qt UI or exercise USB unless requested.

Exercise repeated native-decoder replacement and simulated device sessions separately:

```text
python scripts/stress_worker.py --cycles 72 --output verification-local/worker-stress.json
```

This lane generates temporary image/GIF/video media, samples resources, checks
that decoders and fake display sessions close, and never opens the physical USB device.

Keep measurement artifacts in ignored `verification-local/` unless intentionally publishing sanitized evidence. Reports can expose local paths or errors related to selected media.

## Physical-device lane

Use only the supported profile described in [HARDWARE.md](HARDWARE.md). Close competing renderers and screen applications first. Confirm the required interface drivers/permissions; do not replace drivers automatically as part of a test.

1. Run read-only diagnostics and record the app version, operating system, controller IDs, and backend status.
2. Open the editor in preview mode and check composition appearance.
3. Start output deliberately, then inspect the physical screen. A successful USB return does not prove pixels are visually correct.
4. Stop/start output, change media, and close the editor. Check that an editor-owned worker exits and another session can subsequently acquire the display. Test login/background output separately: it should pick up saved edits, survive editor closure, and stop through **Stop display**.
5. Test unplug/reconnect behavior and record any error or recovery action.

An explicit USB soak sends frames to the real device:

```text
python scripts/soak.py --seconds 120 --usb --output verification-local/usb-soak.json
```

Add `--media FILE` for an animated hardware run. **`--usb`, `--panel`, `--render`, and Apply / Start display cause physical USB writes.** Never put these actions in ordinary CI or run them against an unidentified panel.

Record separately what was observed: enumeration, interface opening, protocol transfer, physical picture, sustained resource behavior, and clean release. Share sanitized photos or measurements with a hardware change. Remove serial numbers and personal paths.

## Package lane

Run the build procedure in [INSTALLATION.md](INSTALLATION.md#build-from-source), then test the generated executable with `--smoke-test` and `--diagnose --output FILE`. On Windows, use `Start-Process -Wait` to collect the GUI executable's completion and file output.

Verify that the full portable folder launches, terms/privacy/notices are present, and a newly installed Windows app launches through its shortcut. Check uninstall behavior with login startup disabled, preserving settings and source media. Test from a path containing spaces.

The release matrix builds Windows x64 and Linux x64 independently. Hardware-free CI can verify Python behavior and packaging; it cannot certify an AIO driver setup on a clean physical Windows installation. Linux archive construction on Ubuntu 22.04 does not by itself verify every desktop distribution or display server.

## Report results precisely

State the commit/version, OS, relevant media properties, command, duration, and observed outcome. Separate automated results from human visual review. Document untested cases and regressions. Avoid claims such as “no leaks,” “all AIOs supported,” or “plug and play” without evidence that supports their actual scope.
