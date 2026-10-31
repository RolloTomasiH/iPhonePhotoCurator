"""
Lightweight Local Web Dashboard Server for iPhone Photo Curator.
Runs on 127.0.0.1 without third-party web frameworks (zero external dependencies).
"""

import os
import sys
import json
import urllib.parse
import hashlib
import subprocess
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from core.scanner import scan_directory, ScanReport
from core.organizer import build_organization_plan, execute_plan, undo_manifest

CACHE_DIR = os.path.expanduser('~/.cache/iPhonePhotoCurator/thumbs')
os.makedirs(CACHE_DIR, exist_ok=True)

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in separate threads for non-blocking thumbnail loading."""
    daemon_threads = True

class CuratorHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence routine thumbnail logs to keep terminal tidy
        if "/api/thumbnail" not in args[0]:
            sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}\n")

    def send_json(self, data: dict, status_code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            html_file = os.path.join(current_dir, "static", "index.html")
            if os.path.exists(html_file):
                with open(html_file, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404, "index.html not found")
            return

        elif path == "/api/common_paths":
            home = os.path.expanduser("~")
            paths = [
                {"name": "图片 (Pictures)", "path": os.path.join(home, "Pictures")},
                {"name": "下载 (Downloads)", "path": os.path.join(home, "Downloads")},
                {"name": "桌面 (Desktop)", "path": os.path.join(home, "Desktop")},
            ]
            # Check mounted external drives
            if os.path.exists("/Volumes"):
                for vol in os.listdir("/Volumes"):
                    if not vol.startswith(".") and vol != "Macintosh HD":
                        paths.append({
                            "name": f"外接盘: {vol}",
                            "path": os.path.join("/Volumes", vol)
                        })
            self.send_json({"status": "success", "paths": paths})
            return

        elif path == "/api/thumbnail":
            params = urllib.parse.parse_qs(parsed.query)
            file_path = params.get("path", [""])[0]
            if not file_path or not os.path.exists(file_path):
                self.send_error(404, "File not found")
                return

            thumb_bytes = self.get_or_create_thumbnail(file_path)
            if thumb_bytes:
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(thumb_bytes)))
                self.send_header('Cache-Control', 'max-age=86400')
                self.end_headers()
                self.wfile.write(thumb_bytes)
            else:
                self.send_error(500, "Failed to render thumbnail")
            return

        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_len).decode('utf-8') if content_len > 0 else "{}"
        try:
            req_json = json.loads(post_data)
        except Exception:
            req_json = {}

        if path == "/api/scan":
            src_dir = os.path.expanduser(req_json.get("src_dir", ""))
            if not os.path.isdir(src_dir):
                self.send_json({"status": "error", "message": f"目录不存在: {src_dir}"}, 400)
                return

            compute_sim = req_json.get("compute_similarity", True)
            v_thresh = int(req_json.get("video_threshold", 100))

            report = scan_directory(
                src_dir=src_dir,
                large_video_threshold_mb=v_thresh,
                compute_similarity=compute_sim
            )
            self.send_json({"status": "success", "report": report.to_dict()})
            return

        elif path == "/api/organize":
            src_dir = os.path.expanduser(req_json.get("src_dir", ""))
            dest_dir = os.path.expanduser(req_json.get("dest_dir", ""))
            mode = req_json.get("mode", "dry_run") # dry_run, copy, move
            separate_screenshots = req_json.get("separate_screenshots", True)
            separate_large_videos = req_json.get("separate_large_videos", True)
            isolate_duplicates = req_json.get("isolate_duplicates", True)
            rename_files = req_json.get("rename_files", True)

            if not os.path.isdir(src_dir):
                self.send_json({"status": "error", "message": f"源目录不存在: {src_dir}"}, 400)
                return

            if not dest_dir:
                dest_dir = f"{src_dir}_organized"

            # Rescan without similarity calculation for fast execution plan
            report = scan_directory(src_dir=src_dir, compute_similarity=False)
            plan = build_organization_plan(
                report=report,
                dest_dir=dest_dir,
                mode=mode,
                separate_screenshots=separate_screenshots,
                separate_large_videos=separate_large_videos,
                isolate_duplicates=isolate_duplicates,
                rename_files=rename_files
            )

            result = execute_plan(plan)
            self.send_json(result)
            return

        elif path == "/api/undo":
            manifest_path = req_json.get("manifest_path", "")
            res = undo_manifest(manifest_path)
            self.send_json(res)
            return

        else:
            self.send_error(404, "API Not Found")

    def get_or_create_thumbnail(self, file_path: str, width: int = 240) -> bytes:
        """Returns JPEG bytes for thumbnail preview."""
        h = hashlib.md5(file_path.encode('utf-8')).hexdigest()
        cache_file = os.path.join(CACHE_DIR, f"{h}_{width}.jpg")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'rb') as f:
                    return f.read()
            except Exception:
                pass

        ext = os.path.splitext(file_path)[1].lower()
        if ext in ['.mov', '.mp4', '.m4v']:
            # Extract video frame using QuickTime / sips or return empty
            return b""

        try:
            cmd = ['sips', '-s', 'format', 'jpeg', '--resampleWidth', str(width), file_path, '--out', cache_file]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            if res.returncode == 0 and os.path.exists(cache_file):
                with open(cache_file, 'rb') as f:
                    return f.read()
        except Exception:
            pass

        return b""

def start_server(port: int = 8765):
    server_address = ('127.0.0.1', port)
    httpd = ThreadedHTTPServer(server_address, CuratorHandler)
    print(f"\n=======================================================")
    print(f"🚀 iPhone Photo Curator 智能整理看板已启动!")
    print(f"🌐 本地访问地址: http://127.0.0.1:{port}")
    print(f"按 Ctrl+C 可停止服务")
    print(f"=======================================================\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已优雅退出。")
        httpd.server_close()

if __name__ == "__main__":
    port = 8765
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    start_server(port)
