"""System 2 — Universal Creative Engine.

Brief in, production-ready media out. Four real jobs:

**Analyse** the source material. An uploaded photograph is measured — palette,
luminance, contrast, warmth, focal point, safe crop — and those measurements
change the art direction. This is why an image-led campaign looks like *that*
image rather than a generic template.

**Choose the model.** The repository ships ~30 image and ~34 video providers,
each declaring capabilities and cost. We rank them against this specific shot
(capabilities actually required, cost, whether a reference image is needed) and
record why the chosen one won. If nothing is configured we say so plainly and use
the local art director.

**Plan the visuals.** Palette, lighting, per-scene framing and camera movement,
transitions — all derived from the chosen concept and the measured source.

**Write the prompts.** Complete, model-ready prompts with a negative prompt and a
style block. Advanced Studio exposes these for editing; Automatic mode never asks
the user to look at them.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Any, Optional

from studio.brain import knowledge as kb
from studio.brain import localfx
from studio.motion import ASPECTS

REPO_ROOT = Path(__file__).resolve().parents[2]

# Safe areas for a 9:16 feed: TikTok's UI covers these bands.
SAFE_INSETS = {"top": 0.10, "bottom": 0.16, "sides": 0.06}


# ---------------------------------------------------------------------------
# media analysis
# ---------------------------------------------------------------------------

def analyse_image(path: str | Path) -> dict[str, Any]:
    """Measure the source photograph. Cheap, deterministic, and actually used."""
    from PIL import Image, ImageFilter, ImageStat

    path = Path(path)
    with Image.open(path) as raw:
        img = raw.convert("RGB")
        width, height = img.size
        small = img.resize((128, max(1, int(128 * height / width))), Image.Resampling.BILINEAR)
        stat = ImageStat.Stat(small)
        r, g, b = stat.mean
        brightness = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
        contrast = (sum(stat.stddev) / 3) / 128
        hsv = small.convert("HSV")
        saturation = ImageStat.Stat(hsv).mean[1] / 255
        warmth = (r - b + 255) / 510

        # dominant colours via a coarse quantise
        quant = small.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
        palette_raw = quant.getpalette() or []
        counts = sorted(quant.getcolors() or [], reverse=True)[:4]
        dominant = []
        for _, index in counts:
            base = index * 3
            if base + 2 < len(palette_raw):
                rgb = palette_raw[base : base + 3]
                dominant.append("#{:02X}{:02X}{:02X}".format(*rgb))

        # focal point: where the edge energy is
        edges = small.convert("L").filter(ImageFilter.FIND_EDGES)
        cols, rows = 4, 6
        best, best_xy = -1.0, (0.5, 0.5)
        for cy in range(rows):
            for cx in range(cols):
                box = (
                    int(cx * edges.width / cols),
                    int(cy * edges.height / rows),
                    int((cx + 1) * edges.width / cols),
                    int((cy + 1) * edges.height / rows),
                )
                energy = ImageStat.Stat(edges.crop(box)).mean[0]
                if energy > best:
                    best, best_xy = energy, ((cx + 0.5) / cols, (cy + 0.5) / rows)

        # how much of a 9:16 frame the source can fill without upscaling
        target_w, target_h = ASPECTS["9:16"]
        cover_ratio = max(target_w / width, target_h / height)

    orientation = "portrait" if height > width * 1.1 else ("landscape" if width > height * 1.1 else "square")
    return {
        "path": str(path),
        "width": width,
        "height": height,
        "orientation": orientation,
        "aspect": round(width / height, 3),
        "brightness": round(brightness, 3),
        "contrast": round(contrast, 3),
        "saturation": round(saturation, 3),
        "warmth": round(warmth, 3),
        "palette": dominant or ["#101319", "#E8E4DC"],
        "focal_point": {"x": round(best_xy[0], 3), "y": round(best_xy[1], 3)},
        "needs_upscale": cover_ratio > 1.15,
        "crop_for_9x16": _crop_plan(width, height, best_xy),
        "notes": _analysis_notes(brightness, contrast, saturation, orientation),
    }


def _crop_plan(width: int, height: int, focal: tuple[float, float]) -> dict[str, Any]:
    target_ratio = 9 / 16
    current = width / height
    if abs(current - target_ratio) < 0.02:
        return {"needed": False, "reason": "source is already vertical"}
    if current > target_ratio:
        crop_w = int(height * target_ratio)
        left = int(max(0, min(width - crop_w, width * focal[0] - crop_w / 2)))
        return {"needed": True, "mode": "crop_sides", "width": crop_w, "height": height,
                "x": left, "y": 0, "reason": "remove side margins, keep the focal point"}
    crop_h = int(width / target_ratio)
    top = int(max(0, min(height - crop_h, height * focal[1] - crop_h / 2)))
    return {"needed": True, "mode": "crop_top_bottom", "width": width, "height": crop_h,
            "x": 0, "y": top, "reason": "remove vertical margins, keep the focal point"}


def _analysis_notes(brightness: float, contrast: float, saturation: float, orientation: str) -> list[str]:
    notes = []
    if brightness > 0.72:
        notes.append("bright source — captions need a dark scrim or they will wash out")
    elif brightness < 0.24:
        notes.append("dark source — lift the grade slightly or the detail disappears on phones")
    if contrast < 0.35:
        notes.append("flat contrast — add a tonal split so the edit has depth")
    if saturation > 0.62:
        notes.append("saturated source — pull colour back 10% so overlays stay readable")
    if orientation != "portrait":
        notes.append(f"{orientation} source re-framed to 9:16 — check nothing important is cropped")
    return notes


# ---------------------------------------------------------------------------
# model selection
# ---------------------------------------------------------------------------

def _tool_row(tool: Any) -> dict[str, Any]:
    try:
        status = str(tool.get_status()).replace("ToolStatus.", "").lower()
    except Exception:
        status = "unknown"
    try:
        cost = float(tool.estimate_cost({}) or 0.0)
    except Exception:
        cost = 0.0
    return {
        "name": tool.name,
        "provider": getattr(tool, "provider", "unknown"),
        "capabilities": list(getattr(tool, "capabilities", []) or []),
        "best_for": list(getattr(tool, "best_for", []) or [])[:3],
        "available": status == "available",
        "status": status,
        "cost_usd": round(cost, 4),
    }


def _catalogue(capability: str) -> list[dict[str, Any]]:
    try:
        from tools.tool_registry import registry as tool_registry

        tool_registry.ensure_discovered()
        rows = []
        for tool in tool_registry.get_by_capability(capability):
            if tool.name.endswith("_selector"):
                continue
            rows.append(_tool_row(tool))
        return rows
    except Exception:
        return []


def choose_image_model(*, needs_text: bool = False, wants_photo: bool = False,
                       wants_edit: bool = False, budget: float = 0.15) -> dict[str, Any]:
    """Rank the real provider catalogue for this shot and explain the winner."""
    rows = _catalogue("image_generation")
    if not rows:
        return {"chosen": None, "available": False, "candidates": [],
                "reason": "No image generation tools were discovered in the repository registry.",
                "fallback": "local"}

    def score(row: dict[str, Any]) -> tuple[float, list[str]]:
        points, why = 0.0, []
        caps = set(row["capabilities"])
        if row["available"]:
            points += 60
            why.append("provider is configured")
        else:
            points -= 40
            why.append("no credentials configured")
        if needs_text and ({"generate_image", "text_to_image"} & caps):
            points += 8
            why.append("supports rendered text in-image")
        if wants_edit and ({"edit_image", "image_edit"} & caps):
            points += 14
            why.append("supports reference-preserving edits")
        if wants_photo and any("photo" in b.lower() for b in row["best_for"]):
            points += 10
            why.append("strongest at photography")
        if row["cost_usd"] <= budget:
            points += 6
            why.append(f"within ${budget:.2f}/image budget")
        else:
            points -= min(12.0, (row["cost_usd"] - budget) * 40)
            why.append(f"over ${budget:.2f}/image budget")
        if "local" in row["provider"]:
            points += 4
            why.append("no metered cost")
        return points, why

    ranked = []
    for row in rows:
        points, why = score(row)
        ranked.append({**row, "score": round(points, 1), "reasons": why})
    ranked.sort(key=lambda r: (r["available"], r["score"]), reverse=True)
    available = [r for r in ranked if r["available"]]
    chosen = available[0] if available else None
    return {
        "chosen": chosen,
        "available": bool(chosen),
        "candidates": ranked[:8],
        "considered": len(ranked),
        "reason": (
            f"Chose {chosen['name']} — {', '.join(chosen['reasons'][:3])}."
            if chosen
            else "Every provider in the repository catalogue is unconfigured in this environment, "
                 "so the local art director will compose the frames and label them as local."
        ),
        "fallback": "none" if chosen else "local",
    }


def choose_video_model(*, needs_motion: bool, image_reference: bool,
                       seconds: float, budget: float = 2.0) -> dict[str, Any]:
    rows = _catalogue("video_generation")
    if not rows:
        return {"chosen": None, "available": False, "candidates": [],
                "reason": "No video generation tools were discovered in the repository registry.",
                "fallback": "local"}

    required = "image_to_video" if image_reference else "text_to_video"
    capable = [r for r in rows if required in r["capabilities"]]
    pool = capable or rows

    def score(row: dict[str, Any]) -> tuple[float, list[str]]:
        points, why = 0.0, []
        if row["available"]:
            points += 60
            why.append("provider is configured")
        else:
            points -= 40
            why.append("no credentials configured")
        if required in row["capabilities"]:
            points += 12
            why.append(f"supports {required.replace('_', ' ')}")
        elif capable:
            points -= 25
            why.append(f"does not declare {required.replace('_', ' ')}")
        if needs_motion and "reference_to_video" in row["capabilities"]:
            points += 4
            why.append("supports reference conditioning for consistency")
        est = row["cost_usd"]
        if est and est * max(1.0, seconds / 5.0) <= budget:
            points += 5
            why.append(f"≈${est * max(1.0, seconds / 5.0):.2f} for this duration")
        elif est:
            points -= 8
            why.append(f"≈${est * max(1.0, seconds / 5.0):.2f} exceeds the ${budget:.2f} budget")
        return points, why

    ranked = []
    for row in pool:
        points, why = score(row)
        ranked.append({**row, "score": round(points, 1), "reasons": why})
    ranked.sort(key=lambda r: (r["available"], r["score"]), reverse=True)
    available = [r for r in ranked if r["available"]]
    chosen = available[0] if available else None
    return {
        "chosen": chosen,
        "available": bool(chosen),
        "candidates": ranked[:8],
        "considered": len(ranked),
        "reason": (
            f"Chose {chosen['name']} — {', '.join(chosen['reasons'][:3])}."
            if chosen
            else "No video model is configured, so each scene is animated with FFmpeg "
                 "camera motion over designed frames — real motion, but not model footage."
        ),
        "fallback": "none" if chosen else "ffmpeg_motion",
    }


# ---------------------------------------------------------------------------
# visual planning
# ---------------------------------------------------------------------------

def _palette_for(intent: dict[str, Any], niche: kb.Niche, media: Optional[dict[str, Any]]) -> list[str]:
    """Prefer the source image's own colours; fall back to the niche playbook."""
    if media and media.get("palette"):
        measured = list(media["palette"])[:3]
        playbook = niche.palettes[0]
        # keep the image's identity but borrow a playbook accent for lift
        accent = playbook[2] if len(playbook) > 2 else "#E4572E"
        return measured + [accent]
    return list(niche.palettes[0])


