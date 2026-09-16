"""标题的淡入淡出与显示时段要记在应用级设置里。

改一次就该一直沿用 —— 每开一个新项目重设一遍 300 → 250、「自定义」→
「全程显示」很烦。和「标题是否开启」「标题布局」是同一类"用户习惯"，所以
存在同一处（``new_project_defaults``）。

尾段那两项是 ``Optional``：``None`` 表示"跟随开头"，是合法取值，不能在存取
过程里被当成缺省丢掉。自定义时间段窗口是逐曲的，不记 —— 新建条目时按工程
时长现铺。
"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from krok_helper.subtitle_render.frontend.main_window import (  # noqa: E402
    SubtitleRenderWindow,
)
from krok_helper.subtitle_render.domain.models import TitleOverlay  # noqa: E402


class _Recorder:
    """一份留在内存里的 subtitle_render 设置命名空间。"""

    def __init__(self) -> None:
        self.data: dict = {}

    def load(self) -> dict:
        return dict(self.data)

    def save(self, data: dict) -> None:
        self.data = dict(data)


@pytest.fixture
def settings() -> _Recorder:
    return _Recorder()


@pytest.fixture
def make_window(settings):
    app = QApplication.instance() or QApplication([])
    built: list[SubtitleRenderWindow] = []

    def factory() -> SubtitleRenderWindow:
        widget = SubtitleRenderWindow.for_embedding(settings_provider=settings)
        built.append(widget)
        return widget

    yield factory
    for widget in built:
        widget.close()
        widget.deleteLater()
    app.processEvents()


def _edit_title(window: SubtitleRenderWindow, **changes) -> None:
    title = (window._style.title_overlays or [TitleOverlay()])[0]
    window._property_panel.set_style(
        replace(
            window._style,
            title_overlays=[replace(title, enabled=True, **changes)],
        ),
        emit=True,
    )
    QApplication.instance().processEvents()


def test_editing_the_fade_updates_the_app_default(make_window) -> None:
    window = make_window()

    _edit_title(window, fade_in_ms=250, fade_out_ms=180)

    app_title = window._app_default_style.title_overlays[0]
    assert app_title.fade_in_ms == 250
    assert app_title.fade_out_ms == 180


def test_the_fade_is_written_next_to_the_other_title_habits(make_window, settings) -> None:
    window = make_window()
    _edit_title(window, fade_in_ms=250)

    window._save_persisted_state()

    defaults = settings.data["new_project_defaults"]
    assert "title_enabled" in defaults and "title_layout_name" in defaults
    assert defaults["title_fades"]["fade_in_ms"] == 250


def test_a_new_instance_starts_from_the_remembered_fade(make_window) -> None:
    """真正要的效果：下次打开还是 250。"""
    first = make_window()
    _edit_title(first, fade_in_ms=250, fade_out_ms=180)
    first._save_persisted_state()

    second = make_window()

    assert second._app_default_style.title_overlays[0].fade_in_ms == 250
    assert second._style.title_overlays[0].fade_in_ms == 250
    assert second._style.title_overlays[0].fade_out_ms == 180


def test_the_tail_none_means_follow_the_head_and_round_trips(make_window, settings) -> None:
    """尾段的 ``None`` 是"跟随开头"，不是"没设置"。"""
    window = make_window()
    _edit_title(window, fade_in_ms=250)
    window._save_persisted_state()

    assert settings.data["new_project_defaults"]["title_fades"]["tail_fade_in_ms"] is None

    reopened = make_window()

    assert reopened._app_default_style.title_overlays[0].tail_fade_in_ms is None


def test_an_explicit_tail_fade_is_remembered_too(make_window) -> None:
    first = make_window()
    _edit_title(first, tail_fade_in_ms=120, tail_fade_out_ms=90)
    first._save_persisted_state()

    second = make_window()

    title = second._app_default_style.title_overlays[0]
    assert title.tail_fade_in_ms == 120
    assert title.tail_fade_out_ms == 90


def test_the_title_text_stays_per_song(make_window) -> None:
    """标题文字是逐曲的，绝不能跟着记进应用级默认。"""
    first = make_window()
    _edit_title(first, text_template="某首歌 / 某歌手", fade_in_ms=250)
    first._save_persisted_state()

    second = make_window()

    assert second._app_default_style.title_overlays[0].fade_in_ms == 250
    assert (
        second._app_default_style.title_overlays[0].text_template
        == TitleOverlay().text_template
    )


def test_garbage_in_the_settings_falls_back_to_the_defaults(make_window, settings) -> None:
    """手改坏了设置文件也不该把标题时长搞成负数或字符串。"""
    settings.data = {
        "new_project_defaults": {
            "title_fades": {"fade_in_ms": "很快", "fade_out_ms": -50}
        }
    }

    window = make_window()

    title = window._app_default_style.title_overlays[0]
    assert title.fade_in_ms == TitleOverlay().fade_in_ms
    assert title.fade_out_ms == 0


def test_editing_show_mode_and_offsets_updates_the_app_default(make_window) -> None:
    """「全程显示 + 时间偏移」这类常用设置跟着用户习惯走。"""
    window = make_window()

    _edit_title(
        window,
        show_mode="whole",
        head_offset_ms=500,
        tail_offset_ms=800,
        duration_ms=15_000,
    )

    app_title = window._app_default_style.title_overlays[0]
    assert app_title.show_mode == "whole"
    assert app_title.head_offset_ms == 500
    assert app_title.tail_offset_ms == 800
    assert app_title.duration_ms == 15_000


def test_timing_is_written_next_to_the_other_title_habits(make_window, settings) -> None:
    window = make_window()
    _edit_title(window, show_mode="whole", head_offset_ms=500)

    window._save_persisted_state()

    timing = settings.data["new_project_defaults"]["title_timing"]
    assert timing["show_mode"] == "whole"
    assert timing["head_offset_ms"] == 500
    assert timing["tail_duration_ms"] is None


def test_a_new_instance_starts_from_the_remembered_timing(make_window) -> None:
    """真正要的效果：下次新建项目，标题直接就是「全程显示」。"""
    first = make_window()
    _edit_title(
        first,
        show_mode="whole",
        head_offset_ms=500,
        tail_offset_ms=800,
        duration_ms=15_000,
    )
    first._save_persisted_state()

    second = make_window()

    title = second._style.title_overlays[0]
    assert title.show_mode == "whole"
    assert title.head_offset_ms == 500
    assert title.tail_offset_ms == 800
    assert title.duration_ms == 15_000
    assert second._app_default_style.title_overlays[0].show_mode == "whole"


def test_a_new_title_entry_inherits_the_remembered_timing(make_window) -> None:
    """「新建标题」同样套用记忆：模式与偏移不再回到出厂默认。"""
    first = make_window()
    _edit_title(first, show_mode="head", head_offset_ms=700, duration_ms=20_000)
    first._save_persisted_state()

    second = make_window()
    entry = second._new_title_entry_defaults()

    assert entry.show_mode == "head"
    assert entry.head_offset_ms == 700
    assert entry.duration_ms == 20_000


def test_editing_the_scheme_reference_is_remembered(make_window) -> None:
    """标题引用的配色方案也是习惯：新工程 / 新条目沿用（悬空时渲染回落内置）。"""
    first = make_window()
    _edit_title(first, scheme_name="角色A")
    first._save_persisted_state()

    second = make_window()
    assert second._app_default_style.title_overlays[0].scheme_name == "角色A"
    assert second._style.title_overlays[0].scheme_name == "角色A"
    assert second._new_title_entry_defaults().scheme_name == "角色A"

    # ``None`` = 内置「标题」方案，同样是合法记忆值，不能被丢成出厂字符串。
    _edit_title(second, scheme_name=None)
    second._save_persisted_state()
    third = make_window()
    assert third._app_default_style.title_overlays[0].scheme_name is None


def test_the_tail_duration_none_and_explicit_values_round_trip(make_window) -> None:
    """``tail_duration_ms`` 的 ``None`` 是"跟随开头"；显式值同样要记。"""
    first = make_window()
    _edit_title(first, show_mode="tail")
    first._save_persisted_state()
    assert (
        first._app_default_style.title_overlays[0].tail_duration_ms is None
    )

    reopened = make_window()
    assert (
        reopened._app_default_style.title_overlays[0].tail_duration_ms is None
    )

    _edit_title(reopened, tail_duration_ms=5_000)
    reopened._save_persisted_state()

    third = make_window()
    assert (
        third._app_default_style.title_overlays[0].tail_duration_ms == 5_000
    )


def test_garbage_timing_falls_back_field_by_field(make_window, settings) -> None:
    """坏掉的显示时段记忆逐字段丢弃，不拖垮其它标题偏好。"""
    settings.data = {
        "new_project_defaults": {
            "title_enabled": True,
            "title_scheme_name": 123,
            "title_timing": {
                "show_mode": "全程",
                "head_offset_ms": -5,
                "tail_offset_ms": "0.8s",
                "duration_ms": 12_000,
            },
            "title_fades": {"fade_in_ms": 250},
        }
    }

    window = make_window()

    title = window._app_default_style.title_overlays[0]
    assert title.show_mode == TitleOverlay().show_mode
    assert title.head_offset_ms == TitleOverlay().head_offset_ms
    assert title.tail_offset_ms == TitleOverlay().tail_offset_ms
    assert title.duration_ms == 12_000
    assert title.scheme_name is None
    assert title.enabled is True
    assert title.fade_in_ms == 250
