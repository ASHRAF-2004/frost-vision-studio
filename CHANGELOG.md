# Changelog

Notable user-facing changes are recorded here. Git tags and [GitHub Releases](https://github.com/ASHRAF-2004/frost-vision-studio/releases) identify published builds and their prerelease status.

## 0.2.0 — 2026-10-29 · initial prerelease

### Added

- Windows and Linux desktop editor based on PySide6, replacing the Linux-only GTK application path.
- Windows HID control and compatible bulk USB transport for the existing `345f:9132` screen driver arrangement.
- Windows x64 installer and portable packaging, plus a Linux x64 archive release lane.
- Installation, architecture, hardware, contribution, security, privacy, and verification documentation.
- Installer terms and explicit disclosure of current hardware and driver requirements.

### Changed

- Incremental media decoding replaces whole-animation frame retention.
- Preview and physical output share the latest rendered frame.
- Animated editor output is capped at 10 fps; static compositions and metrics use a 1 Hz cadence.
- Renderer ownership, resource replacement, and shutdown cleanup are explicit.
- The editor can apply saved edits to a login/background renderer and stop that session through local session-scoped control files.
- Unavailable sensors display `--` rather than a fabricated reading.

### Compatibility

- Current panel scope remains 480 × 480, `VMAXD05`, USB `345f:9132`.
- The Windows installer does not bundle a proprietary USB driver or install the original screen software.
- Other AIO controllers, arbitrary panel resolutions, and macOS remain outside this release's support scope.
- Resource safeguards require sustained verification on representative media and machines; this release does not claim to eliminate every possible leak or CPU spike.

## Earlier source version

The original application provided a Linux GTK editor, local media backgrounds, hardware overlays, and direct Vmax-compatible USB output. See the Git history for the exact source changes; no historical binary-release version is inferred here.
