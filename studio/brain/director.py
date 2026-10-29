"""System 1 — Viral Content Director.

Turns a sentence (and optionally an image) into a decided creative direction.

This is not prompt-writing. It is judgement, made explicit:

1. **Interpret** the request: what is being made, for whom, on which platform,
   at what length, in which niche, with which creative traits.
2. **Generate angles**: every concept in the niche's playbook, instantiated
   against this subject.
3. **Score** each angle against the request's traits and platform mechanics —
   with the *reasons* attached, so the choice is auditable rather than asserted.
4. **Decide**: pick the winner, name the runner-up and why it lost.
5. **Brief**: emit a schema-valid brief plus a hook set and beat sheet that the
   production engine can actually execute.

Honesty: `confidence` reflects how much the request genuinely constrained the
decision. A vague prompt gets a lower score and a stated assumption list; we do
not dress up a guess as certainty.
"""

from __future__ import annotations

import re
from typing import Any

from studio.brain import knowledge as kb
from studio.brain.projects import Project


# ---------------------------------------------------------------------------
# interpretation
# ---------------------------------------------------------------------------

def _says(text: str, words: list[str]) -> bool:
    """Whole-word match, so 'poster' does not read as 'post' or 'image'."""
    for word in words:
        if re.search(rf"(?<![a-z]){re.escape(word)}(?:s|es)?(?![a-z])", text):
            return True
    return False


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _read_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", _clean(text))
    return [p.strip(" .") for p in parts if p.strip(" .")]


DETERMINERS = {"a", "an", "the", "this", "that", "these", "those", "my", "our", "your",
               "some", "any", "each", "every"}
FILLERS = {"really", "very", "quite", "super", "kind", "of", "sort", "with", "for", "and", "to", "in", "on"}


def _subject_of(text: str, niche: kb.Niche) -> tuple[str, bool]:
    """The concrete thing the piece is about, plus whether we actually found it."""
    lower = (text or "").lower()
    for word in sorted(niche.subjects, key=len, reverse=True):
        if re.search(rf"\b{re.escape(word)}\w*", lower):
            # keep a compound like "wool coat" when the noun has a modifier
            match = re.search(rf"((?:[a-z]+\s+){{0,2}}{re.escape(word)}\w*)", lower)
            phrase = match.group(1).strip() if match else word
            tokens = [t for t in phrase.split() if t not in DETERMINERS and t not in FILLERS]
            if tokens:
                return " ".join(tokens[-2:]), True
            return word, True

    # No known subject: take the last noun-ish phrase of the first clause, which
    # is where English puts the head noun ("... tailored wool coat").
    clause = re.split(r"[,.;]", _read_sentences(text)[0] if _read_sentences(text) else text)[0]
    tokens = [t for t in re.findall(r"[a-zA-Z][a-zA-Z'\-]*", clause.lower())
              if t not in DETERMINERS and t not in FILLERS]
    if tokens:
        return " ".join(tokens[-3:]), False
    return niche.subjects[0], False


