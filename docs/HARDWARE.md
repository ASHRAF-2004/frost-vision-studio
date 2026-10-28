# Hardware support

## Current device profile

| Property | Current scope |
|---|---|
| Cooler/product | Invasion Frost Vision 360 mm |
| Panel profile | `VMAXD05` |
| Composed frame | 480 × 480 pixels |
| USB vendor / product | `345f:9132` |
| Control path | HID interface 0 |
| Pixel path | Bulk interface 3, endpoint `0x04` |
| Pixel format | Uncompressed BGR frames using the existing Vmax-compatible picture path |

Panel model and dimensions come from the existing project's hardware profile. A USB ID match identifies the controller family; it does not independently measure physical dimensions or prove another product uses the same initialization sequence.

This release does not offer universal AIO support. Another screen may need a different protocol, resolution, endpoint, timing, or driver. Do not select this profile merely because a cooler looks similar.

## Windows driver requirements

The USB device is composite: interface 0 provides control and interface 3 provides the pixel-transfer path. Both must be accessible through compatible Windows drivers and matching user-space libraries.

Read-only inspection of the Windows 11 x64 development host identified:

- A Microsoft `HidUsb` / HIDClass driver for interface 0.
- An **MS USB Display** driver from provider **MS**, using the `libusb0` service for interface 3.
- A system `libusb0` runtime library, version 1.2.2.0.

These observations establish the host's installed driver arrangement. They do not establish a complete clean-install procedure or universal Windows compatibility. The app reuses compatible existing drivers; its installer does not include proprietary drivers, replace interface drivers automatically, or install the original screen application.

If the preview works but USB output does not, run `--diagnose` and check both interfaces in Device Manager. A missing bulk driver/backend, mismatched architecture, or another process holding the panel can prevent output. Keep interface 0 on its intended HID path. Driver changes should be deliberate and recoverable; this project does not perform them on your behalf.

The **MS** bulk-driver provider above is distinct from the Microsoft HID driver. A driver display name alone does not prove compatibility.

## Linux permissions and libraries

Linux needs a compatible libusb runtime and permission to access the USB device. The supplied `99-invasion-frost-vision.rules` file is scoped to `345f:9132`; the installation guide explains how to install it.

Keep ordinary editing and rendering under your regular user account. An administrator is only needed to install system dependencies or USB permissions. Stop other software that owns the display before starting physical output.

## Sensor availability

CPU/GPU utilization and temperature depend on the operating system, hardware, and providers exposed to the application. They are independent of the AIO display controller.

Windows does not offer a generally reliable CPU-temperature reading through psutil alone. A machine can therefore render a working screen while showing `--` for temperature. GPU readings can also be unavailable. Frost Vision Studio does not fabricate values or install a kernel sensor driver to fill these gaps.

## Verification boundaries

Device enumeration, successful transport opening, a successful frame-transfer return, and a visually correct physical screen are different checks. Record which one was actually performed. A driver inventory alone is not evidence of working frame output, and packaging success is not hardware certification.

For a hardware report, provide application version, operating system, USB IDs, interface driver names, the exact action attempted, and sanitized diagnostic output. Include a photo of the physical output when useful. Remove serial numbers and personal paths before posting.

## Future device support

New device profiles should define identification, resolution, pixel format, control and bulk paths, initialization/cleanup behavior, and supported driver arrangements. Add tests for framing and lifecycle before claiming compatibility, then verify the profile on the actual device. Arbitrary resolution support and macOS are planned separately from the current 480 × 480 release.
