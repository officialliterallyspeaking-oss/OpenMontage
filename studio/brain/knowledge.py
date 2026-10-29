"""Niche knowledge packs — the studio's craft expertise, written down.

These are the rules a creative director actually works from: which concepts travel
on TikTok for a given niche, how fast they are cut, what the camera does, what the
caption does, and which words the audience searches for. They are deliberately
data, not code, so they can be tuned without touching the engines.

Two honesty rules are encoded here and enforced downstream:

* `credibility_note` — what a niche may NOT fake (e.g. sports: generated scenes
  must never be presented as real match footage).
* `seo` — vocabulary only. We never invent search volumes or claim a keyword is
  trending; `growth.py` states plainly that no volume data was used unless a
  research tool supplied it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Concept:
    """A creative direction the director can consider."""

    id: str
    name: str
    why: str  # the strategic reason this works
    hook_templates: list[str]
    structure: list[tuple[str, float]]  # (beat name, share of total runtime)
    treatment: str  # visual approach
    motion: str  # camera language
    cut_rhythm: float  # target seconds per shot
    text_style: str  # on-screen typography approach
    music_mood: str
    narration: str  # none | sparse | full
    seo_terms: list[str]
    hashtags: list[str]
    fits: dict[str, float] = field(default_factory=dict)  # trait weights 0-1


@dataclass(frozen=True)
class Niche:
    id: str
    label: str
    subjects: list[str]
    audiences: list[str]
    tone_words: list[str]
    visual_vocabulary: list[str]
    camera_vocabulary: list[str]
    materials: list[str]
    lighting: list[str]
    palettes: list[list[str]]
    credibility_note: str
    seo_core: list[str]
    seo_longtail: list[str]
    hashtags_core: list[str]
    hashtags_niche: list[str]
    concepts: list[Concept]
    style_playbook: str = "clean-professional"


def _c(**kw: Any) -> Concept:
    return Concept(**kw)


FASHION = Niche(
    id="fashion",
    label="Fashion & Style",
    subjects=["outfit", "look", "garment", "runway", "model", "styling", "collection",
              "fabric", "silhouette", "street style", "brand", "designer", "dress",
              "jacket", "tailoring", "couture", "wardrobe", "coat", "trench", "suit",
              "blazer", "shirt", "knitwear", "sweater", "denim", "jeans", "trousers",
              "skirt", "shoe", "boot", "heel", "bag", "accessory", "scarf", "leather",
              "wool", "silk", "satin", "linen", "sunglasses", "jewellery", "jewelry"],
    audiences=["style-conscious 18-34", "fashion students", "luxury shoppers",
               "streetwear community", "sustainable-fashion buyers"],
    tone_words=["elegant", "luxury", "bold", "editorial", "playful", "minimal",
                "dramatic", "romantic", "raw", "sleek"],
    visual_vocabulary=["fabric drape", "stitch detail", "seam line", "texture close-up",
                       "silhouette against negative space", "garment movement in air",
                       "window light falling across cloth", "reflection on polished floor"],
    camera_vocabulary=["slow dolly along the hemline", "vertical tilt from shoes to collar",
                       "orbit around the silhouette", "macro push into weave",
                       "whip pan between looks", "crane up to full figure"],
    materials=["silk", "wool crepe", "raw denim", "brushed leather", "sheer organza",
               "technical nylon", "hand-dyed cotton", "satin"],
    lighting=["single softbox key from camera-left", "hard sun and long shadow",
              "bounced window light", "rim light separating silhouette from backdrop",
              "warm tungsten practicals", "cool overcast diffusion"],
    palettes=[["#0F0F10", "#E8E2D6", "#B08D57", "#7A1F1F"],
              ["#141414", "#F4F1EC", "#C9C2B6", "#3A4A5C"],
              ["#1B1B1F", "#E4572E", "#F3C969", "#2E4057"]],
    credibility_note=(
        "Preserve garment design, fabric, colour and silhouette from the source image. "
        "Never restyle a real garment into a different product — an outfit reveal must "
        "reveal the outfit that exists."
    ),
    seo_core=["ootd", "outfit ideas", "fashion", "style", "outfit inspiration"],
    seo_longtail=["how to style [piece] for [season]", "[piece] outfit ideas for [occasion]",
                  "quiet luxury outfit formula", "capsule wardrobe [piece]"],
    hashtags_core=["#fashion", "#style", "#ootd", "#outfitinspo", "#fashiontok"],
    hashtags_niche=["#quietluxury", "#streetstyle", "#stylingtips", "#runway",
                    "#capsulewardrobe", "#fashioneditorial"],
    concepts=[
        _c(id="editorial-film", name="Cinematic editorial",
           why="Turns a still into a moving magazine spread; the format signals taste "
               "and makes a single image feel like a campaign.",
           hook_templates=["This is what {subject} looks like when it moves.",
                           "Nobody talks about {subject} like this."],
           structure=[("cold open on detail", 0.18), ("reveal the full look", 0.30),
                      ("texture and movement", 0.30), ("closing frame + line", 0.22)],
           treatment="Editorial film: negative space, single light source, garment as sculpture",
           motion="Slow dolly and vertical tilt, one move per shot",
           cut_rhythm=2.4, text_style="small caps labels, wide tracking, lower third",
           music_mood="minimal cinematic, low strings, restrained percussion",
           narration="sparse", seo_terms=["fashion editorial", "outfit inspiration"],
           hashtags=["#fashioneditorial", "#quietluxury"],
           fits={"premium": 1.0, "calm": 0.9, "fashion": 1.0, "loud": 0.2}),
        _c(id="outfit-reveal", name="The reveal",
           why="Reveal mechanics are the highest-retention structure in fashion; the "
               "payoff is the garment, so the hook is pure promise.",
           hook_templates=["Wait for the {piece}.", "You will not guess what is under this."],
           structure=[("tease a detail", 0.15), ("build tension", 0.25),
                      ("the reveal", 0.35), ("styling breakdown", 0.25)],
           treatment="Tight crops that withhold the full look, then a wide reveal",
           motion="Snap zooms, whip pans, one hero push-in on the reveal",
           cut_rhythm=1.4, text_style="huge centred hook line, 3-4 words max",
           music_mood="beat-driven, build then drop on the reveal",
           narration="none", seo_terms=["outfit reveal", "outfit ideas"],
           hashtags=["#outfitreveal", "#styletok"],
           fits={"premium": 0.6, "calm": 0.2, "fashion": 1.0, "loud": 0.95}),
        _c(id="styling-formula", name="The styling formula",
           why="Teaches something reusable in 30 seconds — saves and shares are the "
               "strongest signal in fashion content.",
           hook_templates=["Three ways to wear {piece}.", "The {piece} formula nobody teaches you."],
           structure=[("promise the formula", 0.15), ("version one", 0.25),
                      ("version two", 0.25), ("version three + save prompt", 0.35)],
           treatment="Clean studio, garment variations side by side, numbered labels",
           motion="Static frames with punch-in on each label",
           cut_rhythm=2.0, text_style="numbered cards, high contrast, safe-zone aware",
           music_mood="clean upbeat, light percussion",
           narration="full", seo_terms=["how to style", "outfit formula"],
           hashtags=["#stylingtips", "#howtostyle"],
           fits={"premium": 0.7, "calm": 0.6, "fashion": 1.0, "loud": 0.5}),
        _c(id="designer-story", name="Behind the design",
           why="Narrative texture around craft earns watch time beyond the first loop "
               "and attracts a deeper audience.",
           hook_templates=["This {piece} took four prototypes.", "The detail most people miss."],
           structure=[("the anomaly", 0.2), ("the craft", 0.35),
                      ("the payoff detail", 0.3), ("closing thought", 0.15)],
           treatment="Macro textures, hands at work, archival-feeling grain",
           motion="Macro slides, slow rack focus feel",
           cut_rhythm=2.8, text_style="serif-quoted lines, small, mid-frame",
           music_mood="ambient, textured, no drums",
           narration="full", seo_terms=["fashion design", "garment detail"],
           hashtags=["#fashiondesign", "#craftsmanship"],
           fits={"premium": 1.0, "calm": 1.0, "fashion": 0.9, "loud": 0.15}),
        _c(id="street-style-cut", name="Street-style cutdown",
           why="Fast, rhythmic and native to the feed; works when the image already "
               "has energy and colour.",
           hook_templates=["{city} street style hits different.", "Nobody is dressing like this."],
           structure=[("hard cut montage", 0.45), ("hero look", 0.3), ("tag the vibe", 0.25)],
           treatment="High-contrast colour, on-location texture, grain",
           motion="Handheld energy, fast lateral moves",
           cut_rhythm=0.9, text_style="sticker-style tags, bright accent",
           music_mood="house or drill-adjacent, high energy",
           narration="none", seo_terms=["street style", "urban fashion"],
           hashtags=["#streetstyle", "#streetwear"],
           fits={"premium": 0.4, "calm": 0.2, "fashion": 1.0, "loud": 1.0}),
    ],
)

SPORTS = Niche(
    id="sports",
    label="Sport & Performance",
    subjects=["football", "soccer", "basketball", "athlete", "player", "match", "goal",
              "training", "stadium", "tactics", "run", "sprint", "gym", "workout",
              "boxing", "tennis", "form", "season", "team", "coach", "pressing",
              "counter", "formation", "midfield", "defence", "defense", "striker",
              "goalkeeper", "derby", "league", "transfer", "injury", "comeback"],
    audiences=["match-going fans", "fantasy football players", "young athletes",
               "fitness enthusiasts", "tactics nerds", "sports bettors"],
    tone_words=["dramatic", "hype", "analytical", "raw", "epic", "technical", "gritty"],
    visual_vocabulary=["floodlight beams and lens flare", "turf texture", "sweat detail",
                       "boots planting", "crowd bokeh", "scoreboard glow",
                       "chalk tactics lines", "slow-motion contact"],
    camera_vocabulary=["tracking shot at knee height", "crane over the pitch",
                       "fast push on the strike", "whip pan to the replay angle",
                       "low angle hero frame", "orbit around the celebration"],
    materials=["wet grass", "compound rubber", "mesh jersey", "brushed metal trophy",
               "chalk on board", "condensation on bottle"],
    lighting=["floodlights against night sky", "hard afternoon sun and long shadows",
              "tunnel light silhouette", "stadium rim light", "overcast flat and gritty"],
    palettes=[["#0A0F1C", "#3DDC84", "#F2F4F7", "#FF4D2E"],
              ["#101418", "#E8B23A", "#C8D0DA", "#2E6BE6"],
              ["#0C0C0E", "#E4572E", "#F5F5F5", "#1F7A4D"]],
    credibility_note=(
        "Never present generated scenes as real match footage or imply a player did "
        "something they did not. Illustrative strategy boards and stylised motion are "
        "fine; fabricated highlights are not."
    ),
    seo_core=["football", "football tactics", "training", "sports analysis", "athlete"],
    seo_longtail=["[player role] explained simply", "how to train [skill] at home",
                  "why [formation] beats [formation]", "football tactics for beginners"],
    hashtags_core=["#football", "#sports", "#soccer", "#training", "#sportstok"],
    hashtags_niche=["#footballtactics", "#matchday", "#footballtraining", "#athletelife",
                    "#sportsanalysis", "#gymtok"],
    concepts=[
        _c(id="tactical-breakdown", name="Tactical breakdown",
           why="Explains something viewers think they already understand — the "
               "re-watch and comment engine of football content.",
           hook_templates=["This is why {subject} works.", "Most fans miss what happens here."],
           structure=[("pose the question", 0.18), ("annotated breakdown", 0.42),
                      ("the consequence", 0.25), ("question to the comments", 0.15)],
           treatment="Chalkboard / broadcast-graphic overlays, arrows, zones",
           motion="Push-ins on highlighted zones, animated arrows",
           cut_rhythm=2.6, text_style="broadcast labels, team colours, bold sans",
           music_mood="tension bed, minimal drums",
           narration="full", seo_terms=["football tactics", "tactical analysis"],
           hashtags=["#footballtactics", "#tactics"],
           fits={"premium": 0.8, "calm": 0.7, "sports": 1.0, "analytical": 1.0}),
        _c(id="sports-hype", name="Hype edit",
           why="Rhythm and impact carry the emotion; the cut itself is the message.",
           hook_templates=["{subject} in slow motion hits differently.", "Turn the volume up."],
           structure=[("impact frame", 0.2), ("escalating cuts", 0.45),
                      ("hero frame", 0.25), ("last line", 0.10)],
           treatment="High contrast, crushed blacks, speed ramps",
           motion="Speed ramps, snap zooms, shake on impact",
           cut_rhythm=1.1, text_style="huge impact words, 1-2 per beat",
           music_mood="phonk or trap, heavy 808s",
           narration="none", seo_terms=["football edit", "sports motivation"],
           hashtags=["#footballedit", "#sportshype"],
           fits={"premium": 0.6, "calm": 0.1, "sports": 1.0, "loud": 1.0}),
        _c(id="player-story", name="Player story",
           why="Human stakes beat highlights; a story arc earns completion rate.",
           hook_templates=["Nobody believed {subject}.", "One season changed everything."],
           structure=[("the low point", 0.22), ("the turn", 0.30),
                      ("the rise", 0.32), ("the takeaway", 0.16)],
           treatment="Documentary stills, archival texture, grain and letterboxing",
           motion="Slow push-ins, held frames, subtle parallax",
           cut_rhythm=3.0, text_style="documentary lower thirds, italic quotes",
           music_mood="orchestral swell, piano",
           narration="full", seo_terms=["player story", "sports documentary"],
           hashtags=["#footballstory", "#sportsdocumentary"],
           fits={"premium": 1.0, "calm": 0.8, "sports": 0.9, "loud": 0.3}),
        _c(id="training-drill", name="Training drill",
           why="Actionable, repeatable value — saves and sends dominate fitness niches.",
           hook_templates=["Do this for 10 minutes a day.", "The drill that fixed {subject}."],
           structure=[("the result first", 0.18), ("the drill steps", 0.5),
                      ("common mistake", 0.2), ("save prompt", 0.12)],
           treatment="Clean field or gym, numbered steps, timer graphics",
           motion="Follow-the-move tracking, step punch-ins",
           cut_rhythm=2.2, text_style="numbered steps, big readable counters",
           music_mood="clean energetic, mid tempo",
           narration="full", seo_terms=["football training", "skill drills"],
           hashtags=["#footballtraining", "#drills"],
           fits={"premium": 0.7, "calm": 0.6, "sports": 1.0, "useful": 1.0}),
        _c(id="debate-bait", name="The debate",
           why="A defensible hot take invites comments — the cheapest reach in sports.",
           hook_templates=["Unpopular opinion about {subject}.", "This take will annoy people."],
           structure=[("the claim", 0.2), ("the evidence", 0.4),
                      ("steelman the other side", 0.25), ("the question", 0.15)],
           treatment="Talking-head energy with stat cards and bold type",
           motion="Punch-in cuts, stat card slides",
           cut_rhythm=1.8, text_style="huge claim text, then stat cards",
           music_mood="light tension, minimal",
           narration="full", seo_terms=["football debate", "hot take"],
           hashtags=["#footballdebate", "#hottake"],
           fits={"premium": 0.5, "calm": 0.3, "sports": 1.0, "loud": 0.8}),
    ],
)

FITNESS = Niche(
    id="fitness",
    label="Fitness & Training",
    subjects=["workout", "training", "gym", "muscle", "strength", "cardio", "form",
              "weights", "progress", "diet", "recovery", "mobility", "squat", "deadlift",
              "bench", "push", "pull", "stretch", "yoga", "running", "hypertrophy"],
    audiences=["beginners starting out", "intermediate lifters", "busy professionals",
               "home-workout crowd"],
    tone_words=["encouraging", "tough", "calm", "technical", "motivating"],
    visual_vocabulary=["chalk dust", "sweat on skin", "plate texture", "mirror reflections",
                       "breath in cold air"],
    camera_vocabulary=["low angle hero frame", "slow orbit around form",
                       "side-on tracking of the rep", "close on grip"],
    materials=["chalked steel", "rubber flooring", "brushed aluminium", "sweat-damp cotton"],
    lighting=["hard side light", "gym practicals", "window backlight"],
    palettes=[["#0C0D10", "#E6E8EB", "#E4572E", "#3DDC84"],
              ["#101216", "#C9CED6", "#F3B23A", "#2E6BE6"]],
    credibility_note=(
        "Never promise physical results or give medical advice. Frame training content "
        "as technique and habit, not guaranteed outcomes."
    ),
    seo_core=["workout", "fitness", "training", "gym"],
    seo_longtail=["[exercise] form for beginners", "20 minute [muscle] workout at home"],
    hashtags_core=["#fitness", "#workout", "#gymtok", "#training"],
    hashtags_niche=["#formcheck", "#homeworkout", "#strengthtraining"],
    concepts=[
        _c(id="form-fix", name="Form fix",
           why="Corrects a mistake the viewer may be making right now — instant relevance.",
           hook_templates=["You are doing {subject} wrong.", "Stop doing this in the gym."],
           structure=[("show the mistake", 0.22), ("the fix", 0.45),
                      ("feel the difference", 0.2), ("save prompt", 0.13)],
           treatment="Side-by-side correct vs incorrect, clean matte background",
           motion="Static comparison, punch-in on joints",
           cut_rhythm=2.0, text_style="red X / green tick callouts",
           music_mood="clean mid tempo",
           narration="full", seo_terms=["exercise form", "workout tips"],
           hashtags=["#formcheck", "#gymtips"],
           fits={"premium": 0.7, "calm": 0.7, "fitness": 1.0, "useful": 1.0}),
        _c(id="progress-film", name="Progress film",
           why="Emotional arc plus visible change sustains completion.",
           hook_templates=["{months} of {subject}.", "This is what consistency looks like."],
           structure=[("before", 0.2), ("the grind", 0.4), ("after", 0.25), ("the line", 0.15)],
           treatment="Documentary grain, time-of-day shifts",
           motion="Slow push-ins, cross-dissolves",
           cut_rhythm=2.8, text_style="date stamps, small caps",
           music_mood="building piano into drums",
           narration="sparse", seo_terms=["fitness progress", "transformation"],
           hashtags=["#progress", "#fitnessjourney"],
           fits={"premium": 0.9, "calm": 0.8, "fitness": 1.0, "loud": 0.3}),
    ],
)

GENERIC = Niche(
    id="generic",
    label="General",
    subjects=["story", "idea", "concept", "project", "moment", "journey"],
    audiences=["curious viewers", "people new to the topic"],
    tone_words=["clear", "warm", "confident", "curious", "bold"],
    visual_vocabulary=["clean negative space", "texture detail", "atmospheric depth",
                       "reflective surfaces"],
    camera_vocabulary=["slow push-in", "lateral dolly", "vertical tilt", "orbit"],
    materials=["glass", "matte paper", "brushed metal", "soft textile"],
    lighting=["soft key light", "window light", "golden hour backlight", "cool studio light"],
    palettes=[["#0E1117", "#F2F0EA", "#E4572E", "#3A6EA5"],
              ["#101418", "#E8E4DC", "#3DDC84", "#B08D57"]],
    credibility_note=(
        "Do not state facts that were not supplied or researched, and never present a "
        "generated visual as documentary evidence."
    ),
    seo_core=["how to", "explained", "tips"],
    seo_longtail=["[topic] explained simply", "[topic] for beginners"],
    hashtags_core=["#learnontiktok", "#explained"],
    hashtags_niche=["#howto", "#creativetok"],
    concepts=[
        _c(id="story-led", name="Story-led",
           why="A single idea carried by narrative beats is the most portable structure "
               "across niches.",
           hook_templates=["Everything you know about {subject} is incomplete.",
                           "Here is what actually happened."],
           structure=[("the hook", 0.18), ("the build", 0.42),
                      ("the turn", 0.25), ("the landing", 0.15)],
           treatment="Cinematic stills with strong negative space",
           motion="Slow push-ins, one move per shot",
           cut_rhythm=2.6, text_style="short caption lines, high contrast",
           music_mood="restrained cinematic bed",
           narration="full", seo_terms=["explained", "story"],
           hashtags=["#storytelling", "#explained"],
           fits={"premium": 0.8, "calm": 0.8, "generic": 1.0}),
        _c(id="visual-poem", name="Visual poem",
           why="Music, motion and image do the work; ideal when the source image is "
               "already striking.",
           hook_templates=["{subject}, in motion.", "Look closer."],
           structure=[("open", 0.3), ("develop", 0.4), ("close", 0.3)],
           treatment="Full-bleed imagery, typography as punctuation",
           motion="Slow drift, parallax depth",
           cut_rhythm=3.2, text_style="one or two words, centred",
           music_mood="ambient, spacious",
           narration="none", seo_terms=["aesthetic", "visual"],
           hashtags=["#aesthetic", "#visualart"],
           fits={"premium": 0.9, "calm": 1.0, "generic": 0.8}),
    ],
)

NICHES = {n.id: n for n in (FASHION, SPORTS, FITNESS, GENERIC)}

# Trait words -> the axis they signal. Used to score concepts against a request.
TRAIT_LEXICON: dict[str, str] = {}
for _word, _trait in [
    ("luxury", "premium"), ("premium", "premium"), ("elegant", "premium"),
    ("editorial", "premium"), ("cinematic", "premium"), ("refined", "premium"),
    ("quality", "premium"), ("high-end", "premium"), ("couture", "premium"),
    ("calm", "calm"), ("minimal", "calm"), ("quiet", "calm"), ("slow", "calm"),
    ("soft", "calm"), ("relaxed", "calm"), ("chill", "calm"), ("ambient", "calm"),
    ("bold", "loud"), ("hype", "loud"), ("loud", "loud"), ("energetic", "loud"),
    ("fast", "loud"), ("dramatic", "loud"), ("aggressive", "loud"), ("intense", "loud"),
    ("viral", "loud"), ("catchy", "loud"),
    ("funny", "playful"), ("playful", "playful"), ("quirky", "playful"),
    ("tactical", "analytical"), ("analysis", "analytical"), ("breakdown", "analytical"),
    ("explain", "analytical"), ("educational", "analytical"), ("technical", "analytical"),
    ("how to", "useful"), ("tips", "useful"), ("tutorial", "useful"),
    ("guide", "useful"), ("drill", "useful"), ("learn", "useful"),
]:
    TRAIT_LEXICON[_word] = _trait

# Words that tell us the user wants a specific deliverable.
DELIVERABLE_LEXICON = {
    "campaign": ["campaign", "post", "publish", "upload", "caption", "hashtag",
                 "seo", "tiktok", "reel", "content package", "everything"],
    "video": ["video", "clip", "reel", "animate", "motion", "film", "teaser",
              "trailer", "edit", "footage"],
    "image": ["image", "photo", "picture", "still", "poster", "graphic", "thumbnail"],
}

PLATFORM_LEXICON = {
    "tiktok": ["tiktok", "fyp", "for you", "reel", "shorts", "vertical"],
    "instagram": ["instagram", "ig", "reels", "story"],
    "youtube": ["youtube", "shorts", "video"],
    "linkedin": ["linkedin", "professional"],
}

# Aspect -> the platform it implies when the user names a ratio instead.
ASPECT_PLATFORM = {"9:16": "tiktok", "16:9": "youtube", "1:1": "instagram", "4:5": "instagram"}


def niche_for_text(text: str) -> tuple[Niche, dict[str, int]]:
    """Pick the niche whose subject lexicon best matches the request."""
    lower = (text or "").lower()
    scores: dict[str, int] = {}
    for niche_id, niche in NICHES.items():
        if niche_id == "generic":
            continue
        hits = sum(1 for word in niche.subjects if word in lower)
        # tone words also count, at lower weight
        hits += sum(0.5 for word in niche.tone_words if word in lower)
        if hits:
            scores[niche_id] = int(hits * 2)
    if not scores:
        return GENERIC, {}
    best = max(scores, key=lambda k: scores[k])
    return NICHES[best], scores


def traits_for_text(text: str) -> dict[str, float]:
    """Map request wording onto concept-fitting traits (0-1 each)."""
    lower = f" {(text or '').lower()} "
    found: dict[str, float] = {}
    for word, trait in TRAIT_LEXICON.items():
        if f" {word}" in lower or f"{word} " in lower:
            found[trait] = min(1.0, found.get(trait, 0.0) + 0.6)
    return found