def _motion_for(index: int, count: int, concept: dict[str, Any], media: Optional[dict[str, Any]]) -> str:
    """Assign camera moves so consecutive shots never repeat."""
    moves = ["ken_burns", "pan_up", "zoom_in", "pan_left", "zoom_out", "pan_right"]
    if concept["cut_rhythm_seconds"] <= 1.6:
        moves = ["zoom_in", "pan_left", "zoom_out", "pan_right"]
    move = moves[index % len(moves)]
    if index == 0:
        move = "zoom_in"  # the hook needs immediate energy
    if index == count - 1:
        move = "ken_burns"  # the close should settle
    if media and media.get("focal_point", {}).get("y", 0.5) > 0.62 and move == "pan_up":
        move = "pan_left"  # subject sits low; a downward-ish move reads better
    return move


def plan_visuals(
    intent: dict[str, Any],
    concept: dict[str, Any],
    beats: list[dict[str, Any]],
    media: Optional[dict[str, Any]],
) -> dict[str, Any]:
    niche = kb.NICHES[intent["niche"]]
    palette = _palette_for(intent, niche, media)
    width, height = ASPECTS["9:16"] if intent["platform"] == "tiktok" else ASPECTS.get(
        intent.get("aspect") or "16:9", (1920, 1080)
    )

    shots = []
    for index, beat in enumerate(beats):
        visual = _shot_visual(index, len(beats), beat["beat"], intent, concept, niche)
        interior = f"{niche.lighting[index % len(niche.lighting)]}, {niche.visual_vocabulary[index % len(niche.visual_vocabulary)]}"
        shots.append(
            {
                "id": f"shot_{index + 1:02d}",
                "scene_index": index,
                "beat": beat["beat"],
                "start_seconds": beat["start_seconds"],
                "end_seconds": beat["end_seconds"],
                "duration_seconds": round(beat["end_seconds"] - beat["start_seconds"], 2),
                "description": visual["description"],
                "framing": visual["framing"],
                "movement": _motion_for(index, len(beats), concept, media),
                "lighting": interior,
                "transition_in": "cut" if index == 0 else ("dissolve" if concept["cut_rhythm_seconds"] > 2.2 else "whip_cut"),
                "text_overlay": visual["text_overlay"],
                "palette_role": ["ground", "ink", "accent", "support"][index % 4],
            }
        )

    return {
        "palette": palette,
        "lighting": niche.lighting[:3],
        "texture": niche.materials[:3],
        "grade": _grade(intent, media),
        "width": width,
        "height": height,
        "safe_insets": SAFE_INSETS,
        "shots": shots,
        "consistency": _consistency_plan(intent, concept, media, palette),
        "source_notes": (media or {}).get("notes", []),
    }


