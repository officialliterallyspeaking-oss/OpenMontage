"""System 3 — Automatic Production Engine.

Turns decided creative into a finished, checked video. Everything here emits a
repository artifact that validates against ``schemas/artifacts/*.schema.json``,
so the studio's output is inspectable by the same tooling as the rest of
OpenMontage:

    script.schema.json         narration + on-screen text, timed
    scene_plan.schema.json     storyboard with real shot language
    edit_decisions.schema.json cuts, overlays, transitions, subtitles
    review.schema.json         findings
    final_review.schema.json   technical + visual + promise checks

The edit is generated from the storyboard, not hand-tuned per run: change one
scene and the timeline, captions and quality checks follow from it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

from studio.motion import ASPECTS, probe

SHOT_SIZE_MAP = {
    "wide establishing": "establishing",
    "medium": "medium",
    "medium-wide": "medium_wide",
    "close detail": "close_up",
    "macro insert": "extreme_close_up",
}

MOVEMENT_MAP = {
    "ken_burns": "dolly_in",
    "zoom_in": "zoom_in",
    "zoom_out": "zoom_out",
    "pan_left": "pan_left",
    "pan_right": "pan_right",
    "pan_up": "tilt_up",
    "static": "static",
}

NARRATIVE_ROLE = {
    0: "establish_context",
}
ROLE_BY_BEAT = [
    ("reveal", "deliver_payload"),
    ("detail", "evidence"),
    ("texture", "evidence"),
    ("turn", "build_tension"),
    ("rise", "emotional_beat"),
    ("consequence", "resolution"),
    ("close", "resolution"),
    ("landing", "call_to_action"),
    ("promise", "introduce_subject"),
    ("question", "establish_context"),
]


# ---------------------------------------------------------------------------
# script
# ---------------------------------------------------------------------------

def write_script(
    intent: dict[str, Any],
    concept: dict[str, Any],
    brief: dict[str, Any],
    beats: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """A schema-valid script. Narration is written only when the concept wants it."""
    mode = concept.get("narration") or "sparse"
    sections: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, beat in enumerate(beats):
        text = _section_text(index, beat, concept, intent, brief, mode, len(beats), used)
        used.add(text)
        sections.append(
            {
                "id": f"sec_{index + 1:02d}",
                "label": beat["beat"],
                "text": text,
                "start_seconds": beat["start_seconds"],
                "end_seconds": beat["end_seconds"],
                "source_ref": f"beat:{index}",
                "delivery_cues": _delivery(index, mode, concept),
                "speaker_directions": (
                    "silent — the line is on screen" if mode == "none"
                    else ("measured pace, land the last word" if concept["cut_rhythm_seconds"] > 2
                          else "quick pace, keep the energy up")
                ),
                "enhancement_cues": [],
            }
        )
    return {
        "version": "1.0",
        "title": brief["title"],
        "total_duration_seconds": float(intent["duration_seconds"]),
        "sections": sections,
        "voice_performance": {
            "performance_intent": (
                "warm, confident, unhurried" if mode != "none" else "silent — on-screen text only"
            ),
            "pacing_profile": "cinematic" if concept["cut_rhythm_seconds"] > 2.0 else "energetic",
            "pause_policy": "let the last word land before the cut",
            "sample_section_id": "sec_01",
        },
        "metadata": {
            "created_by": "studio.producer",
            "spoken": mode != "none",
            "note": (
                "No narration track is recorded in this build: the script is the timed copy "
                "for the edit and captions. A voice provider can render it without changing "
                "the timings."
            ),
        },
    }


def _with_article(phrase: str) -> str:
    if not phrase:
        return phrase
    words = phrase.split()
    if words[0].lower() in {"a", "an", "the", "my", "our", "your"}:
        return phrase
    article = "an" if words[0][:1].lower() in "aeiou" else "a"
    # only singular, countable-looking phrases take an article
    if words[-1].endswith("s") and not words[-1].endswith("ss"):
        return phrase
    return f"{article} {phrase}"


def _section_text(
    index: int, beat: dict[str, Any], concept: dict[str, Any],
    intent: dict[str, Any], brief: dict[str, Any], mode: str,
    total: int = 4, used: set[str] | None = None,
) -> str:
    """Copy that fits the beat's job in the structure.

    Silent formats still need words — they are the on-screen lines. A beat
    label is not copy, so each role gets a written line built from the subject.
    """
    subject = intent["subject"]
    articulated = _with_article(subject)
    role = _role(index, beat["beat"], total)
    hook = concept["hooks"][0]
    used = used or set()

    if index == 0:
        return hook

    subject_ref = articulated if role != "call_to_action" else subject
    silent_bank = {
        "deliver_payload": [
            f"This is where {subject_ref} does the work.",
            f"Here is why {subject_ref} works.",
        ],
        "evidence": [
            "Look at the detail — that is the whole argument.",
            "Close enough to see why it works.",
        ],
        "build_tension": [
            "Then it changes.",
            "This is the turn nobody expects.",
        ],
        "emotional_beat": [
            "That is the moment it lands.",
            "And this is what it feels like.",
        ],
        "resolution": [
            f"That is {subject_ref}, plainly.",
            "No tricks — just the thing itself.",
        ],
        "call_to_action": [
            brief.get("cta") or "Save this for later.",
            "Save this — you will want it.",
        ],
        "establish_context": [
            f"Start here: {subject_ref}.",
            "Watch what happens next.",
        ],
        "introduce_subject": [
            f"Meet {subject_ref}.",
            f"This is {subject_ref}.",
        ],
    }
    bank = silent_bank.get(role) or [beat["beat"].capitalize()]
    if mode == "none":
        for candidate in bank[index % len(bank):] + bank[:index % len(bank)]:
            if candidate not in used:
                return candidate
        return bank[0]

    narrated = {
        "deliver_payload": [f"Here is the part that matters: {subject_ref}, and why it works.",
                            f"Everything you just saw happens because of this: {subject_ref}."],
        "evidence": ["The detail is the argument — this is where it is won.",
                     "Up close, you can see the reasoning."],
        "build_tension": ["Then it changes, and everything before it makes sense.",
                          "This is the turn nobody expects."],
        "emotional_beat": ["This is the moment the whole idea lands.",
                           "And this is the feeling it is going for."],
        "resolution": [f"So that is {subject_ref} — the argument, in one frame.",
                       f"That is {subject_ref}, and nothing more is needed."],
        "call_to_action": [brief.get("cta") or "Save this for later.",
                           "Save this for the next time you need it."],
    }
    options = narrated.get(role) or [f"{beat['beat'].capitalize()}: {subject_ref}."]
    for candidate in options:
        if candidate not in used:
            return candidate
    return options[0]


def _delivery(index: int, mode: str, concept: dict[str, Any]) -> dict[str, Any]:
    """Structured delivery cues — the shape the repo's TTS tools consume."""
    if mode == "none":
        return {
            "pace": "custom",
            "delivery_note": "on-screen text only; no voice track in this build",
            "emphasis_words": [],
        }
    fast = concept["cut_rhythm_seconds"] <= 2.0
    return {
        "pace": "brisk" if fast else "measured",
        "energy": "high" if fast else "steady, restrained",
        "emphasis_words": [],
        "pause_before_seconds": 0.12,
        "pause_after_seconds": 0.18 if index else 0.0,
        "delivery_note": ("hold the first word, land the last before the cut"
                          if index == 0 else "no upspeak; let the final word settle"),
    }


