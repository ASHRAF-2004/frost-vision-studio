"""Retain native dependency sources, upstream patches, and release provenance.

Run from an authenticated gh environment if the upstream deps-artifact fallback
is needed. Locally use gh auth login; in CI set GH_TOKEN with access to public
Actions artifacts. Recipe checksums remain mandatory. If the upstream artifact
expires, obtain these verified archives from this app release's source asset.
"""
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0"
PYAV_RECIPE_REF = "bac889417e26be29615cb6a3f38318151fed55cd"
PYAV_RECIPE_URL = f"https://raw.githubusercontent.com/PyAV-Org/pyav-ffmpeg/{PYAV_RECIPE_REF}/scripts/pkg.py"
SOURCES = {
    "qtbase-6.12.0.tar.gz": "https://github.com/qt/qtbase/archive/refs/tags/v6.12.0.tar.gz",
    "qtsvg-6.12.0.tar.gz": "https://github.com/qt/qtsvg/archive/refs/tags/v6.12.0.tar.gz",
    "pyside-setup-6.12.0.tar.gz": "https://github.com/pyside/pyside-setup/archive/refs/tags/v6.12.0.tar.gz",
    "libusb-1.0.30.tar.gz": "https://github.com/libusb/libusb/archive/refs/tags/v1.0.30.tar.gz",
    "pyav-19.0.2.tar.gz": "https://github.com/PyAV-Org/PyAV/archive/refs/tags/v19.0.2.tar.gz",
    "pyav-ffmpeg-9.0.2-1-recipes.tar.gz": f"https://github.com/PyAV-Org/pyav-ffmpeg/archive/{PYAV_RECIPE_REF}.tar.gz",
}
# These versions come from the release's Windows x64 build log, not from
# current rolling MSYS2 packages. Source packages include packaging patches.
WINDOWS_RUNTIME_SOURCES = (
    "mingw-w64-gcc-16.1.0-5.src.tar.zst",
    "mingw-w64-libiconv-1.19-1.src.tar.zst",
    "mingw-w64-winpthreads-14.0.0.r92.g818fa6510-1.src.tar.zst",
    "mingw-w64-zlib-1.3.2-2.src.tar.zst",
)


def source_registry():
    """Read literal Package metadata without executing downloaded build code."""
    sources = {name: {"url": url} for name, url in SOURCES.items()}
    request = urllib.request.Request(PYAV_RECIPE_URL, headers={"User-Agent": "FrostVisionStudio-release"})
    with urllib.request.urlopen(request, timeout=60) as response:
        recipe = response.read().decode("utf-8")
    for node in ast.walk(ast.parse(recipe)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "Package":
            continue
        fields = {item.arg: item.value.value for item in node.keywords
                  if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str)}
        if not {"name", "source_url", "sha256"} <= fields.keys():
            raise ValueError("Upstream source recipe has an unexpected nonliteral Package entry")
        url = fields["source_url"]
        name = fields.get("source_filename") or url.rsplit("/", 1)[-1]
        sources[name] = {"url": url, "expected_sha256": fields["sha256"], "component": fields["name"]}
    for name in WINDOWS_RUNTIME_SOURCES:
        url = "https://repo.msys2.org/mingw/sources/" + name
        sources[name] = {"url": url, "provenance": "PyAV FFmpeg Windows x64 release job 105945672070"}
        sources[name + ".sig"] = {"url": url + ".sig"}
    return sources


