"""Compare delegate surfaces against actual application GlassButton rendering."""
import pytest
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import QImage, QPainter, QColor, QRegion
from PySide6.QtWidgets import QApplication
from transcomic.ui.capcut_actions import glass_surface, button_rects
from transcomic.ui.glass import GlassButton
from transcomic.ui.theme import DARK, LIGHT


@pytest.mark.parametrize('dark', [False, True])
@pytest.mark.parametrize('state', ['normal', 'hover', 'pressed', 'disabled', 'active'])
def test_surface_matches_real_glass_button(dark, state):
    app = QApplication.instance() or QApplication([])
    c = DARK if dark else LIGHT
    button = GlassButton('')
    button.dark = dark
    button.resize(40, 30)
    button.setEnabled(state != 'disabled')
    button.setDown(state == 'pressed')
    button.setCheckable(True)
    button.setChecked(state == 'active')
    button._light = float(state == 'hover')
    images = []
    for actual in (True, False):
        image = QImage(40, 30, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor(c['background']))
        painter = QPainter(image)
        try:
            if actual:
                button.render(painter, QPoint(), QRegion(), button.RenderFlag.DrawChildren)
            else:
                painter.setRenderHint(QPainter.Antialiasing)
                glass_surface(painter, QRect(0, 0, 40, 30), c,
                              enabled=state != 'disabled', hover=state == 'hover',
                              pressed=state == 'pressed', selected=state == 'active')
        finally:
            painter.end()
        images.append(image)
    # Compare surface away from native label/focus rendering and rounded edges.
    for y in range(3, 24):
        for x in range(11, 29):
            a, b = (im.pixelColor(x, y) for im in images)
            assert max(abs(a.red()-b.red()), abs(a.green()-b.green()),
                       abs(a.blue()-b.blue())) <= 1
    button.close()


def test_focus_and_press_preserve_hit_targets():
    app = QApplication.instance() or QApplication([])
    bounds = QRect(0, 0, 104, 62)
    before = button_rects(bounds)
    image = QImage(104, 62, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    for rect in before:
        surface, _ = glass_surface(painter, rect, DARK, pressed=True, focus=True)
        assert rect.contains(surface.toRect())
    painter.end()
    assert button_rects(bounds) == before
    assert all(rect.size().width() == 40 and rect.height() == 30 for rect in before)


def test_build_stage_includes_exact_public_capcut_resources():
    from pathlib import Path
    from scripts.build_local import input_files
    root = Path(__file__).resolve().parents[1]
    inputs = {p.relative_to(root).as_posix() for p in input_files(root)}
    assert {'transcomic/capcut/mau-structure.zip',
            'transcomic/capcut/mau-origin.json'} <= inputs
    assert not any(p.startswith(('references/', 'tests/', 'artifacts/')) for p in inputs)
    from importlib.metadata import version
    pins = (root/'requirements-release.lock').read_text(encoding='utf8').splitlines()
    assert 'mutagen=='+version('mutagen') in pins
