"""Launch the repository's Backlot board as a companion of the Studio.

Backlot ships with a deliberately narrow Host allowlist (``127.0.0.1`` /
``localhost``) because it serves local project files and defends against DNS
rebinding. That is the right default for desktop use, but when the Studio is
accessed through a port-forwarding preview proxy the browser's Host header is
the proxy's domain, and the board would answer HTTP 400.

This module starts the *unmodified* board and swaps only that middleware for a
permissive one, so a preview proxy can reach it. Nothing in ``backlot/`` is
changed; the board stays read-only.

    python -m studio.board_host            # honors BACKLOT_HOST / BACKLOT_PORT
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    import uvicorn
    from fastapi.middleware.trustedhost import TrustedHostMiddleware

    import backlot.server as board

    class _PreviewHosts(TrustedHostMiddleware):
        """Accept any Host header (preview proxy domains are not knowable)."""

        def __init__(self, app, allowed_hosts=None, www_redirect=False, **kwargs):  # noqa: D401
            super().__init__(app, allowed_hosts=["*"], www_redirect=False)

    board.TrustedHostMiddleware = _PreviewHosts

    host = os.environ.get("BACKLOT_HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("BACKLOT_PORT", "4750"))
    except ValueError:
        port = 4750

    app = board.create_app()
    print(f"backlot: serving on {host}:{port} (preview-proxy hosts allowed)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
