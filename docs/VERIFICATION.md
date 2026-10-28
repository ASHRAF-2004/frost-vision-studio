# 0.2.0 verification record

Measured on Windows 11 x64 on 29 October 2026 with the attached `345f:9132`
panel, using its existing HID and libusb0 drivers. No vendor application or
driver replacement was used. These measurements describe short regression
probes, not guaranteed resource ceilings or proof of long-term leak freedom.

| Direct physical USB probe | Duration | Frames sent | Mean machine CPU | Warm RSS growth |
| --- | --- | --- | --- | --- |
| Static composition | 120 seconds | 120 | 0.06% | -0.04 MiB |
| Generated animated GIF | 120 seconds | 1,777 | 0.30% | +0.56 MiB |
| Generated MPEG-4 video | 120 seconds | 1,782 | 0.47% | +0.96 MiB |

The direct animation probe uses a 15 fps stress cadence. The interactive editor
uses a 10 fps cap. CPU percentages above are normalized over this host's 12
logical processors; the JSON also records ordinary process one-core percentages.

A separate worker test used generated image/GIF/video files and 75 simulated
device sessions, including repeated media replacement, loop boundaries,
start/stop, and two worker lifetimes. All fake devices closed, workers joined,
frame slots released, and handle/thread counts did not grow across owner
lifetimes. Warm memory growth was about 0.19 MiB. Some native libraries retained
two threads and two handles after their first use; subsequent worker lifetimes
did not add further growth.

Windows and Ubuntu 22.04 source tests and offscreen preview checks passed in
[GitHub Actions](https://github.com/ASHRAF-2004/frost-vision-studio/actions).
Windows packaging checks covered frozen read-only detection, a rendered preview
and clean shutdown, installation from a path with spaces, installed launch,
and uninstall with local configuration preserved.

The source editor screenshot was visually inspected. The native Windows UI
automation helper was unavailable, so an interactive installer-page inspection
was not completed. Successful transfers establish that the protocol returned
success; the physical panel's picture still needs owner visual acceptance.
Linux hardware output and a clean Windows driver's installation are separate
qualification gaps. No automatic driver installer is included.

Sanitized measurements: [windows-2026-10-29.json](verification/windows-2026-10-29.json).
Reproduce the lanes with [TESTING.md](TESTING.md).
