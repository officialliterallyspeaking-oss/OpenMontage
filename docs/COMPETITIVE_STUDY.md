# What the field has, and what we took

A survey of the open-source projects that do what OpenMontage does, read at
the source level, and what came out of it. Written to be useful to whoever
picks up the next item on the list.

Survey date: 2026-10-29. Stars move; the mechanics do not.

---

## 1. The headline finding

**Model coverage is not the gap.** OpenMontage already has 132 tool classes,
14 pipelines, 22 TTS voices and integrations for 30+ video models. Every
project surveyed below has *fewer* models than this repo, and several have
none at all.

The gap was **shape** — what exists around the model call. Four capabilities
were confirmed absent from this repo and present upstream:

| # | Capability | Upstream proof | Status |
|---|---|---|---|
| 1 | NLE interchange: Premiere / DaVinci / Final Cut | openfilm (8.0k ★, MIT) exports a timeline on every render | **built** |
| 2 | A shot-recipe library that encodes craft and failure modes | video-shotcraft (20.9k ★): 124 cards, 150 motion previews | **built** (16 cards) |
| 3 | Variant generation — one command, many cuts | hypit (30.3k ★): "100 variants", 64 parallel Chromium renders | not started |
| 4 | An MCP server exposing the tool registry to other agents | palmier-pro, FireRed-OpenStoryline, comfyui-mcp | not started |

Verification of absence, so this is not a guess: `grep -rliE
"fcpxml|edl|premiere|capcut|davinci|otio"` over `tools/ studio/ skills/ lib/`
returned nothing; no MCP server existed at the repo root; `_motion_for()` had
six hardcoded moves; `localfx.COMPOSITIONS` had five flat compositions selected
by `variant % len`.

---

## 2. The surveyed projects

Stars are approximate and were taken on the survey date.

| Project | ★ | Licence | What it is | What was worth taking |
|---|---|---|---|---|
| hypit-ai/hypit | 30.3k | NOASSERTION | "Clone any viral video": SVML markup, 100 variants per command, 64 parallel headless Chromium renders, swap face/words/B-roll | Variant generation; the insight that a workflow can compile captions + motion graphics + code visuals **with no generation model at all** |
| Vincentwei1021/video-shotcraft | 20.9k | Apache-2.0 | 124 shot-recipe cards + 150 motion previews, beat sync | The recipe-card schema (§4) |
| lemomo-ai/lemo-opuscar | 17.5k | — | 99 coded visual styles | (style taxonomy; not yet mined) |
| palmier-io/palmier-pro | 14.8k | GPL-3 | macOS Swift editor with MCP surface and model access | MCP-over-registry pattern |
| openfilm/openfilm | 8.0k | MIT | A film is one HTML file; Studio editor; exports MP4, GIF, audio, stills, transparent video **and the timeline** | **The NLE export** — the most directly useful find |
| FireRedTeam/FireRed-OpenStoryline | 3.7k | Apache-2.0 | LangChain/MCP video-cut agent | Agent-facing editing verbs |
| open-ribbi/velocut | 451 | — | Local-first browser editor | (not yet mined) |

### openfilm: the state of the art for NLE export

Read: `packages/openfilm/studio/server/nle.mjs`, 43,959 characters, plus its
siblings `fcpxml.mjs`, `exports.mjs` and four test files
(`nle-editable`, `nle-source`, `nle-timecode`, `nle-windows-path`).

Its conclusions, which were re-derived and re-tested here rather than copied:

- Frame maths is `round(at × fps)` on **both** edges, so back-to-back clips
  share a cut number and never leave a one-frame gap.
- Track order is reversed between the film model and xmeml: in a film the first
  track is the top, in xmeml V1 is the bottom.
- Overlapping clips on one track are spread across several tracks.
- Anything Basic Motion cannot express is **rendered** to a full-frame MOV with
  alpha rather than approximated with keyframes.
- Hidden track clips and muted sounds are written **disabled**, one click from
  coming back — not dropped.
- Fades become a WAV plus Audio Levels keyframes counted from file start.
- FCPXML clips retain their source rows.

Two of these were adopted directly (frame quantisation, shared boundaries;
explicit handling of holes). Three are recorded here as next steps because they
need the renderer to cooperate: alpha MOV for motion graphics, disabled-but-
present muted clips, and rendered fades.

---

## 3. What was built, and why it is not a stub

### 3.1 Editable timeline export

`tools/publishers/timeline_export.py` — PUBLISH tier, `local` provider,
deterministic, sync. Writes:

