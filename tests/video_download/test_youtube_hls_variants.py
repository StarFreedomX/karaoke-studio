"""YouTube 2026-08 起在格式表里混入的 HLS 变体。

这些 ``m3u8_native`` 条目的 ``tbr`` 普遍比同画质的 DASH 条目高（实测 1080p
4684 vs 1859），却一个体积字段都没有。老的挑选逻辑只按 tbr 排，于是每一档
清晰度的代表都换成了这些无体积条目，界面上所有清晰度显示的都是同一个几 MB
的数字 —— 那其实是音频轨的体积被当成了整条的体积。
"""

from __future__ import annotations

import pytest

from krok_helper.video_download.format_parser import FormatParser, format_bytes


AUDIO = {
    "format_id": "140",
    "ext": "m4a",
    "vcodec": "none",
    "acodec": "mp4a.40.2",
    "abr": 129.5,
    "tbr": 129.5,
    "filesize": 3_538_445,
}


def _dash_1080p() -> dict:
    return {
        "format_id": "137",
        "ext": "mp4",
        "width": 1920,
        "height": 1080,
        "vcodec": "avc1.640028",
        "acodec": "none",
        "protocol": "https",
        "tbr": 1859.024,
        "filesize": 50_774_366,
    }


def _hls_1080p() -> dict:
    return {
        "format_id": "270",
        "ext": "mp4",
        "width": 1920,
        "height": 1080,
        "vcodec": "avc1.640028",
        "acodec": "none",
        "protocol": "m3u8_native",
        "tbr": 4684.109,
        "filesize": None,
        "filesize_approx": None,
    }


def test_sizeless_hls_variant_does_not_take_over_the_resolution() -> None:
    options = FormatParser().parse_formats([AUDIO, _hls_1080p(), _dash_1080p()], duration=219)

    # 同一档里只会留一个代表，它同时就是「最佳质量」那一条。
    row = options[0]
    assert row.download_format == "137+140"
    assert row.filesize == 50_774_366 + 3_538_445


def test_merged_size_is_unknown_instead_of_the_audio_only_size() -> None:
    """视频轨报不出体积、也估不出来时，整条应当是「未知」。

    以前写成 ``(video or 0) + (audio or 0)``，视频轨为 None 时报出去的是音频
    体积 —— 每档清晰度都显示同一个几 MB 的数字，用户以为解析坏了。
    """
    hls = _hls_1080p()
    hls.pop("tbr")

    options = FormatParser().parse_formats([AUDIO, hls], duration=219)

    row = options[0]
    assert row.filesize is None


def test_hls_peak_bandwidth_is_not_used_to_estimate_size() -> None:
    """BANDWIDTH 是峰值，不能按时长相乘后当成平均体积。"""
    options = FormatParser().parse_formats([AUDIO, _hls_1080p()], duration=219)

    row = options[0]
    assert row.filesize is None


def test_estimation_never_outranks_a_real_size() -> None:
    """估算值只用于显示；排序仍按「有没有真实体积」，否则 HLS 又会顶回代表位。"""
    options = FormatParser().parse_formats([AUDIO, _hls_1080p(), _dash_1080p()], duration=219)

    recommended = options[0]
    assert recommended.is_recommended
    assert recommended.download_format == "137+140"


def test_without_duration_there_is_no_estimate() -> None:
    options = FormatParser().parse_formats([AUDIO, _hls_1080p()])

    row = options[0]
    assert row.filesize is None


def _premium_hls() -> dict:
    return {
        **_hls_1080p(),
        "format_id": "616",
        "format_note": "Premium",
        "vcodec": "vp09.00.40.08",
        "tbr": 4680.316,
        "url": (
            "https://manifest.googlevideo.com/api/manifest/hls_playlist/itag/616/"
            "sgovp/clen%3D56721927%3Bdur%3D235.766%3Bgir%3Dyes%3Bitag%3D356/playlist/index.m3u8"
        ),
    }


def test_premium_size_uses_source_bytes_instead_of_peak_bandwidth() -> None:
    """w8grOWgLOB8：旧显示 135.3 MB，实际成品 60,682,404 字节。"""
    audio = {**AUDIO, "filesize": 3_817_312}
    option = FormatParser().parse_formats([audio, _dash_1080p(), _premium_hls()], duration=236)[0]

    assert option.download_format == "616+140"
    assert option.is_recommended
    assert option.filesize == 56_721_927 + 3_817_312
    assert option.filesize_is_estimate
    assert abs(option.filesize - 60_682_404) / 60_682_404 < 0.003
    assert format_bytes(option.filesize, estimated=option.filesize_is_estimate) == "约 57.7 MB"


def test_hls_source_bytes_do_not_require_duration() -> None:
    option = FormatParser().parse_formats([AUDIO, _premium_hls()])[0]
    assert option.filesize == 56_721_927 + AUDIO["filesize"]


@pytest.mark.parametrize("url", [
    "https://example.com/sgovp/clen%3D56721927/playlist/index.m3u8",
    "https://googlevideo.com.example.com/sgovp/clen%3D56721927/playlist/index.m3u8",
    "https://manifest.googlevideo.com/sgovp/clen%3Dinvalid/playlist/index.m3u8",
    "https://manifest.googlevideo.com/sgovp/clen%3D0/playlist/index.m3u8",
    "https://manifest.googlevideo.com/sgovp/clen%3D-100/playlist/index.m3u8",
    "https://manifest.googlevideo.com/sgovp",
    "https://manifest.googlevideo.com/sgoap/clen%3D3817312/playlist/index.m3u8",
    "https://[invalid",
])
def test_unavailable_hls_video_length_stays_unknown(url: str) -> None:
    option = FormatParser().parse_formats([AUDIO, {**_premium_hls(), "url": url}], duration=236)[0]
    assert option.filesize is None


def test_hls_source_estimate_does_not_replace_dash_representative() -> None:
    hls = {**_premium_hls(), "format_note": "1080p"}
    option = FormatParser().parse_formats([AUDIO, _dash_1080p(), hls], duration=236)[0]
    assert option.download_format == "137+140"
    assert not option.filesize_is_estimate


def test_hls_audio_source_bytes_are_included_once() -> None:
    audio = {
        **AUDIO, "filesize": None, "protocol": "m3u8_native",
        "url": "https://manifest.googlevideo.com/sgoap/clen%3D3817312%3Bdur%3D235.821/index.m3u8",
    }
    option = FormatParser().parse_formats([audio, _premium_hls()], duration=236)[0]
    assert option.filesize == 56_721_927 + 3_817_312
    assert option.filesize_is_estimate


def test_missing_audio_size_does_not_display_video_only_size() -> None:
    audio = {**AUDIO, "filesize": None, "tbr": None, "abr": None}
    option = FormatParser().parse_formats([audio, _dash_1080p()], duration=236)[0]
    assert option.filesize is None


@pytest.mark.parametrize("metadata,expected,estimated", [
    ({"filesize": 50_000_000, "filesize_approx": 90_000_000}, 50_000_000, False),
    ({"filesize": None, "filesize_approx": 49_000_000}, 49_000_000, True),
    ({"filesize": None, "tbr": 2000}, 59_000_000, True),
])
def test_non_hls_sizes_keep_precision_information(metadata, expected, estimated) -> None:
    option = FormatParser().parse_formats([AUDIO, {**_dash_1080p(), **metadata}], duration=236)[0]
    assert option.filesize == expected + AUDIO["filesize"]
    assert option.filesize_is_estimate is estimated
