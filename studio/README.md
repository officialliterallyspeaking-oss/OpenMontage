# OpenMontage Studio

Two surfaces over this repository:

**The Creative & Growth Studio** (`/`) — four systems working as one. Describe an
idea or drop an image and you get a decided concept, designed visuals, a script,
a cut video with burned captions, a quality report, and a publish-ready TikTok
package. No prompt engineering, no manual hand-offs between tools.

**The classic tools** (`/ui/classic.html`) — the original single-prompt screens:
prompt → image, prompt → video, image → video.

The repository **is** the backend. Both surfaces call the same `tools/` the agent
calls; nothing is reimplemented in the frontend.

```
Browser ──► studio/api_projects.py ──► studio/brain/orchestrator.py
                                            ├─ director.py    System 1 · Viral Content Director
                                            ├─ creative.py    System 2 · Universal Creative Engine
                                            ├─ producer.py    System 3 · Automatic Production Engine
                                            └─ growth.py      System 4 · TikTok Growth Engine
                                                    │
                                                    ├─► studio/motion.py + brain/assembly.py (FFmpeg)
                                                    └─► tools/graphics/image_selector.py, tools/video/video_selector.py
```

## The four systems

| System | Decides | Produces | Repository artifacts |
|--------|---------|----------|----------------------|
| **Viral Content Director** | which angle wins and why, hook, beat structure, platform, length | scored angle shortlist, brief, hook set, beat sheet | `brief.json` |
| **Universal Creative Engine** | which model to use, palette, lighting, framing, camera moves | measured source analysis, prompts, frames | `scene_plan.json` inputs |
| **Automatic Production Engine** | script, storyboard, cut timing, caption timing | MP4 with burned captions, QA findings | `script.json`, `scene_plan.json`, `edit_decisions.json`, `review.json`, `final_review.json` |
| **TikTok Growth Engine** | caption, hashtags, search terms, sound brief, cadence | publish-ready package, publish log | `publish_log.json` |

They share **one project object** (`projects/<id>/brain/context.json`), not files
passed by hand. Each component records a content hash and its dependencies, so a
refinement recomputes exactly what it invalidated:

| You change | What recomputes |
|------------|-----------------|
| the opening line | script → captions → render → QA → package. **Artwork is reused.** |
| one scene | one shot regenerated → storyboard → cut → render → QA → package |
| the palette | plan → prompts → frames → render → QA → package |
| the angle | everything downstream of the decision |

## Creative decisions are explicit, not asserted

Every angle is scored out of 100 against the request's own traits, with the
points itemised (`+6 works from a single still`, `-8 needs ~16s of rhythm but
only 15s is available`). The runner-up and the reason it lost are shown too.
Nothing is called "viral" or "guaranteed": the package states that no view
count, completion rate or search volume was measured, because none can be.

## Run it

```bash
python -m studio serve                 # http://127.0.0.1:8000
python -m studio serve --port 8080 --warm
python -m studio doctor                # capability envelope, no server
```

`make studio` does the same. FFmpeg is required for video; if `ffmpeg` is not on
`PATH` the Studio links the static binary from the `imageio-ffmpeg` wheel into
`.runtime/bin/` automatically.

## What works without a model provider

The pipeline is real even with no credentials: concept, brief, prompts, script,
storyboard, edit decisions, captions, render, QA and the publishing package all
run. Only the frames change:

* **image-led** — real crops and grades of *your* photograph (provenance `source`)
* **text-led** — frames composed by the studio's art director (provenance `local`)

Both are labelled in the video, in the UI, in the QA report and in the package.
A local frame is never presented as model output. Configure a provider key and
the same pipeline routes to it through the repository's selectors.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/studio/capabilities` | what can actually run here, and why |
| `POST` | `/api/studio/upload` | bring an image in |
| `POST` | `/api/studio/projects` | create a campaign (text, image or full TikTok) |
| `GET` | `/api/studio/projects` | list campaigns |
| `GET` | `/api/studio/projects/{id}` | the whole shared project state + six real progress stages |
| `POST` | `/api/studio/projects/{id}/refine` | Creative Control: `hook`, `scene`, `palette`, `duration`, `concept`, `caption_text`, `sound` |
| `POST` | `/api/studio/projects/{id}/retry` | resume after a failure, keeping finished work |
| `GET` | `/api/studio/projects/{id}/inspect` | prompts, storyboard, edits, cues, artifacts |
| `GET` | `/api/studio/projects/{id}/artifacts/{file}` | the schema-shaped JSON on disk |

