#!/bin/sh
set -eu

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
APP_DIR="$DATA_HOME/frost-vision-studio"
DESKTOP_DIR="$HOME/Desktop"

mkdir -p "$APP_DIR" "$DESKTOP_DIR"
install -m 0755 "$SOURCE_DIR/aio_screen_manager.py" "$APP_DIR/aio_screen_manager.py"
install -m 0644 "$SOURCE_DIR/aio-screen-manager.svg" "$APP_DIR/aio-screen-manager.svg"
install -m 0644 "$SOURCE_DIR/99-invasion-frost-vision.rules" "$APP_DIR/99-invasion-frost-vision.rules"
install -m 0755 "$SOURCE_DIR/install-usb-access.sh" "$APP_DIR/install-usb-access.sh"

cat > "$DESKTOP_DIR/Frost-Vision-Studio.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Frost Vision Studio
Comment=Manage media and hardware overlays on a Frost Vision AIO display
Exec=python3 $APP_DIR/aio_screen_manager.py
Icon=$APP_DIR/aio-screen-manager.svg
Terminal=false
Categories=Settings;Utility;
StartupNotify=true
Keywords=AIO;cooler;screen;temperature;dashboard;
EOF
chmod 0755 "$DESKTOP_DIR/Frost-Vision-Studio.desktop"

sudo sh "$APP_DIR/install-usb-access.sh"

echo "Frost Vision Studio is installed."
echo "Open $DESKTOP_DIR/Frost-Vision-Studio.desktop to start it."
