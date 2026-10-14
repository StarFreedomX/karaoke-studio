"""GPU 预览 A/B 观感对照工具（独立诊断，不属于产品功能）。

同一工程、同一时间戳、同一尺寸下，同时用两个 sidecar 实例渲染：
  A = 旧 baked（DrawGeometryRealization 直绘）
  B = 候选方案（KROK_GPU_STATIC_LAYER_MASK=1，静态层蒙版缓存）
两个实例的其余配置完全一致，避免「两次重启应用」混入时刻、缓存冷热与
窗口尺寸差异。

用法：
  python scripts/gpu_ab_viewer.py --lrc 歌词.lrc --at 62000
  python scripts/gpu_ab_viewer.py --text "永漢Abg" --at 1000 --width 1280 --height 720

按键：
  ←/→   时间 ±1 帧（16.7ms）     PgUp/PgDn  时间 ±500ms
  Space 原尺寸交替显示 A/B       S   保存当前 A/B 对照 PNG（当前目录）
  R     重新渲染当前时间戳       Q/Esc 退出
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from PyQt6.QtCore import Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QImage, QPainter, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow  # noqa: E402

from krok_helper.subtitle_render.domain.models import Style  # noqa: E402
from krok_helper.subtitle_render.domain.timing import (  # noqa: E402
    TimingChar,
    TimingLine,
    TimingTrack,
)
from krok_helper.subtitle_render.native.backend import (  # noqa: E402
    NativeRendererProcess,
    SharedFrameRingReader,
)
from krok_helper.subtitle_render.sources.subtitles import load_nicokara_lrc  # noqa: E402

FRAME_MS = 1000.0 / 60.0


def build_style() -> Style:
    return Style(
        font_family="Meiryo",
        font_family_latin="Arial",
        font_size_px=64,
        font_reference_height=360,
        base_color="#FFFFFF",
        fill_color="#FF2030",
        stroke_color="#101010",
        stroke_width_px=6,
        stroke2_enabled=True,
        stroke2_width_px=4,
        decoration_kind="none",
        line_y_position="center",
        line_horizontal_layout="center",
        line_lead_in_ms=0,
        line_tail_ms=0,
    )


def build_track(args: argparse.Namespace) -> TimingTrack:
    if args.lrc:
        return load_nicokara_lrc(args.lrc)
    text = args.text or "永漢Abg 満開フォント"
    return TimingTrack(
        lines=[
            TimingLine(
                chars=[TimingChar(ch, index * 300) for index, ch in enumerate(text)],
                end_ms=len(text) * 300 + 2000,
            )
        ]
    )


class AbRenderer:
    """一个 sidecar 实例 + 它的 env 身份（A=旧 baked，B=蒙版候选）。"""

    def __init__(self, label: str, mask_enabled: bool, args: argparse.Namespace,
                 track: TimingTrack, style: Style) -> None:
        self.label = label
        if mask_enabled:
            os.environ["KROK_GPU_STATIC_LAYER_MASK"] = "1"
        else:
            os.environ.pop("KROK_GPU_STATIC_LAYER_MASK", None)
        self.process = NativeRendererProcess(response_timeout_s=30.0)
        self.process.start()
        self.process.configure_gpu(
            track, style, width=args.width, height=args.height, fps=60,
            dpr=args.dpr, realization_enabled=True,
        )

    def render(self, t_ms: int) -> QImage | None:
        event = self.process.render_gpu_frame(int(t_ms), frame_index=0)
        if event.get("event") != "gpu_frame_ready":
            return None
        try:
            with SharedFrameRingReader.from_event(event) as reader:
                image = reader.read_qimage(event)
        except Exception:  # noqa: BLE001 - 对照工具：读失败按无帧处理
            return None
        return image

    def close(self) -> None:
        self.process.close()


class Viewer(QMainWindow):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__()
        self.setWindowTitle("GPU 预览 A/B 对照（A=旧 baked | B=蒙版候选）")
        self.t_ms = int(args.at)
        self.alternating = False
        self.showing_b = False
        track = build_track(args)
        style = build_style()
        os.environ.setdefault("KROK_SUBTITLE_NATIVE_RENDERER", "")
        default_exe = REPO_ROOT / "build" / "native-renderer" / "krok_subtitle_renderer.exe"
        os.environ["KROK_SUBTITLE_NATIVE_RENDERER"] = str(default_exe)
        self.a = AbRenderer("旧 baked", False, args, track, style)
        self.b = AbRenderer("蒙版候选", True, args, track, style)
        self.image_a: QImage | None = None
        self.image_b: QImage | None = None
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(self.label)
        self.refresh()
        self.alt_timer = QTimer(self)
        self.alt_timer.setInterval(700)
        self.alt_timer.timeout.connect(self.toggle_alternate)
        self.statusBar().showMessage(
            "←/→ ±1帧  PgUp/PgDn ±500ms  Space 交替  S 存图  R 重渲  Q 退出"
        )

    def refresh(self) -> None:
        self.image_a = self.a.render(self.t_ms)
        self.image_b = self.b.render(self.t_ms)
        self.showing_b = False
        self.update_view()

    def compose_side_by_side(self) -> QImage:
        if self.image_a is None or self.image_b is None:
            placeholder = QImage(640, 360, QImage.Format.Format_ARGB32_Premultiplied)
            placeholder.fill(0)
            return placeholder
        gap = 16
        width = self.image_a.width() + gap + self.image_b.width()
        height = max(self.image_a.height(), self.image_b.height()) + 40
        canvas = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(0xFF202020)
        painter = QPainter(canvas)
        painter.drawImage(0, 0, self.image_a)
        painter.drawImage(self.image_a.width() + gap, 0, self.image_b)
        from PyQt6.QtGui import QColor, QFont

        font = QFont()
        font.setPixelSize(20)
        painter.setFont(font)
        painter.setPen(QColor("#FF7070"))
        painter.drawText(8, self.image_a.height() + 28, "A：旧 baked")
        painter.setPen(QColor("#70FFB0"))
        painter.drawText(self.image_a.width() + gap + 8, self.image_b.height() + 28,
                         "B：蒙版候选")
        painter.end()
        return canvas

    def update_view(self) -> None:
        if self.alternating:
            image = self.image_b if self.showing_b else self.image_a
            if image is None:
                return
            title = f"B：蒙版候选 @ {self.t_ms}ms" if self.showing_b else f"A：旧 baked @ {self.t_ms}ms"
            self.setWindowTitle(f"GPU 预览 A/B 对照 —— 交替 {title}")
            self.label.setPixmap(QPixmap.fromImage(image.copy()))
            self.resize(max(image.width(), 320), image.height() + 40)
        else:
            canvas = self.compose_side_by_side()
            self.setWindowTitle(f"GPU 预览 A/B 对照 @ {self.t_ms}ms")
            self.label.setPixmap(QPixmap.fromImage(canvas.copy()))
            self.resize(canvas.width(), canvas.height())

    def toggle_alternate(self) -> None:
        self.showing_b = not self.showing_b
        self.update_view()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Left:
            self.t_ms = max(0, int(self.t_ms - FRAME_MS))
            self.refresh()
        elif key == Qt.Key.Key_Right:
            self.t_ms = int(self.t_ms + FRAME_MS)
            self.refresh()
        elif key == Qt.Key.Key_PageUp:
            self.t_ms = max(0, self.t_ms - 500)
            self.refresh()
        elif key == Qt.Key.Key_PageDown:
            self.t_ms += 500
            self.refresh()
        elif key == Qt.Key.Key_Space:
            self.alternating = not self.alternating
            if self.alternating:
                self.alt_timer.start()
            else:
                self.alt_timer.stop()
            self.update_view()
        elif key == Qt.Key.Key_R:
            self.refresh()
        elif key == Qt.Key.Key_S:
            stamp = f"ab_{self.t_ms}ms"
            if self.image_a is not None:
                self.image_a.save(f"{stamp}_A_legacy.png")
            if self.image_b is not None:
                self.image_b.save(f"{stamp}_B_mask.png")
            self.statusBar().showMessage(f"已保存 {stamp}_A/B.png（当前目录）")
        elif key in (Qt.Key.Key_Q, Qt.Key.Key_Escape):
            self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.alt_timer.stop()
        self.a.close()
        self.b.close()
        super().closeEvent(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="GPU 预览 A/B 观感对照工具")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--lrc", help="Nicokara LRC 工程文件")
    source.add_argument("--text", help="内联歌词文本（默认演示文本）")
    parser.add_argument("--at", type=int, default=1000, help="起始时间戳 ms")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--dpr", type=float, default=1.0)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    viewer = Viewer(args)
    viewer.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
