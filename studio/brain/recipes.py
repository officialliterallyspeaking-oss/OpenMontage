"""Shot recipes — the craft layer under the visual plan.

The studio used to choose a framing by cycling a list and a camera move by
``index % 5``. That is not direction: it produces four shots that are
*coincidentally* different rather than four shots that each do a job. The
result reads as generated, because nothing in the plan knows what a shot is
*for*.

A recipe is one established short-form device — an aperture that opens onto the
subject, a column of stacked type, a horizon that tilts on the turn — with the
things that make it work and the ways it usually fails. Shots are chosen by
what the beat has to accomplish, not by counting.

Two rules keep a recipe list from becoming a template library:

* **No immediate repeat.** Two shots built the same way in a row read as a
  stutter, however good the device is.
* **Energy has to match the cut.** A patient establishing hold in a 1.2 s cut
  rhythm is a dead frame; a whip-cut macro in a 3 s ballad reads as panic.

Nothing here renders. It decides, and says why, so the plan can be argued with.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Optional

# --------------------------------------------------------------------------- #
# Narrative function
# --------------------------------------------------------------------------- #

# Beat names in this codebase are written for humans ("cold open on detail",
# "tag the vibe"), so function is inferred from the words rather than assumed
# from position — position is only the tie-breaker.
FUNCTION_WORDS: dict[str, tuple[str, ...]] = {
    "hook": ("cold open", "hook", "opening"),
    "context": ("build", "version", "set up", "setup", "context", "explain", "where"),
    "detail": ("detail", "texture", "macro", "close", "insert", "material", "tease"),
    "turn": ("tension", "turn", "consequence", "change", "contrast", "twist",
             "anomaly", "but ", "instead"),
    "evidence": ("craft", "proof", "formula", "evidence", "reason", "why", "because"),
    "payoff": ("reveal", "hero", "full look", "payoff", "result", "finale"),
    "close": ("tag", "landing", "closing", "the line", "save", "outro", "end"),
}

# When two functions are described equally well, the more specific craft wins:
# a beat called "tease a detail" wants a detail device, not a second hook.
FUNCTION_PRIORITY = ("detail", "turn", "evidence", "context", "payoff", "close", "hook")

FUNCTION_ORDER = ("hook", "detail", "context", "turn", "evidence", "payoff", "close")


def classify(beat: str, index: int, total: int) -> str:
    """What does this beat have to *do*?

    Position decides the ends: the first beat is the hook whatever it is called,
    and the last is the close. In between, a piece gets exactly one hook — so
    the word "tease" mid-film means *show a detail*, not *open again*. Three
    hooks in a fifteen-second piece is not three chances; it is a film that
    never gets started.
    """
    lowered = f" {beat.lower()} "
    if index == 0:
        return "hook"
    if total > 1 and index == total - 1:
        return "close"

    best, best_hits = None, 0
    for function in FUNCTION_PRIORITY:
        if function == "hook":
            continue  # one hook, at the top
        words = FUNCTION_WORDS[function]
        hits = sum(1 for word in words if word in lowered)
        if hits > best_hits:
            best, best_hits = function, hits
    if best:
        return best
    # nothing matched: spend the middle of the piece building, then proving
    middle = (total - 2) or 1
    return "context" if index <= middle / 2 else "evidence"


# --------------------------------------------------------------------------- #
# The catalogue
# --------------------------------------------------------------------------- #
#
# ``composition`` names one of localfx.COMPOSITIONS, so choosing a recipe
# actually changes the artwork rather than only the words about it.

RECIPES: tuple[dict[str, Any], ...] = (
    # -- hooks: earn the next two seconds -----------------------------------
    {
        "id": "aperture-open",
        "name": "Aperture open",
        "function": "hook",
        "composition": "aperture",
        "movement": "zoom_in",
        "energy": "high",
        "seconds": (1.0, 2.4),
        "grammar": "A ring of light opens over the subject while the first line lands in the hole it leaves.",
        "why": "Concentric rings give the eye a place to rest and a reason to keep looking; the subject is never fully described, which is what holds attention.",
        "pitfall": "Opening too slowly. Under 2.4 s the ring must reach its widest by the first beat or the hook has already lost.",
    },
    {
        "id": "type-first",
        "name": "Type first",
        "function": "hook",
        "composition": "column",
        "movement": "ken_burns",
        "energy": "mid",
        "seconds": (1.2, 2.6),
        "grammar": "The words arrive before any image does, set to the full height of the frame.",
        "why": "On a feed read in silence, the first frame is a headline. A column of type states the promise without needing a picture to have been made yet.",
        "pitfall": "A full sentence in the column. Three or four words carry; a paragraph turns the hook into homework.",
    },
    {
        "id": "macro-insert",
        "name": "Macro insert",
        "function": "hook",
        "composition": "field",
        "movement": "zoom_in",
        "energy": "high",
        "seconds": (0.8, 2.0),
        "grammar": "So close on texture that the object is not yet identifiable.",
        "why": "Unrecognised texture creates a question the viewer stays to answer. It also reads as expensive, which is useful before you have explained anything.",
        "pitfall": "Holding past two seconds. Once the eye identifies the object the question is gone, and so is the reason to keep watching.",
    },
    # -- detail: the quality argument ---------------------------------------
    {
        "id": "plates",
        "name": "Two plates",
        "function": "detail",
        "composition": "plates",
        "movement": "pan_right",
        "energy": "mid",
        "seconds": (1.4, 3.2),
        "grammar": "Two panels held in the same frame — the thing, and what it is made of.",
        "why": "Comparison inside one frame reads faster than two shots cut together, and it makes an argument instead of a mood.",
        "pitfall": "Two halves of the same picture. If the panels do not differ in kind, it is decoration.",
    },
    {
        "id": "horizon-tilt",
        "name": "Horizon tilt",
        "function": "detail",
        "composition": "horizon",
        "movement": "pan_up",
        "energy": "low",
        "seconds": (1.6, 3.6),
        "grammar": "A level horizon that drifts a few degrees, revealing weight and material.",
        "why": "A nearly-level line with a slow drift is the calmest way to say 'this is well made'.",
        "pitfall": "An actual Dutch angle. A few degrees reads as care; twenty reads as an accident.",
    },
    # -- context: where we are ----------------------------------------------
    {
        "id": "establish-hold",
        "name": "Establishing hold",
        "function": "context",
        "composition": "horizon",
        "movement": "ken_burns",
        "energy": "low",
        "seconds": (2.0, 4.5),
        "grammar": "The widest frame in the piece, held still enough to read.",
        "why": "One plain, legible frame resets the eye after a fast hook and tells the viewer where they now are.",
        "pitfall": "Using it first. An establishing shot as shot one spends the hook on geography.",
    },
    {
        "id": "column-stack",
        "name": "Column stack",
        "function": "context",
        "composition": "column",
        "movement": "pan_up",
        "energy": "mid",
        "seconds": (1.4, 3.0),
        "grammar": "Vertical bands stack into the frame, each carrying one clause of the idea.",
        "why": "Vertical structure matches the phone, and stacking lets a list of three read in one shot instead of three.",
        "pitfall": "More than four bands. Past four the eye stops counting and the list stops being a list.",
    },
    {
        "id": "field-quiet",
        "name": "Quiet field",
        "function": "context",
        "composition": "field",
        "movement": "ken_burns",
        "energy": "low",
        "seconds": (2.0, 4.0),
        "grammar": "A single soft mass in an empty frame, with room for a line of copy.",
        "why": "Negative space is where the viewer's own thought goes. It is the cheapest way to make a claim feel considered.",
        "pitfall": "Pairing it with a busy caption. The frame is already saying 'room to think'; do not fill it.",
    },
    # -- turn: the reason to stay -------------------------------------------
    {
        "id": "aperture-close",
        "name": "Aperture close",
        "function": "turn",
        "composition": "aperture",
        "movement": "zoom_out",
        "energy": "high",
        "seconds": (1.0, 2.2),
        "grammar": "The ring pulls shut, cropping what was on screen down to one thing.",
        "why": "Removing information at the turn is more persuasive than adding it — the viewer leans in to see what was kept.",
        "pitfall": "Closing on nothing in particular. The thing that survives the crop has to be the point.",
    },
    {
        "id": "plates-flip",
        "name": "Plates flip",
        "function": "turn",
        "composition": "plates",
        "movement": "pan_left",
        "energy": "high",
        "seconds": (0.8, 1.8),
        "grammar": "The two panels trade emphasis — what was background becomes the subject.",
        "why": "Reversing inside a single frame reads as a genuine change of mind rather than a new topic.",
        "pitfall": "Doing it twice. The flip is a turn; a second one makes the piece spin.",
    },
    {
        "id": "column-break",
        "name": "Column break",
        "function": "turn",
        "composition": "column",
        "movement": "zoom_in",
        "energy": "high",
        "seconds": (0.8, 1.8),
        "grammar": "One band widens and pushes the others out of frame.",
        "why": "Interrupting an established pattern is the cheapest legitimate surprise available without new footage.",
        "pitfall": "Breaking a pattern the viewer never learned. The column has to be established for at least one shot first.",
    },
    # -- evidence: the part that has to be true -----------------------------
    {
        "id": "macro-evidence",
        "name": "Macro evidence",
        "function": "evidence",
        "composition": "field",
        "movement": "zoom_in",
        "energy": "mid",
        "seconds": (1.6, 3.4),
        "grammar": "Close enough that the material itself is the argument — weave, grain, seam, joint.",
        "why": "Claims about quality are settled by texture, not adjectives.",
        "pitfall": "Stock-grade texture. A soft or upscaled insert contradicts the line it is supposed to prove.",
    },
    {
        "id": "horizon-measure",
        "name": "Horizon measure",
        "function": "evidence",
        "composition": "horizon",
        "movement": "pan_right",
        "energy": "mid",
        "seconds": (1.4, 3.0),
        "grammar": "A level line with one element deliberately set against it, so proportion is visible.",
        "why": "Proportion is the one thing a viewer can verify from a still frame without trusting the voice-over.",
        "pitfall": "Measuring something nobody asked about. If the number is not part of the claim, the line is just a rule.",
    },
    # -- payoff --------------------------------------------------------------
    {
        "id": "full-reveal",
        "name": "Full reveal",
        "function": "payoff",
        "composition": "aperture",
        "movement": "zoom_out",
        "energy": "mid",
        "seconds": (2.0, 4.0),
        "grammar": "The widest, cleanest frame in the piece, subject whole and centred, everything else removed.",
        "why": "After the argument, the viewer has earned one clear look at the thing.",
        "pitfall": "Revealing something already shown at full size. A payoff has to be information, not repetition.",
    },
    {
        "id": "plates-lockup",
        "name": "Plates lockup",
        "function": "payoff",
        "composition": "plates",
        "movement": "zoom_in",
        "energy": "mid",
        "seconds": (1.8, 3.4),
        "grammar": "The pieces seen separately now sit inside one frame, locked together.",
        "why": "Assembling the parts answers the question the detail shots raised, without a word of explanation.",
        "pitfall": "Locking up parts the viewer has not seen apart. The payoff needs the earlier shots to have done their job.",
    },
    # -- close ---------------------------------------------------------------
    {
        "id": "bookend",
        "name": "Bookend",
        "function": "close",
        "composition": "aperture",
        "movement": "ken_burns",
        "energy": "low",
        "seconds": (1.8, 3.6),
        "grammar": "Return to the opening frame, held still, with the closing line in the space the hook left.",
        "why": "Recognising the first frame again is what makes a fifteen-second piece feel finished rather than stopped.",
        "pitfall": "Reusing the hook's copy here. The frame repeats; the words have to move on.",
    },
    {
        "id": "field-close",
        "name": "Quiet close",
        "function": "close",
        "composition": "field",
        "movement": "zoom_out",
        "energy": "low",
        "seconds": (2.0, 4.0),
        "grammar": "Pull back until the subject is one small mass in a wide, empty frame.",
        "why": "Giving the subject less of the frame hands the viewer the closing thought instead of insisting on it.",
        "pitfall": "Pulling back into a busy background. Emptiness is the whole device.",
    },
    {
        "id": "column-sign-off",
        "name": "Column sign-off",
        "function": "close",
        "composition": "column",
        "movement": "pan_up",
        "energy": "mid",
        "seconds": (1.4, 2.8),
        "grammar": "The stack resolves to a single band carrying the closing line.",
        "why": "Ending on structure rather than spectacle keeps a save-worthy piece feeling like advice, not an ad.",
        "pitfall": "Ending on a CTA card. The save prompt belongs in the caption, not in the last frame of the film.",
    },
)

BY_ID = {recipe["id"]: recipe for recipe in RECIPES}


def _energy_fit(recipe: dict[str, Any], rhythm_seconds: float) -> float:
    """How well a recipe's natural hold matches the cut rhythm."""
    low, high = recipe["seconds"]
    if low <= rhythm_seconds <= high:
        return 1.0
    # distance outside the window, normalised so it is comparable with 1.0
    gap = low - rhythm_seconds if rhythm_seconds < low else rhythm_seconds - high
    return max(0.0, 1.0 - gap / max(1.0, rhythm_seconds))


