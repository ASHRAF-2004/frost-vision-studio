"""The existing 480×480 VMAX protocol over Linux USB or Windows HID/USB.

No driver installation, device probing writes, or background retry loops.
Windows HID uses overlapped I/O with cancellation, rather than an unbounded
HidD_SetFeature call. HID report-ID rules follow Microsoft's HIDClass API:
https://learn.microsoft.com/windows-hardware/drivers/ddi/hidclass/ni-hidclass-ioctl_hid_get_feature
"""

from __future__ import annotations

import ctypes
from ctypes.util import find_library
import os
from pathlib import Path
import sys
import time

from .platform_support import IS_WINDOWS

VID, PID = 0x345F, 0x9132
PANEL_SIZE = 480
CONTROL_TIMEOUT_MS = 2000
BULK_TIMEOUT_MS = 5000


def _libusb1():
    import usb.backend.libusb1
    try:
        import libusb_package
        backend = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
    except (ImportError, OSError):
        backend = None
    return backend or usb.backend.libusb1.get_backend()


def _backends():
    if IS_WINDOWS:
        import usb.backend.libusb0
        # Use only the installed OS runtime; never load a DLL from the cwd.
        dll = Path(os.environ.get("WINDIR", "C:/Windows")) / ("System32" if ctypes.sizeof(ctypes.c_void_p) == 8 else "SysWOW64") / "libusb0.dll"
        backend = usb.backend.libusb0.get_backend(find_library=lambda _name: str(dll) if dll.is_file() else None)
        if backend:
            yield "libusb0", backend
    backend = _libusb1()
    if backend:
        yield "libusb1", backend


def detect_display():
    """Read-only discovery; this function never claims or configures a device."""
    result = dict(present=False, vendor_id="345f", product_id="9132", supported_resolution=[480, 480], platform=sys.platform,
                  hid_present=False, usb_backends=[], errors=[])
    if IS_WINDOWS:
        try:
            import hid
            result["hid_present"] = bool(hid.enumerate(VID, PID))
            result["present"] = result["hid_present"]
        except (ImportError, OSError) as error:
            result["errors"].append(f"HID enumeration: {error}")
    try:
        import usb.core
        for name, backend in _backends():
            try:
                found = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
                result["usb_backends"].append(dict(name=name, present=found is not None))
                result["present"] = result["present"] or found is not None
            except Exception as error:
                result["errors"].append(f"{name}: {error}")
    except (ImportError, OSError) as error:
        result["errors"].append(f"USB discovery: {error}")
    if not result["usb_backends"]:
        result["errors"].append("No usable USB runtime. Linux: install libusb-1.0; Windows: an interface-3 libusb0/WinUSB driver is required.")
    return result


