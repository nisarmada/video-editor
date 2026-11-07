"""
Project canvas: output size, fps, and default video fit for export/preview/captions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FIT_MODES = frozenset({"contain", "cover"})
BAR_FILLS = frozenset({"black", "blur"})
DEFAULT_W, DEFAULT_H, DEFAULT_FPS = 1080, 1920, 30


def even_dimension(n: int) -> int:
    """H.264 needs even width/height."""
    v = max(2, int(n))
    return v if v % 2 == 0 else v + 1


@dataclass(frozen=True)
class CanvasSettings:
    width: int
    height: int
    fps: int
    fit: str = "contain"
    bar_fill: str = "black"
    fit_position_x: float = 0.5
    fit_position_y: float = 0.5

    def warnings(self) -> list[str]:
        out: list[str] = []
        raw = (self.width, self.height)
        if any(v % 2 for v in raw):
            out.append(
                f"Canvas {self.width}x{self.height} had odd dimension(s); "
                f"export uses {even_dimension(self.width)}x{even_dimension(self.height)}."
            )
        return out


def resolve_canvas(settings: dict[str, Any] | None) -> CanvasSettings:
    """
    Read settings.canvas or legacy settings.width/height/fps.
    Missing canvas → 1080x1920 @ 30 contain (matches pre-canvas exports).
    """
    s = settings if isinstance(settings, dict) else {}
    block = s.get("canvas") if isinstance(s.get("canvas"), dict) else {}

    def _num(key: str, fallback: int) -> int:
        v = block.get(key, s.get(key, fallback))
        try:
            return even_dimension(int(v))
        except (TypeError, ValueError):
            return even_dimension(fallback)

    w = _num("width", DEFAULT_W)
    h = _num("height", DEFAULT_H)
    try:
        fps = int(block.get("fps", s.get("fps", DEFAULT_FPS)))
    except (TypeError, ValueError):
        fps = DEFAULT_FPS
    fps = max(1, min(fps, 120))

    fit = str(block.get("fit") or "contain").strip().lower()
    if fit not in FIT_MODES:
        fit = "contain"
    bar_fill = str(block.get("bar_fill") or "black").strip().lower()
    if bar_fill not in BAR_FILLS:
        bar_fill = "black"

    try:
        px = float(block.get("fit_position_x", 0.5))
        py = float(block.get("fit_position_y", 0.5))
    except (TypeError, ValueError):
        px, py = 0.5, 0.5
    px = min(1.0, max(0.0, px))
    py = min(1.0, max(0.0, py))

    return CanvasSettings(
        width=w,
        height=h,
        fps=fps,
        fit=fit,
        bar_fill=bar_fill,
        fit_position_x=px,
        fit_position_y=py,
    )


def settings_with_canvas_sync(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Merge resolved canvas into settings.width/height/fps for caption APIs."""
    s = dict(settings) if isinstance(settings, dict) else {}
    c = resolve_canvas(s)
    s["width"] = c.width
    s["height"] = c.height
    s["fps"] = c.fps
    block = dict(s.get("canvas")) if isinstance(s.get("canvas"), dict) else {}
    block.setdefault("width", c.width)
    block.setdefault("height", c.height)
    block.setdefault("fps", c.fps)
    block.setdefault("fit", c.fit)
    block.setdefault("bar_fill", c.bar_fill)
    block.setdefault("fit_position_x", c.fit_position_x)
    block.setdefault("fit_position_y", c.fit_position_y)
    s["canvas"] = block
    return s


def piece_fit_settings(
    piece_fit: str | None,
    piece_bar: str | None,
    piece_px: float | None,
    piece_py: float | None,
    canvas: CanvasSettings,
) -> tuple[str, str, float, float]:
    fit = piece_fit if piece_fit in FIT_MODES else canvas.fit
    bar = piece_bar if piece_bar in BAR_FILLS else canvas.bar_fill
    px = canvas.fit_position_x if piece_px is None else min(1.0, max(0.0, float(piece_px)))
    py = canvas.fit_position_y if piece_py is None else min(1.0, max(0.0, float(piece_py)))
    return fit, bar, px, py
