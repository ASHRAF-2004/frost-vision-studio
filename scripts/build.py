"""Create a reproducible onedir app and portable archive on the current OS."""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0"
APP = "FrostVisionStudio"


def copy_licenses(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "licenses", destination / "open-source", dirs_exist_ok=True)
    packages = ("PySide6-Essentials", "shiboken6", "Pillow", "psutil", "pyusb",
                "hidapi", "libusb-package", "av", "pyinstaller")
    for name in packages:
        distribution = metadata.distribution(name)
        for item in distribution.files or ():
            # Native wheels often include dependency notices beneath .dist-info.
            parts = tuple(part.lower() for part in item.parts)
            if not any("license" in part or "copying" in part or "notice" in part for part in parts):
                continue
            source = Path(distribution.locate_file(item))
            if source.is_file() and source.suffix not in {".pyc", ".pyo"}:
                target = destination / name / Path(*item.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, destination / "Python-LICENSE.txt")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    if platform.system() not in {"Windows", "Linux"}:
        raise SystemExit("Release packaging currently supports Windows and Linux only.")
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("This release is qualified for x64 only.")
    # Rasterize the established vector identity; no new/generated brand mark.
    subprocess.run([sys.executable, "scripts/make_icons.py"], check=True)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
               "--onedir", "--name", APP, "--collect-all", "libusb_package",
               "--collect-all", "av", "--hidden-import", "usb.backend.libusb0",
               "--hidden-import", "usb.backend.libusb1",
               "--exclude-module", "PySide6.QtWebEngineCore",
               "--exclude-module", "PySide6.QtQml",
               "--exclude-module", "PySide6.QtQuick",
               "--exclude-module", "PySide6.QtPdf",
               "--add-data", "aio-screen-manager.svg:.",
               "--add-data", "docs/TERMS.md:docs",
               "--add-data", "docs/PRIVACY.md:docs",
               "--add-data", "LICENSE:.",
               "--add-data", "THIRD_PARTY_NOTICES.md:."]
    if sys.platform == "win32":
        command += ["--windowed", "--icon", "assets/icon.ico",
                    "--version-file", "packaging/version-info.txt"]
    command.append("aio_screen_manager.py")
    subprocess.run(command, check=True)
    output = ROOT / "dist" / APP
    copy_licenses(output / "licenses")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, output / name)
    for name in ("TERMS.md", "PRIVACY.md", "INSTALLATION.md"):
        source = ROOT / "docs" / name
        if source.exists():
            shutil.copy2(source, output / name)
    if sys.platform != "win32":
        for name in ("99-invasion-frost-vision.rules", "install-usb-access.sh"):
            shutil.copy2(ROOT / name, output / name)
    versions = {name: metadata.version(name) for name in (
        "PySide6-Essentials", "shiboken6", "Pillow", "psutil", "pyusb",
        "hidapi", "libusb-package", "av", "pyinstaller")}
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    import av
    (output / "build-info.json").write_text(json.dumps({
        "version": VERSION, "source_commit": commit, "python": platform.python_version(),
        "platform": platform.system(), "architecture": platform.machine(),
        "dependencies": versions, "ffmpeg_version": av.ffmpeg_version_info,
        "ffmpeg_libraries": av._core.library_meta,
    }, indent=2), encoding="utf-8")
    if not args.no_archive:
        name = f"FrostVisionStudio-{VERSION}-{platform.system().lower()}-x64"
        archive = shutil.make_archive(str(ROOT / "dist" / name),
                                      "zip" if sys.platform == "win32" else "gztar",
                                      root_dir=ROOT / "dist", base_dir=APP)
        print(archive)


if __name__ == "__main__":
    main()
