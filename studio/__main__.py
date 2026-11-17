"""CLI for OpenMontage Studio.

    python -m studio serve [--host 0.0.0.0] [--port 8000] [--reload]
    python -m studio doctor          # print the capability envelope
"""

from __future__ import annotations

import argparse
import json
import sys


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from studio.repo_bridge import ensure_ffmpeg

    ffmpeg = ensure_ffmpeg()
    print(f"studio: ffmpeg = {ffmpeg or 'NOT FOUND (video rendering unavailable)'}")

    if args.warm:
        from studio.repo_bridge import catalog

        data = catalog()
        print(f"studio: {data['tool_count']} tools discovered")
        for name, entry in data["capabilities"].items():
            print(f"  {name:18s} {entry['configured']}/{entry['total']} configured")

    uvicorn.run(
        "studio.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    from studio.repo_bridge import catalog, ffmpeg_status, ffprobe_status

    data = catalog()
    print(json.dumps(
        {
            "tools": data["tool_count"],
            "ffmpeg": data["ffmpeg"],
            "ffprobe": ffprobe_status(),
            "capabilities": {
                name: f"{e['configured']}/{e['total']}"
                for name, e in data["capabilities"].items()
            },
            "unlock": data["unlock"],
            "runtimes": data["runtimes"],
            "warnings": data["runtime_warnings"],
        },
        indent=2,
    ))
    return 0 if ffmpeg_status()["available"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="studio", description="OpenMontage Studio")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the Studio web app")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.add_argument("--warm", action="store_true", help="pre-discover tools and print the menu")
    serve.set_defaults(func=cmd_serve)

    doctor = sub.add_parser("doctor", help="print the capability envelope")
    doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