def main():
    directory = ROOT / "release-sources"
    directory.mkdir(exist_ok=True)
    artifact_cache = tempfile.TemporaryDirectory(prefix="FrostVisionStudio-PyAV-sources-")
    artifact_guard = threading.Lock()
    artifact_ready = False

    def original_recipe_archive(name, spec, target):
        # GitHub-generated tag archives can be repacked. The original release
        # build's deps artifact preserves the bytes checked by its build recipe.
        nonlocal artifact_ready
        with artifact_guard:
            if not artifact_ready:
                subprocess.run(["gh", "run", "download", "35461333227", "--repo",
                                "PyAV-Org/pyav-ffmpeg", "--name", "deps", "--dir",
                                artifact_cache.name], check=True)
                artifact_ready = True
            source = Path(artifact_cache.name) / name
            with source.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != spec["expected_sha256"]:
                raise ValueError(f"Original source artifact checksum mismatch: {name}")
            shutil.copy2(source, target)
        return "https://github.com/PyAV-Org/pyav-ffmpeg/actions/runs/35461333227/artifacts/10589534776"

    def fetch(item):
        name, spec = item
        url = spec["url"]
        target = directory / name
        provenance = "retained local archive; canonical origin is source_url" if target.exists() else url
        if not target.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "FrostVisionStudio-release"})
            try:
                with urllib.request.urlopen(request, timeout=60) as response, target.with_suffix(".tmp").open("wb") as output:
                    shutil.copyfileobj(response, output)
                target.with_suffix(".tmp").replace(target)
            except Exception:
                if not spec.get("expected_sha256"):
                    raise
                provenance = original_recipe_archive(name, spec, target)
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if spec.get("expected_sha256") and digest != spec["expected_sha256"]:
            provenance = original_recipe_archive(name, spec, target)
            with target.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return {"file": name, "source_url": url, "sha256": digest,
                "acquired_from": provenance,
                "bytes": target.stat().st_size, **{k: v for k, v in spec.items() if k != "url"}}
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            manifest = list(pool.map(fetch, source_registry().items()))
    finally:
        artifact_cache.cleanup()
    (directory / "SOURCES.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (directory / "README.txt").write_text(
        "Native component sources for Frost Vision Studio 0.2.0.\n"
        "Includes GPL/LGPL codec sources and upstream build recipes/patches.\n"
        "Application source: https://github.com/ASHRAF-2004/frost-vision-studio/tree/v0.2.0\n"
        "SOURCES.json records their original URLs and SHA-256 digests.\n"
        "Each source archive includes its upstream licenses and build documentation.\n"
        "PyAV FFmpeg recipe release: 9.0.2-1, commit " + PYAV_RECIPE_REF + ".\n"
        "Its patches/ffmpeg.patch changes configure license classification for x264/x265.\n"
        "The codecs retain their GPL terms; the FFmpeg runtime license string alone is insufficient.\n"
        "The recipe archive contains the exact build scripts and patches used upstream.\n"
        "scripts/pkg.py lists source versions/checksums for codecs and Linux GnuTLS dependencies.\n"
        "If an origin archive was unavailable/repacked, acquired_from records the upstream deps artifact.\n"
        "Those original cached archives are checked against the recipe's expected SHA-256.\n"
        "Upstream artifact fallback needs authenticated gh (GH_TOKEN in CI).\n"
        "If the upstream artifact expires, retain/reuse this release's verified source archives.\n"
        "Windows runtime versions were identified in official build job 105945672070:\n"
        "https://github.com/PyAV-Org/pyav-ffmpeg/actions/runs/35461333227\n"
        "MSYS2 .src.tar.zst packages contain source, PKGBUILD and packaging patches.\n"
        "MSYS2 detached signatures are retained; this script does not perform GPG verification.\n"
        "Application build instructions: scripts/build.py and CONTRIBUTING.md in the app repository.\n"
        "Binary build-info.json records FFmpeg configure options and library license strings.\n"
        "PySide/Qt: build Qtbase and Qtsvg shared libraries, then pyside-setup.\n"
        "FFmpeg/codecs: use the included pyav-ffmpeg recipes, patches and source checksums.\n"
        "Replace ABI-compatible shared libraries in the application's _internal directory.\n", encoding="utf-8")
    output = ROOT / "dist" / f"FrostVisionStudio-{VERSION}-third-party-sources"
    output.parent.mkdir(exist_ok=True)
    archive = Path(str(output) + ".tar.gz")
    with tarfile.open(archive, "w:gz") as package:
        for name in [item["file"] for item in manifest] + ["README.txt", "SOURCES.json"]:
            package.add(directory / name, arcname="release-sources/" + name)
    print(archive)


if __name__ == "__main__":
    main()
