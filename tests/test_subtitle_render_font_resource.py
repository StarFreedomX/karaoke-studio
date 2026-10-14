"""Physical face transfer, including fonts unavailable in the system catalog."""
from pathlib import Path
import os

import pytest
from PyQt6.QtGui import QFont, QFontDatabase, QRawFont

from krok_helper.subtitle_render.engine.text.font_resource import snapshot_raw_font


@pytest.mark.skipif(os.name != "nt", reason="Windows font resources")
@pytest.mark.parametrize("filename", ["arial.ttf", "meiryo.ttc", "bahnschrift.ttf"])
def test_snapshot_preserves_face_tables(qapp, filename):
    path = Path(os.environ["WINDIR"]) / "Fonts" / filename
    if not path.is_file():
        pytest.skip("font unavailable")
    raw = QRawFont(str(path), 64)
    if not raw.isValid():
        pytest.skip("Qt cannot load font directly")
    snapshot = snapshot_raw_font(raw, ("roundtrip", filename))
    restored = QRawFont(snapshot, 64)
    assert restored.isValid()
    for tag in ("cmap", "glyf", "loca", "CFF ", "fvar", "gvar", "hmtx"):
        assert bytes(restored.fontTable(tag)) == bytes(raw.fontTable(tag)), tag
    assert list(restored.glyphIndexesForString("Ag")) == list(raw.glyphIndexesForString("Ag"))


@pytest.mark.skipif(os.name != "nt", reason="Windows font resources")
def test_application_only_font_is_transferred_to_gpu(qapp, tmp_path):
    from fontTools.ttLib import TTFont
    from krok_helper.subtitle_render.engine.text.font_weight import clear_font_weight_cache
    from krok_helper.subtitle_render.native.backend import NativeRendererProcess, resolve_native_renderer_path
    from krok_helper.subtitle_render.domain.models import Style, TimingTrack, TimingLine, TimingChar
    original = Path(os.environ["WINDIR"]) / "Fonts" / "arial.ttf"
    family = "LinK Application Resource Probe"
    font = TTFont(original)
    for entry in font["name"].names:
        if entry.nameID in (1, 4, 6, 16, 21):
            value = family.replace(" ", "") if entry.nameID == 6 else family
            entry.string = value.encode(entry.getEncoding())
    destination = tmp_path / "application-only.ttf"
    font.save(destination)
    font.close()
    font_id = QFontDatabase.addApplicationFont(str(destination))
    assert font_id >= 0
    clear_font_weight_cache()
    renderer_path = resolve_native_renderer_path()
    if renderer_path is None:
        pytest.skip("sidecar unavailable")
    try:
        track = TimingTrack(lines=[TimingLine(chars=[TimingChar("W", 0)], end_ms=1000)])
        from test_subtitle_render_gpu_backend import _render_g1_frames, _g1_style
        frames = []
        for selected in ("Arial", family):
            with NativeRendererProcess(renderer_path, response_timeout_s=60) as renderer:
                _, rendered = _render_g1_frames(renderer,
                    _g1_style(font_family=selected, font_family_latin=selected),
                    (500,), force_warp=True, track=track)
                frames.append(rendered[0])
        # The renamed face has identical outlines. System substitution would
        # draw a different W; matching whole frames proves actual face transfer.
        assert frames[0] == frames[1]
    finally:
        QFontDatabase.removeApplicationFont(font_id)
        clear_font_weight_cache()
