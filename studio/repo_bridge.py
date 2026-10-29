"""Bridge between the Studio UI and the OpenMontage repository.

Responsibilities, and nothing more:

* make sure ``ffmpeg`` is reachable (the repo shells out to the binary name),
* discover the real tool registry once and cache the capability summary,
* read/write provider keys in ``.env`` (the repo's own config surface),
* expose the subset of the catalog the Studio needs.

No generation logic lives here — that is ``pipelines.py``.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROJECTS_DIR = REPO_ROOT / "projects"
ENV_PATH = REPO_ROOT / ".env"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"
LOCAL_BIN = REPO_ROOT / ".runtime" / "bin"

# Capabilities the Studio cares about (the repo has ~25 families).
STUDIO_CAPABILITIES = ("image_generation", "video_generation", "tts")

_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


# ---------------------------------------------------------------------------
# ffmpeg
# ---------------------------------------------------------------------------

_ffmpeg_lock = threading.Lock()
_ffmpeg_state: dict[str, Any] = {"checked": False, "path": None, "source": None}


def ensure_ffmpeg() -> Optional[str]:
    """Make an ``ffmpeg`` binary resolvable by name, and return its path.

    Order: whatever is already on PATH -> the repo-local ``.runtime/bin``
    shim -> the ``imageio-ffmpeg`` wheel (a static build). The repo's tools
    (``video_compose``, ``video_stitch``, the Backlot thumbnails) all shell
    out to ``ffmpeg``, so putting a directory on PATH is what makes them work.
    """
    with _ffmpeg_lock:
        if _ffmpeg_state["checked"]:
            return _ffmpeg_state["path"]

        found = shutil.which("ffmpeg")
        source = "PATH" if found else None

        if not found:
            candidate = LOCAL_BIN / "ffmpeg"
            if candidate.exists():
                os.environ["PATH"] = f"{LOCAL_BIN}{os.pathsep}{os.environ.get('PATH', '')}"
                found, source = str(candidate), "repo .runtime/bin"
            else:
                try:  # static build shipped inside a Python wheel
                    import imageio_ffmpeg

                    binary = Path(imageio_ffmpeg.get_ffmpeg_exe())
                    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
                    link = LOCAL_BIN / "ffmpeg"
                    if not link.exists():
                        try:
                            link.symlink_to(binary)
                        except OSError:
                            shutil.copy2(binary, link)
                            link.chmod(0o755)
                    os.environ["PATH"] = f"{LOCAL_BIN}{os.pathsep}{os.environ.get('PATH', '')}"
                    found, source = shutil.which("ffmpeg"), "imageio-ffmpeg wheel"
                except Exception:  # pragma: no cover - no wheel, no binary
                    found, source = None, None

        _ffmpeg_state.update(checked=True, path=found, source=source)
        return found


def ffmpeg_status() -> dict[str, Any]:
    path = ensure_ffmpeg()
    return {"available": bool(path), "path": path, "source": _ffmpeg_state.get("source")}


def ffprobe_status() -> dict[str, Any]:
    path = shutil.which("ffprobe")
    return {"available": bool(path), "path": path}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_registry_lock = threading.RLock()
_registry_state: dict[str, Any] = {"loaded": False}


def registry():
    """Discover the repo registry once (import is expensive: ~150 modules)."""
    from tools.tool_registry import registry as tool_registry

    with _registry_lock:
        if not _registry_state["loaded"]:
            tool_registry.discover()
            _registry_state["loaded"] = True
        return tool_registry


def reload_registry() -> None:
    """Force a fresh discovery (used after keys change)."""
    from tools.tool_registry import registry as tool_registry

    with _registry_lock:
        tool_registry.clear()
        tool_registry.discover()
        _registry_state["loaded"] = True
        _registry_state.pop("catalog", None)


def _tool_row(tool) -> dict[str, Any]:
    info = tool.get_info()
    return {
        "name": info["name"],
        "provider": info["provider"],
        "capability": info["capability"],
        "status": info["status"],
        "runtime": info["runtime"],
        "stability": info["stability"],
        "best_for": (info.get("best_for") or [])[:3],
        "dependencies": info.get("dependencies") or [],
        "install_instructions": info.get("install_instructions") or "",
        "agent_skills": info.get("agent_skills") or [],
    }


def catalog() -> dict[str, Any]:
    """The capability menu, shaped for the Studio UI."""
    with _registry_lock:
        cached = _registry_state.get("catalog")
        if cached:
            return cached

        reg = registry()
        summary = reg.provider_menu_summary()
        caps = {c["capability"]: c for c in summary.get("capabilities", [])}

        capabilities: dict[str, Any] = {}
        for capability in STUDIO_CAPABILITIES:
            entry = caps.get(capability, {})
            tools = [_tool_row(t) for t in reg.get_by_capability(capability)]
            tools.sort(key=lambda r: (r["status"] != "available", r["provider"]))
            capabilities[capability] = {
                "configured": entry.get("configured", 0),
                "total": entry.get("total", len(tools)),
                "available_providers": entry.get("available_providers", []),
                "unavailable_providers": entry.get("unavailable_providers", []),
                "tools": tools,
            }

        # Group env vars -> providers they unlock, so the Keys panel can say
        # "FAL_KEY unlocks 6 providers" instead of listing 30 tools.
        unlock: dict[str, list[str]] = {}
        for capability in ("image_generation", "video_generation", "tts"):
            for row in capabilities[capability]["tools"]:
                if row["status"] == "available":
                    continue
                for dep in row["dependencies"]:
                    if dep.startswith("env:"):
                        unlock.setdefault(dep[4:], [])
                        if row["provider"] not in unlock[dep[4:]]:
                            unlock[dep[4:]].append(row["provider"])

        payload = {
            "tool_count": len(reg.list_all()),
            "runtimes": summary.get("composition_runtimes", {}),
            "runtime_warnings": summary.get("runtime_warnings", []),
            "capabilities": capabilities,
            "unlock": dict(
                sorted(unlock.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            ),
            "ffmpeg": ffmpeg_status(),
            "ffprobe": ffprobe_status(),
            "env": {
                "path": str(ENV_PATH),
                "exists": ENV_PATH.exists(),
                "configured": sorted(configured_env_names()),
            },
        }
        _registry_state["catalog"] = payload
        return payload


def provider_choices(capability: str) -> list[dict[str, Any]]:
    """Available providers for a capability, for the UI dropdown."""
    reg = registry()
    rows = [_tool_row(t) for t in reg.get_by_capability(capability)]
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["status"] != "available":
            continue
        seen.setdefault(
            row["provider"],
            {"provider": row["provider"], "tools": [], "runtimes": set()},
        )
        seen[row["provider"]]["tools"].append(row["name"])
        seen[row["provider"]]["runtimes"].add(row["runtime"])
    out = []
    for provider, data in sorted(seen.items()):
        out.append(
            {
                "provider": provider,
                "tools": sorted(data["tools"]),
                "runtime": sorted(data["runtimes"])[0],
            }
        )
    return out


# ---------------------------------------------------------------------------
# .env keys
# ---------------------------------------------------------------------------

def _parse_env_lines(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        pairs.append((key.strip(), value.strip()))
    return pairs


def configured_env_names() -> set[str]:
    """Names of env vars that are set to a non-empty value."""
    names: set[str] = set()
    if ENV_PATH.exists():
        for key, value in _parse_env_lines(ENV_PATH.read_text(encoding="utf-8")):
            if value and not value.startswith("#"):
                names.add(key)
    for key, value in os.environ.items():
        if value and _ENV_NAME_RE.match(key):
            names.add(key)
    return names


def known_keys() -> set[str]:
    """.env.example keys + every env: dependency declared by a tool."""
    names: set[str] = set()
    if ENV_EXAMPLE_PATH.exists():
        for key, _ in _parse_env_lines(ENV_EXAMPLE_PATH.read_text(encoding="utf-8")):
            names.add(key)
    try:
        reg = registry()
        for tool in reg.get_by_capability("image_generation") + reg.get_by_capability(
            "video_generation"
        ) + reg.get_by_capability("tts"):
            for dep in getattr(tool, "dependencies", []) or []:
                if dep.startswith("env:"):
                    names.add(dep[4:])
    except Exception:
        pass
    return names


def save_keys(pairs: dict[str, str]) -> dict[str, Any]:
    """Write provider keys into ``.env``, preserving comments and order.

    Only uppercase env names are accepted; values are stripped and must be
    single-line. An empty value clears the key. The file is written atomically
    and restricted to the owner.
    """
    accepted: dict[str, str] = {}
    rejected: dict[str, str] = {}
    for raw_key, raw_value in pairs.items():
        key = (raw_key or "").strip()
        value = (raw_value or "").strip()
        if not _ENV_NAME_RE.match(key) or "\n" in value or "\r" in value:
            rejected[key or "(empty)"] = "invalid env var name or multi-line value"
            continue
        accepted[key] = value

    if accepted:
        existing = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
        lines = existing.splitlines() if existing else []
        if not lines:
            lines = [
                "# OpenMontage Studio — provider keys written from the UI",
                "# Every key is optional; uncomment or fill what you have.",
                "",
            ]

        pending = dict(accepted)
        out: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.partition("=")[0].strip()
                if key in pending:
                    out.append(f"{key}={pending.pop(key)}")
                    continue
            out.append(line)
        if pending:
            if out and out[-1].strip():
                out.append("")
            out.append("# --- Added by Studio ---")
            for key, value in pending.items():
                out.append(f"{key}={value}")

        tmp = ENV_PATH.with_suffix(".env.tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, ENV_PATH)

    # Make the new keys live for this process without a restart. The repo's
    # tools read os.environ at status-check time, so this is sufficient.
    for key, value in accepted.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)

    _registry_state.pop("catalog", None)
    return {
        "saved": sorted(accepted),
        "rejected": rejected,
        "configured": sorted(configured_env_names() & known_keys()),
    }


def masked_keys() -> list[dict[str, Any]]:
    """Which keys are present (never their values)."""
    known = known_keys()
    configured = configured_env_names()
    catalog_unlock = catalog().get("unlock", {})
    rows = []
    for name in sorted(known | set(catalog_unlock)):
        rows.append(
            {
                "name": name,
                "configured": name in configured,
                "unlocks": catalog_unlock.get(name, []),
            }
        )
    return rows


__all__ = [
    "REPO_ROOT",
    "PROJECTS_DIR",
    "ENV_PATH",
    "ensure_ffmpeg",
    "ffmpeg_status",
    "ffprobe_status",
    "registry",
    "reload_registry",
    "catalog",
    "provider_choices",
    "configured_env_names",
    "known_keys",
    "save_keys",
    "masked_keys",
]
