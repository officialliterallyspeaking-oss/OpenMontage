"""The craft layer: recipes choose devices by intent, not by index.

These tests exist because the failure mode of a "shot library" is quiet: it
keeps producing plausible-looking plans while every shot is structurally the
same. So the assertions here are about *variety and fit*, not about the strings
coming out of a template.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from studio.brain import localfx, recipes  # noqa: E402


def _beats(names: list[str], length: float = 2.2) -> list[dict]:
    return [
        {"beat": name, "start_seconds": round(i * length, 2), "end_seconds": round((i + 1) * length, 2)}
        for i, name in enumerate(names)
    ]


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #

def test_first_beat_is_the_hook_whatever_it_is_called() -> None:
    assert recipes.classify("the anomaly", 0, 5) == "hook"
    assert recipes.classify("anything at all", 0, 5) == "hook"


def test_last_beat_is_the_close_whatever_it_is_called() -> None:
    assert recipes.classify("the craft", 4, 5) == "close"


def test_middle_beats_are_read_from_their_words() -> None:
    assert recipes.classify("tease a detail", 1, 5) == "detail"
    assert recipes.classify("build tension", 1, 5) == "turn"
    assert recipes.classify("reveal the full look", 3, 5) == "payoff"


def test_a_piece_never_gets_a_second_hook() -> None:
    """'cold open' in the middle means a detail, not another opening.

    Three hooks in a fifteen-second film is not three chances to grab someone;
    it is a film that restarts instead of building.
    """
    got = [recipes.classify(name, i, 4) for i, name in enumerate(
        ["cold open on detail", "cold open again", "hook line", "hook tag"]
    )]
    assert got.count("hook") == 1
    assert got[0] == "hook"


def test_a_specific_craft_word_beats_a_generic_one() -> None:
    """'tease a detail' is a detail beat, not a hook or a turn."""
    assert recipes.classify("tease a detail", 2, 6) == "detail"


# --------------------------------------------------------------------------- #
# the catalogue itself
# --------------------------------------------------------------------------- #

def test_every_recipe_is_a_complete_idea() -> None:
    """A card without a pitfall is a card nobody can use to argue with."""
    required = {"id", "name", "function", "composition", "movement", "energy",
                "seconds", "grammar", "why", "pitfall"}
    for recipe in recipes.RECIPES:
        assert required <= set(recipe), f"{recipe.get('id')} is missing fields"
        assert recipe["grammar"] and recipe["why"] and recipe["pitfall"]
        assert len(recipe["pitfall"]) > 30, f"{recipe['id']}'s pitfall says nothing"


def test_recipe_ids_are_unique() -> None:
    ids = [r["id"] for r in recipes.RECIPES]
    assert len(ids) == len(set(ids))


def test_every_recipe_names_a_composition_that_exists() -> None:
    """The recipe must change the artwork, not only the words about it."""
    for recipe in recipes.RECIPES:
        assert recipe["composition"] in localfx.COMPOSITIONS_BY_NAME, recipe["id"]


def test_the_catalogue_covers_every_function() -> None:
    covered = {r["function"] for r in recipes.RECIPES}
    assert covered == set(recipes.FUNCTION_ORDER)


def test_compositions_are_named_not_indexed() -> None:
    assert set(localfx.COMPOSITIONS_BY_NAME) == {
        "aperture", "column", "horizon", "plates", "field"
    }


# --------------------------------------------------------------------------- #
# selection
# --------------------------------------------------------------------------- #

def test_one_recipe_per_beat_in_order() -> None:
    beats = _beats(["cold open on detail", "build tension", "the craft", "tag the vibe"])
    got = recipes.select_recipes(beats)
    assert len(got) == len(beats)
    assert [g["beat"] for g in got] == [b["beat"] for b in beats]
    assert got[0]["function"] == "hook" and got[-1]["function"] == "close"


def test_no_two_consecutive_shots_use_the_same_device() -> None:
    beats = _beats(["cold open on detail", "reveal the full look", "the craft", "tag the vibe"])
    got = recipes.select_recipes(beats)
    for previous, current in zip(got, got[1:]):
        assert current["id"] != previous["id"], f"{current['id']} repeated back to back"


def test_the_whole_piece_varies_its_frame_shape() -> None:
    """Two shots built on the same mass read as the same frame seen twice.

    The failure this guards against is not a lack of distinct shapes — six
    shots can use four shapes and still look repetitive. It is *concentration*:
    one shape coming back again and again, which turns the film into a
    slideshow with a filter over it. So the rule is a ceiling on reuse, and it
    has to hold across the whole piece, not only between neighbours.
    """
    names = ["cold open on detail", "build tension", "tease a detail",
             "the anomaly", "a detail", "the craft", "tag the vibe"]
    got = recipes.select_recipes(_beats(names), rhythm_seconds=2.2)
    shapes = [g["composition"] for g in got]

    # Short films: a single frame shape may come back once, not twice. Longer
    # ones get a little more room, but never more than a fifth of the cut.
    ceiling = max(2, math.ceil(len(names) / 5))
    counts = {shape: shapes.count(shape) for shape in set(shapes)}
    assert max(counts.values()) <= ceiling, counts
    assert len(set(shapes)) >= 4, shapes
    assert recipes.summary(got)["repeats"] == []


def test_a_recipe_whose_hold_fits_the_cut_beats_one_that_does_not() -> None:
    """A 3.5 s establishing hold in a 1 s cut rhythm is a dead frame."""
    slow = recipes.select_recipes(_beats(["cold open on detail", "x", "y"], 1.0), rhythm_seconds=1.0)
    assert all(r["hold_seconds"][0] <= 1.6 for r in slow), [r["id"] for r in slow]

    patient = recipes.select_recipes(_beats(["cold open on detail", "x", "y"], 3.6), rhythm_seconds=3.6)
    assert any(r["hold_seconds"][1] >= 3.0 for r in patient), [r["id"] for r in patient]


def test_the_same_brief_always_gets_the_same_cut() -> None:
    """Refining copy must not silently re-cut the film."""
    beats = _beats(["cold open on detail", "build tension", "the craft", "tag the vibe"])
    first = recipes.select_recipes(beats, rhythm_seconds=2.2, treatment="editorial film")
    second = recipes.select_recipes(beats, rhythm_seconds=2.2, treatment="editorial film")
    assert [r["id"] for r in first] == [r["id"] for r in second]


def test_different_treatments_can_diverge_without_breaking_the_rules() -> None:
    beats = _beats(["cold open on detail", "build tension", "the craft", "tag the vibe"])
    a = recipes.select_recipes(beats, rhythm_seconds=2.2, treatment="editorial film")
    b = recipes.select_recipes(beats, rhythm_seconds=2.2, treatment="graphic ledger")
    # divergence is allowed; breaking the craft rules is not
    for chosen in (a, b):
        assert len({r["id"] for r in chosen}) == len(chosen)


def test_each_choice_carries_its_reason() -> None:
    got = recipes.select_recipes(_beats(["cold open on detail", "the craft", "tag the vibe"]))
    for row in got:
        assert row["reason"], row["id"]
        assert row["why"] and row["grammar"]
        assert isinstance(row["hold_seconds"], list) and len(row["hold_seconds"]) == 2


def test_an_uploaded_photo_gets_to_be_seen() -> None:
    """With a real photograph in hand, recipes that reveal texture are favoured."""
    beats = _beats(["cold open on detail", "the craft", "tag the vibe"])
    with_image = recipes.select_recipes(beats, has_image=True)
    assert any(r["composition"] in {"field", "horizon"} for r in with_image)


def test_summary_reports_variety_and_coverage() -> None:
    got = recipes.select_recipes(_beats(["cold open on detail", "build tension", "tag the vibe"]))
    summary = recipes.summary(got)
    assert summary["shot_count"] == 3
    assert summary["distinct_devices"] == 3
    assert summary["composition_spread"] >= 2
    assert set(summary["functions"]) <= set(recipes.FUNCTION_ORDER)


def test_empty_beats_produce_an_empty_plan_not_a_crash() -> None:
    assert recipes.select_recipes([]) == []
    assert recipes.summary([])["shot_count"] == 0


def test_a_beat_with_no_recognisable_words_still_gets_a_shot() -> None:
    got = recipes.select_recipes(_beats(["cold open", "zzz qqq", "mmm"], 2.0))
    assert len(got) == 3
    assert all(row["id"] in recipes.BY_ID for row in got)
