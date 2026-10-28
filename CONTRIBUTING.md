# Contributing to Frost Vision Studio

We'd love your help with **Frost Vision Studio**! Open an issue to report a bug or suggest a feature, or send a pull request to improve the code or docs.

The current scope is Windows and Linux support for the 480 × 480 `345f:9132` screen. Keep support for other panels behind explicit capability work and hardware evidence. macOS support is planned for a later release.

## Development setup

1. Fork or clone the repository.
2. Create a Python virtual environment and install the project dependencies using the [source installation steps](docs/INSTALLATION.md#from-source).
3. Run the fast checks in [docs/TESTING.md](docs/TESTING.md).
4. Start the editor in preview mode; USB hardware is optional for ordinary UI and renderer work.

Use the [architecture map](docs/ARCHITECTURE.md) to find the layer that owns a change. Avoid introducing platform-specific imports into modules that must load on both Windows and Linux.

## Working on a change

- Keep each pull request focused on one problem or coherent feature.
- Preserve existing settings where possible. Document migrations and recovery steps when configuration changes.
- Treat media input as untrusted. Decode incrementally, close replaced resources, and avoid retaining every frame of a long animation or video.
- Keep sensor work out of the painting path. Preserve the sampling and frame-rate limits unless measurements justify a deliberate change.
- Make hardware access explicit. Unit tests and ordinary CI must not configure USB devices or send panel frames.
- Report unavailable readings as `--`; do not substitute a fabricated temperature or utilization value.
- Do not bundle the original screen application, proprietary drivers, or media without redistribution rights.

## Checks and evidence

Use the [fast unit and UI lane](docs/TESTING.md#fast-lane) for normal changes. Run the [soak lane](docs/TESTING.md#soak-lane) when changing decoding, rendering, threading, timers, sensors, or cleanup. Hardware changes also need the [physical-device lane](docs/TESTING.md#physical-device-lane).

In the pull request, state what you tested, the operating system, the commands used, and what remains unverified. Build success does not establish visual quality, correct physical output, or absence of leaks. Attach a sanitized screenshot for a visible UI change and measured data for performance claims.

## Issues

Use the bug or feature issue template. For device problems, include the USB vendor/product IDs, interface drivers, application version, operating system, and diagnostic output with personal paths and identifiers removed. Do not publish device serial numbers, private media, access tokens, or an unredacted system inventory.

Security issues follow [SECURITY.md](SECURITY.md).

## Versioning and releases

The application version follows `MAJOR.MINOR.PATCH`. During the 0.x series, a minor release may change behavior; document configuration or compatibility changes in [CHANGELOG.md](CHANGELOG.md). Git tags identify release commits, and the GitHub release records whether a build is a prerelease.

Version 0.2.0 is initially distributed as a prerelease. Windows x64 installer/portable packages and Linux x64 archives are built from the same tagged source. A release should include checksums, relevant validation results, and known hardware or driver limitations. Do not promote an untested platform or device to supported status merely because packaging succeeded.

## License

By contributing, you agree that your contribution may be distributed under the repository's [MIT license](LICENSE). Keep third-party notices and attribution intact.
