# Frost Vision Studio

Frost Vision Studio is a standalone Linux editor and direct USB display driver
for the 480×480 screen used by the Invasion Frost Vision 360 mm AIO cooler.

It communicates directly with the cooler's MacroSilicon USB display
(`345f:9132`), so it does not depend on treating the screen as a desktop monitor.

## Features

- Static images, animated GIFs, and looping video backgrounds
- Live 480×480 editor preview
- Drag-and-drop positioning for text layers
- CPU and GPU temperature
- CPU and GPU usage
- 12-hour clock
- Independent font, size, color, opacity, bold style, prefix, position, and rotation
- Background rotation and horizontal or vertical flipping
- Automatic startup option
- Direct USB transfer using the panel's Vmax-compatible protocol

## Supported hardware

The direct USB implementation was tested with:

- Invasion Frost Vision 360 mm
- 480×480 display
- USB ID `345f:9132`
- Panel model `VMAXD05`

Other products using the same USB controller may require a different panel mode
or timing.

## Dependencies

On Ubuntu or Debian, install the GTK, Pillow, VLC, font, and USB runtime
packages:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-cairo python3-pil \
  python3-vlc vlc libusb-1.0-0 fontconfig fonts-noto-core
```

## Install

```bash
chmod +x install.sh install-usb-access.sh
./install.sh
```

The installer copies the application into your local data directory, creates a
desktop shortcut, and installs a udev rule for direct access to the cooler. The
udev step asks for the administrator password.

## Run from the source directory

Install the USB access rule once:

```bash
sudo sh ./install-usb-access.sh
```

Then start the editor:

```bash
python3 ./aio_screen_manager.py
```

To start only the display renderer:

```bash
python3 ./aio_screen_manager.py --render
```

Settings are stored in:

```text
~/.config/aio-screen-manager/settings.json
```

## Notes

- The cooler is claimed through USB interfaces 0 and 3 while the renderer is
  active.
- Only one renderer instance should control the cooler at a time.
- The included udev rule is limited to USB device `345f:9132`.
