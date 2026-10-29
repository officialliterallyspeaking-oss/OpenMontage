# OpenMontage Studio

A small web frontend for this repository. One prompt — or one uploaded image —
becomes an image or a motion video. The repository **is** the backend: the Studio
adds an HTTP surface and a UI, and calls the same tools the agent does.

```
Browser ──► studio/app.py (FastAPI) ──► studio/pipelines.py
                                            ├─► tools/graphics/image_selector.py  → any configured image model
                                            ├─► tools/video/video_selector.py     → any configured video model
                                            └─► studio/motion.py (FFmpeg)         → camera moves over stills
```

Everything it produces lands in a real OpenMontage project workspace
(`projects/studio-<slug>-<id>/`) with schema-valid artifacts and checkpoints, so
the [Backlot board](../backlot/README.md) can watch it.

## Run it

```bash
# from the repository root
python -m studio serve                 # http://127.0.0.1:8000
python -m studio serve --port 8080 --warm
python -m studio doctor                # capability envelope, no server
```

`make studio` does the same. Install deps first with `make setup`, or at minimum:

```bash
pip install -r requirements.txt
```

FFmpeg is required for video. If `ffmpeg` is not on `PATH`, the Studio links the
static binary from the `imageio-ffmpeg` wheel into `.runtime/bin/` automatically —
nothing to configure.

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
