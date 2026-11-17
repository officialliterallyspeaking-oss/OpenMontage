"""Timeline interchange — hand the edit to a real NLE.

Every pipeline here ends in a rendered MP4, and that is the wrong end of the
job for anyone who wants to *finish* a piece: recut a beat, swap a take, fix a
line of copy, or grade it properly. Today the only way to keep the work is to
rebuild it by hand in an editor, because the timeline only exists inside the
renderer.

This tool writes that timeline back out in the three formats an editor will
open without a plugin:

* ``xmeml`` v4 (Final Cut Pro 7 XML) — imported by **Premiere Pro**
  (File > Import) and **DaVinci Resolve** (File > Import > Timeline).
* ``fcpxml`` 1.10 — **Final Cut Pro X**.  ``.fcpxml`` is the extension FCP
  opens (``.xml`` of the same document is treated as FCP7 XML).
* ``edl`` CMX 3600 — the lowest common denominator, readable by everything,
  including Avid and older grading suites.

The part that actually matters is frame arithmetic. Editors treat a timeline as
a table of integer frames, so a clip that starts at 1.999 s and a neighbour that
ends at 2.001 s do not touch: you get a one-frame hole, and a 15-shot piece
looks like it is full of mistakes. Every boundary here is computed once, as
``round(seconds * fps)``, and the *next* clip starts on the previous clip's end
— so consecutive shots share one number and a gap is impossible unless the
timeline genuinely left one.

Gaps are not silently closed either. If the caller leaves 0.4 s between two
shots, that 0.4 s is written as an explicit gap item rather than absorbed, so
what the editor shows is what was asked for.

Nothing here touches the network or needs a licence: it is XML and text.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import quote

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)

# Frame rates an editor treats as "NTSC" — 1000/1001 pulldown, which means the
# timecode has to drop frame numbers to stay in sync with wall clock.
NTSC_RATES = {23.976: 24, 29.97: 30, 47.952: 48, 59.94: 60}


def _frames(seconds: float, fps: float) -> int:
    """Seconds to an absolute frame index.

    Rounding (not truncating) is the whole point: two shots that meet at 2.0 s
    both resolve to frame 60 at 30 fps, so the cut is shared rather than
    doubled or lost.
    """
    # half-up, not Python's banker's rounding: round(112.5) is 112 in Python,
    # which would make a 3.75 s timeline end on frame 112 while the same
    # boundary computed from the other side could land on 113.
    return int(math.floor(max(0.0, float(seconds)) * float(fps) + 0.5))


def _twos(value: int) -> str:
    return f"{int(value):02d}"


def timecode(total_frames: int, fps: float, *, drop_frame: bool = False) -> str:
    """Frame count to HH:MM:SS:FF, drop-frame when the rate is a 1000/1001 rate.

    Drop-frame exists because 29.97 fps is not 30: a label that counts every
    frame drifts a frame every ~33 s. DF labels skip ;00 and ;01 at the top of
    each minute except every tenth, so a 10-minute block holds 17982 frames
    (1800 + 9 * 1798) and an hour holds exactly 107892 — which is also
    29.97 * 3600, so label and clock agree. Editors print ``;`` before the
    frame field to mark it.
    """
    nominal = int(round(fps)) if fps not in NTSC_RATES else NTSC_RATES[fps]
    frames = int(total_frames)

    if drop_frame and nominal in (30, 60):
        drop = round(fps * 0.066666)  # 2 at 29.97, 4 at 59.94
        frames_per_minute = nominal * 60 - drop
        frames_per_ten = int(round(fps * 600))
        tens, rest = divmod(frames, frames_per_ten)
        # the first minute of every ten keeps all of its labels
        if rest > drop:
            frames += drop * 9 * tens + drop * ((rest - drop) // frames_per_minute)
        else:
            frames += drop * 9 * tens
        sep = ";"
    else:
        sep = ":"

    ff = frames % nominal
    ss = (frames // nominal) % 60
    mm = (frames // (nominal * 60)) % 60
    hh = frames // (nominal * 3600)
    return f"{_twos(hh)}:{_twos(mm)}:{_twos(ss)}{sep}{_twos(ff)}"


def _is_ntsc(fps: float) -> bool:
    return any(abs(float(fps) - r) < 0.01 for r in NTSC_RATES)


def _file_url(path: Path) -> str:
    """A file:// URL an NLE will accept, with spaces and # escaped."""
    return "file://" + quote(str(path.resolve()), safe="/")


