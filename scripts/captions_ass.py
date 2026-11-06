"""
ASS subtitle generation from timed caption clips (timeline seconds).
Preview and render use the same builder — feed events from caption_events().
"""

from __future__ import annotations

from typing import Any

from caption_style_resolve import merge_style_dict
from font_mapping import ass_font_name


def hex_to_ass_bgr(hex_color: str) -> str:
    if not isinstance(hex_color, str) or len(hex_color) != 7 or hex_color[0] != "#":
        return "&H00FFFFFF&"
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"&H{b:02X}{g:02X}{r:02X}&"


def ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def escape_word_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _word_display(
    word_text: str,
    st: dict[str, Any],
    primary: str,
    active_c: str,
    outline_c: str,
    is_active: bool,
    video_h: float,
    line_duration_ms: int,
) -> str:
    t = escape_word_text(word_text)
    if st.get("uppercase"):
        t = t.upper()
    bold_tag = -1 if st.get("bold") else 0
    italic_tag = -1 if st.get("italic") else 0
    bord = float(st.get("outline_width", 2.0))
    intensity = float(st.get("animation_intensity", 0.8))
    scale = float(st.get("active_word_scale", 1.15))
    anim = str(st.get("animation", "word_highlight"))
    blur = max(0.0, intensity * 2.0) if anim == "neon" else 0.0

    base_inactive = (
        f"{{\\b{bold_tag}\\i{italic_tag}\\blur{blur:.1f}\\c{primary}\\3c{outline_c}\\bord{bord:.1f}}}"
    )

    if not is_active:
        return f"{base_inactive}{t}"

    if anim in ("none", "word_highlight", "karaoke_sweep"):
        return f"{{\\b{bold_tag}\\i{italic_tag}\\c{active_c}\\3c{outline_c}\\bord{bord:.1f}}}{t}"

    if anim == "word_pop":
        half = max(40, int(line_duration_ms * 0.35))
        sc = int(scale * 100)
        return (
            f"{{\\b{bold_tag}\\i{italic_tag}\\c{active_c}\\3c{outline_c}\\bord{bord:.1f}"
            f"\\t(0,{half},\\fscx{sc}\\fscy{sc})\\t({half},{line_duration_ms},\\fscx100\\fscy100)}}{t}"
        )

    if anim == "word_box":
        bc = hex_to_ass_bgr(str(st.get("box_color", "#000000")))
        pad = max(2.0, float(st.get("box_padding", 6.0)))
        bx = max(2.0, pad * video_h / 200.0)
        return f"{{\\b{bold_tag}\\i{italic_tag}\\c{active_c}\\3c{bc}\\bord{bx:.1f}\\shad0}}{t}"

    if anim == "typewriter":
        fad_in = max(30, int(line_duration_ms * 0.4))
        return (
            f"{{\\b{bold_tag}\\i{italic_tag}\\fad({fad_in},0)\\c{active_c}\\3c{outline_c}\\bord{bord:.1f}}}{t}"
        )

    if anim == "bounce_in":
        half = max(50, int(line_duration_ms * 0.45))
        sc = int(scale * 100)
        return (
            f"{{\\b{bold_tag}\\i{italic_tag}\\c{active_c}\\3c{outline_c}\\bord{bord:.1f}"
            f"\\t(0,{half},\\fscy{sc}\\frz-8)\\t({half},{line_duration_ms},\\fscy100\\frz0)}}{t}"
        )

    if anim == "fade_in":
        fi = max(40, int(line_duration_ms * 0.5))
        return (
            f"{{\\b{bold_tag}\\i{italic_tag}\\fad({fi},0)\\c{active_c}\\3c{outline_c}\\bord{bord:.1f}}}{t}"
        )

    return f"{{\\b{bold_tag}\\i{italic_tag}\\c{active_c}\\3c{outline_c}\\bord{bord:.1f}}}{t}"


def _karaoke_line(chunk: list[dict], st: dict[str, Any]) -> str:
    """Karaoke sweep: \\k duration uses SecondaryColour from the style header."""
    parts: list[str] = []
    for w in chunk:
        txt = escape_word_text(str(w.get("word", "")))
        if st.get("uppercase"):
            txt = txt.upper()
        dur_cs = max(1, int((float(w["end"]) - float(w["start"])) * 100))
        parts.append(f"{{\\k{dur_cs}}}{txt}")
    return " ".join(parts)


