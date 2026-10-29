"""Timeline assembly with FFmpeg — scenes, transitions and burned captions.

The static FFmpeg build here has no ``drawtext``, but it does have libass, so
captions are authored as a real ASS script (styled, timed, safe-area aware) and
burned with the ``subtitles`` filter. That is the same mechanism a captioning
house would use, and it means captions are a *timeline object* the user can
retime in Advanced Studio rather than a baked-in afterthought.

Pipeline shape (each stage cached by content hash, so a caption change does not
re-render the scenes):

    still + camera move  ->  scene clip (exact duration)
    scene clips + cuts   ->  assembled timeline
    timeline + ASS cues  ->  finished video
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from studio.motion import _camera_filter, _run, ffmpeg_bin, poster_frame, probe

ASPECT_SIZE = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}


def _hash(*parts: object) -> str:
    blob = json.dumps([str(p) for p in parts]).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def scene_clip(
    image: str | Path,
    out: str | Path,
    *,
    seconds: float,
    motion: str = "ken_burns",
    aspect: str = "9:16",
    fps: int = 30,
) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = ASPECT_SIZE.get(aspect, ASPECT_SIZE["9:16"])
    frames = max(6, int(round(seconds * fps)))
    vf = _camera_filter(motion, frames, width, height).replace("{fps}", str(fps))
    result = _run(
        [
            ffmpeg_bin(), "-y", "-loglevel", "error",
            "-loop", "1", "-framerate", str(fps), "-t", f"{seconds:.3f}",
            "-i", str(image),
            "-vf", vf,
            "-frames:v", str(frames),
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", "-r", str(fps),
            str(out),
        ]
    )
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"scene render failed: {result.stderr.strip()[:600]}")
    return out


def assemble(
    clips: Sequence[Path],
    out: Path,
    *,
    transitions: Sequence[str],
    fades: Sequence[float] | None = None,
    fps: int = 30,
    fade: float = 0.28,
) -> Path:
    """Join scene clips with hard cuts or dissolves, preserving exact timing."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    clips = list(clips)
    if not clips:
        raise RuntimeError("nothing to assemble")
    if len(clips) == 1:
        result = _run([ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(clips[0]),
                       "-c", "copy", "-movflags", "+faststart", str(out)])
        if result.returncode != 0:
            raise RuntimeError(f"mux failed: {result.stderr.strip()[:600]}")
        return out

    durations = [float(probe(c).get("duration_seconds") or 0) for c in clips]

    # Hard cuts everywhere -> concat demuxer (fast, frame exact).
    if all(t in {"cut", "whip_cut"} for t in transitions[1:]):
        listing = out.parent / f".concat_{_hash(*clips)}.txt"
        listing.write_text("".join(f"file '{c.resolve()}'\n" for c in clips), encoding="utf-8")
        result = _run([ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                       "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out)])
        try:
            listing.unlink()
        except OSError:
            pass
        if result.returncode != 0 or not out.exists():
            raise RuntimeError(f"concat failed: {result.stderr.strip()[:600]}")
        return out

    # Mixed transitions -> chained xfade. A "cut" is an xfade with a 1-frame
    # duration, which keeps one code path and keeps the maths exact.
    inputs: list[str] = []
    for clip in clips:
        inputs += ["-i", str(clip)]
    filters: list[str] = []
    prev = "[0:v]"
    cumulative = durations[0]
    fade_total = 0.0
    for index in range(1, len(clips)):
        transition = transitions[index] if index < len(transitions) else "dissolve"
        if fades is not None and index < len(fades):
            fade_len = float(fades[index])
        else:
            fade_len = (
                min(0.04, durations[index - 1] * 0.2)
                if transition in {"cut", "whip_cut"}
                else min(fade, durations[index - 1] * 0.45, durations[index] * 0.45)
            )
        # xfade offset is measured on the chained output: every previous
        # transition removed `fade_total` seconds from the timeline.
        start = max(0.0, cumulative - fade_total - fade_len)
        label = f"[v{index}]"
        filters.append(
            f"{prev}[{index}:v]xfade=transition=fade:duration={fade_len:.3f}:offset={start:.3f}{label}"
        )
        prev = label
        cumulative += durations[index]
        fade_total += fade_len
    result = _run(
        [ffmpeg_bin(), "-y", "-loglevel", "error", *inputs,
         "-filter_complex", ";".join(filters),
         "-map", prev, "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", str(out)]
    )
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"xfade assembly failed: {result.stderr.strip()[:600]}")
    return out


# ---------------------------------------------------------------------------
# captions
# ---------------------------------------------------------------------------

def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _ass_colour(hex_colour: str, alpha: int = 0) -> str:
    value = hex_colour.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    r, g, b = value[0:2], value[2:4], value[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def write_ass(
    cues: Sequence[dict[str, Any]],
    out: Path,
    *,
    width: int,
    height: int,
    palette: Sequence[str],
    style: str = "caption",
    kicker: str = "",
) -> Path:
    """Author a styled caption script. Cues are (text, start, end, style)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    from studio.brain.localfx import palette_roles

    roles = palette_roles(list(palette) or ["#0E1117", "#F2F0EA", "#E4572E"])
    ink, accent, ground = roles["ink"], roles["accent"], roles["base"]
    base = min(width, height)

    caption_size = int(base * 0.052) if width < height else int(base * 0.048)
    label_size = int(base * 0.032) if width < height else int(base * 0.028)
    margin_v = int(height * 0.21) if height > width else int(height * 0.11)

    head = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,DejaVu Sans,{caption_size},{_ass_colour(ink)},"
        f"{_ass_colour(ink)},&H00000000,&H64000000,-1,0,0,0,100,100,0.5,0,1,"
        f"{max(3, caption_size // 12)},0,2,{int(width * 0.10)},{int(width * 0.10)},{margin_v},1",
        f"Style: Label,DejaVu Sans,{label_size},{_ass_colour(accent)},"
        f"{_ass_colour(accent)},&H00000000,&H64000000,-1,0,0,0,100,100,2.5,0,1,"
        f"{max(2, label_size // 14)},0,8,{int(width * 0.08)},{int(width * 0.08)},"
        f"{int(height * 0.10)},1",
        f"Style: CTA,DejaVu Sans,{int(caption_size * 0.82)},{_ass_colour(ground)},"
        f"{_ass_colour(ground)},&H00000000,{_ass_colour(accent, 0x00)},-1,0,0,0,100,100,0.5,0,"
        f"3,0,0,2,{int(width * 0.08)},{int(width * 0.08)},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events: list[str] = []
    if kicker:
        events.append(
            f"Dialogue: 0,{_ass_time(0)},{_ass_time(max(c['end_seconds'] for c in cues) if cues else 3)},"
            f"Label,,0,0,0,,{_escape(kicker)}"
        )
    for cue in cues:
        text = _escape(cue.get("text", ""))
        if not text:
            continue
        style_name = cue.get("style") or ("CTA" if cue.get("cta") else "Caption")
        start = cue.get("start_seconds", 0)
        end = cue.get("end_seconds", start + 2)
        # a soft fade on every cue so cuts never look like a glitch
        effect = r"{\fad(120,120)}"
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style_name},,0,0,0,,{effect}{text}"
        )

    out.write_text("\n".join(head + events) + "\n", encoding="utf-8")
    return out


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("\\", "/")
        .replace("{", "(")
        .replace("}", ")")
        .replace("\n", r"\N")
    )


def build_scrim(out: Path, *, width: int, height: int, strength: float = 0.62) -> Path:
    """A bottom gradient that guarantees caption contrast over bright footage.

    The media analysis measures the source's brightness; when a frame is bright
    the grade alone cannot keep white type readable, so a scrim is composited
    underneath the captions. It is derived from the measurement, not applied
    blindly to every video.
    """
    from PIL import Image

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return out
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    band_top = int(height * 0.58)
    pixels = img.load()
    span = max(1, height - band_top)
    for y in range(band_top, height):
        # ease-in curve so there is no visible edge
        t = (y - band_top) / span
        alpha = int(255 * strength * (t ** 1.6))
        for x in range(width):
            pixels[x, y] = (0, 0, 0, alpha)
    img.save(out)
    return out


def burn_captions(src: Path, out: Path, ass_path: Path, scrim: Path | None = None) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # subtitles filter needs an escaped path and a font that exists on disk
    escaped = str(ass_path.resolve()).replace("\\", "/").replace(":", r"\:")
    fonts_dir = Path("/usr/share/fonts")
    subs = f"subtitles='{escaped}'"
    if fonts_dir.is_dir():
        subs += f":fontsdir='{fonts_dir}'"
    if scrim and scrim.exists():
        cmd = [
            ffmpeg_bin(), "-y", "-loglevel", "error",
            "-i", str(src), "-i", str(scrim),
            "-filter_complex", f"[0:v][1:v]overlay=0:0,{subs}",
            "-c:v", "libx264", "-crf", "19", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out),
        ]
    else:
        cmd = [
            ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(src), "-vf", subs,
            "-c:v", "libx264", "-crf", "19", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out),
        ]
    result = _run(cmd)
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"caption burn failed: {result.stderr.strip()[:600]}")
    return out


def render_timeline(
    shots: Sequence[dict[str, Any]],
    out_path: Path,
    *,
    aspect: str = "9:16",
    cues: Sequence[dict[str, Any]] = (),
    palette: Sequence[str] = ("#0E1117", "#F2F0EA", "#E4572E"),
    kicker: str = "",
    workdir: Path | None = None,
    fps: int = 30,
    cache: dict[str, str] | None = None,
    scrim_strength: float = 0.0,
) -> dict[str, Any]:
    """Full render: scene clips -> assembly -> captions. Cached by scene hash."""
    out_path = Path(out_path)
    work = Path(workdir) if workdir else out_path.parent / ".timeline"
    work.mkdir(parents=True, exist_ok=True)
    cache = cache if cache is not None else {}

    clips: list[Path] = []
    # transitions[i] / fades[i] describe the join *into* shot i; fades[0] = 0.
    transitions: list[str] = [(shot.get("transition_in") or "cut") for shot in shots]
    fades: list[float] = [0.0]
    for index in range(1, len(shots)):
        transition = transitions[index]
        fades.append(0.04 if transition in {"cut", "whip_cut"} else 0.28)

    # A dissolve overlaps two shots, so the outgoing clip is rendered *longer*
    # by exactly the overlap. The timeline then keeps the planned duration to
    # the frame and the captions stay where the script put them.

    for index, shot in enumerate(shots):
        image = shot.get("asset_path") or shot.get("image")
        if not image or not Path(image).exists():
            raise RuntimeError(f"scene {shot.get('id')} has no rendered asset")
        extension = fades[index + 1] if index + 1 < len(fades) else 0.0
        clip_seconds = float(shot["duration_seconds"]) + extension
        key = _hash(image, shot.get("movement"), round(clip_seconds, 3), aspect, fps)
        cached = cache.get(key)
        clip = Path(cached) if cached and Path(cached).exists() else work / f"scene_{index:02d}_{key}.mp4"
        if not clip.exists():
            scene_clip(
                image, clip,
                seconds=clip_seconds,
                motion=shot.get("movement") or "ken_burns",
                aspect=aspect, fps=fps,
            )
        cache[key] = str(clip)
        clips.append(clip)

    assembled = work / f"assembled_{_hash(*[c.name for c in clips])}.mp4"
    if not assembled.exists():
        assemble(clips, assembled, transitions=transitions, fades=fades, fps=fps)

    ass_path = work / "captions.ass"
    width, height = ASPECT_SIZE.get(aspect, ASPECT_SIZE["9:16"])
    write_ass(cues, ass_path, width=width, height=height, palette=palette, kicker=kicker)

    if cues:
        scrim_path = None
        if scrim_strength > 0:
            scrim_path = build_scrim(work / "caption_scrim.png", width=width, height=height,
                                     strength=scrim_strength)
        burn_captions(assembled, out_path, ass_path, scrim=scrim_path)
    else:
        assembled.replace(out_path)

    info = probe(out_path)
    poster = poster_frame(out_path, out_path.with_suffix(".jpg"), at=min(1.2, info.get("duration_seconds", 3) / 3))
    return {
        "output": str(out_path),
        "poster": str(poster) if poster else None,
        "duration_seconds": info.get("duration_seconds"),
        "width": info.get("width"),
        "height": info.get("height"),
        "bytes": out_path.stat().st_size,
        "scenes": len(clips),
        "caption_cues": len(cues),
        "scrim": scrim_strength > 0,
        "rendered_at": None,
    }


def write_concat_list(clips: Iterable[Path], path: Path) -> Path:
    path.write_text("".join(f"file '{Path(c).resolve()}'\n" for c in clips), encoding="utf-8")
    return path