def _xml_escape(value: Any) -> str:
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@dataclass
class Clip:
    """One picture (or sound) clip on the timeline, already frame-quantised."""

    name: str
    path: Optional[Path]
    start_f: int
    end_f: int
    source_in_f: int = 0
    track: int = 0
    enabled: bool = True
    kind: str = "video"  # video | audio
    role: str = "footage"  # footage | voice | music | sfx
    rate: float = 30.0

    @property
    def duration_f(self) -> int:
        return max(1, self.end_f - self.start_f)


@dataclass
class Timeline:
    title: str
    fps: float
    width: int
    height: int
    clips: list[Clip] = field(default_factory=list)
    gaps: list[dict[str, int]] = field(default_factory=list)

    @property
    def frames(self) -> int:
        if not self.clips:
            return 0
        return max(c.end_f for c in self.clips)

    @property
    def seconds(self) -> float:
        return self.frames / float(self.fps) if self.fps else 0.0

    def video_clips(self) -> list[Clip]:
        return [c for c in self.clips if c.kind == "video"]

    def audio_clips(self) -> list[Clip]:
        return [c for c in self.clips if c.kind == "audio"]


# --------------------------------------------------------------------------- #
# Building the timeline
# --------------------------------------------------------------------------- #


def build_timeline(
    scenes: Iterable[dict[str, Any]],
    *,
    title: str,
    fps: float = 30.0,
    width: int = 1080,
    height: int = 1920,
    audio: Optional[Iterable[dict[str, Any]]] = None,
) -> Timeline:
    """Quantise a scene list into integer frames, closing nothing.

    Each scene may carry ``start_seconds``/``end_seconds`` or just
    ``duration_seconds``; with only durations the clock is accumulated. When a
    scene's start is later than the running end, that hole is recorded as a gap
    instead of being quietly absorbed.
    """
    fps = float(fps)
    clips: list[Clip] = []
    gaps: list[dict[str, int]] = []
    cursor = 0.0

    for index, scene in enumerate(scenes):
        if scene.get("start_seconds") is not None:
            start_s = float(scene["start_seconds"])
        else:
            start_s = cursor
        if scene.get("end_seconds") is not None:
            end_s = float(scene["end_seconds"])
        else:
            end_s = start_s + float(scene.get("duration_seconds") or 0)

        start_f = _frames(start_s, fps)
        end_f = _frames(end_s, fps)
        if end_f <= start_f:
            # a zero-length clip cannot be placed; give it one frame rather than
            # emitting something an editor will reject
            end_f = start_f + 1

        if start_f > _frames(cursor, fps):
            gaps.append({"start_f": _frames(cursor, fps), "end_f": start_f})

        path = scene.get("asset_path") or scene.get("path")
        clips.append(
            Clip(
                name=str(
                    scene.get("name")
                    or scene.get("id")
                    or (Path(path).stem if path else f"shot_{index + 1:02d}")
                ),
                path=Path(path) if path else None,
                start_f=start_f,
                end_f=end_f,
                source_in_f=_frames(float(scene.get("source_in_seconds") or 0), fps),
                track=int(scene.get("track") or 0),
                enabled=bool(scene.get("enabled", True)),
                kind="video",
                role=str(scene.get("role") or "footage"),
                rate=fps,
            )
        )
        cursor = max(cursor, end_s)

    # Sound: an explicit list, or the picture takes its own audio
    audio_list = list(audio or [])
    for index, item in enumerate(audio_list):
        start_s = float(item.get("start_seconds") or 0.0)
        end_s = float(item.get("end_seconds") or (start_s + float(item.get("duration_seconds") or 0)))
        start_f, end_f = _frames(start_s, fps), _frames(end_s, fps)
        if end_f <= start_f:
            end_f = start_f + 1
        path = item.get("asset_path") or item.get("path")
        clips.append(
            Clip(
                name=str(
                    item.get("name")
                    or item.get("id")
                    or (Path(path).stem if path else f"audio_{index + 1:02d}")
                ),
                path=Path(path) if path else None,
                start_f=start_f,
                end_f=end_f,
                source_in_f=_frames(float(item.get("source_in_seconds") or 0), fps),
                track=int(item.get("track") or 0),
                enabled=bool(item.get("enabled", True)),
                kind="audio",
                role=str(item.get("role") or "music"),
                rate=fps,
            )
        )

    return Timeline(title=title, fps=fps, width=int(width), height=int(height),
                    clips=clips, gaps=gaps)