class _WindowsHid:
    """Interface-0 HID feature reports with a finite OS I/O deadline."""

    def __init__(self):
        import hid
        from ctypes import wintypes as w
        paths = [item["path"] for item in hid.enumerate(VID, PID)
                 if item.get("interface_number") == 0 or b"&mi_00" in item.get("path", b"").lower()]
        if not paths:
            raise OSError("Frost Vision HID interface 0 was not found.")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
        self.api.CreateFileW.restype = w.HANDLE
        self.api.CreateEventW.argtypes = [ctypes.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR]
        self.api.CreateEventW.restype = w.HANDLE
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.api.CloseHandle.restype = w.BOOL
        self.api.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        self.api.WaitForSingleObject.restype = w.DWORD

        class Overlapped(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t), ("Offset", w.DWORD), ("OffsetHigh", w.DWORD), ("hEvent", w.HANDLE)]
        self.Overlapped = Overlapped
        self.api.DeviceIoControl.argtypes = [w.HANDLE, w.DWORD, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(Overlapped)]
        self.api.DeviceIoControl.restype = w.BOOL
        self.api.GetOverlappedResult.argtypes = [w.HANDLE, ctypes.POINTER(Overlapped), ctypes.POINTER(w.DWORD), w.BOOL]
        self.api.GetOverlappedResult.restype = w.BOOL
        self.api.CancelIoEx.argtypes = [w.HANDLE, ctypes.POINTER(Overlapped)]
        self.api.CancelIoEx.restype = w.BOOL
        path = paths[0].decode("utf-8") if isinstance(paths[0], bytes) else paths[0]
        self.handle = self.api.CreateFileW(path, 0xC0000000, 3, None, 3, 0x40000000, None)
        if self.handle == ctypes.c_void_p(-1).value:
            self.handle = None
            raise ctypes.WinError(ctypes.get_last_error())
        self._pending = None

    def _report(self, payload, reading=False):
        from ctypes import wintypes as w
        if self.handle is None:
            raise OSError("The HID connection is closed.")
        # Windows buffers include an extra zero report-ID byte for this device.
        data = ctypes.create_string_buffer(b"\0" + bytes(payload), 9)
        transferred = w.DWORD()
        operation = self.Overlapped()
        operation.hEvent = self.api.CreateEventW(None, True, False, None)
        if not operation.hEvent:
            raise ctypes.WinError(ctypes.get_last_error())
        pending = False
        try:
            control = 0x000B0192 if reading else 0x000B0191
            if reading:
                ok = self.api.DeviceIoControl(self.handle, control, None, 0, data, 9, ctypes.byref(transferred), ctypes.byref(operation))
            else:
                ok = self.api.DeviceIoControl(self.handle, control, data, 9, None, 0, ctypes.byref(transferred), ctypes.byref(operation))
            if not ok:
                error = ctypes.get_last_error()
                if error != 997:  # ERROR_IO_PENDING
                    raise ctypes.WinError(error)
                pending = True
                waited = self.api.WaitForSingleObject(operation.hEvent, CONTROL_TIMEOUT_MS)
                if waited != 0:
                    self.api.CancelIoEx(self.handle, ctypes.byref(operation))
                    # Retain buffers if a broken kernel driver fails to acknowledge cancellation.
                    if self.api.WaitForSingleObject(operation.hEvent, CONTROL_TIMEOUT_MS) != 0:
                        self._pending = (operation, data, transferred)
                        operation = None
                        self.close()
                    raise TimeoutError("Frost Vision HID command timed out; playback was stopped.")
                if not self.api.GetOverlappedResult(self.handle, ctypes.byref(operation), ctypes.byref(transferred), False):
                    raise ctypes.WinError(ctypes.get_last_error())
            if reading and transferred.value not in (8, 9):
                raise OSError(f"Incomplete HID feature report ({transferred.value} bytes).")
            return data.raw[1:9]
        finally:
            if operation is not None:
                self.api.CloseHandle(operation.hEvent)

    def write(self, payload):
        if len(payload) != 8:
            raise ValueError("VMAX feature reports must contain exactly 8 bytes.")
        self._report(payload)

    def read(self):
        return self._report(b"\0" * 8, reading=True)

    def close(self):
        if self.handle is not None:
            self.api.CloseHandle(self.handle)
            self.handle = None
        if self._pending is not None:
            operation, _data, _transferred = self._pending
            if self.api.WaitForSingleObject(operation.hEvent, CONTROL_TIMEOUT_MS) == 0:
                self.api.CloseHandle(operation.hEvent)
                self._pending = None


