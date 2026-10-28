# Third-party notices

Frost Vision Studio's application code and original icon are MIT licensed.
Binary distributions also contain independently licensed dependencies.
The build copies their installed license files into `licenses/` alongside
this notice. Those licenses govern their respective components.

| Component | License | Upstream source |
| --- | --- | --- |
| Python | PSF License | https://www.python.org/downloads/source/ |
| Qt / PySide6 / Shiboken | LGPL-3.0 / GPL / commercial, according to component; this build uses LGPL modules | https://code.qt.io/pyside/pyside-setup.git/ |
| Pillow | MIT-CMU and bundled library licenses | https://github.com/python-pillow/Pillow |
| psutil | BSD-3-Clause | https://github.com/giampaolo/psutil |
| PyUSB | BSD-3-Clause | https://github.com/pyusb/pyusb |
| hidapi Python binding | BSD-3-Clause | https://github.com/trezor/cython-hidapi |
| HIDAPI | BSD / GPL-3.0 / HIDAPI license alternatives | https://github.com/libusb/hidapi |
| libusb / libusb-package | LGPL-2.1 / Apache-2.0 wrapper | https://github.com/libusb/libusb and https://github.com/pyocd/libusb-package |
| PyAV | BSD-3-Clause | https://github.com/PyAV-Org/PyAV |
| FFmpeg libraries in PyAV wheels | LGPL-3.0-or-later and component licenses in the selected wheel; see build-info.json | https://ffmpeg.org/download.html |
| PyInstaller bootloader | GPL-2.0 with distribution exception | https://github.com/pyinstaller/pyinstaller |

No manufacturer application, firmware or proprietary USB driver is redistributed.
On Windows, the libusb0 backend can use a compatible driver already installed
on the machine; it is not included in this distribution.

## Shared-library replacement

The frozen application uses an ordinary directory layout, not a monolithic
single-file executable. Qt, Shiboken, libusb and media libraries remain
separate shared libraries in `_internal/`. You may replace them with ABI
compatible modified builds, retain license notices, and debug those changes.
For an unrestricted rebuild, obtain this release's source from GitHub, install
your modified dependencies in a Python environment, and run `python scripts/build.py`.
No signature check or DRM prevents library replacement.

Dependency versions are pinned in `requirements.txt`; the generated
`build-info.json` in each binary distribution records exact installed versions.
Corresponding source archives for the pinned native dependencies are included
as a release asset when publishing binaries. Their upstream build instructions
describe rebuilding on each supported platform.