def audit(timeline: Timeline) -> dict[str, Any]:
    """Prove the placement before writing it.

    Returns the facts a person can check without opening an editor: total
    frames, whether the picture is continuous, any hole, and any overlap. An
    overlap is legitimate (a dissolve) but must be deliberate, so it is
    reported rather than merged.
    """
    video = sorted(timeline.video_clips(), key=lambda c: (c.track, c.start_f))
    holes: list[dict[str, Any]] = []
    overlaps: list[dict[str, Any]] = []

    by_track: dict[int, list[Clip]] = {}
    for clip in video:
        by_track.setdefault(clip.track, []).append(clip)

    for track, clips in by_track.items():
        previous_end: Optional[int] = None
        for clip in clips:
            if previous_end is not None:
                if clip.start_f > previous_end:
                    holes.append({"track": track, "from_f": previous_end, "to_f": clip.start_f})
                elif clip.start_f < previous_end:
                    overlaps.append({"track": track, "at_f": clip.start_f,
                                     "frames": previous_end - clip.start_f})
            previous_end = max(previous_end or 0, clip.end_f)

    coverage = sum(c.duration_f for c in video)
    return {
        "fps": timeline.fps,
        "frames": timeline.frames,
        "seconds": round(timeline.seconds, 3),
        "duration_timecode": timecode(timeline.frames, timeline.fps,
                                      drop_frame=_is_ntsc(timeline.fps)),
        "clips": len(video),
        "audio_clips": len(timeline.audio_clips()),
        "tracks": len(by_track),
        "picture_frames": coverage,
        "continuous": not holes,
        "holes": holes,
        "overlaps": overlaps,
        "disabled_clips": sum(1 for c in video if not c.enabled),
        "gaps_written": len(timeline.gaps),
    }


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #


def write_xmeml(timeline: Timeline) -> str:
    """Final Cut Pro 7 XML (xmeml v4) — Premiere Pro and Resolve both import it."""
    root = ET.Element("xmeml", {"version": "4"})
    seq = ET.SubElement(root, "sequence", {"id": "sequence-1"})
    ET.SubElement(seq, "name").text = timeline.title
    ET.SubElement(seq, "duration").text = str(timeline.frames)

    rate = ET.SubElement(seq, "rate")
    ET.SubElement(rate, "timebase").text = str(int(round(timeline.fps)))
    ET.SubElement(rate, "ntsc").text = "TRUE" if _is_ntsc(timeline.fps) else "FALSE"

    media = ET.SubElement(seq, "media")
    video = ET.SubElement(media, "video")
    fmt = ET.SubElement(video, "format")
    sc = ET.SubElement(fmt, "samplecharacteristics")
    vrate = ET.SubElement(sc, "rate")
    ET.SubElement(vrate, "timebase").text = str(int(round(timeline.fps)))
    ET.SubElement(vrate, "ntsc").text = "TRUE" if _is_ntsc(timeline.fps) else "FALSE"
    ET.SubElement(sc, "width").text = str(timeline.width)
    ET.SubElement(sc, "height").text = str(timeline.height)
    ET.SubElement(sc, "anamorphic").text = "FALSE"
    ET.SubElement(sc, "pixelaspectratio").text = "square"
    ET.SubElement(sc, "fielddominance").text = "none"

    # xmeml stacks V1 at the bottom. Track 0 is our base track, so it is
    # written first; a caller's track 1 lands above it, which matches the way
    # the timeline is described to us (higher track = on top).
    for track_index in sorted({c.track for c in timeline.video_clips()}):
        track = ET.SubElement(video, "track")
        for clip in sorted((c for c in timeline.video_clips() if c.track == track_index),
                           key=lambda c: c.start_f):
            _xmeml_clipitem(track, clip, timeline, index=len(track), kind="video")

    audio_clips = timeline.audio_clips()
    if audio_clips:
        audio = ET.SubElement(media, "audio")
        ET.SubElement(audio, "numOutputChannels").text = "2"
        afmt = ET.SubElement(audio, "format")
        asc = ET.SubElement(afmt, "samplecharacteristics")
        ET.SubElement(asc, "depth").text = "16"
        ET.SubElement(asc, "samplerate").text = "48000"
        for track_index in sorted({c.track for c in audio_clips}):
            track = ET.SubElement(audio, "track")
            for clip in sorted((c for c in audio_clips if c.track == track_index),
                               key=lambda c: c.start_f):
                _xmeml_clipitem(track, clip, timeline, index=len(track), kind="audio")

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(
        root, encoding="unicode"
    )


