"""Local motion rendering + placeholder artwork.

Two jobs:

``render_motion_video``
    Turn one or more stills into an MP4 with eased camera motion (push in,
    pull out, lateral pans, ken-burns) and cross-fades. This is plain FFmpeg —
    the same engine the repo's post pipeline uses — so it works with no API
    keys, no Node, and no GPU.

``demo_poster``
    When no image provider is configured, the Studio can still demonstrate the
    full flow. This draws a deliberate-looking poster from the prompt using the
    repository's *own* style-playbook palettes. It is labelled as a placeholder
    everywhere it surfaces — it is never passed off as a model output.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent

ASPECTS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "4:3": (1440, 1080),
}

MOTION_PRESETS = {
    "ken_burns": "Slow push-in with a drifting pan",
    "zoom_in": "Push in toward the subject",
    "zoom_out": "Pull back to reveal the frame",
    "pan_left": "Lateral pan, right to left",
    "pan_right": "Lateral pan, left to right",
    "pan_up": "Vertical tilt upward",
    "static": "Hold the frame, no camera move",
}

_FALLBACK_PALETTES = {
    "clean-professional": ["#2563EB", "#F59E0B", "#10B981", "#8B5CF6"],
    "flat-motion-graphics": ["#7C3AED", "#EC4899", "#06B6D4", "#F59E0B"],
    "anime-ghibli": ["#A8E6CF", "#FFB347", "#FF6B9D", "#87CEEB"],
    "premium-minimalist": ["#E4E4E7", "#A1A1AA", "#D4AF7A", "#52525B"],
    "minimalist-diagram": ["#0F172A", "#3B82F6", "#94A3B8", "#F43F5E"],
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def ffmpeg_bin() -> str:
    from studio.repo_bridge import ensure_ffmpeg

    return ensure_ffmpeg() or "ffmpeg"


def _run(cmd: Sequence[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


def playbook_palette(style: str = "clean-professional") -> list[str]:
    """Read a real style playbook's chart palette (graceful fallback)."""
    try:
        import yaml

        path = REPO_ROOT / "styles" / f"{style}.yaml"
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            palette = data.get("chart_palette")
            if isinstance(palette, list) and palette:
                return [str(c) for c in palette]
    except Exception:
        pass
    return _FALLBACK_PALETTES.get(style, _FALLBACK_PALETTES["clean-professional"])


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates = [
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans"
        f"{'-Bold' if bold else '-Regular'}.ttf",
        "/System/Library/Fonts/Supplemental/Arial"
        f"{' Bold' if bold else ''}.ttf",
        "C:/Windows/Fonts/arial" + ("bd" if bold else "") + ".ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _font_mono(size: int):
    from PIL import ImageFont

    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "C:/Windows/Fonts/consola.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return _font(size)


def _wrap_px(draw, text: str, font, max_width: float) -> list[str]:
    """Greedy word wrap measured in pixels (not characters)."""
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Placeholder artwork (no model, no key)
# ---------------------------------------------------------------------------

def demo_poster(
    prompt: str,
    out_path: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    seed: Optional[int] = None,
    style: str = "clean-professional",
    variant: int = 0,
) -> Path:
    """Draw a deterministic placeholder poster derived from the prompt."""
    from PIL import Image, ImageDraw, ImageFilter

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256(f"{prompt}|{seed}|{variant}".encode()).hexdigest()
    rng = random.Random(int(digest[:16], 16))

    palette = playbook_palette(style)
    accents = [_hex_to_rgb(c) for c in palette] or [(37, 99, 235)]
    accent = accents[variant % len(accents)]
    accent2 = accents[(variant + 2) % len(accents)]

    base_dark = _mix((9, 12, 20), accent, 0.10)
    base_light = _mix((18, 24, 38), accent2, 0.22)

    # --- background gradient -------------------------------------------------
    canvas = Image.new("RGB", (width, height), base_dark)
    draw = ImageDraw.Draw(canvas)
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line([(0, y), (width, y)], fill=_mix(base_dark, base_light, t ** 0.85))

    # --- soft light blobs ----------------------------------------------------
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    blob_count = 3
    for i in range(blob_count):
        cx = rng.uniform(0.05, 0.95) * width
        cy = rng.uniform(0.05, 0.75) * height
        r = rng.uniform(0.22, 0.52) * max(width, height)
        colour = accents[(variant + i) % len(accents)]
        gdraw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(*colour, rng.randint(38, 66)),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(24, width // 14)))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), glow)
    draw = ImageDraw.Draw(canvas)

    # --- geometric structure -------------------------------------------------
    kind = rng.choice(("arcs", "grid", "orbit", "bands"))
    ink = (255, 255, 255, 26)
    if kind == "arcs":
        cx, cy = width * rng.uniform(0.25, 0.75), height * rng.uniform(0.7, 1.05)
        for i in range(7):
            r = max(width, height) * (0.18 + i * 0.09)
            draw.arc(
                [cx - r, cy - r, cx + r, cy + r],
                start=200, end=340, fill=(*accent, 40 + i * 6), width=max(2, width // 640),
            )
    elif kind == "grid":
        step = max(48, width // 22)
        for x in range(0, width, step):
            draw.line([(x, 0), (x, height)], fill=ink, width=1)
        for y in range(0, height, step):
            draw.line([(0, y), (width, y)], fill=ink, width=1)
    elif kind == "orbit":
        cx, cy = width * rng.uniform(0.55, 0.8), height * rng.uniform(0.35, 0.55)
        for i in range(5):
            rx = width * (0.14 + i * 0.07)
            ry = rx * rng.uniform(0.42, 0.62)
            draw.ellipse(
                [cx - rx, cy - ry, cx + rx, cy + ry],
                outline=(*accent2, 46), width=max(2, width // 720),
            )
        draw.ellipse(
            [cx - width * 0.05, cy - width * 0.05, cx + width * 0.05, cy + width * 0.05],
            fill=(*accent, 120),
        )
    else:  # bands
        for i in range(6):
            y0 = height * (0.18 + i * 0.11)
            thickness = max(3, height // 190)
            draw.line(
                [(0, y0), (width, y0 - rng.uniform(-height * 0.05, height * 0.05))],
                fill=(*accents[(variant + i) % len(accents)], 34),
                width=thickness,
            )

    # --- grain + vignette ----------------------------------------------------
    try:
        import numpy as np

        noise = np.random.default_rng(int(digest[16:32], 16)).normal(
            0, 5.5, (height, width, 1)
        )
        arr = np.asarray(canvas.convert("RGB"), dtype=np.float32) + noise
        canvas = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"), "RGB")
    except Exception:
        canvas = canvas.convert("RGB")

    vignette = Image.new("L", (width, height), 0)
    vdraw = ImageDraw.Draw(vignette)
    vdraw.ellipse(
        [-width * 0.25, -height * 0.35, width * 1.25, height * 1.35], fill=190
    )
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=max(40, width // 12)))
    dark = Image.new("RGB", (width, height), (3, 5, 9))
    canvas = Image.composite(canvas, dark, vignette)

    # --- typography ----------------------------------------------------------
    draw = ImageDraw.Draw(canvas)
    margin = int(width * 0.075)
    portrait = height > width
    max_text_width = int(width * (0.84 if portrait else 0.60))
    title_size = max(30, int(width * (0.078 if portrait else 0.050)))
    title_font = _font(title_size, bold=True)
    kicker_font = _font_mono(max(15, int(title_size * 0.28)))
    meta_font = _font_mono(max(13, int(title_size * 0.24)))

    clean = re.sub(r"\s+", " ", (prompt or "Untitled").strip())
    all_lines = _wrap_px(draw, clean[:200], title_font, max_text_width)
    wrapped = all_lines[:3]
    if len(all_lines) > 3 or len(clean) > 200:
        wrapped[-1] = wrapped[-1].rstrip(" ,.;:") + "…"
    if not wrapped:
        wrapped = ["Untitled"]

    line_h = int(title_size * 1.18)
    block_h = line_h * len(wrapped)
    y = height - margin - block_h

    rule_y = y - int(title_size * 0.80)
    draw.line(
        [(margin, rule_y), (margin + int(width * 0.085), rule_y)],
        fill=accent,
        width=max(3, width // 480),
    )
    draw.text(
        (margin, rule_y - int(title_size * 0.66)),
        "OPENMONTAGE STUDIO",
        font=kicker_font,
        fill=accent,
    )

    for line in wrapped:
        draw.text((margin + 2, y + 2), line, font=title_font, fill=(0, 0, 0))
        draw.text((margin, y), line, font=title_font, fill=(247, 245, 242))
        y += line_h

    # Honesty chip, top-right: this frame is not a model output.
    chip_text = "PLACEHOLDER · NO MODEL"
    chip_font = _font_mono(max(13, int(width * 0.011)))
    padding = max(8, width // 160)
    text_w = draw.textlength(chip_text, font=chip_font)
    chip_h = max(26, int(width * 0.026))
    x1 = width - margin
    x0 = x1 - text_w - padding * 2
    y0 = margin - chip_h * 0.35
    draw.rounded_rectangle(
        [x0, y0, x1, y0 + chip_h],
        radius=chip_h / 2,
        fill=(245, 245, 245, 26),
        outline=(255, 255, 255, 60),
        width=1,
    )
    draw.text(
        (x0 + padding, y0 + chip_h * 0.5),
        chip_text,
        font=chip_font,
        fill=(196, 202, 214),
        anchor="lm",
    )

    canvas.save(out_path, "PNG")
    return out_path


# ---------------------------------------------------------------------------
# Motion rendering
# ---------------------------------------------------------------------------

def _camera_filter(preset: str, frames: int, width: int, height: int) -> str:
    """FFmpeg zoompan filter producing eased camera motion on a still."""
    frames = max(2, frames)
    t = f"(on/{frames - 1})"  # 0 -> 1 across the clip
    cx = "iw/2-(iw/zoom/2)"
    cy = "ih/2-(ih/zoom/2)"

    if preset == "zoom_in":
        z, x, y = f"1+0.16*{t}", cx, cy
    elif preset == "zoom_out":
        z, x, y = f"1.16-0.16*{t}", cx, cy
    elif preset == "pan_left":
        z, x, y = "1.14", f"(iw-iw/zoom)*(1-{t})", cy
    elif preset == "pan_right":
        z, x, y = "1.14", f"(iw-iw/zoom)*{t}", cy
    elif preset == "pan_up":
        z, x, y = "1.14", cx, f"(ih-ih/zoom)*(1-{t})"
    elif preset == "static":
        z, x, y = "1.001", cx, cy
    else:  # ken_burns
        z = f"1+0.13*{t}"
        x = f"(iw-iw/zoom)*(0.5+0.18*({t}-0.5))"
        y = f"(ih-ih/zoom)*(0.5+0.12*({t}-0.5))"

    return (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={{fps}},"
        f"setsar=1,format=yuv420p"
    )


def render_motion_video(
    images: Iterable[str | Path],
    out_path: str | Path,
    *,
    preset: str = "ken_burns",
    aspect: str = "16:9",
    total_seconds: float = 6.0,
    fps: int = 30,
    crossfade: float = 0.6,
    workdir: Optional[str | Path] = None,
) -> dict[str, Any]:
    """Render stills into an MP4 with camera motion + cross-fades.

    Returns ``{"output", "duration_seconds", "width", "height", "preset"}``.
    Raises ``RuntimeError`` with ffmpeg's stderr when a stage fails.
    """
    from PIL import Image

    image_paths = [Path(p) for p in images]
    if not image_paths:
        raise RuntimeError("render_motion_video needs at least one image")
    for path in image_paths:
        if not path.exists():
            raise RuntimeError(f"source image not found: {path}")

    width, height = ASPECTS.get(aspect, ASPECTS["16:9"])
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(workdir) if workdir else out_path.parent / ".motion_tmp"
    work.mkdir(parents=True, exist_ok=True)

    count = len(image_paths)
    per = max(1.2, float(total_seconds) / count)
    xf = 0.0 if count == 1 else min(float(crossfade), per * 0.6)
    binary = ffmpeg_bin()

    segments: list[Path] = []
    for index, image_path in enumerate(image_paths):
        segment_seconds = per + (xf if index < count - 1 else 0.0)
        frames = max(2, int(round(segment_seconds * fps)))
        seg = work / f"seg_{index:02d}.mp4"
        vf = _camera_filter(preset, frames, width, height).replace("{fps}", str(fps))
        result = _run(
            [
                binary, "-y", "-loglevel", "error",
                "-loop", "1", "-framerate", str(fps),
                "-t", f"{segment_seconds:.3f}",
                "-i", str(image_path),
                "-vf", vf,
                "-frames:v", str(frames),
                "-c:v", "libx264", "-crf", "19", "-preset", "veryfast",
                "-pix_fmt", "yuv420p",
                str(seg),
            ]
        )
        if result.returncode != 0 or not seg.exists():
            raise RuntimeError(f"motion segment {index} failed: {result.stderr.strip()[:800]}")
        segments.append(seg)

    if len(segments) == 1:
        result = _run([binary, "-y", "-loglevel", "error", "-i", str(segments[0]),
                       "-c", "copy", "-movflags", "+faststart", str(out_path)])
        if result.returncode != 0 or not out_path.exists():
            raise RuntimeError(f"mux failed: {result.stderr.strip()[:800]}")
    else:
        inputs: list[str] = []
        for seg in segments:
            inputs += ["-i", str(seg)]
        parts = []
        prev = "[0:v]"
        for i in range(1, len(segments)):
            offset = per * i
            label = f"[v{i}]"
            parts.append(
                f"{prev}[{i}:v]xfade=transition=fade:duration={xf:.3f}:"
                f"offset={offset:.3f}{label}"
            )
            prev = label
        filter_complex = ";".join(parts)
        result = _run(
            [binary, "-y", "-loglevel", "error", *inputs,
             "-filter_complex", filter_complex, "-map", prev,
             "-c:v", "libx264", "-crf", "19", "-preset", "veryfast",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
        )
        if result.returncode != 0 or not out_path.exists():
            # Fallback: plain concat, no cross-fade (still valid output).
            list_file = work / "concat.txt"
            list_file.write_text(
                "".join(f"file '{seg.as_posix()}'\n" for seg in segments), encoding="utf-8"
            )
            result = _run(
                [binary, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                 "-i", str(list_file), "-c:v", "libx264", "-crf", "19",
                 "-preset", "veryfast", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", str(out_path)]
            )
            if result.returncode != 0 or not out_path.exists():
                raise RuntimeError(f"cross-fade failed: {result.stderr.strip()[:800]}")

    try:
        for seg in segments:
            seg.unlink(missing_ok=True)
    except Exception:
        pass

    return {
        "output": str(out_path),
        "duration_seconds": round(per * count, 2),
        "width": width,
        "height": height,
        "preset": preset,
        "fps": fps,
    }


def probe(path: str | Path) -> dict[str, Any]:
    """Minimal media probe (ffmpeg only; no ffprobe dependency)."""
    binary = ffmpeg_bin()
    result = _run([binary, "-hide_banner", "-i", str(path)], timeout=60)
    text = (result.stderr or "") + (result.stdout or "")
    info: dict[str, Any] = {"path": str(path)}
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if match:
        hours, minutes, seconds = match.groups()
        info["duration_seconds"] = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", text)
    if match:
        info["width"], info["height"] = int(match.group(1)), int(match.group(2))
    match = re.search(r"(\d+(?:\.\d+)?)\s*fps", text)
    if match:
        info["fps"] = float(match.group(1))
    info["has_video"] = "Video:" in text
    info["has_audio"] = "Audio:" in text
    match = re.search(r"bitrate:\s*(\d+)\s*kb/s", text)
    if match:
        info["bitrate_kbps"] = int(match.group(1))
    return info


def poster_frame(video_path: str | Path, out_path: str | Path, at: float = 0.6) -> Optional[Path]:
    """Grab a JPEG frame for the gallery."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = _run(
        [ffmpeg_bin(), "-y", "-loglevel", "error", "-ss", f"{at:.2f}",
         "-i", str(video_path), "-frames:v", "1",
         "-vf", "scale=720:-2", "-q:v", "3", str(out_path)]
    )
    return out_path if result.returncode == 0 and out_path.exists() else None


def image_size(path: str | Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as img:
        return img.size
