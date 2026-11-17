"""OpenMontage Studio — a small web frontend driving the repo's own tools.

The repository is the backend: this package never re-implements generation.
It discovers capabilities through ``tools.tool_registry``, calls the real
selector tools (``image_selector`` / ``video_selector``), and renders motion
with FFmpeg exactly the way the repo's post pipeline does.
"""

__version__ = "1.0.0"