The classic endpoints (`/api/images`, `/api/videos/from-text`,
`/api/videos/from-image`, `/api/jobs`, `/api/catalog`, `/api/keys`) are unchanged.

## The three flows

| Flow | What it does | Endpoint |
|------|--------------|----------|
| **Image** | Prompt → one to four stills | `POST /api/images` |
| **Video from prompt** | Prompt → stills → camera-move MP4 | `POST /api/videos/from-text` |
| **Image → video** | Your uploaded image → camera-move MP4 | `POST /api/videos/from-image` |

For video there are two engines:

- **Local camera motion** (default) — FFmpeg `zoompan`/`xfade`: push-in, pull-back,
  pans, ken-burns, cross-fades. No API key, no Node, no GPU. Renders in seconds.
- **AI video model** — routes through `video_selector` (image-to-video or
  text-to-video). Billed per second by whichever provider you configured. If it
  is unavailable or fails, the Studio says so and falls back to local motion
  rather than failing the run.

## Providers and keys

Nothing is required to start. The header shows real counts from
`tools/tool_registry.py` (e.g. `Image 6/29`), and the **Keys** panel writes to
`.env` — the same file the repo's tools read. Keys are written with `0600`
permissions, never returned to the browser, and never logged.

With no image provider configured the Studio still produces a video: it draws a
**labelled placeholder poster** from your prompt using the real style-playbook
palettes (`styles/*.yaml`), then animates it. Every placeholder asset carries
`provenance: "placeholder"` and a `PLACEHOLDER · NO MODEL` chip in the frame, so it
is never mistaken for a model output.

`GET /api/catalog` reports which env var unlocks which providers, derived from each
tool's declared `dependencies` — no hardcoded provider lists.

## What it writes

```
projects/studio-<slug>-<id>/
├── project.json                     # marker the Backlot board reads
├── artifacts/
│   ├── studio_request.json          # exactly what was asked for
│   ├── brief.json                   # stage `idea`  (schemas/artifacts/brief.schema.json)
│   ├── asset_manifest.json          # stage `assets`
│   └── render_report.json           # stage `compose`
├── assets/images/…                  # stills (or the uploaded source)
├── renders/final.mp4 (+ .jpg)       # the deliverable and its poster frame
├── checkpoint_idea.json
├── checkpoint_assets.json
├── checkpoint_compose.json
└── events.jsonl                     # written by BaseTool instrumentation
```

Those checkpoints run through `lib/checkpoint.write_checkpoint`, so the repo's own
gates, schema validation, history archiving and decision-log merging all apply.
The pipeline is declared in [`pipeline_defs/studio.yaml`](../pipeline_defs/studio.yaml)
with director skills in [`skills/pipelines/studio/`](../skills/pipelines/studio/),
which is what makes `pipeline_defs/` contract tests pass for it.

## API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | service, job counts, ffmpeg status |
| `GET` | `/api/presets` | aspects, camera moves, style playbooks (read from `styles/`) |
| `GET` | `/api/catalog` | capabilities, providers, key→provider unlock map, runtimes |
| `GET` | `/api/keys` | which keys are set (never values) |
| `POST` | `/api/keys` | write keys to `.env`, then re-discover tools |
| `POST` | `/api/images` | image job |
| `POST` | `/api/videos/from-text` | video job from a prompt |
| `POST` | `/api/videos/from-image` | video job from an uploaded image |
| `GET` | `/api/jobs` · `/api/jobs/{id}` | gallery and job state |
| `DELETE` | `/api/jobs/{id}` | drop a run from the gallery (files stay on disk) |
| `GET` | `/api/board/*` | start/redirect to the Backlot board |
| `GET` | `/media/projects/…` | serves project media (path-traversal guarded) |

Interactive docs at `/api/docs`.

## Tests

```bash
python -m pytest tests/studio -v
```

They run against the live app and the real registry — including a real MP4 render
— and assert the documented degradation (placeholder art when no provider is
configured) rather than mocking the tools.

## Notes

- **Concurrency**: two renders at a time (`threading.BoundedSemaphore`); more just
  queue.
- **Persistence**: jobs are mirrored to `studio_state/jobs.json` (gitignored) so the
  gallery survives a restart. Uploads live in `studio_state/uploads/`.
- **Backlot**: the board binds `127.0.0.1` and only trusts `localhost` hosts. When
  the Studio runs behind a port-forwarding proxy it starts the board through
  `studio/board_host.py`, which widens that one middleware so the preview can reach
  it. `backlot/` itself is untouched and stays read-only.
