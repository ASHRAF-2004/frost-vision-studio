# Third-party notices

Frost Vision Studio's application code and original icon are MIT licensed.
Binary distributions also contain independently licensed dependencies.
The build copies their installed license files into `licenses/` alongside
this notice. Those licenses govern their respective components.

| Component | License | Upstream source |
| --- | --- | --- |
| Python | PSF License | https://www.python.org/downloads/source/ |
| QtBase / QtSvg / QtWayland / QtImageFormats / PySide6 / Shiboken | LGPL-3.0 / GPL / commercial, according to component; this build uses LGPL modules, including Linux Wayland integration and Qt image-format plugins | https://github.com/qt/qtbase and https://github.com/qt/qtsvg and https://github.com/qt/qtwayland and https://github.com/qt/qtimageformats and https://code.qt.io/pyside/pyside-setup.git/ |
| Pillow | MIT-CMU and bundled library licenses | https://github.com/python-pillow/Pillow |
| psutil | BSD-3-Clause | https://github.com/giampaolo/psutil |
| PyUSB | BSD-3-Clause | https://github.com/pyusb/pyusb |
| hidapi Python binding | BSD-3-Clause | https://github.com/trezor/cython-hidapi |
| HIDAPI | BSD / GPL-3.0 / HIDAPI license alternatives | https://github.com/libusb/hidapi |
| libusb / libusb-package | LGPL-2.1 / Apache-2.0 wrapper | https://github.com/libusb/libusb and https://github.com/pyocd/libusb-package |
| PyAV | BSD-3-Clause | https://github.com/PyAV-Org/PyAV |
| FFmpeg 9.0.2 libraries in PyAV wheels | FFmpeg LGPL/GPL terms plus the linked component licenses; this wheel is not an LGPL-only media stack | https://ffmpeg.org/download.html |
| x264 b35605ace3ddf7c1a5d67a2eb553f034aef41d55 | GPL-2.0-or-later | https://code.videolan.org/videolan/x264 |
| x265 4.3 | GPL-2.0-or-later | https://github.com/Multicorewareinc/x265 |
| LAMER 3.101.0, derived from LAME | LGPL terms and upstream notices | https://github.com/basswood-io/lamer |
| Opus 1.6.1 / dav1d 1.5.4 | BSD-style licenses and applicable patent notices | https://opus-codec.org/ and https://code.videolan.org/videolan/dav1d |
| SVT-AV1 4.2.0 / libvpx 1.17.0 | BSD-style licenses and applicable patent notices | https://gitlab.com/AOMediaCodec/SVT-AV1 and https://github.com/webmproject/libvpx |
| libpng 1.6.58 / libwebp 1.6.0 / libvmaf 3.2.1 | libpng / BSD-style licenses and component notices | https://libpng.org/ and https://github.com/webmproject/libwebp and https://github.com/Netflix/vmaf |
| Intel libvpl 2.16.0 / AMF headers 1.5.2 / NV codec headers 13.0.19.0 | MIT-style upstream licenses | https://github.com/intel/libvpl and https://github.com/GPUOpen-LibrariesAndSDKs/AMF and https://github.com/FFmpeg/nv-codec-headers |
| Linux: GnuTLS 3.8.13 / Nettle 4.0 / GMP 6.3.0 / libunistring 1.4.2 / ALSA 1.2.14 | LGPL/GPL alternatives according to component; source archives retain exact notices | https://www.gnutls.org/ and https://www.gnu.org/software/nettle/ and https://gmplib.org/ and https://www.gnu.org/software/libunistring/ and https://www.alsa-project.org/ |
| Windows: GNU libiconv 1.19 | LGPL-2.1-or-later library; source package includes its separate tool licenses | https://www.gnu.org/software/libiconv/ |
| Windows: GCC 16.1.0 runtimes | GPL-3.0 with GCC Runtime Library Exception 3.1 | https://gcc.gnu.org/onlinedocs/libstdc++/manual/license.html |
| Windows: MinGW-w64 winpthreads 14.0.0.r92.g818fa6510 | Upstream MIT/BSD-style component licenses | https://github.com/mingw-w64/mingw-w64 |
| Windows: zlib 1.3.2 | zlib license | https://zlib.net/ |
| PyInstaller bootloader | GPL-2.0 with distribution exception | https://github.com/pyinstaller/pyinstaller |

No manufacturer application, firmware or proprietary USB driver is redistributed.
On Windows, the libusb0 backend can use a compatible driver already installed
on the machine; it is not included in this distribution.

## Media-wheel license scope

PyAV 19.0.2 selects the upstream [pyav-ffmpeg 9.0.2-1 build](https://github.com/PyAV-Org/pyav-ffmpeg/tree/9.0.2-1).
Its [build recipe](https://github.com/PyAV-Org/pyav-ffmpeg/blob/9.0.2-1/scripts/pkg.py)
identifies the native source versions above. The wheel includes x264 and x265
shared libraries, even though this app only uses video decoding.

The upstream [FFmpeg configure patch](https://github.com/PyAV-Org/pyav-ffmpeg/blob/9.0.2-1/patches/ffmpeg.patch)
changes x264/x265 classification from the GPL dependency list to the version-3
list. Consequently an FFmpeg runtime string that says LGPL-3.0 does not establish
that the linked media stack is LGPL-only. The codec licenses still apply.
These binary distributions include GPL components and must be redistributed
with their applicable GPL notices and corresponding source obligations; the
original Frost Vision Studio source remains available under its MIT license.
The application MIT notice does not replace dependency licenses.

The release's third-party source asset contains the pinned native sources and
the upstream recipes/patches at commit
`bac889417e26be29615cb6a3f38318151fed55cd`. Windows runtime provenance comes from
the official [Windows x64 build job](https://github.com/PyAV-Org/pyav-ffmpeg/actions/runs/35461333227/job/105945672070):
MSYS2 GCC `16.1.0-5`, libiconv `1.19-1`, winpthreads
`14.0.0.r92.g818fa6510-1`, and zlib `1.3.2-2`. Their MSYS2 source packages include
the packaging recipes and patches. GPL/LGPL and GCC exception texts are retained
in the source repository's `licenses/media/` and the binary package's
`licenses/open-source/media/`; native source archives also retain component copyright,
patent, and license notices. See the manifest for exact URLs and hashes.

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