def _xmeml_clipitem(track: ET.Element, clip: Clip, timeline: Timeline, *, index: int, kind: str) -> None:
    tag = "clipitem" if clip.path or kind == "video" else "clipitem"
    item = ET.SubElement(track, tag, {"id": f"{kind}-item-{index}-{clip.start_f}"})
    ET.SubElement(item, "name").text = clip.name
    ET.SubElement(item, "duration").text = str(clip.duration_f)
    rate = ET.SubElement(item, "rate")
    ET.SubElement(rate, "timebase").text = str(int(round(clip.rate)))
    ET.SubElement(rate, "ntsc").text = "TRUE" if _is_ntsc(clip.rate) else "FALSE"
    ET.SubElement(item, "start").text = str(clip.start_f)
    ET.SubElement(item, "end").text = str(clip.end_f)
    ET.SubElement(item, "in").text = str(clip.source_in_f)
    ET.SubElement(item, "out").text = str(clip.source_in_f + clip.duration_f)

    if clip.path:
        file_el = ET.SubElement(item, "file", {"id": f"file-{index}-{clip.start_f}"})
        ET.SubElement(file_el, "name").text = clip.path.name
        if clip.kind == "audio":
            ET.SubElement(file_el, "pathurl").text = _file_url(clip.path)
        else:
            ET.SubElement(file_el, "pathurl").text = _file_url(clip.path)
        frate = ET.SubElement(file_el, "rate")
        ET.SubElement(frate, "timebase").text = str(int(round(clip.rate)))
        ET.SubElement(frate, "ntsc").text = "TRUE" if _is_ntsc(clip.rate) else "FALSE"
        ET.SubElement(file_el, "duration").text = str(clip.duration_f)
        fmedia = ET.SubElement(file_el, "media")
        if clip.kind == "video":
            fvideo = ET.SubElement(fmedia, "video")
            fsc = ET.SubElement(fvideo, "samplecharacteristics")
            ET.SubElement(fsc, "width").text = str(timeline.width)
            ET.SubElement(fsc, "height").text = str(timeline.height)
            ET.SubElement(fsc, "anamorphic").text = "FALSE"
            ET.SubElement(fsc, "pixelaspectratio").text = "square"
            ET.SubElement(fsc, "fielddominance").text = "none"
        else:
            faudio = ET.SubElement(fmedia, "audio")
            fasc = ET.SubElement(faudio, "samplecharacteristics")
            ET.SubElement(fasc, "depth").text = "16"
            ET.SubElement(fasc, "samplerate").text = "48000"
            ET.SubElement(faudio, "channelcount").text = "2"

    if not clip.enabled:
        # A hidden track in the source keeps its clips, disabled — one click
        # from returning, rather than missing and needing to be rebuilt.
        ET.SubElement(item, "enabled").text = "FALSE"