def interpret(request: dict[str, Any], image_facts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read the request the way a creative director reads a client call."""
    text = _clean(request.get("text") or "")
    has_image = bool(request.get("upload_path"))
    lower = text.lower()

    niche, niche_scores = kb.niche_for_text(text)
    subject, subject_found = _subject_of(text, niche)
    traits = kb.traits_for_text(text)

    # -- deliverable --------------------------------------------------------
    deliverable = "video"
    if has_image and not _says(lower, kb.DELIVERABLE_LEXICON["video"]):
        deliverable = "video"  # an image alone still implies motion: it is a still
    wants_campaign = _says(lower, kb.DELIVERABLE_LEXICON["campaign"])
    wants_image_only = (
        _says(lower, kb.DELIVERABLE_LEXICON["image"])
        and not _says(lower, kb.DELIVERABLE_LEXICON["video"])
    )
    if wants_image_only and not wants_campaign:
        deliverable = "image"
    elif wants_campaign:
        deliverable = "campaign"

    # -- platform -----------------------------------------------------------
    platform, platform_evidence = "tiktok", "default"
    explicit = request.get("platform")
    if explicit:
        platform, platform_evidence = str(explicit).lower(), "requested"
    else:
        for name, words in kb.PLATFORM_LEXICON.items():
            if _says(lower, words):
                platform = name
                platform_evidence = f"mentioned '{next(w for w in words if _says(lower, [w]))}'"
                break
        else:
            aspect = request.get("aspect")
            if aspect in kb.ASPECT_PLATFORM:
                platform = kb.ASPECT_PLATFORM[aspect]
                platform_evidence = f"aspect {aspect}"

    # -- duration -----------------------------------------------------------
    duration, duration_evidence = 15.0, "TikTok default"
    explicit_duration = request.get("duration_seconds")
    if explicit_duration:
        duration, duration_evidence = float(explicit_duration), "requested"
    else:
        match = re.search(r"(\d{1,2})\s*(?:s|sec|secs|second|seconds)\b", lower)
        if match:
            duration, duration_evidence = float(match.group(1)), f"mentioned '{match.group(0)}'"
    if platform == "tiktok":
        duration = max(7.0, min(60.0, duration))
    elif platform == "instagram":
        duration = max(7.0, min(60.0, duration))
    else:
        duration = max(5.0, min(120.0, duration))

    # -- audience -----------------------------------------------------------
    audience = niche.audiences[0]
    aud_match = re.search(r"for ([a-z0-9 \-]{3,40}?)(?:[,.!]|$)", lower)
    if aud_match:
        audience = aud_match.group(1).strip()

    # -- tone ---------------------------------------------------------------
    tone_hits = [w for w in niche.tone_words if w in lower]
    if "funny" in lower:
        tone_hits.append("playful")
    tone = tone_hits[0] if tone_hits else ("premium" if traits.get("premium") else "clear and confident")

    # -- assumptions --------------------------------------------------------
    assumptions: list[str] = []
    if not subject_found:
        assumptions.append(f"No specific {niche.label.lower()} subject was named, so I interpreted it as '{subject}'.")
    if platform_evidence in {"default", "aspect"}:
        assumptions.append(f"No platform specified — optimising for TikTok ({duration:.0f}s, 9:16).")
    if duration_evidence == "TikTok default":
        assumptions.append(f"No length specified — {duration:.0f}s is the strongest watch-time window for this format.")
    if not tone_hits:
        assumptions.append("No tone specified — using the tone that performs best for this niche.")

    confidence = 0.35
    if subject_found:
        confidence += 0.25
    if platform_evidence != "default":
        confidence += 0.15
    if tone_hits:
        confidence += 0.15
    if has_image:
        confidence += 0.10
    confidence = round(min(0.95, confidence), 2)

    intent: dict[str, Any] = {
        "text": text,
        "subject": subject,
        "subject_found": subject_found,
        "niche": niche.id,
        "niche_label": niche.label,
        "niche_scores": niche_scores,
        "traits": traits,
        "deliverable": deliverable,
        "wants_campaign": wants_campaign,
        "platform": platform,
        "platform_evidence": platform_evidence,
        "duration_seconds": round(duration, 1),
        "duration_evidence": duration_evidence,
        "audience": audience,
        "tone": tone,
        "has_image": has_image,
        "confidence": confidence,
        "assumptions": assumptions,
        "sentences": _read_sentences(text),
        "keywords": _keywords(text),
    }
    if image_facts:
        intent["image"] = image_facts
        # An image is strong evidence: let its palette drive the tone if the
        # request was silent about mood.
        if not tone_hits and image_facts.get("warmth") is not None:
            intent["tone"] = "warm" if image_facts["warmth"] > 0.55 else "cool and cinematic"
    return intent


def _keywords(text: str) -> list[str]:
    stop = {
        "the", "a", "an", "and", "or", "for", "with", "that", "this", "make", "create",
        "video", "tiktok", "about", "into", "from", "your", "our", "its", "it's", "of",
        "to", "in", "on", "at", "is", "are", "be", "me", "my", "we", "you", "i",
        "please", "want", "need", "should", "would", "could", "some", "very", "really",
    }
    words = re.findall(r"[a-zA-Z][a-zA-Z'\-]{2,}", (text or "").lower())
    seen: list[str] = []
    for word in words:
        if word in stop or word in seen:
            continue
        seen.append(word)
    return seen[:12]


# ---------------------------------------------------------------------------
# angles & scoring
# ---------------------------------------------------------------------------

def _instantiate(template: str, subject: str, piece: str, niche: kb.Niche) -> str:
    return (
        template.replace("{subject}", subject)
        .replace("{piece}", piece)
        .replace("{city}", "Amsterdam")
        .replace("{season}", "autumn")
        .replace("{occasion}", "work")
        .replace("{months}", "12 months")
    )


def _score_concept(
    concept: kb.Concept, intent: dict[str, Any], image_facts: dict[str, Any] | None
) -> dict[str, Any]:
    """Score 0-100 with an itemised, human-readable reason for every point."""
    traits = intent.get("traits") or {}
    reasons: list[dict[str, Any]] = []
    score = 50.0

    def add(points: float, why: str) -> None:
        nonlocal score
        score += points
        reasons.append({"points": round(points, 1), "why": why})

    # 1. trait fit ---------------------------------------------------------
    for trait, weight in traits.items():
        fit = concept.fits.get(trait)
        if fit is None:
            continue
        delta = round((fit - 0.5) * 28 * weight, 1)
        if abs(delta) >= 1:
            add(delta, f"matches your '{trait}' cue ({int(fit * 100)}% fit)")

    # 2. platform mechanics ------------------------------------------------
    platform = intent.get("platform")
    duration = float(intent.get("duration_seconds") or 15)
    beats = len(concept.structure)
    # Rhythmic concepts need enough runtime to land their cuts.
    needed = concept.cut_rhythm * beats
    if duration >= needed:
        add(4.0, f"{beats} beats fit comfortably in {duration:.0f}s")
    else:
        add(-8.0, f"needs ~{needed:.0f}s of rhythm but only {duration:.0f}s is available")
    if platform == "tiktok" and concept.narration == "none":
        add(2.0, "no narration is native to the TikTok feed")
    if platform == "tiktok" and concept.cut_rhythm <= 2.0:
        add(2.0, "cut rhythm is fast enough to hold the first three seconds")

    # 3. source material ---------------------------------------------------
    if intent.get("has_image"):
        if concept.motion.lower().startswith(("slow", "static", "macro")):
            add(6.0, "works from a single still without pretending to be new footage")
        if concept.id in {"sports-hype", "street-style-cut"}:
            add(-6.0, "expects real movement a still cannot supply")

    # 4. niche default bias ------------------------------------------------
    if concept.id == "editorial-film" and intent.get("niche") == "fashion":
        add(3.0, "the highest-performing format in fashion for still-image sources")

    # 5. honesty guard -----------------------------------------------------
    if concept.id == "debate-bait" and intent.get("niche") == "sports":
        add(-3.0, "invites claims that would need verification")

    # 6. image brightness sanity ------------------------------------------
    if image_facts:
        brightness = image_facts.get("brightness")
        if brightness is not None:
            if brightness < 0.22 and concept.text_style.startswith("small"):
                add(-4.0, "dark source image would swallow small type")
            if brightness > 0.78 and "high contrast" in concept.treatment.lower():
                add(-2.0, "bright source image fights a high-contrast grade")

    score = max(1.0, min(99.0, score))
    return {"score": round(score, 1), "reasons": reasons}


def direct(project: Project, intent: dict[str, Any]) -> dict[str, Any]:
    """Produce ranked angles, a decision, and the creative brief components."""
    niche = kb.NICHES[intent["niche"]]
    subject = intent["subject"]
    image_facts = intent.get("image")
    text = intent.get("text") or ""

    # A "piece" is the concrete noun a hook can point at (garment, drill, ...).
    piece = subject

    options: list[dict[str, Any]] = []
    for concept in niche.concepts:
        scored = _score_concept(concept, intent, image_facts)
        hooks = [_instantiate(h, subject, piece, niche) for h in concept.hook_templates]
        options.append(
            {
                "id": concept.id,
                "name": concept.name,
                "description": concept.why,
                "score": scored["score"],
                "reasons": scored["reasons"],
                "hook": hooks[0],
                "hooks": hooks,
                "structure": [
                    {"beat": beat, "share": round(share, 3)} for beat, share in concept.structure
                ],
                "treatment": concept.treatment,
                "motion": concept.motion,
                "cut_rhythm_seconds": concept.cut_rhythm,
                "text_style": concept.text_style,
                "music_mood": concept.music_mood,
                "narration": concept.narration,
                "seo_terms": concept.seo_terms,
                "hashtags": concept.hashtags,
            }
        )
    options.sort(key=lambda o: o["score"], reverse=True)

    selected = options[0]
    runner_up = options[1] if len(options) > 1 else None
    why_not = ""
    if runner_up:
        gap = round(selected["score"] - runner_up["score"], 1)
        losing = [r for r in runner_up["reasons"] if r["points"] < 0]
        reason = losing[0]["why"] if losing else "scored lower on fit"
        why_not = (
            f"'{runner_up['name']}' was close ({gap:+.1f} pts) but {reason}."
            if gap < 8
            else f"'{runner_up['name']}' trailed by {gap:.1f} pts — {reason}."
        )

    concept_payload = {
        "selected": {
            "id": selected["id"],
            "name": selected["name"],
            "score": selected["score"],
            "why": selected["why"] if "why" in selected else selected["description"],
            "hook": selected["hook"],
            "hooks": selected["hooks"],
            "structure": selected["structure"],
            "treatment": selected["treatment"],
            "motion": selected["motion"],
            "cut_rhythm_seconds": selected["cut_rhythm_seconds"],
            "text_style": selected["text_style"],
            "music_mood": selected["music_mood"],
            "narration": selected["narration"],
        },
        "options": options,
        "runner_up": runner_up["name"] if runner_up else None,
        "why_not": why_not,
        "decided_by": "trait fit, platform mechanics, source-material suitability",
    }

    brief = build_brief(intent, selected, niche, options)
    hooks = hook_set(intent, selected, niche, options)
    beats = beat_sheet(intent, selected)

    return {
        "concept": concept_payload,
        "brief": brief,
        "hooks": hooks,
        "beats": beats,
    }


def build_brief(intent: dict[str, Any], selected: dict[str, Any], niche: kb.Niche,
                options: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A brief that satisfies schemas/artifacts/brief.schema.json."""
    subject = intent["subject"]
    duration = float(intent["duration_seconds"])
    pool = options or []
    angle_options = [
        {"name": o["name"], "description": f"{o.get('description', o.get('why', ''))} "
                                          f"(score {o.get('score', '—')})"}
        for o in pool[:5] if o.get("id") != selected.get("id")
    ]
    angle_options = [
        {"name": selected["name"],
         "description": selected.get("description") or selected.get("why") or selected.get("treatment", "")}
    ] + angle_options

    key_points = [
        selected["hook"],
        f"{selected['treatment']}",
        f"Built for {intent['audience']} on {intent['platform']}",
        f"{duration:.0f}s at {selected['cut_rhythm_seconds']}s per beat",
    ]
    return {
        "version": "1.0",
        "title": f"{selected['name']}: {subject}"[:90],
        "hook": selected["hook"],
        "key_points": key_points,
        "tone": intent["tone"],
        "style": f"{selected['treatment']} · {selected['music_mood']}",
        "target_platform": intent["platform"] if intent["platform"] in {
            "youtube", "instagram", "tiktok", "linkedin", "generic"
        } else "generic",
        "target_duration_seconds": duration,
        "target_audience": intent["audience"],
        "angle_options": angle_options,
        "selected_angle": selected["name"],
        "cta": _cta(intent),
        "metadata": {
            "created_by": "studio.director",
            "credibility_note": niche.credibility_note,
            "narration_mode": selected["narration"],
            "assumptions": intent.get("assumptions", []),
            "confidence": intent.get("confidence"),
        },
    }


def _cta(intent: dict[str, Any]) -> str:
    if intent["platform"] == "tiktok":
        return "Save this for the next time you need it."
    if intent["platform"] == "linkedin":
        return "Follow for more breakdowns like this."
    return "Follow for more."


def hook_set(intent: dict[str, Any], selected: dict[str, Any], niche: kb.Niche,
             options: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Several hooks so the user — or a test — can swap without re-deciding."""
    primary = selected["hooks"][0]
    alternates = selected["hooks"][1:]
    # borrow one hook from the next-best concept for variety
    for option in options or []:
        if option["id"] != selected["id"] and option["hook"] not in alternates:
            alternates.append(option["hook"])
            break
    scores = []
    for i, hook in enumerate([primary] + alternates):
        words = len(hook.split())
        length_fit = 1.0 if words <= 9 else max(0.4, 1 - (words - 9) * 0.08)
        curiosity = 0.9 if re.search(r"\?|not|nobody|never|why|wait|stop|secret", hook.lower()) else 0.7
        scores.append(
            {
                "hook": hook,
                "length_words": words,
                "score": round((length_fit * 0.55 + curiosity * 0.45) * 100, 1),
                "note": "recommended" if i == 0 else "alternative",
            }
        )
    scores.sort(key=lambda h: h["score"], reverse=True)
    return {"primary": primary, "options": scores}


def beat_sheet(intent: dict[str, Any], selected: dict[str, Any]) -> list[dict[str, Any]]:
    duration = float(intent["duration_seconds"])
    beats = []
    cursor = 0.0
    for i, beat in enumerate(selected["structure"]):
        share = beat["share"]
        length = round(duration * share, 2)
        end = round(duration, 2) if i == len(selected["structure"]) - 1 else round(cursor + length, 2)
        beats.append(
            {
                "index": i,
                "beat": beat["beat"],
                "start_seconds": round(cursor, 2),
                "end_seconds": end,
                "share": share,
            }
        )
        cursor = end
    return beats
