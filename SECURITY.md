# Security

## Supported release line

Security fixes target the latest 0.2.x prerelease/release line. Older source snapshots may not receive fixes. Update to the latest published build before reproducing an issue.

## Reporting a vulnerability

If GitHub shows **Security → Report a vulnerability** for this repository, use that private reporting route. Include the affected version, operating system, impact, minimal reproduction, and any relevant sanitized logs. Do not include credentials, private media, or full device serial numbers.

If private reporting is unavailable, open an issue asking for a private contact channel without posting exploit details or sensitive data. Ordinary crashes, missing sensors, and unsupported hardware can use the bug template.

## Application boundaries

- The editor reads local media and settings and can write frames to a supported USB panel when output is started.
- Media decoders and USB libraries are dependencies with their own security updates. Open files from sources you trust and keep the application current.
- Normal editing does not require administrator privileges. Linux USB permission setup may require an administrator; Windows interface-driver installation is outside the app installer.
- Frost Vision Studio does not install the original screen application, replace USB drivers automatically, or provide a kernel sensor driver.
- Device identification and protocol compatibility are intentionally narrow. A matching product name alone does not establish safe compatibility with another panel.

See [privacy information](docs/PRIVACY.md), [hardware support](docs/HARDWARE.md), and the [terms](docs/TERMS.md) for related information.
