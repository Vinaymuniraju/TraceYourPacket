"""A small web front end: type a site or an IP, read the route report in the page.

Standard library only. The server runs the normal ``tracemap`` command as a child
process (no shell) for each request, one at a time, and serves the finished report
inside a sandboxed frame. The probes start from the machine running the server,
not from the visitor's device.

    tracemap-web --origin 12.97,77.59 --origin-name Bengaluru
    tracemap-web --host 0.0.0.0 --port 8080        # reachable from your home network
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

from .cli import _origin
from .runner import TargetError, validate_target

ASSETS = Path(__file__).resolve().parent / "assets"
PACKAGE_PARENT = Path(__file__).resolve().parent.parent

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,32}$")
# Only these lines of the child's output are shown to visitors. Everything else
# (paths, saved-run notes) stays on the server.
_PUBLIC_LINE = re.compile(r"^(\s*\d+\s|run \d+ of \d+|note:\s|hint:\s|warn:\s)")

MAX_BODY = 2048
MAX_LOG_LINES = 200


class BusyError(Exception):
    """The queue is full."""


class RateLimitError(Exception):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


def normalise_target(text: str) -> str:
    """Turn what a person typed into a bare host name or IPv4 address.

    Accepts ``example.com``, ``https://example.com/some/page?q=1``, ``8.8.8.8:443``.
    """
    text = (text or "").strip()
    if not text or len(text) > 300 or any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise TargetError("type a website or an IPv4 address")
    probe = text if "://" in text else "//" + text
    try:
        host = urlsplit(probe).hostname
    except ValueError as exc:
        raise TargetError("that does not look like a website or an IP address") from exc
    if not host:
        raise TargetError("that does not look like a website or an IP address")
    return host.rstrip(".")


def resolve_public(text: str) -> tuple[str, str]:
    """Return (host name, IPv4) for a public target, or raise TargetError.

    Private, loopback, link-local, carrier-grade NAT, multicast and reserved
    addresses are refused so the site cannot be used to probe the network it
    runs on.
    """
    host = normalise_target(text)
    name, ip = validate_target(host)
    addr = ipaddress.ip_address(ip)
    if not addr.is_global or addr.is_multicast or addr.is_reserved:
        raise TargetError("private and internal addresses cannot be traced from this site")
    return name, ip


class Job:
    def __init__(self, job_id: str, name: str, ip: str, outdir: Path, client: str):
        self.id = job_id
        self.name = name
        self.ip = ip
        self.outdir = outdir
        self.client = client
        self.state = "queued"           # queued | running | done | error
        self.created = time.time()
        self.finished: Optional[float] = None
        self.lines: list[str] = []
        self.error: Optional[str] = None
        self.report: Optional[Path] = None
        self.map: Optional[Path] = None

    @property
    def active(self) -> bool:
        return self.state in ("queued", "running")


def default_command(ip: str, outdir: Path, *, origin: Optional[tuple[float, float]] = None,
                    cables: str = "auto", max_hops: int = 30, timeout: int = 120) -> list[str]:
    cmd = [sys.executable, "-m", "tracemap", ip, "-o", str(outdir), "--no-save",
           "--max-hops", str(max_hops), "--timeout", str(timeout), "--cables", cables]
    if origin:
        cmd += ["--origin", f"{origin[0]},{origin[1]}"]
    return cmd


class TraceService:
    """Queue, rate limits, cache and the worker that runs the child process."""

    def __init__(self, workdir: Path, *,
                 command: Optional[Callable[[str, Path], list[str]]] = None,
                 resolver: Callable[[str], tuple[str, str]] = resolve_public,
                 max_queue: int = 5, cache_ttl: int = 600, job_ttl: int = 3600,
                 max_jobs: int = 60, run_timeout: int = 180,
                 per_client_active: int = 2, per_client_window: int = 10,
                 window_seconds: int = 600, start_worker: bool = True):
        self.workdir = workdir
        self.command = command or (lambda ip, outdir: default_command(ip, outdir))
        self.resolver = resolver
        self.max_queue = max_queue
        self.cache_ttl = cache_ttl
        self.job_ttl = job_ttl
        self.max_jobs = max_jobs
        self.run_timeout = run_timeout
        self.per_client_active = per_client_active
        self.per_client_window = per_client_window
        self.window_seconds = window_seconds
        self._jobs: dict[str, Job] = {}
        self._queue: "queue.Queue[Job]" = queue.Queue()
        self._recent: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        if start_worker:
            self._worker = threading.Thread(target=self._loop, name="trace-worker", daemon=True)
            self._worker.start()

    # ---- submitting -------------------------------------------------------------

    def submit(self, raw_target: str, client: str) -> tuple[Job, bool]:
        """Return (job, reused). Raises TargetError, RateLimitError or BusyError."""
        name, ip = self.resolver(raw_target)
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            for job in self._jobs.values():
                if job.ip != ip:
                    continue
                if job.active or (job.state == "done" and job.finished
                                  and now - job.finished < self.cache_ttl):
                    return job, True
            mine = [j for j in self._jobs.values() if j.client == client and j.active]
            if len(mine) >= self.per_client_active:
                raise RateLimitError("you already have traces running, wait for them to finish", 10)
            stamps = [t for t in self._recent.get(client, []) if now - t < self.window_seconds]
            if len(stamps) >= self.per_client_window:
                wait = int(self.window_seconds - (now - stamps[0])) + 1
                raise RateLimitError("too many traces in a short time, try again soon", wait)
            if sum(1 for j in self._jobs.values() if j.active) >= self.max_queue:
                raise BusyError("the server is busy, try again in a minute")
            stamps.append(now)
            self._recent[client] = stamps
            job_id = secrets.token_urlsafe(9)
            outdir = self.workdir / job_id
            job = Job(job_id, name, ip, outdir, client)
            self._jobs[job_id] = job
            self._queue.put(job)
        return job, False

    def get(self, job_id: str) -> Optional[Job]:
        if not _ID_RE.match(job_id):
            return None
        with self._lock:
            return self._jobs.get(job_id)

    def position(self, job: Job) -> int:
        """0 when running or finished, otherwise how many jobs are ahead in the queue."""
        with self._lock:
            if job.state != "queued":
                return 0
            ahead = [j for j in self._jobs.values()
                     if j.state in ("queued", "running") and j.created < job.created]
            return len(ahead)

    # ---- worker -----------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._run(job)
            except Exception as exc:  # never let the worker die
                self._fail(job, f"internal error: {type(exc).__name__}")

    def _fail(self, job: Job, message: str) -> None:
        with self._lock:
            job.state = "error"
            job.error = message
            job.finished = time.time()

    def _run(self, job: Job) -> None:
        with self._lock:
            job.state = "running"
        job.outdir.mkdir(parents=True, exist_ok=True)
        cmd = self.command(job.ip, job.outdir)
        # Make sure the child can import this package even when it is run from a
        # source checkout instead of being pip-installed.
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(p for p in (str(PACKAGE_PARENT), env.get("PYTHONPATH", "")) if p)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, errors="replace", stdin=subprocess.DEVNULL, env=env,
                                    cwd=job.outdir)
        except OSError as exc:
            self._fail(job, f"could not start the trace: {exc.strerror or 'error'}")
            return
        timer = threading.Timer(self.run_timeout, proc.kill)
        timer.start()
        last_error = None
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line.startswith("error:"):
                    last_error = line[len("error:"):].strip()
                if _PUBLIC_LINE.match(line) and len(job.lines) < MAX_LOG_LINES:
                    with self._lock:
                        job.lines.append(line[:300])
            proc.wait()
        finally:
            timer.cancel()
        if proc.returncode != 0:
            msg = last_error or "the trace did not finish"
            msg = msg.replace(str(self.workdir), "…")[:300]
            self._fail(job, msg)
            return
        reports = sorted(p for p in job.outdir.glob("route_*.html") if not p.name.endswith("_map.html"))
        maps = sorted(job.outdir.glob("route_*_map.html"))
        if not reports:
            self._fail(job, "the trace finished but no report was written")
            return
        with self._lock:
            job.report = reports[0]
            job.map = maps[0] if maps else None
            job.state = "done"
            job.finished = time.time()

    # ---- housekeeping -----------------------------------------------------------

    def _prune_locked(self, now: float) -> None:
        old = [j for j in self._jobs.values() if not j.active and j.finished
               and now - j.finished > self.job_ttl]
        extra = len(self._jobs) - self.max_jobs
        if extra > 0:
            finished = sorted((j for j in self._jobs.values() if not j.active and j not in old),
                              key=lambda j: j.finished or 0)
            old += finished[:extra]
        for job in old:
            self._jobs.pop(job.id, None)
            shutil.rmtree(job.outdir, ignore_errors=True)
        for client in [c for c, s in self._recent.items()
                       if all(now - t >= self.window_seconds for t in s)]:
            self._recent.pop(client, None)

    def close(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=2)


# ---- HTTP ------------------------------------------------------------------------

_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_PAGE_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
             "connect-src 'self'; frame-src 'self'; img-src data:; base-uri 'none'; "
             "form-action 'none'; frame-ancestors 'none'")
# The report is self-contained. Sandboxing it without allow-same-origin gives it a
# throw-away origin, so nothing inside it can reach the API or the page around it.
_REPORT_CSP = ("sandbox allow-scripts; connect-src 'none'; form-action 'none'; "
               "base-uri 'none'; frame-ancestors 'self'")


def make_handler(service: TraceService, info: dict) -> type[BaseHTTPRequestHandler]:
    index_html = (ASSETS / "web_index.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        server_version = "tracemap-web"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # keep the console readable
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

        def _send(self, status: int, body: bytes, ctype: str, extra: Optional[dict] = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in {**_BASE_HEADERS, **(extra or {})}.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload: dict, extra: Optional[dict] = None) -> None:
            headers = {"Cache-Control": "no-store", **(extra or {})}
            self._send(status, json.dumps(payload).encode(), "application/json; charset=utf-8", headers)

        def _job_payload(self, job: Job, reused: bool = False) -> dict:
            payload = {"id": job.id, "target": job.name, "ip": job.ip, "state": job.state,
                       "lines": list(job.lines), "reused": reused}
            if job.state == "queued":
                payload["ahead"] = service.position(job)
            if job.state == "error":
                payload["error"] = job.error
            if job.state == "done":
                payload["report"] = f"/report/{job.id}"
                payload["map"] = f"/report/{job.id}/map" if job.map else None
            return payload

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/":
                return self._send(200, index_html, "text/html; charset=utf-8",
                                  {"Content-Security-Policy": _PAGE_CSP, "Cache-Control": "no-cache"})
            if path == "/healthz":
                return self._send(200, b"ok\n", "text/plain; charset=utf-8")
            if path == "/api/info":
                return self._json(200, info)
            m = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)", path)
            if m:
                job = service.get(m.group(1))
                if not job:
                    return self._json(404, {"error": "unknown trace"})
                return self._json(200, self._job_payload(job))
            m = re.fullmatch(r"/report/([A-Za-z0-9_-]+)(/map)?", path)
            if m:
                job = service.get(m.group(1))
                target = (job.map if m.group(2) else job.report) if job else None
                if not job or job.state != "done" or target is None:
                    return self._send(404, b"not found\n", "text/plain; charset=utf-8")
                try:
                    body = target.read_bytes()
                except OSError:
                    return self._send(404, b"not found\n", "text/plain; charset=utf-8")
                return self._send(200, body, "text/html; charset=utf-8",
                                  {"Content-Security-Policy": _REPORT_CSP, "Cache-Control": "no-store"})
            self._send(404, b"not found\n", "text/plain; charset=utf-8")

        def do_POST(self):
            if urlsplit(self.path).path != "/api/trace":
                self.close_connection = True
                return self._send(404, b"not found\n", "text/plain; charset=utf-8")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= MAX_BODY:
                self.close_connection = True
                return self._json(400, {"error": "bad request"}, {"Connection": "close"})
            try:
                data = json.loads(self.rfile.read(length))
                target = data["target"]
                if not isinstance(target, str):
                    raise TypeError
            except (ValueError, KeyError, TypeError):
                return self._json(400, {"error": "send JSON like {\"target\": \"example.com\"}"})
            client = self.client_address[0]
            try:
                job, reused = service.submit(target, client)
            except TargetError as exc:
                return self._json(400, {"error": str(exc)})
            except RateLimitError as exc:
                return self._json(429, {"error": str(exc)}, {"Retry-After": str(exc.retry_after)})
            except BusyError as exc:
                return self._json(503, {"error": str(exc)}, {"Retry-After": "30"})
            self._json(202, self._job_payload(job, reused))

    return Handler


def make_server(host: str, port: int, service: TraceService, info: Optional[dict] = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(service, info or {}))
    server.daemon_threads = True
    return server


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="tracemap-web",
                                description="Serve a page where you type a site or IP and see its route on the cable map.")
    p.add_argument("--host", default="127.0.0.1",
                   help="address to listen on (default 127.0.0.1, this machine only; use 0.0.0.0 for your whole network)")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--origin", type=_origin, metavar="LAT,LON", help="where this server is, drawn as the route's start")
    p.add_argument("--origin-name", default="", help="place name shown on the page, for example Bengaluru")
    p.add_argument("--cables", choices=["auto", "telegeography", "illustrative", "none"], default="auto")
    p.add_argument("--max-hops", type=int, default=30)
    p.add_argument("--trace-timeout", type=int, default=120, help="seconds before one traceroute is stopped")
    p.add_argument("--max-queue", type=int, default=5, help="traces waiting or running at once")
    p.add_argument("--cache-seconds", type=int, default=600, help="reuse a finished trace to the same IP for this long")
    p.add_argument("--workdir", type=Path, help="where reports are kept (default: a temporary folder)")
    args = p.parse_args(argv)

    if not 1 <= args.port <= 65535 or not 1 <= args.max_hops <= 64 or args.trace_timeout < 5:
        p.error("port, max-hops or trace-timeout out of range")

    own_dir = args.workdir is None
    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="tracemap-web-"))
    workdir.mkdir(parents=True, exist_ok=True)

    def command(ip: str, outdir: Path) -> list[str]:
        return default_command(ip, outdir, origin=args.origin, cables=args.cables,
                               max_hops=args.max_hops, timeout=args.trace_timeout)

    service = TraceService(workdir, command=command, max_queue=args.max_queue,
                           cache_ttl=args.cache_seconds, run_timeout=args.trace_timeout + 60)
    info = {"origin_name": args.origin_name[:60], "origin": list(args.origin) if args.origin else None}
    try:
        server = make_server(args.host, args.port, service, info)
    except OSError as exc:
        print(f"error: cannot listen on {args.host}:{args.port}: {exc.strerror}", file=sys.stderr)
        service.close()
        return 1
    shown = "localhost" if args.host in ("127.0.0.1", "::1") else args.host
    print(f"tracemap-web listening on http://{shown}:{args.port}/  (Ctrl+C to stop)")
    if args.host not in ("127.0.0.1", "::1", "localhost"):
        print("note: anyone who can reach this port can start traces from this machine", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
        service.close()
        if own_dir:
            shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