def write_fcpxml(timeline: Timeline) -> str:
    """FCPXML 1.10 for Final Cut Pro X."""
    fps = float(timeline.fps)
    nominal = int(round(fps)) if fps not in NTSC_RATES else NTSC_RATES[fps]
    ntsc = _is_ntsc(fps)
    # FCP stores "rational" times: numerator/denominator with an "s" suffix.
    denom = int(round(fps * 1001)) if ntsc else nominal
    num = 1001 if ntsc else 1

    def t(frames: int) -> str:
        return f"{(int(frames) * num)}/{denom}s"

    root = ET.Element("fcpxml", {"version": "1.10"})
    resources = ET.SubElement(root, "resources")
    # The format id FCP itself uses for this frame size and rate.
    format_name = f"FFVideoFormat{timeline.height}p{nominal}"
    ET.SubElement(
        resources,
        "format",
        {
            "id": "r1",
            "name": format_name if timeline.width < timeline.height else f"FFVideoFormat{timeline.width}x{timeline.height}p{nominal}",
            "frameDuration": f"{num}/{denom}s",
            "width": str(timeline.width),
            "height": str(timeline.height),
        },
    )

    asset_ids: dict[str, str] = {}
    for index, clip in enumerate(timeline.clips):
        if not clip.path:
            continue
        key = str(clip.path)
        if key in asset_ids:
            continue
        asset_id = f"r{len(asset_ids) + 2}"
        asset_ids[key] = asset_id
        has_video = "1" if clip.kind == "video" else "0"
        has_audio = "1" if clip.kind == "audio" else "0"
        asset = ET.SubElement(
            resources,
            "asset",
            {
                "id": asset_id,
                "name": clip.path.stem,
                "start": "0/1s",
                "duration": t(clip.duration_f),
                "hasVideo": has_video,
                "hasAudio": has_audio,
            },
        )
        if has_video == "1":
            asset.set("format", "r1")
        ET.SubElement(asset, "media-rep", {"kind": "original-media", "src": _file_url(clip.path)})

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", {"name": timeline.title})
    project = ET.SubElement(event, "project", {"name": timeline.title})
    sequence = ET.SubElement(
        project,
        "sequence",
        {
            "format": "r1",
            "duration": t(timeline.frames),
            "tcStart": "0/1s",
            "tcFormat": "DF" if ntsc else "NDF",
            "audioLayout": "stereo",
            "audioRate": "48k",
        },
    )
    spine = ET.SubElement(sequence, "spine")

    for track_index in sorted({c.track for c in timeline.video_clips()}):
        parent = spine if track_index == 0 else ET.SubElement(spine, "spine")
        cursor = 0
        for clip in sorted((c for c in timeline.video_clips() if c.track == track_index),
                           key=lambda c: c.start_f):
            if clip.start_f > cursor:
                ET.SubElement(parent, "gap", {"offset": t(cursor), "start": "0/1s",
                                              "duration": t(clip.start_f - cursor)})
            if clip.path and str(clip.path) in asset_ids:
                attrs = {
                    "ref": asset_ids[str(clip.path)],
                    "offset": t(clip.start_f),
                    "start": t(clip.source_in_f),
                    "duration": t(clip.duration_f),
                    "name": clip.name,
                }
                if not clip.enabled:
                    attrs["enabled"] = "0"
                ET.SubElement(parent, "asset-clip", attrs)
            else:
                attrs = {"offset": t(clip.start_f), "start": "0/1s",
                         "duration": t(clip.duration_f), "name": clip.name}
                if not clip.enabled:
                    attrs["enabled"] = "0"
                ET.SubElement(parent, "gap", attrs)
            cursor = clip.end_f

    # Sound lives in its own connected lanes in FCP.
    for lane, role in enumerate(sorted({c.role for c in timeline.audio_clips()}), start=-1):
        for clip in sorted((c for c in timeline.audio_clips() if c.role == role),
                           key=lambda c: c.start_f):
            if clip.path and str(clip.path) in asset_ids:
                attrs = {
                    "ref": asset_ids[str(clip.path)],
                    "lane": str(lane),
                    "offset": t(clip.start_f),
                    "start": t(clip.source_in_f),
                    "duration": t(clip.duration_f),
                    "name": clip.name,
                }
                if not clip.enabled:
                    attrs["enabled"] = "0"
                ET.SubElement(spine, "asset-clip", attrs)

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(
        root, encoding="unicode"
    )


