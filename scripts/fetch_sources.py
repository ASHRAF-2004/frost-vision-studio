"""Retain corresponding LGPL dependency source archives for release downloads."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0"
SOURCES = {
    "qtbase-6.12.0.tar.gz": "https://github.com/qt/qtbase/archive/refs/tags/v6.12.0.tar.gz",
    "qtsvg-6.12.0.tar.gz": "https://github.com/qt/qtsvg/archive/refs/tags/v6.12.0.tar.gz",
    "pyside-setup-6.12.0.tar.gz": "https://github.com/pyside/pyside-setup/archive/refs/tags/v6.12.0.tar.gz",
    "ffmpeg-9.0.2.tar.gz": "https://github.com/FFmpeg/FFmpeg/archive/refs/tags/n9.0.2.tar.gz",
    "libusb-1.0.30.tar.gz": "https://github.com/libusb/libusb/archive/refs/tags/v1.0.30.tar.gz",
}


def main():
    directory = ROOT / "release-sources"
    directory.mkdir(exist_ok=True)
    def fetch(item):
        name, url = item
        target = directory / name
        if not target.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "FrostVisionStudio-release"})
            with urllib.request.urlopen(request, timeout=180) as response, target.with_suffix(".tmp").open("wb") as output:
                shutil.copyfileobj(response, output)
            target.with_suffix(".tmp").replace(target)
        digest = hashlib.file_digest(target.open("rb"), "sha256").hexdigest()
        return {"file": name, "source_url": url, "sha256": digest, "bytes": target.stat().st_size}
    with ThreadPoolExecutor(max_workers=3) as pool:
        manifest = list(pool.map(fetch, SOURCES.items()))
    (directory / "SOURCES.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (directory / "README.txt").write_text(
        "Corresponding LGPL component sources for Frost Vision Studio 0.2.0.\n"
        "These are unmodified upstream source archives for the pinned dependencies.\n"
        "SOURCES.json records their original URLs and SHA-256 digests.\n"
        "Each archive includes upstream licenses and build documentation.\n"
        "Application build instructions: scripts/build.py and CONTRIBUTING.md in the app repository.\n"
        "Binary build-info.json records FFmpeg configure options and library license strings.\n"
        "PySide/Qt: build Qtbase and Qtsvg shared libraries, then pyside-setup.\n"
        "FFmpeg: use the recorded configuration and upstream installation instructions.\n"
        "Replace ABI-compatible shared libraries in the application's _internal directory.\n", encoding="utf-8")
    output = ROOT / "dist" / f"FrostVisionStudio-{VERSION}-third-party-sources"
    output.parent.mkdir(exist_ok=True)
    print(shutil.make_archive(str(output), "gztar", root_dir=ROOT, base_dir="release-sources"))


if __name__ == "__main__":
    main()