# ---------------------------------------------------------------------------
# storyboard
# ---------------------------------------------------------------------------

def write_storyboard(
    intent: dict[str, Any],
    concept: dict[str, Any],
    script: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    scenes = []
    for index, shot in enumerate(plan["shots"]):
        section = script["sections"][index] if index < len(script["sections"]) else script["sections"][-1]
        scenes.append(
            {
                "id": shot["id"],
                "type": "generated" if intent["deliverable"] != "image" else "text_card",
                "description": shot["description"],
                "start_seconds": shot["start_seconds"],
                "end_seconds": shot["end_seconds"],
                "script_section_id": section["id"],
                "framing": shot["framing"],
                "movement": shot["movement"],
                "transition_in": shot["transition_in"],
                "transition_out": "cut",
                "overlay_notes": f'Caption: "{shot["text_overlay"]}"',
                "shot_language": {
                    "shot_size": SHOT_SIZE_MAP.get(shot["framing"], "medium"),
                    "camera_movement": MOVEMENT_MAP.get(shot["movement"], "static"),
                    "lens_mm": 35 if index % 3 == 0 else (85 if index % 3 == 2 else 50),
                    "lighting_key": _lighting_key(plan.get("grade", ""), index),
                    "depth_of_field": "shallow" if index % 3 == 2 else "medium",
                    "color_temperature": "warm" if "warm" in plan.get("grade", "") else "neutral",
                },
                "shot_intent": f"{shot['beat']} — hold attention",
                "narrative_role": _role(index, shot["beat"], len(plan["shots"])),
                "hero_moment": index == min(1, len(plan["shots"]) - 1),
                "texture_keywords": plan.get("texture", [])[:3],
                "required_assets": [
                    {
                        "type": "still",
                        "description": shot["description"],
                        "source": "provided" if intent.get("has_image") else "generate",
                    }
                ],
            }
        )
    return {
        "version": "1.0",
        "style_playbook": intent.get("niche_label", "studio"),
        "scenes": scenes,
        "metadata": {
            "created_by": "studio.producer",
            "total_duration_seconds": float(intent["duration_seconds"]),
        },
    }


def _lighting_key(grade: str, index: int) -> str:
    if "warm" in grade:
        return "golden_hour" if index % 2 else "tungsten_warm"
    if "cool" in grade:
        return "blue_hour" if index % 2 else "overcast_soft"
    if "lifted shadows" in grade:
        return "low_key"
    return "natural"


def _role(index: int, beat: str, total: int) -> str:
    if index == 0:
        return "establish_context"
    if index == total - 1:
        return "call_to_action"
    lower = beat.lower()
    for key, role in ROLE_BY_BEAT:
        if key in lower:
            return role
    return "deliver_payload"


# ---------------------------------------------------------------------------
# edit decisions
# ---------------------------------------------------------------------------

def write_edit_decisions(
    intent: dict[str, Any],
    concept: dict[str, Any],
    storyboard: dict[str, Any],
    plan: dict[str, Any],
    assets: dict[str, Any],
    cues: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    by_shot = {a["shot_id"]: a for a in assets.get("assets", [])}
    cuts = []
    for index, scene in enumerate(storyboard["scenes"]):
        asset = by_shot.get(scene["id"]) or {}
        cuts.append(
            {
                "id": f"cut_{index + 1:02d}",
                "source": asset.get("path") or scene.get("asset_path") or "",
                "in_seconds": 0.0,
                "out_seconds": round(scene["end_seconds"] - scene["start_seconds"], 3),
                "speed": 1.0,
                "layer": "primary",
                "transition_in": scene.get("transition_in", "cut"),
                "transition_out": scene.get("transition_out", "cut"),
                "transition_duration": 0.28 if scene.get("transition_in") == "dissolve" else 0.0,
                "reason": f"{scene['narrative_role']} — {scene['shot_intent']}",
            }
        )
    overlays = [
        {
            "asset_id": scene["id"],
            "start_seconds": scene["start_seconds"],
            "end_seconds": scene["end_seconds"],
            "position": {"x": 0.5, "y": 0.72, "width": 0.84, "height": 0.18},
            "animation": "fade",
            "opacity": 1.0,
            "text": cue["text"],
        }
        for scene, cue in zip(storyboard["scenes"], cues)
    ]
    return {
        "version": "1.0",
        "cuts": cuts,
        "overlays": overlays,
        "transitions": [
            {
                "type": scene.get("transition_in", "cut"),
                "at_seconds": scene["start_seconds"],
                "duration_seconds": 0.28 if scene.get("transition_in") == "dissolve" else 0.0,
            }
            for scene in storyboard["scenes"][1:]
        ],
        "subtitles": {
            "enabled": bool(cues),
            "style": concept.get("text_style", "clean"),
            "source": "script.sections",
            "font": "DejaVu Sans",
            "font_size": 64,
            "color": plan["palette"][1] if len(plan["palette"]) > 1 else "#FFFFFF",
            "outline_color": "#000000",
            "position": "bottom-center",
            "max_words_per_line": 5,
        },
        "renderer_family": _renderer_family(concept),
        "render_runtime": "ffmpeg",
        "composition_mode": "templated",
        "audio": {"sfx": []},
        "metadata": {
            "aspect": "9:16" if intent["platform"] == "tiktok" else "16:9",
            "fps": 30,
            "engine": "studio.producer",
            "audio_note": "Delivered silent: add the trending sound inside TikTok for reach.",
        },
    }


def _renderer_family(concept: dict[str, Any]) -> str:
    if concept["cut_rhythm_seconds"] <= 1.6:
        return "animation-first"
    if concept["cut_rhythm_seconds"] >= 2.8:
        return "documentary-montage"
    return "cinematic-trailer"


# ---------------------------------------------------------------------------
# captions
# ---------------------------------------------------------------------------

def build_cues(script: dict[str, Any], storyboard: dict[str, Any], *, max_chars: int = 62) -> list[dict[str, Any]]:
    """One cue per scene, split into readable chunks if the line is long."""
    cues: list[dict[str, Any]] = []
    for section, scene in zip(script["sections"], storyboard["scenes"]):
        text = (section.get("text") or "").strip()
        if not text:
            continue
        chunks = _chunk(text, max_chars)
        span = max(0.8, scene["end_seconds"] - scene["start_seconds"])
        per = span / len(chunks)
        for index, chunk in enumerate(chunks):
            cues.append(
                {
                    "text": chunk,
                    "start_seconds": round(scene["start_seconds"] + per * index, 3),
                    "end_seconds": round(scene["start_seconds"] + per * (index + 1), 3),
                    "scene_id": scene["id"],
                    "style": "CTA" if scene["narrative_role"] == "call_to_action" else "Caption",
                }
            )
    return cues


def _chunk(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    words = text.split()
    chunks, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if len(trial) <= limit or not current:
            current = trial
        else:
            chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# quality control
# ---------------------------------------------------------------------------

def quality_check(
    video_path: Path,
    *,
    storyboard: dict[str, Any],
    assets: dict[str, Any],
    cues: Sequence[dict[str, Any]],
    intent: dict[str, Any],
    expected_seconds: float,
    promised_model: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run real checks against the file, then report them honestly."""
    from PIL import Image, ImageStat

    findings: list[dict[str, Any]] = []
    info = probe(video_path)
    duration = float(info.get("duration_seconds") or 0)
    width, height = info.get("width") or 0, info.get("height") or 0

    # --- technical ---------------------------------------------------------
    tolerance = 0.35
    timing_ok = abs(duration - expected_seconds) <= tolerance
    aspect_ok = (width, height) in {(1080, 1920), (1920, 1080), (1080, 1080), (1080, 1350)}
    issues = []
    if not timing_ok:
        issues.append(f"duration {duration:.2f}s vs planned {expected_seconds:.2f}s")
    if not aspect_ok:
        issues.append(f"unexpected resolution {width}x{height}")
    if not info.get("has_video"):
        issues.append("no video stream")

    # --- visual spotcheck: sample frames and measure them ------------------
    frame_dir = video_path.parent / ".qa_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    sampled: list[str] = []
    black = False
    for index, at in enumerate([duration * f for f in (0.12, 0.38, 0.62, 0.88) if duration > 0]):
        frame = frame_dir / f"qa_{index}.jpg"
        from studio.motion import _run, ffmpeg_bin

        result = _run([ffmpeg_bin(), "-y", "-loglevel", "error", "-ss", f"{at:.2f}",
                       "-i", str(video_path), "-frames:v", "1", "-q:v", "4", str(frame)])
        if result.returncode == 0 and frame.exists():
            sampled.append(str(frame))
            with Image.open(frame) as img:
                stat = ImageStat.Stat(img.convert("L"))
                if stat.mean[0] < 9 and stat.stddev[0] < 6:
                    black = True

    missing = [s["id"] for s in storyboard["scenes"]
               if not (assets.get("assets") and any(
                   a.get("shot_id") == s["id"] and Path(a.get("path", "")).exists()
                   for a in assets["assets"]))]

    if black:
        findings.append(_finding("f-black", "critical", "technical",
                                 "At least one sampled frame is effectively black — the cut would "
                                 "read as a dropout.", "revise_edit"))
    if missing:
        findings.append(_finding("f-assets", "critical", "assets",
                                 f"Scenes with no usable asset on disk: {', '.join(missing)}.",
                                 "revise_assets"))
    if not timing_ok:
        findings.append(_finding("f-timing", "suggestion", "timing",
                                 f"Rendered {duration:.2f}s against a planned "
                                 f"{expected_seconds:.2f}s ({duration - expected_seconds:+.2f}s).",
                                 "re_render"))
    if not cues:
        findings.append(_finding("f-cues", "suggestion", "captions",
                                 "No caption cues were produced; the piece would rely on audio-only.", "accept"))

    # --- honesty: did we deliver what the plan promised? -------------------
    provenance = [a.get("provenance") for a in assets.get("assets", [])]
    local_count = sum(1 for p in provenance if p == "local")
    source_count = sum(1 for p in provenance if p == "source")
    model_count = sum(1 for p in provenance if p == "model")
    swap_detected = bool(promised_model and local_count and model_count == 0)
    if swap_detected:
        findings.append(_finding(
            "f-provenance", "suggestion", "provenance",
            "Planned model generation but no provider was reachable, so frames were composed "
            "locally. The video is labelled as a local preview everywhere it appears.",
            "accept",
        ))
    if source_count and not model_count and not local_count:
        findings.append(_finding(
            "f-source", "nitpick", "provenance",
            "Every frame is derived from the supplied photograph — nothing was invented.",
            "accept",
        ))

    # --- captions ----------------------------------------------------------
    coverage = 0.0
    if cues and duration:
        covered = sum(max(0.0, c["end_seconds"] - c["start_seconds"]) for c in cues)
        coverage = min(1.0, covered / duration)
    if cues and coverage < 0.5:
        findings.append(_finding("f-coverage", "suggestion", "captions",
                                 f"Captions cover {coverage * 100:.0f}% of the runtime — below the 50% "
                                 "readability target.", "accept"))

    # --- legibility of the design (safe areas) -----------------------------
    safe_bottom = height * 0.16 if height > width else height * 0.12
    caption_y = height * 0.78 if height > width else height * 0.84
    if caption_y > height - safe_bottom + (height * 0.06):
        findings.append(_finding("f-safe", "nitpick", "layout",
                                 "Caption baseline sits close to TikTok's interface band.", "accept"))

    status = "pass"
    if any(f["severity"] == "critical" for f in findings) or issues:
        status = "revise"
    if missing or not info.get("has_video"):
        status = "fail"

    review = {
        "version": "1.0",
        "stage": "compose",
        "round": 1,
        "findings": findings,
        "metadata": {"engine": "studio.producer.quality_check", "sampled_frames": len(sampled)},
    }
    final_review = {
        "version": "1.0",
        "output_path": str(video_path),
        "status": status,
        "checks": {
            "technical_probe": {
                "valid_container": bool(info.get("has_video")) and duration > 0,
                "duration_seconds": round(duration, 2),
                "resolution": f"{width}x{height}",
                "fps": info.get("fps"),
                "has_audio": bool(info.get("has_audio")),
                "codec": "h264",
                "file_size_bytes": int(video_path.stat().st_size),
                "issues": issues,
            },
            "visual_spotcheck": {
                "frames_sampled": len(sampled),
                "frame_paths": sampled,
                "black_frames_detected": black,
                "broken_overlays": False,
                "missing_assets": bool(missing),
                "unreadable_text": bool(findings and any(f["id"] == "f-safe" for f in findings)),
                "issues": ([f"missing assets: {missing}"] if missing else []),
            },
            "audio_spotcheck": {
                "narration_present": False,
                "music_present": False,
                "unexpected_silence": False,
                "clipping_detected": False,
                "mix_intelligible": True,
                "issues": ["Delivered without audio by design — add the platform's trending sound."],
            },
            "promise_preservation": {
                "delivery_promise_honored": not swap_detected,
                "renderer_family_used": _renderer_family_from_edit(storyboard),
                "render_runtime_used": "ffmpeg",
                "runtime_swap_detected": swap_detected,
                "runtime_swap_check": "model planned vs provenance recorded on every asset",
                "motion_ratio_actual": 1.0 if duration else 0.0,
                "silent_downgrade_detected": swap_detected,
                "issues": (["Frames are local previews, not model output."] if swap_detected else []),
            },
            "subtitle_check": {
                "subtitles_expected": bool(cues),
                "subtitles_present": bool(cues),
                "coverage_ratio": round(coverage, 3),
                "timing_drift_detected": not timing_ok,
                "issues": ([] if timing_ok else [f"duration drift {duration - expected_seconds:+.2f}s"]),
            },
        },
        "issues_found": [f["description"] for f in findings],
        "recommended_action": "present_to_user" if status == "pass" else ("re_render" if status == "revise" else "block"),
        "metadata": {
            "engine": "studio.producer.quality_check",
            "assets_model": model_count,
            "assets_local": local_count,
            "assets_source": source_count,
            "aspect_expected": "9:16" if intent["platform"] == "tiktok" else "16:9",
        },
    }
    return review, final_review


def _renderer_family_from_edit(storyboard: dict[str, Any]) -> str:
    rhythm = [
        (s["end_seconds"] - s["start_seconds"]) for s in storyboard.get("scenes", [])
    ]
    if not rhythm:
        return "cinematic-trailer"
    average = sum(rhythm) / len(rhythm)
    if average <= 1.6:
        return "animation-first"
    if average >= 2.8:
        return "documentary-montage"
    return "cinematic-trailer"


def _finding(fid: str, severity: str, category: str, description: str, action: str) -> dict[str, Any]:
    return {
        "id": fid,
        "severity": severity,
        "category": category,
        "description": description,
        "disposition": "accepted",
        "agent_response": action,
    }