def _seed(*parts: Any) -> hash:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


def select_recipes(
    beats: Iterable[dict[str, Any]],
    *,
    rhythm_seconds: float = 2.0,
    has_image: bool = False,
    treatment: str = "",
) -> list[dict[str, Any]]:
    """One recipe per beat, with the reason it was chosen.

    Deterministic for the same inputs — a re-run of the same brief has to
    produce the same film, or a refinement is not a refinement.
    """
    beats = list(beats)
    total = len(beats)
    chosen: list[dict[str, Any]] = []
    used: set[str] = set()
    previous_composition: Optional[str] = None
    composition_uses: dict[str, int] = {}

    for index, beat in enumerate(beats):
        label = str(beat.get("beat", ""))
        function = classify(label, index, total)
        duration = float(beat.get("end_seconds", 0)) - float(beat.get("start_seconds", 0)) or rhythm_seconds

        scored: list[tuple[float, dict[str, Any], list[str]]] = []
        for recipe in RECIPES:
            if function not in {recipe["function"], "payoff"}:
                continue
            reasons: list[str] = []
            score = 1.0 if recipe["function"] == function else 0.45

            energy = _energy_fit(recipe, min(duration, rhythm_seconds))
            score += energy * 1.4
            if energy == 1.0:
                reasons.append(f"its {recipe['seconds'][0]:g}–{recipe['seconds'][1]:g}s hold fits the "
                               f"{min(duration, rhythm_seconds):.1f}s cut")

            if recipe["composition"] == previous_composition:
                score -= 0.9
                reasons.append("but it repeats the previous frame's shape")
            # Not only the neighbour matters: two shots built on the same mass
            # at opposite ends of a fifteen-second piece still read as the same
            # frame seen twice, and a viewer notices that before they notice
            # anything clever.
            reuses = composition_uses.get(recipe["composition"], 0)
            if reuses:
                score -= 0.75 * reuses
            if recipe["id"] in used:
                score -= 1.2
            if has_image and recipe["composition"] in {"field", "horizon"}:
                score += 0.2  # the photo is the texture, so let it be seen

            # a stable tie-break, so equal scores do not depend on dict order
            score += (_seed(treatment, index, recipe["id"]) % 100) / 1000
            scored.append((score, recipe, reasons))

        if not scored:  # impossible with this catalogue, but never crash a plan
            recipe = BY_ID["field-quiet"]
            scored = [(1.0, recipe, [])]

        scored.sort(key=lambda row: row[0], reverse=True)
        score, recipe, reasons = scored[0]

        chosen.append(
            {
                "beat": label,
                "function": function,
                "id": recipe["id"],
                "name": recipe["name"],
                "composition": recipe["composition"],
                "movement": recipe["movement"],
                "grammar": recipe["grammar"],
                "why": recipe["why"],
                "pitfall": recipe["pitfall"],
                "hold_seconds": list(recipe["seconds"]),
                "reason": "; ".join(reasons) or f"it does the {function} job nothing else on the sheet does",
            }
        )
        used.add(recipe["id"])
        previous_composition = recipe["composition"]
        composition_uses[recipe["composition"]] = composition_uses.get(recipe["composition"], 0) + 1

    return chosen


def summary(chosen: list[dict[str, Any]]) -> dict[str, Any]:
    """What the viewer of the plan needs: variety and coverage in one object."""
    functions = [c["function"] for c in chosen]
    return {
        "shot_count": len(chosen),
        "distinct_devices": len({c["id"] for c in chosen}),
        "composition_spread": len({c["composition"] for c in chosen}),
        "functions": functions,
        "repeats": [
            chosen[i]["id"]
            for i in range(1, len(chosen))
            if chosen[i]["id"] == chosen[i - 1]["id"]
        ],
    }