| Formats key | File | Opens in |
|---|---|---|
| `premiere_resolve` | `timeline.xml` (FCP7 XML / xmeml v4) | Premiere Pro: File → Import; DaVinci Resolve: File → Import → Timeline |
| `final_cut` | `timeline.fcpxml` (FCPXML 1.10) | Final Cut Pro X |
| `edl` | `timeline.edl` (CMX 3600) | Avid, older grading suites, anything |

Wired in three places, because a tool nobody calls is a library:

1. `orchestrator._write_timeline()` — runs after a completed render, cannot
   fail the project, skipped for failed ones.
2. `GET /api/studio/projects/{id}` returns an `edit` payload read from disk;
   `GET .../edit/{filename}` serves the files.
3. The project view gets a collapsed "Open this cut in your editor" disclosure.

### 3.2 The hard part was not the XML

Three bugs were found by tests, not by inspection:

- **Banker's rounding.** Python's `round()` rounds half to even, so
  `round(112.5) == 112`. Fifteen 0.25 s cuts at 30 fps drifted a frame every
  other shot. Fixed with `math.floor(x * fps + 0.5)`.
- **Drop-frame timecode.** The first implementation produced `00:00:59;12` for
  frame 1800, which is nonsense. The correct invariant is that an hour of DF
  timecode is 107892 frames, which is also 29.97 × 3600. Verified:
  1800 → `00:01:00;02`, 17982 → `00:10:00;00`, 107892 → `01:00:00;00`.
- **Absolute paths in the manifest.** `formats` held
  `/home/user/OpenMontage/projects/.../timeline.xml`. That is useless to a
  browser and discloses the server's layout. Now `{"premiere_resolve":
  "timeline.xml", ...}` — named by the application that opens it.

### 3.3 The craft layer

`studio/brain/recipes.py`. Sixteen devices, each carrying grammar, rationale,
natural hold in seconds, the composition it draws, and **the way it usually
fails**. Selection rules:

- the first beat is the hook and the last is the close, whatever they are named;
- a piece gets exactly one hook, so "tease a detail" mid-film means a detail;
- the hold must suit the cut rhythm;
- no immediate repeat, and no frame shape more than twice in a short piece;
- deterministic for the same brief, so refining copy does not silently re-cut.

The recipe names a `localfx` composition by meaning, and the renderer honours
it, so the choice changes pixels — verified by asserting two frames rendered
with different composition names differ byte-for-byte.

---

## 4. The recipe-card schema (worth reusing)

From `video-shotcraft/references/shots/rhythm/speed-ramp-freeze.md`. The
structure that makes a card usable rather than decorative:

1. Front matter: `name`, intent, applicability, **duration in frames**, energy.
2. Intent — what the shot is for.
3. Motion core — the mechanism.
4. **Parameter table** — parameter, typical value, how it feels when tuned.
5. **Known traps** — e.g. "pin SFX to output frames, not source frames";
   "freeze-annotate at most twice per 30 s". ← *this is the part that makes a
   library useful; it is what the person writing the next shot gets wrong.*
6. Reference implementation.

Field names here are `grammar` / `why` / `pitfall` / `hold_seconds` rather than
the Chinese originals, so they read naturally in this codebase.

---

## 5. What to build next, in order

1. **Variant generation.** Nothing in this repo produces alternatives. hypit's
   model is the right one: one brief → N cuts that differ in *decision* (angle,
   rhythm, palette), scored, with the winner promoting to the main line. The
   deterministic recipe selector is already the seeding mechanism — vary the
   treatment string and the rhythm, and the selector produces genuinely
   different films.
2. **MCP server over `ToolRegistry`.** 156 tools are already discoverable with
   typed `input_schema`; exposing them to external agents is mostly a transport
   and a permission boundary, and it makes every tool available to every agent.
3. **Finish the openfilm parity list.** Alpha MOV for motion graphics, muted
   clips present-but-disabled, fades as rendered WAV + keyframes.
4. **Grow the catalogue.** 16 recipes is enough to be useful and not enough to
   be rich. video-shotcraft's 124 is the target; the schema is already in place.

---

## 6. Honest limits of this round

- **No exported timeline was opened in an actual NLE.** The conformance claims
  are structural: the XML parses, the frame maths is asserted, the EDL record
  times are continuous, and the rules were derived from a project that does
  ship working imports. That is strong evidence, not a screenshot from Premiere.
- The accessibility gate (`ui_a11y.js`) needs a Chromium this sandbox could not
  download, so it did not run this round. It is not a passing gate — it is an
  unrun one.
- Stars and licence fields were read from the GitHub API on the survey date;
  hypit's licence reads NOASSERTION and palmier-pro is GPL-3, which matters if
  any of their code is ever vendored rather than re-derived. Nothing was
  vendored here.
