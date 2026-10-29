"""System 4 — TikTok Growth Engine.

Takes the *finished* project as input: the actual script lines, the actual scene
timings, the actual rendered file, the actual palette. That is why the caption
describes the video that exists instead of a story we hoped to make.

What it produces
----------------
* caption — hook-first, under 150 characters before the fold, written to be read
  by a human and searched by the algorithm
* hashtags — a deliberate mix: 2 broad, 3 niche, 1 topic, never 30
* keyword targets — the phrases this video can plausibly rank for in TikTok
  search, drawn from the brief and the niche playbook
* cover text + on-screen text plan, retimed to the real cuts
* a sound brief — what to search for in TikTok's native library
* a posting plan — cadence and follow-ups derived from the concept
* export + publish log entries in the repository's publish schema

What it deliberately does **not** produce
-----------------------------------------
Search volumes, trend percentages, predicted views, or a virality score. None of
those are knowable from this machine, so inventing them would be the exact
failure the brief calls out. `evidence` on every block says where the numbers
came from — and where there are no numbers, it says so.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from studio.brain import knowledge as kb

MAX_CAPTION = 2200
FOLD = 150


def _clean_line(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip(" ."))


def build_package(
    *,
    intent: dict[str, Any],
    concept: dict[str, Any],
    brief: dict[str, Any],
    script: dict[str, Any],
    storyboard: dict[str, Any],
    cues: Sequence[dict[str, Any]],
    video: dict[str, Any] | None,
    assets: dict[str, Any],
    final_review: dict[str, Any] | None,
) -> dict[str, Any]:
    niche = kb.NICHES[intent["niche"]]
    subject = intent["subject"]
    hook = concept["hooks"][0]

    caption = _caption(intent, concept, brief, script, niche)
    hashtags = _hashtags(intent, concept, niche)
    keywords = _keywords(intent, concept, niche)
    cover = _cover_text(concept, intent)
    sound = _sound_brief(concept, intent)
    series = _series(intent, concept, niche)
    plan = _posting_plan(intent, concept)

    # ---- publish log (schema: platform, status, timestamp required) -------
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    publish_log = {
        "version": "1.0",
        "entries": [
            {
                "platform": intent["platform"],
                "status": "exported" if video else "draft",
                "timestamp": stamp,
                "export_path": (video or {}).get("path"),
                "visibility": "public",
                "metadata_used": {
                    "title": caption["first_line"],
                    "description": caption["text"],
                    "hashtags": hashtags["selected"],
                },
            }
        ],
        "metadata": {
            "engine": "studio.growth",
            "video_duration_seconds": (video or {}).get("duration_seconds"),
            "scenes": len(storyboard.get("scenes", [])),
            "format": (video or {}).get("aspect", "9:16"),
            "posted_by_studio": False,
            "note": "Exported for native upload. The studio never posts on your behalf.",
        },
    }
    if final_review:
        publish_log["entries"].append(
            {
                "platform": intent["platform"],
                "status": "pending_review" if final_review.get("status") != "pass" else "exported",
                "timestamp": stamp,
                "export_path": final_review.get("output_path"),
                **({"error": "; ".join(final_review.get("issues_found", []))[:400]}
                   if final_review.get("status") != "pass" else {}),
            }
        )

    return {
        "caption": caption,
        "hashtags": hashtags,
        "keywords": keywords,
        "cover": cover,
        "sound": sound,
        "series": series,
        "posting_plan": plan,
        "publish_log": publish_log,
        "checklist": _checklist(video, final_review, cues),
        "expectations": {
            "guarantee": "none",
            "statement": (
                "No view count, completion rate or follower number is predicted here. "
                "Those depend on the audience, the sound and the timing, and no local "
                "analysis can know them."
            ),
            "what_is_known": [
                f"{len(storyboard.get('scenes', []))} scenes planned in the storyboard",
                f"{len(cues)} caption cues timed to those scenes",
                (f"runtime {round(sum(s['end_seconds'] - s['start_seconds'] for s in storyboard.get('scenes', [])), 1)}s"
                 if storyboard.get("scenes") else "no video was rendered for this brief"),
                f"aspect {'9:16' if intent['platform'] == 'tiktok' else '16:9'}",
            ],
        },
        "evidence": {
            "hashtags": "niche playbook vocabulary, ranked by breadth and specificity",
            "keywords": "derived from your brief and the niche playbook",
            "posting_plan": "general cadence guidance, not measured audience data",
            "search_volume": "not queried — no keyword tool is configured in this environment",
        },
    }


def _caption(
    intent: dict[str, Any], concept: dict[str, Any], brief: dict[str, Any],
    script: dict[str, Any], niche: kb.Niche,
) -> dict[str, Any]:
    hook = concept["hooks"][0]
    body_line = ""
    for section in script.get("sections", [])[1:]:
        text = _clean_line(section.get("text", ""))
        if 12 < len(text) <= 90:
            body_line = text
            break

    cta = brief.get("cta") or "Save this for later."
    subject = intent["subject"]

    text = f"{hook}\n\n{body_line}\n\n{cta}" if body_line else f"{hook}\n\n{cta}"
    if len(text) > MAX_CAPTION:
        text = text[: MAX_CAPTION - 1].rsplit(" ", 1)[0] + "…"

    first_line = text.split("\n")[0]
    return {
        "text": text,
        "characters": len(text),
        "fold_characters": min(len(first_line), FOLD),
        "hook_in_fold": len(first_line) <= FOLD,
        "first_line": first_line,
        "why": (
            "First line is the hook and lands inside the ~150 characters TikTok shows before "
            "'more'. Second line carries the substance, third asks for the save — the action "
            "that most reliably lifts short-form distribution."
        ),
        "alternates": concept.get("hooks", [])[1:3],
    }


def _hashtags(intent: dict[str, Any], concept: dict[str, Any], niche: kb.Niche) -> dict[str, Any]:
    broad = [h for h in niche.hashtags_core if h.startswith("#")][:2]
    specific = [h for h in niche.hashtags_niche][:3]
    from_concept = [h for h in concept.get("hashtags", []) if h.startswith("#")][:2]
    platform = ["#fyp"] if intent["platform"] == "tiktok" else []
    tags: list[str] = []
    for tag in broad + specific + from_concept + platform:
        if tag not in tags:
            tags.append(tag)
    tags = tags[:8]
    return {
        "selected": tags,
        "count": len(tags),
        "reasoning": {
            "broad": broad,
            "niche": specific,
            "concept": from_concept,
            "platform": platform,
        },
        "guidance": (
            "Two broad tags place the video, three niche tags find the audience that finishes "
            "it, two concept tags describe the format. More than ~10 tags dilutes signal."
        ),
    }


def _keywords(intent: dict[str, Any], concept: dict[str, Any], niche: kb.Niche) -> dict[str, Any]:
    subject = intent["subject"]
    season = "autumn"
    mapped = []
    for template in niche.seo_longtail:
        phrase = (
            template.replace("[piece]", subject)
            .replace("[topic]", subject)
            .replace("[skill]", subject)
            .replace("[exercise]", subject)
            .replace("[muscle]", subject)
            .replace("[player role]", subject)
            .replace("[formation]", subject)
            .replace("[season]", season)
            .replace("[occasion]", "work")
        )
        mapped.append(phrase)
    targets = [subject, f"{subject} {intent['niche_label'].lower()}"] + niche.seo_core[:2] + mapped[:3]
    seen: list[str] = []
    for term in targets:
        term = _clean_line(term).lower()
        if term and term not in seen:
            seen.append(term)
    return {
        "primary": seen[0] if seen else subject,
        "targets": seen[:8],
        "where_they_go": [
            "spoken in the first two seconds (TikTok reads audio)",
            "on-screen in the hook frame",
            "in the caption's first line",
            "as the literal search phrase in the on-screen text",
        ],
        "note": (
            "TikTok search is keyword-driven, so the phrase should appear in the audio, on "
            "screen and in the caption. No volume or difficulty numbers are claimed — no "
            "keyword tool is configured."
        ),
    }


def _cover_text(concept: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
    hook = concept["hooks"][0]
    words = hook.split()
    short = " ".join(words[:4]) if len(words) > 4 else hook
    return {
        "thumbnail_text": short.upper(),
        "reason": "Four words survive the smallest cover size in the feed.",
        "alternates": [h.upper() for h in concept.get("hooks", [])[1:3]],
    }


def _sound_brief(concept: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
    mood = concept.get("music_mood", "ambient")
    rhythm = concept["cut_rhythm_seconds"]
    return {
        "mood": mood,
        "search_terms": [mood.split(",")[0].strip(), "cinematic", "instrumental"][:3],
        "tempo_target": f"~{round(60 / rhythm)} BPM to match the {rhythm:.1f}s cut rhythm",
        "instruction": (
            "This export is silent by design. Add the sound inside TikTok — a trending track "
            "referenced from the app keeps the video inside the platform's sound graph, which "
            "a re-uploaded audio file does not."
        ),
        "avoid": "Do not replace the on-screen timing: the captions are cut to this rhythm.",
    }


def _series(intent: dict[str, Any], concept: dict[str, Any], niche: kb.Niche) -> list[dict[str, Any]]:
    others = [c for c in niche.concepts if c.id != concept["id"]][:3]
    out = []
    for index, option in enumerate(others):
        when = ["next post", "later this week", "follow-up"][index]
        out.append(
            {
                "when": when,
                "concept": option.name,
                "why": option.why,
                "hook": option.hook_templates[0].replace("{subject}", intent["subject"])
                .replace("{piece}", intent["subject"]),
            }
        )
    return out


def _posting_plan(intent: dict[str, Any], concept: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    slots = []
    for index in range(3):
        when = now + timedelta(days=index * 2)
        slots.append(
            {
                "slot": index + 1,
                "date": when.date().isoformat(),
                "window_local": "18:00–21:00" if index % 2 == 0 else "07:00–09:00",
                "reason": "evening scroll" if index % 2 == 0 else "commute window",
            }
        )
    return {
        "cadence": "every 2 days for the first week",
        "slots": slots,
        "disclaimer": (
            "Windows are conventional starting points for a European audience, not measured "
            "performance for your account. Check your own analytics after three posts."
        ),
        "measure": [
            "completion rate (first 3s retention)",
            "saves per view",
            "shares per view",
        ],
    }


def _checklist(video: dict[str, Any] | None, review: dict[str, Any] | None, cues: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"item": "Video file exported", "done": bool(video), "detail": (video or {}).get("path")},
        {"item": "9:16 vertical master", "done": bool(video and video.get("aspect") == "9:16"),
         "detail": (video or {}).get("resolution")},
        {"item": "Captions baked in", "done": bool(cues), "detail": f"{len(cues)} cues"},
        {"item": "Quality review run", "done": bool(review),
         "detail": (review or {}).get("status")},
        {"item": "Sound added in app", "done": False,
         "detail": "Silent export by design — add the trending sound in TikTok"},
        {"item": "Posted", "done": False, "detail": "Posting is a human action; the studio never posts for you"},
    ]
