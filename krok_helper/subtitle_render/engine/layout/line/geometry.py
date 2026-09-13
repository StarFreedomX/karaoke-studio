"""Layout-facing line geometry semantics independent from a paint backend."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from krok_helper.subtitle_render.engine.guide import (
    render_line_with_guide_symbols,
)
from krok_helper.subtitle_render.engine.layout.line.style import style_for_line
from krok_helper.subtitle_render.engine.timing.timeline import compute_char_intervals
from krok_helper.subtitle_render.domain.models import Style
from krok_helper.subtitle_render.domain.timing import TimingLine


CharWidthResolver = Callable[[TimingLine, Style], Sequence[int]]


def line_has_role_labels(line: TimingLine) -> bool:
    return any(bool(char.role_label) for char in line.chars)


def resolve_char_intervals(
    line: TimingLine,
    style: Style,
    char_widths_for: CharWidthResolver,
    char_ink_widths_for: CharWidthResolver | None = None,
) -> list[tuple[int, int]]:
    """Resolve final character intervals using backend-provided glyph widths.

    ``char_ink_widths_for`` is optional ink-width weights; they only drive the
    multi-checkpoint leader guard split inside ``compute_char_intervals`` and
    fall back to layout widths when absent.
    """
    line_style = style_for_line(style, line)
    render_line = render_line_with_guide_symbols(line)
    if line_style.vertical:
        return compute_char_intervals(render_line)
    ink_widths = (
        list(char_ink_widths_for(render_line, line_style))
        if char_ink_widths_for is not None
        else None
    )
    return compute_char_intervals(
        render_line,
        list(char_widths_for(render_line, line_style)),
        ink_widths=ink_widths,
    )


__all__ = [
    "CharWidthResolver",
    "line_has_role_labels",
    "resolve_char_intervals",
]
