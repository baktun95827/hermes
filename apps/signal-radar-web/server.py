#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_DIR = REPO_ROOT / "services" / "signal-radar-worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from worker import DEFAULT_CONFIG, DEFAULT_JOBS_DIR, create_manual_job  # noqa: E402


WORKER = WORKER_DIR / "worker.py"
DEFAULT_HOST = os.environ.get("XRADAR_WEB_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("XRADAR_WEB_PORT", "8765"))
CONFIG_PATH = os.environ.get("XRADAR_CONFIG", str(DEFAULT_CONFIG))
JOBS_DIR = os.environ.get("XRADAR_JOBS_DIR", str(DEFAULT_JOBS_DIR))
PROVIDER = os.environ.get("XRADAR_ANALYZER_PROVIDER", "fixture")
MODEL = os.environ.get("XRADAR_CODEX_MODEL", "gpt-5.4")


def read_json(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def html_page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --ink: #1f2421;
      --muted: #6f746d;
      --line: #d7cfbf;
      --accent: #22543d;
      --panel: #fffaf0;
    }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 10% 0%, rgba(191, 161, 102, 0.25), transparent 35%),
        linear-gradient(135deg, #f7f0df, #edf1e7);
      font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
    }}
    main {{
      max-width: 920px;
      margin: 48px auto;
      padding: 0 20px;
    }}
    .panel {{
      background: rgba(255, 250, 240, 0.92);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 28px;
      box-shadow: 0 22px 80px rgba(31, 36, 33, 0.12);
    }}
    h1 {{ margin-top: 0; font-size: 34px; letter-spacing: -0.03em; }}
    label {{ display: block; margin: 16px 0 6px; color: var(--muted); }}
    input, textarea, select {{
      width: 100%;
      box-sizing: border-box;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px 14px;
      background: #fffdf7;
      color: var(--ink);
      font: inherit;
    }}
    textarea {{ min-height: 240px; resize: vertical; }}
    button, .button {{
      display: inline-block;
      margin-top: 18px;
      border: 0;
      border-radius: 999px;
      padding: 12px 20px;
      background: var(--accent);
      color: white;
      font: inherit;
      text-decoration: none;
      cursor: pointer;
    }}
    pre {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: #1f2421;
      color: #f8f3e7;
      border-radius: 16px;
      padding: 16px;
    }}
    .muted {{ color: var(--muted); }}
    .row {{ display: grid; gap: 14px; grid-template-columns: 1fr 1fr; }}
    @media (max-width: 700px) {{ .row {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      {body}
    </section>
  </main>
</body>
</html>
""".encode("utf-8")


def render_index() -> bytes:
    body = f"""
<h1>Signal Radar Manual Ingest</h1>
<p class="muted">提交文本后会生成 manual collector batch，并交给 worker 分析。当前 provider: <strong>{html.escape(PROVIDER)}</strong></p>
<form method="post" action="/ingest-text">
  <label>标题，可选</label>
  <input name="title" placeholder="例如：英维克液冷订单传闻">
  <div class="row">
    <div>
      <label>来源标签</label>
      <input name="user_label" value="user_note">
    </div>
    <div>
      <label>URL，可选</label>
      <input name="url" placeholder="https://...">
    </div>
  </div>
  <label>内容</label>
  <textarea name="text" required placeholder="粘贴新闻、研报片段、社交媒体内容或你的研究笔记"></textarea>
  <label>
    <input type="checkbox" name="requires_verification" value="1" style="width: auto;">
    需要额外验证
  </label>
  <button type="submit">提交分析</button>
</form>
"""
    return html_page("Signal Radar", body)


def render_job(job_id: str) -> bytes:
    job_dir = Path(JOBS_DIR).expanduser().resolve() / job_id
    status = read_json(job_dir / "status.json")
    if not status:
        return html_page("Job Not Found", f"<h1>Job not found</h1><p>{html.escape(job_id)}</p>")
    summary_path = Path(status.get("paths", {}).get("summary", job_dir / "summary.txt"))
    summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    log_path = Path(status.get("paths", {}).get("worker_log", job_dir / "worker.log"))
    log_text = log_path.read_text(encoding="utf-8")[-8000:] if log_path.exists() else ""
    body = f"""
<h1>Job {html.escape(job_id)}</h1>
<p class="muted">Status: <strong>{html.escape(str(status.get("status")))}</strong></p>
<p><a class="button" href="/">提交新内容</a></p>
<h2>Status JSON</h2>
<pre>{html.escape(json.dumps(status, ensure_ascii=False, indent=2))}</pre>
<h2>Summary</h2>
<pre>{html.escape(summary or "summary not ready")}</pre>
<h2>Worker Log</h2>
<pre>{html.escape(log_text or "log not ready")}</pre>
"""
    return html_page(f"Job {job_id}", body)


class Handler(BaseHTTPRequestHandler):
    def send_html(self, payload: bytes, status: int = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            payload = b"ok\n"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/":
            self.send_html(render_index())
            return
        if parsed.path.startswith("/jobs/"):
            job_id = parsed.path.removeprefix("/jobs/").strip("/")
            self.send_html(render_job(job_id))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/ingest-text":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw_body = self.rfile.read(length).decode("utf-8")
        fields = parse_qs(raw_body)
        text = (fields.get("text") or [""])[0].strip()
        if not text:
            self.send_html(html_page("Missing Text", "<h1>Missing text</h1>"), HTTPStatus.BAD_REQUEST)
            return
        job_dir = create_manual_job(
            text=text,
            config_path=CONFIG_PATH,
            jobs_dir=JOBS_DIR,
            title=(fields.get("title") or [None])[0] or None,
            url=(fields.get("url") or [None])[0] or None,
            user_label=(fields.get("user_label") or ["user_note"])[0] or "user_note",
            input_channel="web",
            content_type="note",
            requires_verification=bool(fields.get("requires_verification")),
        )
        log_file = (job_dir / "web-dispatch.log").open("ab")
        try:
            subprocess.Popen(
                [
                    sys.executable,
                    str(WORKER),
                    "run-job",
                    "--job-dir",
                    str(job_dir),
                    "--provider",
                    PROVIDER,
                    "--model",
                    MODEL,
                ],
                cwd=str(REPO_ROOT),
                stdout=log_file,
                stderr=log_file,
                close_fds=True,
            )
        finally:
            log_file.close()
        job_id = job_dir.name
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/jobs/{job_id}")
        self.end_headers()


def main() -> int:
    server = ThreadingHTTPServer((DEFAULT_HOST, DEFAULT_PORT), Handler)
    print(f"Signal Radar Web listening on http://{DEFAULT_HOST}:{DEFAULT_PORT}")
    print(f"provider={PROVIDER} config={CONFIG_PATH} jobs_dir={JOBS_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
