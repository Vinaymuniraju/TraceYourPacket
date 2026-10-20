import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tracemap.runner import TargetError
from tracemap.web import (BusyError, RateLimitError, TraceService, make_server,
                          normalise_target, resolve_public)

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.mark.parametrize("text,host", [
    ("example.com", "example.com"),
    ("  Example.COM  ", "example.com"),
    ("https://example.com/some/page?q=1#x", "example.com"),
    ("http://user:pw@example.com:8080/", "example.com"),
    ("example.com.", "example.com"),
    ("8.8.8.8", "8.8.8.8"),
    ("8.8.8.8:443", "8.8.8.8"),
])
def test_normalise_target(text, host):
    assert normalise_target(text) == host


@pytest.mark.parametrize("text", ["", "   ", "http://", "a\nb.com", "x" * 400, "http://[::1"])
def test_normalise_rejects_junk(text):
    with pytest.raises(TargetError):
        normalise_target(text)


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.1.2.3", "192.168.1.1", "172.16.0.9", "169.254.1.1", "100.64.0.1",
    "0.0.0.0", "224.0.0.1", "255.255.255.255", "240.0.0.1",
])
def test_non_public_addresses_are_refused(ip):
    with pytest.raises(TargetError):
        resolve_public(ip)
    with pytest.raises(TargetError):
        resolve_public(f"http://{ip}/admin")


def test_public_ip_is_accepted():
    assert resolve_public("https://8.8.8.8/x") == ("8.8.8.8", "8.8.8.8")


def test_option_like_target_is_refused():
    with pytest.raises(TargetError):
        resolve_public("-h")


def _sample_command(ip, outdir):
    """Replay the bundled sample instead of running a real traceroute."""
    return [sys.executable, "-m", "tracemap", ip, "--input", str(SAMPLES / "traceroute_sample.txt"),
            "--geo-file", str(SAMPLES / "geo_sample.json"), "--offline", "--no-cache", "--no-save",
            "--cables", "illustrative", "--origin", "12.97,77.59", "-o", str(outdir)]


def _fake_resolver(text):
    host = normalise_target(text)
    table = {"example.test": "203.0.113.10", "other.test": "198.51.100.7"}
    if host in table:
        return host, table[host]
    return resolve_public(host)


