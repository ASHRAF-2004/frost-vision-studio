"""Small OS integration layer; importing it never changes system settings."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"
CONFIG_DIR = (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "FrostVisionStudio"
              if IS_WINDOWS else Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "aio-screen-manager")
CONFIG_FILE = CONFIG_DIR / "settings.json"
AUTOSTART_FILE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart" / "frost-vision-studio.desktop"


def app_command(*arguments):
    if getattr(sys, "frozen", False):
        return [sys.executable, *arguments]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "aio_screen_manager.py"), *arguments]


class RendererLock:
    """An OS-owned lock, released even if the renderer crashes."""

    def __init__(self, path=None):
        self.path = Path(path) if path else CONFIG_DIR / "renderer.lock"
        self._file = None

    def acquire(self):
        if self._file is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            if IS_WINDOWS:
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self._file = stream
        return True

    def release(self):
        if self._file is None:
            return
        stream, self._file = self._file, None
        try:
            stream.seek(0)
            if IS_WINDOWS:
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    close = release

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Another Frost Vision renderer already controls the display.")
        return self

    def __exit__(self, *_exc):
        self.release()


def autostart_enabled():
    if IS_WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                value, _ = winreg.QueryValueEx(key, "FrostVisionStudio")
                return bool(value)
        except OSError:
            return False
    return AUTOSTART_FILE.is_file() or _owned_legacy_autostart() is not None


def _owned_legacy_autostart():
    """Recognize only this app's historical filename and command, never glob."""
    legacy = AUTOSTART_FILE.with_name("aio-screen-manager.desktop")
    try:
        if legacy.stat().st_size > 65536:
            return None
        entries = dict(line.split("=", 1) for line in legacy.read_text(encoding="utf-8").splitlines()
                       if "=" in line and not line.lstrip().startswith("#"))
        name = entries.get("Name", "").strip()
        arguments = shlex.split(entries.get("Exec", ""))
        known_command = any(Path(argument).name in ("aio_screen_manager.py", "FrostVisionStudio") for argument in arguments)
        known_name = name in ("Frost Vision Composition", "Frost Vision Studio", "AIO Screen Manager")
        return legacy if known_command and known_name and "--render" in arguments else None
    except (OSError, ValueError, UnicodeError):
        return None


def migrate_legacy_autostart(enabled):
    """Repoint an identified old Linux startup entry to this installation.

    Called by an upgrading Linux installer or app startup; unrelated entries
    that happen to share the old filename remain intact.
    """
    if not IS_WINDOWS and _owned_legacy_autostart() is not None:
        set_autostart(enabled)
        return True
    return False


def set_autostart(enabled):
    """Opt-in per-user startup, with no administrator or scheduled service."""
    command = app_command("--render")
    if IS_WINDOWS:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            if enabled:
                winreg.SetValueEx(key, "FrostVisionStudio", 0, winreg.REG_SZ, subprocess.list2cmdline(command))
            else:
                try:
                    winreg.DeleteValue(key, "FrostVisionStudio")
                except FileNotFoundError:
                    pass
        return
    if enabled:
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Desktop Entry Exec quoting is distinct from shell quoting.
        quoted = " ".join('"' + item.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%") + '"' for item in command)
        AUTOSTART_FILE.write_text("[Desktop Entry]\nType=Application\nName=Frost Vision Studio\nExec=" + quoted + "\nTerminal=false\n", encoding="utf-8")
    else:
        AUTOSTART_FILE.unlink(missing_ok=True)
    # Write the new entry first so a failed upgrade retains a working startup.
    legacy = _owned_legacy_autostart()
    if legacy is not None:
        legacy.unlink(missing_ok=True)
