# Idea Director — Studio Pipeline

## When to Use

You are the planning stage for a **single-request Studio run**. There is no
research phase and no multi-concept proposal: the user already wrote the prompt,
picked the aspect, look, camera motion and provider in the Studio UI, and pressed
**Generate**. Your job is to turn that request into a `brief` artifact that the
asset and compose stages can execute without re-deciding anything.

The form submission *is* the approval. `human_approval_default` is `false` for
this stage on purpose: the user approving their own request is what started the
run. Do not invent a second gate.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/brief.schema.json` | Artifact validation |
| Request | `artifacts/studio_request.json` | What the user asked for (kind, prompt, aspect, style, motion, duration, provider) |
| Registry | `tools/tool_registry.py` | Which providers are actually configured |

## Process

### Step 1: Read the request

`artifacts/studio_request.json` is written by `studio/pipelines.py` before any
generation. It carries:

- `kind` — `image`, `video_from_text`, or `video_from_image`
- `prompt` — the user's words, verbatim
- `aspect` / `style` / `motion` / `duration_seconds`
- `engine` — `motion` (local ffmpeg) or `video_model`
- `provider_used` — the announced selection (`status`, `selected`, `available`)

### Step 2: Write the brief

| Field | Source |
|-------|--------|
| `title` | A short kebab-case-safe distillation of the prompt |
| `hook` | The prompt's first clause, or the dominant visual idea |
| `key_points` | The concrete visual elements named in the prompt |
| `tone` | Inferred from the style playbook (`cinematic`, `educational`, …) |
| `style` | The playbook id the user chose |
| `target_platform` | Derived from aspect: `16:9` → `youtube`, `9:16` → `tiktok`, `1:1`/`4:5` → `instagram` |
| `target_duration_seconds` | `duration_seconds` for video kinds, `0` for stills |

Keep the prompt unedited. Prompt rewriting is a quality bug in the Studio path:
the user must be able to trace what they typed to what was generated.

## Composition runtime — render_runtime

This pipeline does **not** dispatch through `video_compose`, so there is no
Remotion vs HyperFrames fork to present. The runtime for every Studio job is the
local FFmpeg path (`render_runtime: "ffmpeg"`), because the whole point of the
pipeline is zero-install operation.

That is a **locked constraint, not a default** — so state it plainly rather than
silently choosing:

> "Studio renders motion with FFmpeg camera moves (`render_runtime="ffmpeg"`).
> Remotion and **HyperFrames** (the `hyperframes` npm package, Node ≥ 22) are
> available in this repository for authored compositions, but this pipeline does
> not use them. If you want a bespoke animated composition instead of a camera
> move over a still, use the `animated-explainer` or `animation` pipeline — that
> is where **present both** runtimes applies."

Never imply a HyperFrames or Remotion render happened for a Studio job. If the
user later asks for a composed piece, hand off to a pipeline whose planning stage
runs the `render_runtime_selection` conversation.

## Success Criteria

- Schema-valid `brief` with all required fields present
- `style` matches the playbook the user picked
- Prompt preserved verbatim in `key_points` or `hook`
- No provider is promised that `provider_used.available` does not list