def write_edl(timeline: Timeline) -> str:
    """CMX 3600 EDL — the format every conform suite can still read."""
    fps = float(timeline.fps)
    ntsc = _is_ntsc(fps)
    lines = [
        f"TITLE: {timeline.title[:70]}",
        "FCM: " + ("DROP FRAME" if ntsc else "NON-DROP FRAME"),
        "",
    ]
    record_cursor = 0
    number = 1
    for clip in sorted(timeline.video_clips(), key=lambda c: (c.track, c.start_f)):
        # A gap becomes a black event so the EDL's record timecode stays honest.
        if clip.start_f > record_cursor:
            lines.append(
                f"{number:03d}  BL       V     C        "
                f"{timecode(0, fps, drop_frame=ntsc)} "
                f"{timecode(clip.start_f - record_cursor, fps, drop_frame=ntsc)} "
                f"{timecode(record_cursor, fps, drop_frame=ntsc)} "
                f"{timecode(clip.start_f, fps, drop_frame=ntsc)}"
            )
            lines.append("* FROM CLIP NAME: BLACK")
            lines.append("")
            number += 1

        reel = (clip.name.upper()[:8] or "AX").ljust(8)
        src_in = timecode(clip.source_in_f, fps, drop_frame=ntsc)
        src_out = timecode(clip.source_in_f + clip.duration_f, fps, drop_frame=ntsc)
        rec_in = timecode(clip.start_f, fps, drop_frame=ntsc)
        rec_out = timecode(clip.end_f, fps, drop_frame=ntsc)
        lines.append(f"{number:03d}  {reel} V     C        {src_in} {src_out} {rec_in} {rec_out}")
        if clip.path:
            lines.append(f"* FROM CLIP NAME: {clip.path.name}")
        else:
            lines.append(f"* FROM CLIP NAME: {clip.name}")
        if not clip.enabled:
            lines.append("* DISABLED")
        lines.append("")
        record_cursor = clip.end_f
        number += 1

    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# The tool
# --------------------------------------------------------------------------- #