def _shot_visual(
    index: int, total: int, beat: str, intent: dict[str, Any], concept: dict[str, Any], niche: kb.Niche
) -> dict[str, str]:
    """Scene description that follows the beat's dramatic function."""
    subject = intent["subject"]
    lower = beat.lower()
    framing_cycle = ["wide establishing", "medium", "close detail", "medium-wide", "macro insert"]
    framing = framing_cycle[index % len(framing_cycle)]

    if index == 0:
        return {
            "description": f"{subject}, held in a patient wide frame; negative space where the hook lands",
            "framing": "wide establishing",
            "text_overlay": concept["hooks"][0],
        }
    if "reveal" in lower:
        return {
            "description": f"the full {subject} revealed in one clean, front-on frame",
            "framing": "medium-wide",
            "text_overlay": "here it is",
        }
    if "detail" in lower or "texture" in lower or "macro" in lower:
        return {
            "description": f"macro study of {niche.materials[index % len(niche.materials)]} — the quality argument",
            "framing": "macro insert",
            "text_overlay": concept["text_style"].split(",")[0],
        }
    if "turn" in lower or "consequence" in lower or "rise" in lower:
        return {
            "description": f"{subject} at the moment of change; tighter frame, warmer light",
            "framing": "medium",
            "text_overlay": "and then",
        }
    if "close" in lower or "landing" in lower or "the line" in lower:
        return {
            "description": f"final frame — {subject} held in stillness, space reserved for the closing line",
            "framing": "wide establishing",
            "text_overlay": "save this",
        }
    return {
        "description": f"{beat}: {subject} framed {framing} under {niche.lighting[index % len(niche.lighting)]}",
        "framing": framing,
        "text_overlay": beat,
    }


