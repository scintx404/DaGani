"""Convenience launcher for GSuite web editor + gani-agent AI Copilot."""
import argparse
import asyncio
import http.server
import json
import logging
import socket
import socketserver
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENT_DIR = ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from gani_agent.server import build_router, serve

class GSuiteHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        url_path = self.path.split("?")[0]
        norm_dir = url_path.rstrip("/") + "/"
        if norm_dir == "/ganis/":
            ganis_dir = ROOT / "ganis"
            files = sorted([f.name for f in ganis_dir.iterdir() if f.is_file() and f.suffix.lower() == ".gani"]) if ganis_dir.exists() else []
            return self._send_json(files)
        elif norm_dir == "/levels/":
            levels_dir = ROOT / "levels"
            exts = (".nw", ".zelda", ".graal", ".gmap")
            files = sorted([f.name for f in levels_dir.iterdir() if f.is_file() and f.suffix.lower() in exts]) if levels_dir.exists() else []
            return self._send_json(files)
        elif norm_dir == "/objects/":
            objs_dir = ROOT / "objects"
            files = sorted([f.name for f in objs_dir.iterdir() if f.is_file() and f.suffix.lower() == ".npc"]) if objs_dir.exists() else []
            return self._send_json(files)
        elif url_path in ("/token", "/.gani-agent/token"):
            token_p = ROOT / ".gani-agent" / "token"
            if token_p.exists():
                return self._send_text(token_p.read_text().strip())

        return super().do_GET()

    def _send_json(self, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def guess_type(self, path):
        p = str(path).lower()
        if p.endswith((".gani", ".nw", ".npc", ".zelda", ".graal", ".gmap")):
            return "text/plain"
        return super().guess_type(path)

    def log_message(self, format, *args):
        if logging.getLogger("gani_agent").isEnabledFor(logging.DEBUG):
            super().log_message(format, *args)

def is_port_in_use(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

def start_web_server(host="0.0.0.0", port=13772):
    if is_port_in_use(port, host="127.0.0.1"):
        logging.getLogger("gani_agent").info("Web port %d already active (e.g. node server.js)", port)
        return None
    try:
        class ReusableTCPServer(socketserver.TCPServer):
            allow_reuse_address = True
        server = ReusableTCPServer((host, port), GSuiteHTTPHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server
    except OSError as e:
        logging.getLogger("gani_agent").warning("Could not bind web port %d: %s", port, e)
        return None

def main():
    p = argparse.ArgumentParser(prog="gani-agent", description="GSuite Web Editor + GANI AI Copilot Launcher")
    p.add_argument("--port", type=int, default=8765, help="AI sidecar WebSocket port (default: 8765)")
    p.add_argument("--host", default="127.0.0.1", help="AI sidecar host (default: 127.0.0.1)")
    p.add_argument("--web-port", type=int, default=13772, help="GSuite web editor port (default: 13772)")
    p.add_argument("--no-browser", action="store_true", help="Do not automatically open web browser")
    p.add_argument("-v", action="store_true", help="Verbose debug logging")
    a = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO)

    start_web_server("0.0.0.0", a.web_port)

    web_url = f"http://localhost:{a.web_port}/"
    ws_url = f"ws://{a.host}:{a.port}"

    print("=" * 60)
    print("  GSuite Animation Editor + GANI AI Copilot")
    print("=" * 60)
    print(f"  Web Editor:  {web_url}")
    print(f"  AI Sidecar:  {ws_url}")
    print("=" * 60)

    if not a.no_browser:
        def open_browser():
            time.sleep(0.7)
            webbrowser.open(web_url)
        threading.Thread(target=open_browser, daemon=True).start()

    asyncio.run(serve(build_router(), a.host, a.port, web_port=a.web_port))

if __name__ == "__main__":
    main()
