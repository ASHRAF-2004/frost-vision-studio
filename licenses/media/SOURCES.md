# Retained media dependency notices

The components/ subdirectories retain license, copyright, patent and notice files extracted without modification from the native source archives pinned by PyAV-Org/pyav-ffmpeg release 9.0.2-1. See scripts/fetch_sources.py and the release source asset SOURCES.json for the exact source URLs and SHA-256 digests.

Original native archives were obtained from the upstream release build deps artifact (run 35461333227, artifact 10589534776), then verified against scripts/pkg.py at commit bac889417e26be29615cb6a3f38318151fed55cd. This retains the original bytes even when a current GitHub-generated tag archive has been repacked.

The top-level x264/x265 GPL texts came from the same source revision's COPYING file. GNU GPL/LGPL and GCC Runtime Library Exception texts came from GCC release gcc-16.1.0 COPYING3, COPYING3.LIB, COPYING.LIB and COPYING.RUNTIME, retained verbatim. The x265 COPYING file also records its separate commercial-license option; this build does not claim such a commercial license.

Windows libiconv copyright/license files were extracted from the original MSYS2 libiconv1.19-1 source package. Winpthreads COPYING comes from mingw-w64 commit818fa6510, and zlib LICENSE from madler/zlib tagv1.3.2. The full MSYS2 source packages include packaging recipes and patches for the exact runtime package revisions reported by the upstream Windows release job.

These notices supplement wheel-provided licenses. They do not replace the complete licenses, copyright notices and build instructions retained in the corresponding source archives.