def _grade(intent: dict[str, Any], media: Optional[dict[str, Any]]) -> str:
    if media and media.get("brightness", 0.5) < 0.3:
        return "lifted shadows, warm mids, gentle contrast"
    if media and media.get("brightness", 0.5) > 0.7:
        return "held highlights, cool mids, controlled saturation"
    if intent.get("tone") in {"luxury", "premium", "elegant"}:
        return "filmic, desaturated, warm highlight roll-off"
    return "neutral contrast, slight warm bias, clean blacks"


def _consistency_plan(
    intent: dict[str, Any], concept: dict[str, Any], media: Optional[dict[str, Any]], palette: list[str]
) -> dict[str, Any]:
    """How the piece stays visually coherent across shots."""
    return {
        "palette": palette,
        "grade": _grade(intent, media),
        "light_direction": "key from camera-left in every shot"
        if concept["id"] in {"editorial-film", "designer-story"}
        else "single dominant light source per shot",
        "lens_language": "35mm wide for establishes, 85mm for details",
        "subject_lock": "same subject, same material story, no new objects introduced late",
        "color_anchor": palette[2] if len(palette) > 2 else "#E4572E",
        "source_reference": (media or {}).get("path"),
    }


# ---------------------------------------------------------------------------
# prompt construction
# ---------------------------------------------------------------------------

