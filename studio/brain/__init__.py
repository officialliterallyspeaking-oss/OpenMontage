"""The four intelligence systems behind the studio.

    director    System 1 — Viral Content Director (what to make, and why)
    creative    System 2 — Universal Creative Engine  (brief -> assets)
    producer    System 3 — Automatic Production Engine (assets -> finished video)
    growth      System 4 — TikTok Growth Engine        (video -> publishing package)

They share one `Project` (see `projects.py`) and are sequenced by
`orchestrator.py`. Nothing here calls an LLM: creative judgement is encoded as
explicit, inspectable knowledge and scoring, so every recommendation can be
explained and reproduced.
"""

from studio.brain.projects import Project, ProjectStore

__all__ = ["Project", "ProjectStore"]
