"""Render the existing SVG into native installer/application icon assets."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PIL import Image

root = Path(__file__).resolve().parents[1]
app = QGuiApplication.instance() or QGuiApplication([])
(root / "assets").mkdir(exist_ok=True)
canvas = QImage(256, 256, QImage.Format.Format_ARGB32)
canvas.fill(0)
painter = QPainter(canvas)
QSvgRenderer(str(root / "aio-screen-manager.svg")).render(painter)
painter.end()
canvas.save(str(root / "assets/icon.png"))
with Image.open(root / "assets/icon.png") as icon:
    icon.save(root / "assets/icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