def build_prompts(intent: dict[str, Any], concept: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Model-ready prompts, one per shot, plus negative and style blocks."""
    niche = kb.NICHES[intent["niche"]]
    style_block = (
        f"{concept['treatment']}. {plan['grade']}. "
        f"Palette: {', '.join(plan['palette'])}. "
        f"Lighting: {plan['lighting'][0]}. "
        f"Texture: {', '.join(plan['texture'])}. "
        f"Shot as a still from a {intent['platform']} vertical film, 9:16, shallow depth of field."
    )
    negative = (
        "text, watermark, logo, signature, extra fingers, distorted anatomy, warped faces, "
        "duplicate subjects, clutter, oversaturated HDR, fisheye distortion, low resolution, "
        "jpeg artefacts, stock-photo posing, obvious AI gloss"
    )
    shots = []
    for shot in plan["shots"]:
        prompt = (
            f"{shot['description']}. {shot['framing']} framing, {shot['lighting']}. "
            f"{style_block}"
        )
        shots.append(
            {
                "shot_id": shot["id"],
                "prompt": prompt,
                "negative_prompt": negative,
                "aspect_ratio": "9:16" if intent["platform"] == "tiktok" else "16:9",
                "seed_policy": "fixed per shot so refinements keep continuity",
                "edit_target": f"shots[{shot['scene_index']}]",
            }
        )
    return {
        "style_block": style_block,
        "negative_prompt": negative,
        "shots": shots,
        "editable": True,
        "note": "Prompts are derived from the brief and the measured source image. "
                "Editing them in Advanced Studio affects the asset step only.",
    }


# ---------------------------------------------------------------------------
# asset production
# ---------------------------------------------------------------------------

def _url_for(path: Path) -> str:
    # the UI joins this onto /api/studio/projects/<id>/media/ so the same
    # record is valid no matter which host the studio is served from
    return path.name


def produce_assets(
    project_dir: Path,
    intent: dict[str, Any],
    concept: dict[str, Any],
    plan: dict[str, Any],
    prompts: dict[str, Any],
    *,
    upload_path: Optional[str] = None,
    allow_local: bool = True,
    provider: Optional[str] = None,
    progress=None,
    previous: Optional[dict[str, Any]] = None,
    reuse: bool = True,
    media: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Generate (or derive) one still per shot. Records honest provenance."""
    width, height = plan["width"], plan["height"]
    assets_dir = project_dir / "assets" / "frames"
    assets_dir.mkdir(parents=True, exist_ok=True)

    image_route = choose_image_model(needs_text=False, wants_photo=True, wants_edit=bool(upload_path))
    use_model = image_route["available"] and not provider == "local"
    if provider and provider != "auto" and provider != "local":
        image_route["chosen"] = next(
            (c for c in image_route["candidates"] if c["name"] == provider or c["provider"] == provider),
            image_route["chosen"],
        )
        use_model = bool(image_route["chosen"] and image_route["chosen"]["available"])

    shots = plan["shots"]
    assets: list[dict[str, Any]] = []
    prior = {}
    if reuse and previous:
        for record in previous.get("assets", []):
            if record.get("path") and Path(record["path"]).exists():
                prior[record.get("shot_id")] = record

    # --- image-led campaigns derive frames from the photograph -------------
    if upload_path and not use_model:
        variants = localfx.photography_variants(
            upload_path, assets_dir, palette=plan["palette"], width=width, height=height,
            count=len(shots), narrate=concept.get("name", ""),
            focus=(
                float((media or {}).get("focal_point", {}).get("x", 0.5)),
                float((media or {}).get("focal_point", {}).get("y", 0.45)),
            ),
        )
        for shot, variant in zip(shots, variants):
            if shot["id"] in prior:
                assets.append(prior[shot["id"]])
                continue
            assets.append(
                {
                    "id": shot["id"],
                    "shot_id": shot["id"],
                    "path": variant["path"],
                    "url": _url_for(Path(variant["path"])),
                    "kind": "still",
                    "width": variant["width"],
                    "height": variant["height"],
                    "provenance": "source",
                    "producer": "studio.localfx.photography_variants",
                    "provider": "local",
                    "model": None,
                    "treatment": variant["treatment"],
                    "derived_from": variant["derived_from"],
                    "focus": {"x": 0.5, "y": 0.45},
                    "instructions": variant["instructions"],
                    "prompt": next((p["prompt"] for p in prompts["shots"] if p["shot_id"] == shot["id"]), ""),
                    "prompt_hash": _prompt_hash(next((p["prompt"] for p in prompts["shots"] if p["shot_id"] == shot["id"]), "")),
                }
            )
        route_note = (
            "Frames are real crops and grades of the uploaded photograph — no generative "
            "model was used, so the product stays exactly as photographed."
        )
    else:
        for index, shot in enumerate(shots):
            if progress:
                progress(index, len(shots), shot["beat"])
            prompt = next((p["prompt"] for p in prompts["shots"] if p["shot_id"] == shot["id"]), "")
            prompt_hash = _prompt_hash(prompt)
            if shot["id"] in prior and prior[shot["id"]].get("prompt_hash") in {None, prompt_hash}:
                reused = dict(prior[shot["id"]])
                reused["prompt_hash"] = prompt_hash
                reused["reused"] = True
                assets.append(reused)
                continue
            out = assets_dir / f"{shot['id']}.jpg"
            record: dict[str, Any] = {
                "id": shot["id"],
                "shot_id": shot["id"],
                "path": str(out),
                "url": _url_for(out),
                "kind": "still",
                "width": width,
                "height": height,
                "prompt": prompt,
                "prompt_hash": prompt_hash,
            }
            if use_model:
                try:
                    record.update(_generate_with_model(project_dir, prompt, out, width, height,
                                                       image_route["chosen"], index))
                except Exception as exc:  # keep the pipeline alive, record the truth
                    record.update(
                        _local_frame(out, shot, plan, concept, intent, width, height, index,
                                     fallback_reason=str(exc)[:240])
                    )
            else:
                record.update(
                    _local_frame(out, shot, plan, concept, intent, width, height, index,
                                 fallback_reason="no image provider is configured in this environment")
                )
            assets.append(record)
        route_note = (
            f"Generated with {image_route['chosen']['name']} ({image_route['chosen']['provider']})."
            if use_model and any(a.get("provenance") == "model" for a in assets)
            else "Composed locally by the studio's art director because no image provider is configured. "
                 "These are designed frames, not model output, and are labelled as such."
        )

    return {
        "route": image_route,
        "used_model": use_model,
        "assets": assets,
        "note": route_note,
        "count": len(assets),
        "reused": sum(1 for a in assets if a.get("reused")),
    }


def _prompt_hash(prompt: str) -> str:
    import hashlib

    return hashlib.sha256((prompt or "").encode()).hexdigest()[:12]


def _generate_with_model(
    project_dir: Path, prompt: str, out: Path, width: int, height: int,
    chosen: dict[str, Any], index: int,
) -> dict[str, Any]:
    from studio.repo_bridge import registry

    tool = registry().get("image_selector")
    if tool is None:
        raise RuntimeError("image_selector missing")
    out.parent.mkdir(parents=True, exist_ok=True)
    result = tool.execute(
        {
            "prompt": prompt,
            "output_path": str(out),
            "width": width,
            "height": height,
            "aspect_ratio": "9:16" if height > width else "16:9",
            "preferred_provider": chosen["provider"],
            "seed": 4242 + index * 17,
        }
    )
    if not result.success:
        raise RuntimeError(result.error or "image provider failed")
    data = result.data or {}
    produced = Path(data.get("output_path") or data.get("output") or out)
    if not produced.exists() and data.get("image_paths"):
        produced = Path(data["image_paths"][0])
    if not produced.exists():
        raise RuntimeError("provider returned success but no file")
    if produced != out:
        shutil.copy2(produced, out)
    return {
        "provenance": "model",
        "producer": "image_selector",
        "provider": data.get("selected_provider") or chosen["provider"],
        "model": data.get("model") or data.get("selected_tool") or chosen["name"],
        "selection_reason": data.get("selection_reason") or chosen["reasons"][0],
        "cost_usd": float(result.cost_usd or 0.0),
    }


def _local_frame(
    out: Path, shot: dict[str, Any], plan: dict[str, Any], concept: dict[str, Any],
    intent: dict[str, Any], width: int, height: int, index: int, *,
    fallback_reason: str,
) -> dict[str, Any]:
    # The frame carries the *scene*, not the spoken hook: the hook is burned by
    # the caption layer. That way refining copy never re-renders the artwork.
    headline = shot.get("beat") or shot.get("text_overlay") or concept["name"]
    headline = headline.replace("_", " ")
    localfx.design_frame(
        out,
        headline=headline.title() if headline.isupper() else headline,
        kicker=intent["niche_label"],
        body=shot["description"][:90],
        palette=plan["palette"],
        width=width,
        height=height,
        variant=index,
        style="editorial" if concept["cut_rhythm_seconds"] > 2.0 else "graphic",
        label="LOCAL PREVIEW · NO MODEL",
    )
    return {
        "provenance": "local",
        "producer": "studio.localfx.design_frame",
        "provider": "local",
        "model": None,
        "fallback_reason": fallback_reason,
    }
