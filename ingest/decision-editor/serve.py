#!/usr/bin/env python3
"""Local server for the decision editor (skeleton).

Serves the single-page app from web/ and exposes the workspace's decision artifacts as JSON. Stdlib
only — no dependencies, no build step.

  python3 ingest/decision-editor/serve.py [workspace] [--port 8765]

With a workspace path it reads `<workspace>/.photos-ingest/photos-21-time-decisions.json` and
`…/photos-22-gps-decisions.json`. With no workspace it runs in DEMO mode, loading the `examples/`
fixtures so the app is runnable with nothing set up. (Skeleton: read-only. Saving, the map/photo panel,
and re-run land in later phases — see design-notes.md.)
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
EXAMPLES = os.path.join(HERE, "examples")
CONTROL = ".photos-ingest"
TIME_NAME = "photos-21-time-decisions.json"
GPS_NAME = "photos-22-gps-decisions.json"

_CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
                  ".svg": "image/svg+xml"}


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as e:
        return {"_error": f"could not read {os.path.basename(path)}: {e}"}


def _load_artifacts(workspace):
    """Return {workspace, demo, time, gps}. Demo mode loads the requires-input example fixtures."""
    if workspace:
        cd = os.path.join(workspace, CONTROL)
        return {"workspace": os.path.abspath(workspace), "demo": False,
                "time": _read_json(os.path.join(cd, TIME_NAME)),
                "gps": _read_json(os.path.join(cd, GPS_NAME))}
    return {"workspace": None, "demo": True,
            "time": _read_json(os.path.join(EXAMPLES, "photos-21-time-decisions.requires-input.json")),
            "gps": _read_json(os.path.join(EXAMPLES, "photos-22-gps-decisions.requires-input.json"))}


class Handler(BaseHTTPRequestHandler):
    workspace = None

    def log_message(self, *a):
        pass  # quiet

    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, rel):
        rel = rel.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(WEB, rel))
        if not full.startswith(WEB + os.sep) and full != os.path.join(WEB, "index.html"):
            return self._send(403, {"error": "forbidden"})
        if not os.path.isfile(full):
            return self._send(404, {"error": f"not found: {rel}"})
        ct = _CONTENT_TYPES.get(os.path.splitext(full)[1], "application/octet-stream")
        with open(full, "rb") as f:
            self._send(200, f.read(), ct)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/artifacts":
            return self._send(200, _load_artifacts(self.workspace))
        if path == "/":
            return self._serve_static("index.html")
        return self._serve_static(path)


def main():
    ap = argparse.ArgumentParser(description="Decision editor server (skeleton).")
    ap.add_argument("workspace", nargs="?", default=None,
                    help="Workspace dir (reads its .photos-ingest/). Omit for demo mode (example fixtures).")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    if args.workspace and not os.path.isdir(os.path.join(args.workspace, CONTROL)):
        print(f"warning: {args.workspace}/{CONTROL} not found — is that a workspace?", file=sys.stderr)
    Handler.workspace = args.workspace
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    mode = "demo (example fixtures)" if not args.workspace else f"workspace {os.path.abspath(args.workspace)}"
    print(f"decision editor — {mode}\n  open http://{args.host}:{args.port}/   (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
