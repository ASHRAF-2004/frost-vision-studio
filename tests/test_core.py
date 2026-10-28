import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import PropertyMock, patch

from PIL import GifImagePlugin, Image

from frostvision import core
from frostvision.platform_support import RendererLock
from frostvision import platform_support


class CoreTests(unittest.TestCase):
    def test_settings_merge_and_legacy_media(self):
        settings = core.normalize_settings({"image": "sample.png", "overlay_styles": {"clock": {"x": 42}}, "overlays": {"cpu_temp": False}})
        self.assertEqual((settings["media_type"], settings["media_path"]), ("image", "sample.png"))
        self.assertEqual(settings["overlay_styles"]["clock"]["x"], 42)
        self.assertEqual(settings["overlay_styles"]["clock"]["size"], 30)
        self.assertTrue(settings["overlays"]["clock"])
        self.assertFalse(settings["overlays"]["cpu_temp"])
        settings["overlay_styles"]["clock"]["x"] = 11
        self.assertEqual(core.OVERLAY_DEFAULTS["clock"]["x"], 240)

    def test_corrupt_setting_shapes_and_limits(self):
        settings = core.normalize_settings({"overlays": [], "overlay_styles": {"clock": {"size": "bad", "x": 99999}}, "background_transform": {"rotation": None}, "max_fps": 1000})
        self.assertEqual(settings["overlay_styles"]["clock"]["size"], 30)
        self.assertEqual(settings["overlay_styles"]["clock"]["x"], 480)
        self.assertEqual(settings["max_fps"], 30)
        frame = core.render_frame(settings, metrics={"clock": "01:30 PM"})
        self.assertEqual((frame.size, frame.mode), ((480, 480), "RGB"))

    def test_unrotated_text_opacity_composites_with_background(self):
        background = Image.new("RGB", (480, 480), (20, 40, 60))
        settings = core.default_settings()
        settings["overlays"] = {key: key == "clock" for key in core.OVERLAY_DEFAULTS}
        settings["overlay_styles"]["clock"].update(x=240, y=240, size=80, color="#DC642800", rotation=0)
        transparent = core.render_frame(settings, background, metrics={"clock": "MMMM"})
        self.assertEqual(transparent.tobytes(), background.tobytes())
        settings["overlay_styles"]["clock"]["color"] = "#DC6428FF"
        opaque = core.render_frame(settings, background, metrics={"clock": "MMMM"})
        pixels = opaque.tobytes()
        index = max(range(480 * 480), key=lambda index: pixels[index * 3])
        point = (index % 480, index // 480)
        self.assertEqual(opaque.getpixel(point), (220, 100, 40))
        settings["overlay_styles"]["clock"]["color"] = "#DC642880"
        half = core.render_frame(settings, background, metrics={"clock": "MMMM"})
        self.assertEqual(half.getpixel(point), (120, 70, 50))

    def test_atomic_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with patch.object(core, "CONFIG_DIR", path), patch.object(core, "CONFIG_FILE", path / "settings.json"):
                settings = core.default_settings()
                settings["overlay_styles"]["clock"]["prefix"] = "الوقت "
                core.save_settings(settings)
                self.assertEqual(core.load_settings(), settings)
                self.assertEqual(list(path.glob("*.tmp")), [])
                (path / "settings.json").write_text("not json", encoding="utf-8")
                self.assertEqual(core.load_settings(), core.default_settings())

    def test_streaming_gif_retains_no_frame_list_and_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "animation.gif"
            Image.new("RGB", (8, 8), "red").save(path, save_all=True, append_images=[Image.new("RGB", (8, 8), "blue")], duration=20, loop=0)
            with patch.object(GifImagePlugin.GifImageFile, "n_frames", new_callable=PropertyMock, side_effect=AssertionError("Full animation scan is forbidden")):
                source = core.BackgroundSource({"media_type": "image", "media_path": str(path)})
            self.assertTrue(source.animate)
            self.assertFalse(hasattr(source, "frames"))
            self.assertEqual(source.frame().getpixel((200, 200)), (255, 0, 0))
            source._deadline = 0
            self.assertEqual(source.frame().getpixel((200, 200)), (0, 0, 255))
            source._deadline = 0
            self.assertEqual(source.frame().getpixel((200, 200)), (255, 0, 0))
            source.close()
            self.assertIsNone(source._source)
            self.assertFalse(source.animate)

    def test_gif_frame_and_image_pixel_limits_close_decoder(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "animation.gif"
            Image.new("RGB", (8, 8), "red").save(path, save_all=True, append_images=[Image.new("RGB", (8, 8), "blue")], duration=20)
            with patch.object(core, "MAX_ANIMATION_FRAMES", 1):
                source = core.BackgroundSource({"media_type": "image", "media_path": str(path)})
                self.assertTrue(source.animate)
                source._deadline = 0
                with self.assertRaisesRegex(ValueError, "10,000-frame"):
                    source.frame()
                self.assertIsNone(source._source)
            with patch.object(core, "MAX_IMAGE_PIXELS", 32):
                with self.assertRaisesRegex(ValueError, "megapixel"):
                    core.BackgroundSource({"media_type": "image", "media_path": str(path)})
            path.unlink()  # Windows denies this if failed initialization leaked its file handle.

    def test_metrics_sample_at_most_once_a_second(self):
        with patch.object(core, "_metric_deadline", 0), patch.object(core, "_metrics", {}), patch.object(core, "_sensor_snapshot", return_value={"cpu_usage": 25}) as sampler:
            with patch.object(core.time, "monotonic", side_effect=[1.0, 1.1, 1.9, 2.1]):
                self.assertEqual(core.metric_value("cpu_usage"), "25%")
                core.metrics_snapshot()
                core.metrics_snapshot()
                core.metrics_snapshot()
            self.assertEqual(sampler.call_count, 2)

    def test_os_renderer_lock_excludes_second_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            first = RendererLock(Path(directory) / "lock")
            second = RendererLock(Path(directory) / "lock")
            try:
                self.assertTrue(first.acquire())
                self.assertFalse(second.acquire())
                first.release()
                self.assertTrue(second.acquire())
            finally:
                first.release()
                second.release()

    def test_linux_startup_migrates_only_known_legacy_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            current = path / "frost-vision-studio.desktop"
            legacy = path / "aio-screen-manager.desktop"
            known = "[Desktop Entry]\nName=Frost Vision Composition\nExec=python3 /old/app/aio_screen_manager.py --render\n"
            with patch.object(platform_support, "IS_WINDOWS", False), patch.object(platform_support, "AUTOSTART_FILE", current), patch.object(platform_support, "app_command", return_value=["/new app/python", "/new app/aio_screen_manager.py", "--render"]):
                legacy.write_text(known, encoding="utf-8")
                self.assertTrue(platform_support.autostart_enabled())
                self.assertTrue(platform_support.migrate_legacy_autostart(True))
                self.assertFalse(legacy.exists())
                self.assertIn('"/new app/python"', current.read_text(encoding="utf-8"))
                legacy.write_text(known, encoding="utf-8")
                platform_support.set_autostart(False)
                self.assertFalse(legacy.exists())
                self.assertFalse(current.exists())
                unrelated = "[Desktop Entry]\nName=Unrelated monitor tool\nExec=echo aio_screen_manager.py --render\n"
                legacy.write_text(unrelated, encoding="utf-8")
                platform_support.set_autostart(False)
                self.assertEqual(legacy.read_text(encoding="utf-8"), unrelated)
                self.assertFalse(platform_support.migrate_legacy_autostart(True))


if __name__ == "__main__":
    unittest.main()
