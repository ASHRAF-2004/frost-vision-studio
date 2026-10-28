#!/bin/sh
# Per-user source install. USB permissions are a separate, explicit step.
set -eu

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
APP_DIR="$DATA_HOME/frost-vision-studio"
APPLICATIONS_DIR="$DATA_HOME/applications"
if [ "$(uname -s)" != Linux ]; then
    echo "Use the Windows setup EXE on Windows; this script is for Linux." >&2
    exit 1
fi
if [ "$SOURCE_DIR" = "$APP_DIR" ]; then
    echo "Run install.sh from your source checkout, outside the install directory." >&2
    exit 1
fi
mkdir -p "$APP_DIR" "$APPLICATIONS_DIR"
for name in frostvision docs assets; do
    cp -R "$SOURCE_DIR/$name" "$APP_DIR/"
done
for name in aio_screen_manager.py aio-screen-manager.svg requirements.txt LICENSE THIRD_PARTY_NOTICES.md 99-invasion-frost-vision.rules install-usb-access.sh; do
    cp "$SOURCE_DIR/$name" "$APP_DIR/$name"
done
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
"$APP_DIR/.venv/bin/python" - "$APP_DIR" "$APPLICATIONS_DIR" <<'PY'
from pathlib import Path
import sys
app, applications = map(Path, sys.argv[1:])
sys.path.insert(0, str(app))
def quote(value):
    value = str(value)
    for old, new in (("\\", "\\\\"), ('"', '\\"'), ("`", "\\`"), ("$", "\\$"), ("%", "%%")):
        value = value.replace(old, new)
    return '"' + value + '"'
(applications / 'frost-vision-studio.desktop').write_text(
    '[Desktop Entry]\nVersion=1.0\nType=Application\nName=Frost Vision Studio\n'
    + 'Comment=Compose media and metrics for the Frost Vision USB display\n'
    + 'Exec=' + quote(app / '.venv/bin/python') + ' ' + quote(app / 'aio_screen_manager.py') + '\n'
    + 'Icon=' + str(app / 'aio-screen-manager.svg') + '\nTerminal=false\nCategories=Settings;Utility;\n',
    encoding='utf-8')
from frostvision.core import load_settings
from frostvision.platform_support import migrate_legacy_autostart
migrate_legacy_autostart(bool(load_settings().get('autostart')))
PY
echo "Frost Vision Studio installed for the current user. Open it from your applications menu."
echo "For Linux USB access, separately run: sudo sh \"$APP_DIR/install-usb-access.sh\""