def _wait(service, job, states=("done", "error"), timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if job.state in states:
            return
        time.sleep(0.1)
    raise AssertionError(f"job stuck in {job.state}")


@pytest.fixture
def service(tmp_path):
    svc = TraceService(tmp_path / "work", command=_sample_command, resolver=_fake_resolver)
    yield svc
    svc.close()


def test_job_runs_and_writes_report(service):
    job, reused = service.submit("https://example.test/page", "1.2.3.4")
    assert not reused
    _wait(service, job)
    assert job.state == "done", job.error
    assert job.report.name.startswith("route_") and job.report.read_text().startswith("<!doctype html>")
    assert job.map is not None


def test_only_hop_lines_reach_visitors(tmp_path):
    script = (
        "import sys, pathlib\n"
        "out = pathlib.Path(sys.argv[1])\n"
        "print(' 1  192.168.1.1  1.0 ms  1.1 ms  1.2 ms')\n"
        "print('saved:  /srv/secret/run.json')\n"
        "print('note:   cables are illustrative')\n"
        "print('report: ' + str(out / 'route_x.html'))\n"
        "(out / 'route_x.html').write_text('<!doctype html>ok')\n"
    )
    svc = TraceService(tmp_path / "w", resolver=_fake_resolver,
                       command=lambda ip, out: [sys.executable, "-c", script, str(out)])
    try:
        job, _ = svc.submit("example.test", "c")
        _wait(svc, job)
        assert job.state == "done", job.error
        assert job.lines == [" 1  192.168.1.1  1.0 ms  1.1 ms  1.2 ms", "note:   cables are illustrative"]
    finally:
        svc.close()


def test_same_target_is_reused_from_cache(service):
    first, _ = service.submit("example.test", "1.2.3.4")
    _wait(service, first)
    again, reused = service.submit("EXAMPLE.test", "5.6.7.8")
    assert reused and again.id == first.id


def test_failed_trace_reports_error(tmp_path):
    svc = TraceService(tmp_path / "w", resolver=_fake_resolver,
                       command=lambda ip, out: [sys.executable, "-c", "import sys;print('error: boom');sys.exit(1)"])
    try:
        job, _ = svc.submit("example.test", "c")
        _wait(svc, job)
        assert job.state == "error" and job.error == "boom"
    finally:
        svc.close()


def test_rate_limit_and_queue(tmp_path):
    svc = TraceService(tmp_path / "w", resolver=_fake_resolver, start_worker=False,
                       per_client_active=2, max_queue=3)
    try:
        svc.submit("8.8.8.8", "a")
        svc.submit("8.8.4.4", "a")
        with pytest.raises(RateLimitError):
            svc.submit("1.1.1.1", "a")          # third active job for the same client
        svc.submit("1.1.1.1", "b")
        with pytest.raises(BusyError):
            svc.submit("9.9.9.9", "c")           # queue of 3 is full
    finally:
        svc.close()


def test_window_limit(tmp_path):
    svc = TraceService(tmp_path / "w", resolver=_fake_resolver, start_worker=False,
                       per_client_active=99, per_client_window=2, max_queue=99)
    try:
        svc.submit("8.8.8.8", "a")
        svc.submit("8.8.4.4", "a")
        with pytest.raises(RateLimitError) as exc:
            svc.submit("1.1.1.1", "a")
        assert exc.value.retry_after > 0
    finally:
        svc.close()


# ---- over HTTP ------------------------------------------------------------------

@pytest.fixture
def http(tmp_path):
    svc = TraceService(tmp_path / "work", command=_sample_command, resolver=_fake_resolver)
    server = make_server("127.0.0.1", 0, svc, {"origin_name": "Testville"})
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, svc
    server.shutdown()
    server.server_close()
    svc.close()


def _call(base, path, data=None, raw=None):
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(base + path, data=body, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_http_flow(http):
    base, svc = http
    status, headers, body = _call(base, "/")
    assert status == 200 and b"TraceYourPacket" in body
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert json.loads(_call(base, "/api/info")[2])["origin_name"] == "Testville"

    status, _, body = _call(base, "/api/trace", {"target": "https://example.test/x"})
    assert status == 202
    job = json.loads(body)
    _wait(svc, svc.get(job["id"]))
    status, _, body = _call(base, f"/api/jobs/{job['id']}")
    info = json.loads(body)
    assert info["state"] == "done" and info["report"] == f"/report/{job['id']}"

    status, headers, body = _call(base, info["report"])
    assert status == 200 and body.startswith(b"<!doctype html>")
    assert headers["Content-Security-Policy"].startswith("sandbox allow-scripts")
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert _call(base, info["map"])[0] == 200


def test_http_rejects_bad_requests(http):
    base, _ = http
    assert _call(base, "/api/trace", {"target": "192.168.1.1"})[0] == 400
    assert _call(base, "/api/trace", {"target": "127.0.0.1"})[0] == 400
    assert _call(base, "/api/trace", {"target": 5})[0] == 400
    assert _call(base, "/api/trace", raw=b"not json")[0] == 400
    assert _call(base, "/api/trace", raw=b"x" * 5000)[0] == 400
    assert _call(base, "/api/trace", {"nope": 1})[0] == 400


def test_http_unknown_and_unsafe_paths(http, tmp_path):
    base, _ = http
    for path in ["/nope", "/api/jobs/doesnotexist1", "/report/doesnotexist1", "/report/../../etc/passwd",
                 "/report/%2e%2e%2f%2e%2e%2fetc%2fpasswd", "/api/jobs/x", "/tracemap/web.py"]:
        assert _call(base, path)[0] == 404, path
    assert _call(base, "/healthz")[0] == 200
