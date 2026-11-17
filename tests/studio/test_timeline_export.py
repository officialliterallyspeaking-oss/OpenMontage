"""Tests for the NLE timeline export.

The point of this feature is that an editor opens the file and finds the same
cut that was rendered. Everything here is about the arithmetic that makes that
true — frame quantisation, contiguous boundaries, drop-frame timecode, and
gaps that stay gaps.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.publishers import timeline_export as te  # noqa: E402


def _clip(tmp_path: Path, name: str, seconds: float) -> Path:
    """A tiny real file, so the export is not referring to nothing."""
    path = tmp_path / f"{name}.mp4"
    path.write_bytes(b"\x00" * 16)
    return path


def _scenes(tmp_path: Path, durations: list[float]) -> list[dict]:
    scenes = []
    clock = 0.0
    for index, duration in enumerate(durations):
        scenes.append(
            {
                "id": f"shot_{index + 1:02d}",
                "asset_path": str(_clip(tmp_path, f"shot_{index + 1:02d}", duration)),
                "start_seconds": clock,
                "end_seconds": clock + duration,
            }
        )
        clock += duration
    return scenes


# --------------------------------------------------------------------------- #
# Frame arithmetic
# --------------------------------------------------------------------------- #


def test_consecutive_clips_share_a_frame_boundary(tmp_path: Path) -> None:
    """The bug this prevents: a one-frame hole at every cut.

    0.1 + 0.2 in floats is 0.30000000000000004, so a naive round of the *end*
    of one shot and the *start* of the next can disagree by a frame. Here the
    starts are derived from one accumulating clock, so they cannot.
    """
    durations = [0.1, 0.2, 0.1, 0.2, 0.1, 0.2]
    timeline = te.build_timeline(_scenes(tmp_path, durations), title="t", fps=30)
    checks = te.audit(timeline)

    assert checks["continuous"] is True
    assert checks["holes"] == []
    assert checks["clips"] == 6

    ordered = sorted(timeline.video_clips(), key=lambda c: c.start_f)
    for previous, following in zip(ordered, ordered[1:]):
        assert following.start_f == previous.end_f


def test_total_frames_match_the_requested_duration(tmp_path: Path) -> None:
    timeline = te.build_timeline(_scenes(tmp_path, [2.0, 3.0, 1.5]), title="t", fps=30)
    # 6.5 s at 30 fps = 195 frames, and the last clip must end exactly there.
    assert timeline.frames == 195
    assert timeline.seconds == pytest.approx(6.5)


def test_quarter_second_boundaries_do_not_drift(tmp_path: Path) -> None:
    """15 shots of 0.25 s must land on 112.5 -> 113 frames, not 120."""
    timeline = te.build_timeline(_scenes(tmp_path, [0.25] * 15), title="t", fps=30)
    ordered = sorted(timeline.video_clips(), key=lambda c: c.start_f)
    assert ordered[-1].end_f == 113
    # half-up quantisation: every clip is 7 or 8 frames, never 0 and never 15
    assert {c.duration_f for c in ordered} <= {7, 8}
    assert te.audit(timeline)["continuous"] is True


def test_a_real_gap_is_reported_and_not_closed(tmp_path: Path) -> None:
    """A timeline that leaves a hole must not have that hole quietly filled."""
    scenes = _scenes(tmp_path, [1.0])
    scenes.append(
        {
            "asset_path": str(_clip(tmp_path, "late", 1.0)),
            "start_seconds": 1.4,
            "end_seconds": 2.4,
        }
    )
    timeline = te.build_timeline(scenes, title="t", fps=30)
    checks = te.audit(timeline)

    assert checks["continuous"] is False
    assert checks["holes"] == [{"track": 0, "from_f": 30, "to_f": 42}]
    # and the EDL pays for it with a black event
    edl = te.write_edl(timeline)
    assert "FROM CLIP NAME: BLACK" in edl


def test_overlap_is_reported_not_merged(tmp_path: Path) -> None:
    """A deliberate dissolve is legitimate; hiding it from the report is not."""
    scenes = _scenes(tmp_path, [2.0])
    scenes.append(
        {
            "asset_path": str(_clip(tmp_path, "b", 2.0)),
            "start_seconds": 1.8,
            "end_seconds": 3.8,
        }
    )
    timeline = te.build_timeline(scenes, title="t", fps=30)
    checks = te.audit(timeline)
    assert checks["overlaps"] == [{"track": 0, "at_f": 54, "frames": 6}]


# --------------------------------------------------------------------------- #
# Timecode
# --------------------------------------------------------------------------- #


def test_timecode_non_drop() -> None:
    assert te.timecode(0, 30) == "00:00:00:00"
    assert te.timecode(30, 30) == "00:00:01:00"
    assert te.timecode(90, 30) == "00:00:03:00"
    assert te.timecode(30 * 60, 30) == "00:01:00:00"
    assert te.timecode(30 * 3600, 30) == "01:00:00:00"


def test_timecode_drop_frame_skips_the_right_numbers() -> None:
    """29.97 DF drops labels ;00 and ;01 each minute, except every tenth.

    The invariants that matter: the first minute of a ten-minute block keeps
    all 1800 frames (so label 00:01:00;02 is frame 1800), each of the next nine
    minutes is 1798 frames, ten minutes is 17982, and an hour is 107892 — which
    is also 29.97 * 3600, so the label and the clock agree.
    """
    assert te.timecode(0, 29.97, drop_frame=True) == "00:00:00;00"
    assert te.timecode(1800, 29.97, drop_frame=True) == "00:01:00;02"
    # the last frame before the skip
    assert te.timecode(1799, 29.97, drop_frame=True) == "00:00:59;29"
    assert te.timecode(17982, 29.97, drop_frame=True) == "00:10:00;00"
    assert te.timecode(107892, 29.97, drop_frame=True) == "01:00:00;00"


def test_drop_frame_minutes_add_up() -> None:
    """1800 + 9 * 1798 frames must be exactly ten minutes of DF timecode."""
    assert 1800 + 9 * 1798 == 17982
    # minute 2 starts on frame 1800 and runs 1798 frames, so frame 3598 is the
    # first of minute 3 — and it lands on ;02, not ;00, because ;00 and ;01
    # were dropped at the top of the minute
    assert te.timecode(1800 + 1798, 29.97, drop_frame=True) == "00:02:00;02"


def test_ntsc_detection() -> None:
    assert te._is_ntsc(29.97) is True
    assert te._is_ntsc(23.976) is True
    assert te._is_ntsc(30.0) is False
    assert te._is_ntsc(25) is False


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #


def test_xmeml_is_well_formed_and_places_every_clip(tmp_path: Path) -> None:
    timeline = te.build_timeline(_scenes(tmp_path, [1.0, 2.0, 3.0]), title="Kitchen",
                                 fps=30, width=1080, height=1920)
    text = te.write_xmeml(timeline)
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<!DOCTYPE xmeml>" in text

    # strip the DOCTYPE so ElementTree will parse it
    root = ET.fromstring(text.split("\n", 2)[2])
    assert root.get("version") == "4"
    seq = root.find("sequence")
    assert seq.findtext("name") == "Kitchen"
    assert seq.findtext("duration") == "180"

    items = seq.findall("media/video/track/clipitem")
    assert len(items) == 3
    assert [i.findtext("start") for i in items] == ["0", "30", "90"]
    assert [i.findtext("end") for i in items] == ["30", "90", "180"]
    # each file reference points at a real absolute path
    for item in items:
        url = item.findtext("file/pathurl")
        assert url.startswith("file:///")
        assert item.findtext("file/media/video/samplecharacteristics/width") == "1080"


def test_xmeml_escapes_awkward_titles(tmp_path: Path) -> None:
    timeline = te.build_timeline(_scenes(tmp_path, [1.0]), title='Tom & "Jerry" <cut>', fps=30)
    text = te.write_xmeml(timeline)
    root = ET.fromstring(text.split("\n", 2)[2])
    assert root.find("sequence").findtext("name") == 'Tom & "Jerry" <cut>'


def test_fcpxml_is_well_formed_with_a_spine(tmp_path: Path) -> None:
    timeline = te.build_timeline(_scenes(tmp_path, [1.0, 1.0]), title="FCP", fps=30,
                                 width=1080, height=1920)
    text = te.write_fcpxml(timeline)
    root = ET.fromstring(text.split("\n", 2)[2])
    assert root.get("version") == "1.10"
    fmt = root.find("resources/format")
    assert fmt.get("width") == "1080"
    assert fmt.get("frameDuration") == "1/30s"

    spine = root.find("library/event/project/sequence/spine")
    clips = spine.findall("asset-clip")
    assert len(clips) == 2
    assert clips[0].get("offset") == "0/30s"
    assert clips[1].get("offset") == "30/30s"
    assert clips[1].get("duration") == "30/30s"


def test_edl_has_one_record_per_clip(tmp_path: Path) -> None:
    timeline = te.build_timeline(_scenes(tmp_path, [1.0, 2.0]), title="EDL", fps=30)
    edl = te.write_edl(timeline)
    records = [ln for ln in edl.splitlines() if ln[:3].isdigit()]
    assert len(records) == 2
    assert records[0].startswith("001")
    assert "00:00:00:00 00:00:01:00 00:00:00:00 00:00:01:00" in records[0]
    assert records[1].startswith("002")
    assert "00:00:00:00 00:00:02:00 00:00:01:00 00:00:03:00" in records[1]


def test_disabled_clips_survive_as_disabled(tmp_path: Path) -> None:
    """A hidden track is one click from coming back, not a rebuild."""
    scenes = _scenes(tmp_path, [1.0])
    scenes[0]["enabled"] = False
    timeline = te.build_timeline(scenes, title="t", fps=30)
    assert "FALSE" in te.write_xmeml(timeline)
    assert "* DISABLED" in te.write_edl(timeline)
    assert te.audit(timeline)["disabled_clips"] == 1


def test_track_order_is_preserved(tmp_path: Path) -> None:
    scenes = _scenes(tmp_path, [1.0])
    scenes.append(
        {
            "asset_path": str(_clip(tmp_path, "overlay", 1.0)),
            "start_seconds": 0.0,
            "end_seconds": 1.0,
            "track": 1,
        }
    )
    # a clip with no explicit name takes its file name, so the editor shows the
    # same label a person sees on disk
    timeline = te.build_timeline(scenes, title="t", fps=30)
    text = te.write_xmeml(timeline)
    root = ET.fromstring(text.split("\n", 2)[2])
    tracks = root.findall("sequence/media/video/track")
    assert len(tracks) == 2
    # track 0 written first (bottom), overlay above it
    assert tracks[1].find("clipitem/name").text == "overlay"


# --------------------------------------------------------------------------- #
# The tool itself
# --------------------------------------------------------------------------- #


def test_tool_writes_all_three_formats(tmp_path: Path) -> None:
    tool = te.TimelineExport()
    out = tmp_path / "export"
    result = tool.execute(
        {
            "scenes": _scenes(tmp_path, [2.0, 3.0]),
            "title": "Campaign",
            "out_dir": str(out),
            "fps": 30,
            "width": 1080,
            "height": 1920,
        }
    )
    assert result.success, result.error
    for filename in ("timeline.xml", "timeline.fcpxml", "timeline.edl", "timeline.json"):
        assert (out / filename).is_file(), filename
    assert result.data["timeline"]["frames"] == 150
    assert result.data["checks"]["continuous"] is True


def test_the_manifest_names_files_by_the_app_that_opens_them(tmp_path: Path) -> None:
    """The manifest is read by a browser, so it must hold names, not paths.

    An absolute path here leaks the server's layout and gives the UI nothing it
    can turn into a download link; and "xmeml" means nothing to someone looking
    for the Premiere file.
    """
    import json

    tool = te.TimelineExport()
    out = tmp_path / "export"
    result = tool.execute({"scenes": _scenes(tmp_path, [2.0]), "title": "t",
                           "out_dir": str(out)})
    assert result.success, result.error

    manifest = json.loads((out / "timeline.json").read_text())
    assert manifest["formats"] == {
        "premiere_resolve": "timeline.xml",
        "final_cut": "timeline.fcpxml",
        "edl": "timeline.edl",
    }
    for name in manifest["formats"].values():
        assert not Path(name).is_absolute() and (out / name).is_file()


def test_only_the_requested_formats_are_written(tmp_path: Path) -> None:
    tool = te.TimelineExport()
    out = tmp_path / "partial"
    result = tool.execute({"scenes": _scenes(tmp_path, [2.0]), "title": "t",
                           "out_dir": str(out), "formats": ["edl"]})
    assert result.success, result.error
    assert (out / "timeline.edl").is_file()
    assert not (out / "timeline.xml").exists()
    import json
    assert json.loads((out / "timeline.json").read_text())["formats"] == {"edl": "timeline.edl"}


def test_tool_accepts_durations_instead_of_timestamps(tmp_path: Path) -> None:
    tool = te.TimelineExport()
    scenes = [
        {"asset_path": str(_clip(tmp_path, "a", 2.0)), "duration_seconds": 2.0},
        {"asset_path": str(_clip(tmp_path, "b", 2.0)), "duration_seconds": 2.0},
    ]
    result = tool.execute({"scenes": scenes, "title": "t", "out_dir": str(tmp_path / "o"), "fps": 25})
    assert result.success, result.error
    assert result.data["timeline"]["frames"] == 100
    assert result.data["checks"]["continuous"] is True


def test_tool_reports_missing_media_without_failing(tmp_path: Path) -> None:
    tool = te.TimelineExport()
    scenes = [{"asset_path": str(tmp_path / "nope.mp4"), "duration_seconds": 1.0}]
    result = tool.execute({"scenes": scenes, "title": "t", "out_dir": str(tmp_path / "o")})
    assert result.success
    assert result.data["checks"]["missing_media"] == [str(tmp_path / "nope.mp4")]


def test_tool_rejects_empty_timeline(tmp_path: Path) -> None:
    tool = te.TimelineExport()
    result = tool.execute({"scenes": [], "title": "t", "out_dir": str(tmp_path)})
    assert result.success is False


def test_tool_rejects_unknown_format(tmp_path: Path) -> None:
    tool = te.TimelineExport()
    result = tool.execute(
        {
            "scenes": _scenes(tmp_path, [1.0]),
            "title": "t",
            "out_dir": str(tmp_path / "o"),
            "formats": ["aaf"],
        }
    )
    assert result.success is False
    assert "unknown format" in (result.error or "")


def test_audio_lands_on_its_own_track(tmp_path: Path) -> None:
    tool = te.TimelineExport()
    result = tool.execute(
        {
            "scenes": _scenes(tmp_path, [3.0]),
            "title": "t",
            "out_dir": str(tmp_path / "o"),
            "fps": 30,
            "audio": [
                {"asset_path": str(_clip(tmp_path, "music", 3.0)),
                 "start_seconds": 0, "end_seconds": 3.0, "role": "music"}
            ],
        }
    )
    assert result.success, result.error
    assert result.data["timeline"]["audio_clips"] == 1
    root = ET.fromstring((tmp_path / "o" / "timeline.xml").read_text().split("\n", 2)[2])
    audio_tracks = root.findall("sequence/media/audio/track")
    assert len(audio_tracks) == 1
    assert audio_tracks[0].find("clipitem/name").text == "music"