class TimelineExport(BaseTool):
    name = "export_timeline"
    version = "0.1.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "local"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = []
    install_instructions = (
        "No setup required — writes FCP7 XML, FCPXML and CMX 3600 EDL with the "
        "Python standard library."
    )
    agent_skills = []

    capabilities = ["export_nle_timeline", "export_edl"]
    supports = {"local_offline": True, "free": True, "uploads": False}
    best_for = [
        "handing a finished cut to Premiere Pro, DaVinci Resolve or Final Cut Pro",
        "letting a human recut, regrade or fix copy without rebuilding the edit",
        "delivering a conform-ready EDL alongside the render",
    ]
    not_good_for = [
        "burning in captions or effects (those live in the render, not the timeline)",
        "replacing the final MP4 — the timeline references source clips, not the render",
    ]

    input_schema = {
        "type": "object",
        "required": ["scenes", "title", "out_dir"],
        "properties": {
            "scenes": {
                "type": "array",
                "description": "Picture, in order. {asset_path, start_seconds|duration_seconds, "
                               "end_seconds?, source_in_seconds?, name?, track?, enabled?}",
                "items": {"type": "object"},
            },
            "title": {"type": "string", "description": "Sequence name shown in the editor."},
            "out_dir": {"type": "string", "description": "Directory to write the timelines into."},
            "fps": {"type": "number", "description": "Timeline frame rate. Default 30."},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "formats": {
                "type": "array",
                "items": {"type": "string", "enum": ["xmeml", "fcpxml", "edl"]},
                "description": "Which interchange formats to write. Default: all three.",
            },
            "audio": {
                "type": "array",
                "description": "Optional sound: {asset_path, start_seconds, end_seconds, role, name}",
                "items": {"type": "object"},
            },
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "files_written": {"type": "array", "items": {"type": "string"}},
            "timeline": {"type": "object"},
            "checks": {"type": "object"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=64, vram_mb=0, disk_mb=0,
                                       network_required=False)
    side_effects = ["writes .xml / .fcpxml / .edl timeline files to disk"]
    user_visible_verification = [
        "Import timeline.xml into Premiere Pro or DaVinci Resolve and confirm the "
        "cuts land on the same frames as the render",
    ]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        scenes = inputs.get("scenes") or []
        if not scenes:
            return ToolResult(success=False, error="scenes must contain at least one clip")

        fps = float(inputs.get("fps") or 30)
        if fps <= 0:
            return ToolResult(success=False, error="fps must be positive")

        out_dir = Path(inputs["out_dir"]).expanduser()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return ToolResult(success=False, error=f"cannot create out_dir: {exc}")

        # A missing source file is not fatal — the caller may be exporting a
        # plan — but it is worth naming, because the editor will show offline
        # media and that is confusing if nobody said so.
        missing: list[str] = []
        for scene in scenes:
            path = scene.get("asset_path") or scene.get("path")
            if path and not Path(path).expanduser().is_file():
                missing.append(str(path))

        timeline = build_timeline(
            scenes,
            title=str(inputs["title"]),
            fps=fps,
            width=int(inputs.get("width") or 1080),
            height=int(inputs.get("height") or 1920),
            audio=inputs.get("audio"),
        )
        checks = audit(timeline)
        if missing:
            checks["missing_media"] = missing

        requested = inputs.get("formats") or ["xmeml", "fcpxml", "edl"]
        # (filename, writer, who opens it). The manifest names files by the app
        # that opens them, not by the spec: a person looking for "the Premiere
        # file" should not have to know that Premiere reads FCP7 XML.
        writers = {
            "xmeml": ("timeline.xml", write_xmeml, "premiere_resolve"),
            "fcpxml": ("timeline.fcpxml", write_fcpxml, "final_cut"),
            "edl": ("timeline.edl", write_edl, "edl"),
        }

        files_written: list[str] = []
        written_formats: dict[str, str] = {}
        for kind in requested:
            if kind not in writers:
                return ToolResult(success=False, error=f"unknown format: {kind}")
            filename, writer, opener = writers[kind]
            target = out_dir / filename
            try:
                target.write_text(writer(timeline), encoding="utf-8")
            except OSError as exc:
                return ToolResult(success=False, error=f"could not write {filename}: {exc}")
            files_written.append(str(target))
            # Relative on purpose: the manifest is served to a browser, and an
            # absolute path is both useless to the browser and an unnecessary
            # disclosure of the server's filesystem layout.
            written_formats[opener] = filename

        # A small machine-readable summary, so an agent or the UI can show the
        # numbers without parsing XML.
        manifest = out_dir / "timeline.json"
        manifest.write_text(
            json.dumps(
                {
                    "title": timeline.title,
                    "fps": timeline.fps,
                    "width": timeline.width,
                    "height": timeline.height,
                    "checks": checks,
                    "formats": written_formats,
                    "clips": [
                        {
                            "name": c.name,
                            "start_f": c.start_f,
                            "end_f": c.end_f,
                            "duration_f": c.duration_f,
                            "kind": c.kind,
                            "role": c.role,
                            "enabled": c.enabled,
                            "path": str(c.path) if c.path else None,
                        }
                        for c in timeline.clips
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        files_written.append(str(manifest))

        return ToolResult(
            success=True,
            artifacts=files_written,
            data={
                "files_written": files_written,
                "formats": written_formats,
                "timeline": {
                    "title": timeline.title,
                    "fps": timeline.fps,
                    "resolution": f"{timeline.width}x{timeline.height}",
                    "frames": timeline.frames,
                    "seconds": round(timeline.seconds, 3),
                    "clips": len(timeline.video_clips()),
                    "audio_clips": len(timeline.audio_clips()),
                },
                "checks": checks,
            },
        )
