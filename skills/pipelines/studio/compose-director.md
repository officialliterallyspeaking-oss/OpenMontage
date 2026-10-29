# Compose Director — Studio Pipeline

## When to Use

You are the compose stage for a Studio run: stills (or one uploaded image) exist
on disk and must become an MP4, or a video model has already returned a clip that
needs validation.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/render_report.schema.json` | Artifact validation |
| Prior artifact | `artifacts/asset_manifest.json` | What to render |
| Tool | `studio.motion.render_motion_video` | FFmpeg camera-move renderer |
| Tool | `tools/video/video_compose.py` | Reference implementation for this repo's post pipeline |

## Runtime routing

`render_runtime` is **locked to `"ffmpeg"`** for this pipeline. That is a
declared constraint of the Studio surface, not a silent fallback:

| Runtime | Used by this pipeline | Why |
|---------|----------------------|-----|
| `ffmpeg` | **yes** | Camera moves over stills, concat, encode — no Node, no GPU |
| `remotion` | no | Requires `remotion-composer/` + `node_modules`; that is the authored-composition path |
| `hyperframes` | no | Requires Node ≥ 22 + the `hyperframes` npm package; used by `animation` and `character-animation` |

Consequences you must respect:

- Do **not** hand a Studio job to Remotion or **HyperFrames** to "make it look
  better". Switching engines changes the output character and is a user decision,
  not an implementation detail.
- If a user asks for authored animation (kinetic typography, scene composition,
  choreographed multi-beat motion), say so explicitly and route them to the
  `animated-explainer` or `animation` pipeline, where the planning stage presents
  both runtimes and records a `render_runtime_selection` decision.
- `video_compose` refuses stills on the FFmpeg path by design ("Use
  operation='render'"). That guard is correct — this pipeline renders stills with
  the motion renderer instead and records the result in `render_report`.

## Process

### Step 1: Verify inputs

Every path in `asset_manifest.json` must exist. A missing still is a hard stop,
not a reason to render a shorter video.

### Step 2: Render

- One still → a single camera move across the requested duration.
- Several stills → one segment per still, cross-faded, total duration respected.
- A model clip → validate with `probe()` and skip the motion pass entirely.

Camera moves available: `ken_burns`, `zoom_in`, `zoom_out`, `pan_left`,
`pan_right`, `pan_up`, `static`. Pick the move the user selected; do not
substitute a different one because it "reads better".

### Step 3: Write the report

`render_report` must state the real output: path, resolution, fps, duration,
file size and the `render_grammar` that matches what actually ran. Record in
`warnings` when the source frames were labelled placeholders — a placeholder
render is not a model render and must never be reported as one.

## Success Criteria

- Output MP4 exists and plays
- Resolution and duration match the request (within ~10%)
- A poster frame was extracted for the gallery
- `render_report` validates and lists any placeholder warnings
