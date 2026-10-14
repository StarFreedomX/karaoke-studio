"""按字（verbatim）预览的铺轴单元与输出形态。

粒度规则：汉字 / 假名 / 谚文按单字成轴；字母词组（英文、德文等拉丁文本）
按整词成轴 —— 英文的「逐字」就是 word by word，输出 ``[ts]词`` 形态，
与 SUG 中「英文词 = 一个节奏点单位」的模型一致。

（注：word by word 的标签进 SUG 后能否不丢字，取决于 SUG 的逐字判定；
这里只钉工作台的转换输出。）
"""

from __future__ import annotations

import pytest

import krok_helper  # noqa: F401 - installs bundled SUG src path
from krok_helper.lyrics import (
    _build_estimated_verbatim_lrc,
    _convert_krc_text,
    _convert_yrc_text,
    _split_verbatim_units,
    parse_lrc_lines,
)

GERMAN_LINE = "Wir im fernen Vaterland geboren"
GERMAN_KRC = "[1000,2000]<0,500,0>Wir <500,400,0>im <900,900,0>fernen <1800,1500,0>Vaterland <3300,900,0>geboren"


def _import_via_sug(text: str):
    pytest.importorskip("numpy")
    from strange_uta_game.frontend.editor.timing.lyric_loader import parse_lyric_content

    return parse_lyric_content(text, "singer-0")[0]


def test_split_verbatim_units_groups_latin_words() -> None:
    units = [unit for _offset, unit in _split_verbatim_units("Apple, it's red 春日影")]
    assert units == ["Apple", ",", "it's", "red", "春", "日", "影"]


def test_estimated_verbatim_groups_letter_words_per_word() -> None:
    rendered = _build_estimated_verbatim_lrc(
        parse_lrc_lines(
            "[00:01.00]Wir im fernen Vaterland geboren\n"
            "[00:05.00]Nahmen nichts als Haß im Herzen mit"
        )
    )
    assert rendered.splitlines() == [
        "[00:01.00]Wir [00:01.80]im [00:02.60]fernen [00:03.40]Vaterland [00:04.20]geboren",
        "[00:05.00]Nahmen [00:05.58]nichts [00:06.16]als [00:06.74]Haß [00:07.32]im [00:07.90]Herzen [00:08.48]mit",
    ]


def test_estimated_verbatim_keeps_cjk_per_char() -> None:
    rendered = _build_estimated_verbatim_lrc(parse_lrc_lines("[00:01.00]春日影"))
    assert rendered == "[00:01.00]春[00:01.40]日[00:01.80]影"


def test_estimated_verbatim_mixed_line_word_by_word() -> None:
    rendered = _build_estimated_verbatim_lrc(parse_lrc_lines("[00:01.00]春のAppleは赤い"))
    assert rendered == "[00:01.00]春[00:01.23]の[00:01.47]Apple[00:01.70]は[00:01.93]赤[00:02.17]い"


def test_krc_verbatim_word_by_word_for_letter_words() -> None:
    _line, verbatim, _plain, _translation = _convert_krc_text(GERMAN_KRC)
    assert verbatim == "[00:01.00]Wir [00:01.50]im [00:01.90]fernen [00:02.80]Vaterland [00:04.30]geboren"


def test_krc_verbatim_keeps_char_form_for_cjk() -> None:
    _line, verbatim, _plain, _translation = _convert_krc_text(
        "[1000,2000]<0,500,0>春<500,400,0>日<900,900,0>影"
    )
    assert verbatim == "[00:01.00]春[00:01.50]日[00:01.90]影"


def test_yrc_verbatim_word_by_word_for_letter_words() -> None:
    _line, verbatim, _plain = _convert_yrc_text(
        "[12340,2600](12340,400,0)Apple (12740,300,0)is (13040,400,0)red"
    )
    assert verbatim == "[00:12.34]Apple [00:12.74]is [00:13.04]red"


def test_cjk_char_verbatim_import_keeps_every_character() -> None:
    _line, verbatim, _plain, _translation = _convert_krc_text(
        "[1000,2000]<0,500,0>春<500,400,0>日<900,900,0>影"
    )
    sentences = _import_via_sug(verbatim)
    assert "".join(sentence.text for sentence in sentences) == "春日影"
    axes = [
        (ch.char, ch.timestamps)
        for sentence in sentences
        for ch in sentence.characters
        if ch.timestamps
    ]
    assert axes == [("春", [1000]), ("日", [1500]), ("影", [1900])]