def _is_active_word(w: dict, active: dict) -> bool:
    return w is active or (
        w.get("word") == active.get("word")
        and abs(float(w["start"]) - float(active["start"])) < 0.001
    )


def build_ass(
    clips: list[dict[str, Any]],
    style: dict[str, Any],
    video_w: int,
    video_h: int,
) -> str:
    """
    One Dialogue per clip. Each clip:
      - start, end: timeline seconds
      - words: list of {word or text, start, end} in timeline seconds
      - active: highlighted word
      - style: optional partial override
      - line_text: static line if words empty
    """
    w = int(video_w)
    h = int(video_h)
    base = merge_style_dict(style, {})
    font = ass_font_name(str(base.get("font_family", "Arial")))
    px = max(8.0, float(base.get("font_size", 0.04)) * h)
    bold = -1 if base.get("bold") else 0
    italic = -1 if base.get("italic") else 0

    primary = hex_to_ass_bgr(str(base.get("text_color", "#FFFFFF")))
    secondary = hex_to_ass_bgr(str(base.get("active_word_color", "#FFFF00")))
    outline = hex_to_ass_bgr(str(base.get("outline_color", "#000000")))
    back = "&H80000000&"

    margin_v = int(max(10, h * 0.06))
    pos_y_default = float(base.get("position_y", 78.0))
    x_center = w // 2

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{px:.0f},{primary},{secondary},{outline},{back},{bold},{italic},0,0,100,100,0,0,1,{float(base.get("outline_width", 2.5)):.1f},2,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: list[str] = [header]

    for clip in clips:
        t0 = float(clip["start"])
        t1 = float(clip["end"])
        if t1 <= t0:
            t1 = t0 + 0.05
        st = merge_style_dict(base, clip.get("style"))
        py = float(st.get("position_y", pos_y_default))
        ay = max(h * 0.05, min(h * (py / 100.0), h * 0.95))

        words_in = clip.get("words") or []
        words: list[dict[str, Any]] = []
        for wdict in words_in:
            words.append(
                {
                    "word": str(wdict.get("text", wdict.get("word", ""))),
                    "start": float(wdict["start"]),
                    "end": float(wdict["end"]),
                }
            )

        line_ms = int(max(1, (t1 - t0) * 1000))
        anim = str(st.get("animation", "none"))
        primary_c = hex_to_ass_bgr(str(st.get("text_color", "#FFFFFF")))
        active_c = hex_to_ass_bgr(str(st.get("active_word_color", "#FFFF00")))
        outline_c = hex_to_ass_bgr(str(st.get("outline_color", "#000000")))

        if not words:
            static = str(clip.get("line_text", "")).strip()
            if not static:
                continue
            if st.get("uppercase"):
                static = static.upper()
            dialogue = f"{{\\an5\\pos({x_center:.0f},{ay:.0f})}}{escape_word_text(static)}"
            lines.append(
                f"Dialogue: 0,{ass_time(t0)},{ass_time(t1)},Default,,0,0,0,,{dialogue}\n"
            )
            continue

        active = clip.get("active")
        if not isinstance(active, dict):
            active = words[-1]

        pos_tag = f"{{\\an5\\pos({x_center:.0f},{ay:.0f})}}"

        if anim == "karaoke_sweep":
            inner = _karaoke_line(words, st)
            dialogue = f"{pos_tag}{inner}"
        else:
            parts = [
                _word_display(
                    str(w["word"]),
                    st,
                    primary_c,
                    active_c,
                    outline_c,
                    _is_active_word(w, active),
                    float(h),
                    line_ms,
                )
                for w in words
            ]
            dialogue = pos_tag + " ".join(parts)

        lines.append(
            f"Dialogue: 0,{ass_time(t0)},{ass_time(t1)},Default,,0,0,0,,{dialogue}\n"
        )

    return "".join(lines)


def build_ass_from_events(
    events: list[dict[str, Any]],
    default_style: dict[str, Any],
    video_w: int,
    video_h: int,
) -> str:
    clips: list[dict[str, Any]] = []
    for e in events:
        chunk = e.get("chunk") or []
        active = e.get("active") or {}
        ev_style = e.get("style")
        words = [
            {"word": w.get("word", ""), "start": float(w["start"]), "end": float(w["end"])}
            for w in chunk
        ]
        clips.append(
            {
                "start": float(e["start"]),
                "end": float(e["end"]),
                "words": words,
                "active": active,
                "style": ev_style if isinstance(ev_style, dict) else None,
            }
        )
    return build_ass(clips, default_style, video_w, video_h)
