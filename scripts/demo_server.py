#!/usr/bin/env python3
"""Presenter server for the D5 audit-first demo (stdlib only, no dependencies).

Serves the static HTML recommendation artifacts in ``scripts/out/`` over HTTP so a
presenter can click through the deterministic, cited recommendation sets without starting
the full Next.js console or the API. Run ``scripts/demo.py`` first to generate the JSON,
then ``scripts/render_recommendation_ui.py`` on each (or use ``--render``) to produce HTML.

Usage::

    python scripts/demo.py
    python scripts/demo_server.py --render        # render all out/*.json then serve
    # open http://localhost:8711/
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
from pathlib import Path

_OUT = Path(__file__).resolve().parent / "out"


def _render_all() -> None:
    from render_recommendation_ui import main as render_main  # type: ignore[import-not-found]

    for json_path in sorted(_OUT.glob("*.json")):
        render_main([str(json_path)])


def _index_html() -> str:
    links = []
    stems = [p.stem for p in sorted(_OUT.glob("*.html")) if p.name != "index.html"]
    for stem in stems:
        links.append(f"<li><a data-artifact='{stem}' href='{stem}.html'>{stem}</a></li>")
    body = "".join(links) or "<li>(run scripts/demo.py then --render)</li>"
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>D5 Next-Best-Action demo</title>"
        "<style>body{font:15px/1.6 system-ui;margin:40px;max-width:680px}"
        "h1{font-size:20px}li{margin:6px 0}</style></head><body>"
        "<h1>D5 Next-Best-Action — demo artifacts</h1>"
        "<p>Deterministic, cited recommendation sets (offline local profile).</p>"
        f"<ul data-panel='artifact-index' data-artifact-count='{len(stems)}'>{body}</ul>"
        "</body></html>"
    )


def make_server(port: int = 0, *, render: bool = False) -> socketserver.TCPServer:
    """Build the REAL presenter server, bound to ``port`` (``0`` = ephemeral).

    Shared by ``main`` and by the F2 anti-rot checks (``scripts/demo_selftest.py`` and
    ``tests/browser/test_served_demo_ui.py``), so those checks exercise the server the
    presenter actually runs rather than a stand-in they built themselves.
    """
    _OUT.mkdir(parents=True, exist_ok=True)
    if render:
        _render_all()
    (_OUT / "index.html").write_text(_index_html(), encoding="utf-8")
    socketserver.TCPServer.allow_reuse_address = True
    return socketserver.TCPServer(("127.0.0.1", port), _make_handler(_OUT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Presenter server for the D5 demo.")
    parser.add_argument("--port", type=int, default=8711)
    parser.add_argument("--render", action="store_true", help="Render all out/*.json first.")
    args = parser.parse_args(argv)

    with make_server(args.port, render=args.render) as httpd:
        print(f"serving D5 demo artifacts at http://127.0.0.1:{args.port}/ (Ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


def _make_handler(directory: Path) -> type[http.server.SimpleHTTPRequestHandler]:
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):  # type: ignore[no-untyped-def]
            super().__init__(*a, directory=str(directory), **kw)

    return Handler


if __name__ == "__main__":
    raise SystemExit(main())