class _UsbConnection:
    def __init__(self):
        import usb.core
        import usb.util
        self.device = None
        self.claimed = []
        self.detached = []
        self.hid = None
        self.name = ""
        failures = []
        try:
            for name, backend in _backends():
                try:
                    device = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
                    if device is not None:
                        # Reading descriptors establishes openability without changing configuration.
                        device.get_active_configuration()
                        self.device, self.name = device, name
                        break
                except Exception as error:
                    failures.append(f"{name}: {error}")
            if self.device is None:
                extra = " ".join(failures)
                raise OSError("Cannot open Frost Vision USB 345f:9132. " + ("Check the interface-3 libusb0/WinUSB driver. " if IS_WINDOWS else "Install the provided udev permission rule. ") + extra)
            if IS_WINDOWS:
                self.hid = _WindowsHid()
                interfaces = (3,)
            else:
                interfaces = (0, 3)
            for interface in interfaces:
                if not IS_WINDOWS:
                    try:
                        if self.device.is_kernel_driver_active(interface):
                            self.device.detach_kernel_driver(interface)
                            self.detached.append(interface)
                    except NotImplementedError:
                        pass
                usb.util.claim_interface(self.device, interface)
                self.claimed.append(interface)
        except Exception:
            self.close()
            raise

    def write_report(self, report):
        if self.hid is not None:
            self.hid.write(report)
        elif self.device.ctrl_transfer(0x21, 0x09, 0x0300, 0, report, timeout=CONTROL_TIMEOUT_MS) != 8:
            raise OSError("Incomplete VMAX HID command.")

    def read_report(self):
        if self.hid is not None:
            report = self.hid.read()
        else:
            report = bytes(self.device.ctrl_transfer(0xA1, 0x01, 0x0300, 0, 8, timeout=CONTROL_TIMEOUT_MS))
        if len(report) != 8:
            raise OSError("Incomplete VMAX HID response.")
        return report

    def bulk(self, pixels, timeout=BULK_TIMEOUT_MS):
        actual = self.device.write(0x04, pixels, timeout=timeout)
        if actual != len(pixels):
            raise OSError(f"Incomplete VMAX frame ({actual}/{len(pixels)} bytes).")

    def close(self):
        import usb.util
        if self.hid is not None:
            self.hid.close()
            self.hid = None
        if self.device is not None:
            for interface in reversed(self.claimed):
                try:
                    usb.util.release_interface(self.device, interface)
                except Exception:
                    pass
            for interface in reversed(self.detached):
                try:
                    self.device.attach_kernel_driver(interface)
                except Exception:
                    pass
            try:
                usb.util.dispose_resources(self.device)
            except Exception:
                pass
            self.device = None
        self.claimed.clear()
        self.detached.clear()


class VmaxUsbDisplay:
    """Known VMAXD05 sequence preserved from the original Linux implementation."""
    VID, PID = VID, PID
    HID_INTERFACE, BULK_INTERFACE, BULK_ENDPOINT = 0, 3, 0x04

    def __init__(self, connection_factory=None):
        self.connection = None
        self.frame_index = 0
        self.first_frame = True
        try:
            self.connection = (connection_factory or _UsbConnection)()
            self.configure()
        except Exception:
            self.close()
            raise

    def _hid_write(self, command, subcommand, payload=b""):
        report = bytes((command, subcommand)) + bytes(payload)
        if len(report) > 8:
            raise ValueError("VMAX command is larger than its eight-byte report.")
        self.connection.write_report(report.ljust(8, b"\0"))

    def _read_xdata(self, address):
        self.connection.write_report(bytes((0xB5, address >> 8, address & 0xFF, 0, 0, 0, 0, 0)))
        return self.connection.read_report()[3]

    def _write_xdata(self, address, value):
        self.connection.write_report(bytes((0xB6, address >> 8, address & 0xFF, value & 0xFF, 0, 0, 0, 0)))

    def _screen(self, enabled):
        value = self._read_xdata(0xFB07)
        self._write_xdata(0xFB07, value & ~0x02 if enabled else value | 0x02)

    def configure(self):
        size = bytes((1, 224, 1, 224))
        self._hid_write(0xA6, 0x04, b"\0")
        self._hid_write(0xA6, 0x05, b"\0")
        self._screen(False)
        time.sleep(0.05)
        self._hid_write(0xA6, 0x07, b"\x01\x02")
        time.sleep(0.05)
        self._hid_write(0xA6, 0x03, b"\0")
        self._hid_write(0xA6, 0x01, size + b"\x21\0")
        self._hid_write(0xA6, 0x02, b"\x8f\x01" + size)
        self._hid_write(0xA6, 0x04, b"\x01")
        time.sleep(0.05)
        self._hid_write(0xA6, 0x05, b"\0")
        self._screen(False)
        self.frame_index = 1 if self._read_xdata(0xD003) else 0
        self.first_frame = True

    def send(self, image):
        if image.size != (PANEL_SIZE, PANEL_SIZE):
            raise ValueError("This driver supports the verified 480×480 panel only.")
        if self.connection is None:
            raise OSError("The display connection is closed.")
        self.connection.bulk(image.convert("RGB").tobytes("raw", "BGR"))
        self.connection.bulk(b"", timeout=CONTROL_TIMEOUT_MS)
        self.frame_index = 0 if self.frame_index else 1
        self._hid_write(0xA6, 0x00, bytes((self.frame_index, 100)))
        if self.first_frame:
            self._hid_write(0xA6, 0x05, b"\x01")
            self._screen(True)
            self.first_frame = False

    def close(self):
        if self.connection is not None:
            connection, self.connection = self.connection, None
            connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
