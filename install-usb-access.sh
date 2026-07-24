#!/bin/sh
set -eu

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

install -m 0644 \
    "$SOURCE_DIR/99-invasion-frost-vision.rules" \
    /etc/udev/rules.d/99-invasion-frost-vision.rules
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb --attr-match=idVendor=345f --attr-match=idProduct=9132
udevadm settle
