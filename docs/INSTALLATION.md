# Installation and use

Version 0.2.1 is initially published as a **prerelease** for Windows 11 x64 and Linux x64. The supported USB profile is `345f:9132`, `VMAXD05`, 480 × 480. Read [HARDWARE.md](HARDWARE.md) before attempting physical output on another panel.

## Download

Choose the matching asset on [GitHub Releases](https://github.com/ASHRAF-2004/frost-vision-studio/releases):

| Asset | Purpose |
|---|---|
| `FrostVisionStudio-0.2.1-windows-x64-setup.exe` | Per-user Windows installer |
| `FrostVisionStudio-0.2.1-windows-x64.zip` | Windows portable application folder |
| `FrostVisionStudio-0.2.1-linux-x64.tar.gz` | Linux portable application folder |
| `SHA256SUMS.txt` | Checksums for the published packages |

These packages include the Python application runtime. You do not need to install Python to use them. Linux still needs compatible system graphics/USB libraries; Windows physical output still needs compatible interface drivers.

To check a download on Windows, run `Get-FileHash -Algorithm SHA256 .\PACKAGE_NAME` in PowerShell and compare the result with `SHA256SUMS.txt`. On Linux, keep the packages and checksum file together and run `sha256sum --check SHA256SUMS.txt --ignore-missing`. A matching checksum verifies the bytes against the downloaded checksum file; it is not a digital publisher signature.

## Windows installer

1. Download the setup `.exe` from this repository's release page.
2. Run it and review the terms shown by the installer. The default installation is under your user account and does not require administrator rights.
3. Choose whether to create a Desktop shortcut, then finish installation.
4. Launch **Frost Vision Studio** from Start. The editor initially opens in preview mode.

The default application folder is `%LOCALAPPDATA%\Programs\FrostVisionStudio`. The installer does not install the original screen application, bundle a proprietary screen driver, or replace USB drivers. A clean Windows installation may therefore be able to open the editor but unable to drive the panel until compatible drivers are available. See [Windows driver requirements](HARDWARE.md#windows-driver-requirements).

The current community build is unsigned. Windows can display an unknown-publisher prompt. Check the repository, release version, and checksum before deciding whether to run it; this project does not provide a commercial publisher certificate.

## Windows portable

Extract the entire ZIP into a folder you can write to. Open the extracted `FrostVisionStudio` directory and run `FrostVisionStudio.exe`. Keep its `_internal`, `licenses`, and documentation files together; copying only the `.exe` is insufficient.

Settings use the same per-user configuration directory as the installed version. Portable here means the executable folder can be relocated; settings are not stored beside the executable. Disable login startup before moving that folder, then enable it again from the new location if desired.

## Linux archive

The Linux x64 build uses Ubuntu 22.04 as its build baseline. A compatible desktop Linux distribution with glibc and Qt runtime dependencies is required; older glibc systems, musl-only distributions, ARM, and headless-only systems are outside this package's qualification scope.

For Debian/Ubuntu desktop systems, the relevant runtime packages include:

```bash
sudo apt install libegl1 libopengl0 libusb-1.0-0 libxcb-cursor0 \
  libxkbcommon-x11-0 fontconfig fonts-dejavu-core
```

Extract and launch:

```bash
tar -xzf FrostVisionStudio-0.2.1-linux-x64.tar.gz
cd FrostVisionStudio
./FrostVisionStudio
```

Keep the extracted application directory intact. The archive launches the editor; it does not install system packages, a driver, or USB permissions automatically.

### Linux USB access

From the extracted application folder or source checkout, review `99-invasion-frost-vision.rules`, then install it once:

```bash
sudo sh ./install-usb-access.sh
```

Reconnect the USB device if needed. This step installs a system udev rule for `345f:9132`; normal app use should remain under your regular user account. The rule does not make another controller compatible. If a Linux kernel display driver or another application owns the interface, follow the connection error rather than repeatedly launching additional renderers.

## From source

Use **Python 3.11 or newer**. Python 3.12 is used by the release build. Clone the repository:

```text
git clone https://github.com/ASHRAF-2004/frost-vision-studio.git
cd frost-vision-studio
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe aio_screen_manager.py
```

Linux, with Python 3.11+ already available:

```bash
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python aio_screen_manager.py
```

Install the Linux runtime dependencies and USB permissions above when needed. A source checkout should stay in place while its virtual environment or login-startup entry refers to it.

For development and packaging tools, use the virtual environment's Python:

```text
python -m pip install -e ".[dev]"
```

Alternatively, install `requirements-dev.txt`. The examples below use `python` to mean that virtual environment's interpreter.

## Command line

| Command | Behavior | Physical USB writes |
|---|---|---|
| `python aio_screen_manager.py` | Open the editor in preview mode | Only after Apply / Start display |
| `python aio_screen_manager.py --panel` | Open the editor and start its display session | Yes |
| `python aio_screen_manager.py --render` | Run the saved composition without an editor window | Yes |
| `python aio_screen_manager.py --diagnose` | Report device/backend information as JSON | No |
| `python aio_screen_manager.py --smoke-test` | Open, render, and close the editor automatically | No |
| `python aio_screen_manager.py --version` | Print the application version | No |

`--diagnose` and `--smoke-test` accept `--output FILE` to write JSON. Create the destination's parent directory first. Review diagnostics before sharing: they can include platform information and device or library details.

For a packaged build, replace `python aio_screen_manager.py` with its executable. The Windows GUI executable has no console, so use an output file for diagnostics. From the portable app directory:

```powershell
Start-Process -FilePath .\FrostVisionStudio.exe -ArgumentList '--diagnose --output diagnostics.json' -Wait
Get-Content .\diagnostics.json
```

Stop a source `--render` session with Ctrl+C, or open the editor and use **Stop display**. Closing the editor stops the display session owned by that editor. A separately started login/background session continues until stopped. Only one physical renderer can own the app's device lock at a time.

## Compose and apply

1. Choose an image/GIF or video, or use **Clear** to return to the built-in background.
2. Select a text layer, enable it, and adjust its font, size, color, opacity, prefix, position, and rotation. Drag enabled text in the preview to reposition it.
3. Apply background rotation or flips if desired. Settings save automatically after edits.
4. Select **Apply / Start display** to connect to the supported physical screen. **Stop display** releases it while keeping the preview available.

Unsupported metrics show `--`. The editor uses a capped rendering loop, so a high-frame-rate source plays with fewer displayed updates rather than requesting an unrestricted USB frame rate. Excessive image dimensions, animation frame counts, video dimensions, or file size can be rejected with a media error.

## Settings, logs, and startup

| Platform | Configuration directory |
|---|---|
| Windows | `%LOCALAPPDATA%\FrostVisionStudio` |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/aio-screen-manager` |

The directory contains `settings.json`, a renderer lock file, session status/control JSON files, and rotating `frost-vision-studio.log` files. Log rotation keeps the main log at approximately 1 MiB with two backups. A lock file remaining on disk is not by itself evidence that a renderer is still running: ownership is enforced by an OS file lock.

The previous Linux settings path is preserved. Windows can import a legacy `~/.config/aio-screen-manager/settings.json` if the new Windows settings file does not exist. Keep a backup before manually editing settings; malformed data falls back to defaults.

**Start this composition when I log in** is opt-in. It runs the saved composition through `--render`, using a current-user Windows Run entry or a Linux desktop autostart entry. An editor opened later detects that session: saved edits are picked up by the background renderer, **Apply / Start display** saves the composition for it, and **Stop display** requests a session-scoped stop. Closing the editor leaves that background session running. Disable login startup before moving a portable/source installation or uninstalling, and stop the current session too.

## Update and uninstall

Close Frost Vision Studio before updating. Run the new Windows installer, or replace a portable folder as a complete unit. Source users should update their checkout and reinstall the pinned requirements in the virtual environment.

Disable login startup before uninstalling. On Windows, use **Settings → Apps → Installed apps → Frost Vision Studio → Uninstall**. For portable builds, remove the extracted application folder after quitting. Settings and source media are preserved. To remove settings too, delete only the configuration directory listed above after closing the app; media stays where you selected it.

## Build from source

Build on the target operating system with a Python 3.12 x64 environment and development dependencies installed:

```text
python -m pip install -r requirements-dev.txt
python scripts/build.py
```

The script generates icons from the existing SVG, creates `dist/FrostVisionStudio`, collects third-party notices/licenses, records build versions, and produces the platform's portable archive. `--no-archive` builds only the application folder. PyInstaller does not cross-compile Windows packages from Linux or Linux packages from Windows.

On Windows, compile the installer with Inno Setup 6 after building the application:

```text
ISCC.exe packaging/windows.iss
```

Use the full path to `ISCC.exe` if it is not on PATH. The installer appears in `dist/`. The [Release workflow](../.github/workflows/release.yml) builds both platforms from the tagged source, verifies the version, runs non-hardware checks, adds SHA-256 checksums, and publishes the GitHub prerelease.

## Troubleshooting

| Symptom | Check |
|---|---|
| Editor opens but panel is unavailable | Run `--diagnose`; check the correct device, both interface drivers/permissions, and exclusive renderer ownership. |
| CPU or GPU temperature shows `--` | This sensor is unavailable on the current platform/provider. It is not a panel connection error. |
| Media error or built-in fallback | Try a supported, smaller local file; check file availability and the log. |
| Linux Qt platform-plugin error | Verify the desktop session and system graphics/X11 runtime dependencies. Offscreen mode is for tests, not normal desktop use. |
| Physical display looks wrong despite transfer success | Stop output and report the exact profile, driver arrangement, and a photo. A returned USB transfer is not visual confirmation. |
| Resource use grows over time | Record the source media properties and run the [soak lane](TESTING.md#soak-lane); share sanitized measurements and reproduction steps. |
