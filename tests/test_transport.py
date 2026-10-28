import unittest
import ctypes
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from frostvision.transport import VmaxUsbDisplay, _WindowsHid, _UsbConnection


class RecordingConnection:
    def __init__(self):
        self.reports = []
        self.bulks = []
        self.closed = False

    def write_report(self, report):
        self.reports.append(bytes(report))

    def read_report(self):
        return bytes(8)

    def bulk(self, payload, timeout=None):
        self.bulks.append((bytes(payload), timeout))

    def close(self):
        self.closed = True


class TransportTests(unittest.TestCase):
    def test_windows_feature_reports_use_correct_ioctl_buffer_direction(self):
        from ctypes import wintypes
        class Operation(ctypes.Structure):
            _fields_ = [("hEvent", wintypes.HANDLE)]
        def device_io(_handle, _control, _input, _input_length, _output, _output_length, count, _operation):
            ctypes.cast(count, ctypes.POINTER(wintypes.DWORD))[0] = 9 if _output_length else 0
            return True
        hid = _WindowsHid.__new__(_WindowsHid)
        hid.handle = 10
        hid.Overlapped = Operation
        hid.api = SimpleNamespace(CreateEventW=Mock(return_value=11), CloseHandle=Mock(), DeviceIoControl=Mock(side_effect=device_io))
        hid.write(bytes.fromhex("a604000000000000"))
        sent = hid.api.DeviceIoControl.call_args.args
        self.assertEqual((sent[1], sent[3], sent[5]), (0x000B0191, 9, 0))
        self.assertIsNotNone(sent[2])
        self.assertIsNone(sent[4])
        hid.read()
        received = hid.api.DeviceIoControl.call_args.args
        self.assertEqual((received[1], received[3], received[5]), (0x000B0192, 0, 9))
        self.assertIsNone(received[2])
        self.assertIsNotNone(received[4])

    def test_usb_bulk_rejects_partial_frame_and_zero_packet_lengths(self):
        connection = _UsbConnection.__new__(_UsbConnection)
        connection.device = SimpleNamespace(write=Mock(return_value=2))
        with self.assertRaisesRegex(OSError, "2/3"):
            connection.bulk(b"abc")
        connection.device.write.return_value = 1
        with self.assertRaisesRegex(OSError, "1/0"):
            connection.bulk(b"")

    @patch("frostvision.transport.time.sleep")
    def test_original_configuration_sequence_and_frame_encoding(self, _sleep):
        connection = RecordingConnection()
        display = VmaxUsbDisplay(lambda: connection)
        self.assertEqual(connection.reports[:3], [bytes.fromhex("a604000000000000"), bytes.fromhex("a605000000000000"), bytes.fromhex("b5fb070000000000")])
        self.assertIn(bytes.fromhex("a60101e001e02100"), connection.reports)
        self.assertIn(bytes.fromhex("a6028f0101e001e0"), connection.reports)
        display.send(Image.new("RGB", (480, 480), (1, 2, 3)))
        self.assertEqual(len(connection.bulks[0][0]), 480 * 480 * 3)
        self.assertEqual(connection.bulks[0][0][:6], bytes((3, 2, 1, 3, 2, 1)))
        self.assertEqual(connection.bulks[1][0], b"")
        self.assertIn(bytes.fromhex("a600016400000000"), connection.reports)
        self.assertFalse(display.first_frame)
        display.send(Image.new("RGB", (480, 480)))
        self.assertEqual(connection.reports[-1], bytes.fromhex("a600006400000000"))
        display.close()
        display.close()
        self.assertTrue(connection.closed)

    @patch("frostvision.transport.time.sleep")
    def test_partial_initialization_closes_connection(self, _sleep):
        connection = RecordingConnection()
        connection.write_report = lambda _report: (_ for _ in ()).throw(OSError("unplugged"))
        with self.assertRaisesRegex(OSError, "unplugged"):
            VmaxUsbDisplay(lambda: connection)
        self.assertTrue(connection.closed)

    @patch("frostvision.transport.time.sleep")
    def test_wrong_resolution_is_rejected_before_bulk_write(self, _sleep):
        connection = RecordingConnection()
        display = VmaxUsbDisplay(lambda: connection)
        with self.assertRaisesRegex(ValueError, "480"):
            display.send(Image.new("RGB", (640, 480)))
        self.assertEqual(connection.bulks, [])
        display.close()

    @patch("frostvision.transport.time.sleep")
    def test_failed_pixel_transfer_never_flips_visible_frame(self, _sleep):
        connection = RecordingConnection()
        display = VmaxUsbDisplay(lambda: connection)
        before = list(connection.reports)
        connection.bulk = lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("short transfer"))
        with self.assertRaisesRegex(OSError, "short transfer"):
            display.send(Image.new("RGB", (480, 480)))
        self.assertEqual(connection.reports, before)
        self.assertTrue(display.first_frame)
        display.close()


if __name__ == "__main__":
    unittest.main()
