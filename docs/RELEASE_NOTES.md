Frost Vision Studio now has a portable Windows/Linux editor and native Windows installer.

This 0.2.1 preview also removes unused Qt PDF, virtual keyboard and QML/Quick
components from the Windows package, while retaining native Linux Wayland support.

- Windows 11 x64 setup EXE with terms, privacy information, Start menu shortcut and uninstaller.
- Portable Windows x64 ZIP and Linux x64 tar.gz.
- Preserved images, animated GIFs, video, draggable metric layers, transforms and login startup.
- Streaming media, bounded frame storage, capped frame rate, cached metrics and explicit resource cleanup.
- Direct USB support for the existing 480×480 Frost Vision / VMAXD05 panel (`345f:9132`).
- No original screen application or proprietary driver bundled; no silent driver replacement.

Windows USB output requires an already compatible bulk interface driver. The development machine's existing libusb0 driver is supported alongside native Windows HID. New Windows installations may need separate USB driver configuration; installing this EXE alone does not install that driver.

This is a preview release. macOS, other panels and other resolutions are not yet qualified. CPU/GPU temperature availability depends on the operating system and sensor provider; unavailable readings show `--`. The app does not control cooling, fans or firmware.

On the development Windows machine, separate two-minute static, GIF and video USB runs averaged 0.06%, 0.30% and 0.47% machine CPU respectively, without a growing memory trend in these short probes. Repeated media/session cleanup also passed. See docs/VERIFICATION.md for scope, measurements and unverified physical-picture acceptance.

Download the `windows-x64-setup.exe` to install on Windows, or extract the portable archive for your platform. Review `docs/INSTALLATION.md` for Linux USB access and runtime requirements. Compare downloads with `SHA256SUMS.txt`.

The Windows executable is not Authenticode signed; the verified publisher dialog will not show a commercial signing identity. Repository source, MIT license, third-party notices, contributing guide and architecture documentation are included in the project.
