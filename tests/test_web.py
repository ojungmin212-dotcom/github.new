import http.client
import json
import threading
import types
from datetime import UTC, datetime

import pytest
from conftest import NOW, FakeTransport, api_repo, ok_json, search_page

from ghrank import web
from ghrank.categories import load_categories
from ghrank.github import GitHubClient, Response
from ghrank.web import App, BadRequest, bind, find_running, normalize_repo, shortcut_script

README = "## Installation\n```bash\npip install sd-ui\n```\n## Usage\n```bash\nsd-ui --port 7860\n```\n"
CATS = load_categories()


def make_client(transport: FakeTransport, token: str | None = None) -> GitHubClient:
    return GitHubClient(token=token, transport=transport, sleep=lambda s: None, now=lambda: 1_000_000.0, log=lambda m: None)


def image_transport() -> FakeTransport:
    t = FakeTransport()
    t.add("search/repositories", search_page([
        api_repo("a/sd-ui", 700, description="Stable Diffusion <script>alert(1)</script> UI", license={"spdx_id": "AGPL-3.0"}),
        api_repo("a/awesome-image", 500, description="curated list"),
    ]))
    t.add("raw.githubusercontent.com/a/sd-ui", Response(200, {}, README.encode()))
    t.add("rate_limit", ok_json({"resources": {"search": {"limit": 30}, "core": {"limit": 5000}}}))
    return t


@pytest.fixture
def server():
    """실제 HTTP 서버를 임의 포트에 띄운다(가짜 GitHub 응답)."""
    transport = image_transport()
    app = App(make_client(transport, token="t"), CATS, now=lambda: NOW)
    srv = bind(app, 0, log=lambda m: None)
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    srv.transport = transport  # type: ignore[attr-defined]
    srv.app = app  # type: ignore[attr-defined]
    yield srv
    srv.shutdown()
    srv.server_close()


def request(srv, path, method="GET", headers=None, api=True):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    hdrs = {"X-Ghrank": "1"} if api else {}
    hdrs.update(headers or {})
    conn.request(method, path, headers=hdrs)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp, body


def get_json(srv, path):
    resp, body = request(srv, path)
    return resp.status, json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------------------
# 정적 파일·보안
# ---------------------------------------------------------------------------
def test_static_files_and_security_headers(server):
    resp, body = request(server, "/", api=False)
    assert resp.status == 200 and b"<title>ghrank</title>" in body
    csp = resp.getheader("Content-Security-Policy")
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert resp.getheader("X-Content-Type-Options") == "nosniff"
    for path, ctype in (("/app.js", "text/javascript"), ("/app.css", "text/css")):
        resp, body = request(server, path, api=False)
        assert resp.status == 200 and resp.getheader("Content-Type").startswith(ctype) and body


def test_frontend_never_uses_innerhtml():
    # README·설명 같은 외부 텍스트가 스크립트로 실행되지 않도록 화면 코드는 textContent 만 쓴다
    from importlib import resources

    js = resources.files("ghrank").joinpath("web", "app.js").read_text(encoding="utf-8")
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert forbidden not in js


def test_api_requires_custom_header(server):
    resp, body = request(server, "/api/categories", api=False)
    assert resp.status == 403 and "화면에서만" in json.loads(body)["error"]


def test_rejects_foreign_host_header(server):
    # DNS 리바인딩: 다른 도메인 이름으로 들어온 요청은 거부
    resp, _ = request(server, "/", api=False, headers={"Host": "evil.example:80"})
    assert resp.status == 403
    resp, _ = request(server, "/api/ping", headers={"Host": "evil.example"})
    assert resp.status == 403


def test_localhost_host_is_allowed(server):
    port = server.server_address[1]
    resp, _ = request(server, "/api/ping", headers={"Host": f"localhost:{port}"})
    assert resp.status == 200


def test_unknown_paths(server):
    assert request(server, "/nope", api=False)[0].status == 404
    assert request(server, "/api/nope")[0].status == 404
    assert request(server, "/favicon.ico", api=False)[0].status == 204
    assert request(server, "/api/nope", method="POST")[0].status == 404


def test_head_request(server):
    resp, body = request(server, "/", method="HEAD", api=False)
    assert resp.status == 200 and body == b""


# ---------------------------------------------------------------------------
# 기능
# ---------------------------------------------------------------------------
def test_ping_status_categories(server):
    assert get_json(server, "/api/ping") == (200, {"app": "ghrank", "version": web.__version__})
    status, data = get_json(server, "/api/status")
    assert status == 200 and data["token"] is True and data["limits"] == {"search": 30, "core": 5000}
    status, cats = get_json(server, "/api/categories")
    assert status == 200 and len(cats) == len(CATS) and cats[0]["key"] == "image"


def test_status_reports_rejected_token():
    t = FakeTransport()
    t.add("rate_limit", Response(401, {}, b"{}"))
    info = App(make_client(t, token="bad"), CATS).status()
    assert info["token"] is True and info["limits"] is None and "401" in info["error"]


def test_rate_limit_status_is_not_cached(tmp_path):
    from ghrank.github import FileCache

    t = FakeTransport()
    t.add("rate_limit", ok_json({"resources": {"search": {"limit": 10}, "core": {"limit": 60}}}))
    client = make_client(t)
    client.cache = FileCache(tmp_path, 3600)
    client.rate_limit()
    client.rate_limit()
    assert len(t.requests) == 2 and list(tmp_path.iterdir()) == []


def test_search_top_by_korean_alias(server):
    status, data = get_json(server, "/api/search?mode=top&category=%EC%9D%B4%EB%AF%B8%EC%A7%80&n=5")
    assert status == 200
    (ranking,) = data["rankings"]
    assert ranking["category"] == "image" and ranking["dropped_lists"] == 1
    repo = ranking["repos"][0]
    assert repo["full_name"] == "a/sd-ui" and any("AGPL" in c for c in repo["caveats"])
    # 외부 텍스트는 가공 없이 그대로(화면에서 textContent 로 넣음)
    assert "<script>" in repo["description"]


def test_search_find_free_text(server):
    status, data = get_json(server, "/api/search?mode=find&q=stable+diffusion+ui&raw=1")
    assert status == 200 and data["rankings"][0]["category"] is None
    assert "in%3Aname%2Cdescription%2Ctopics" in server.transport.requests[-1][0]


def test_find_note_mentions_checkbox_not_cli_flag(server):
    status, data = get_json(server, "/api/search?mode=find&q=%EC%9D%B4%EB%AF%B8%EC%A7%80")  # '이미지'
    assert status == 200 and "'검색어 그대로'" in data["notes"][0] and "--raw" not in data["notes"][0]


@pytest.mark.parametrize(
    ("query", "needle"),
    [
        ("mode=top", "분야를 고르세요"),
        ("mode=top&category=nope", "분야가 없습니다"),
        ("mode=find&q=", "검색어를 입력"),
        ("mode=find&q=" + "a" * 201, "200자"),
        ("mode=top&category=image&n=0", "개수"),
        ("mode=top&category=image&n=x", "숫자"),
        ("mode=top&category=image&sort=best", "정렬"),
        ("mode=top&category=image&lang=%3Cscript%3E", "언어"),
        ("mode=other", "조회 방식"),
    ],
)
def test_search_bad_requests(server, query, needle):
    status, data = get_json(server, "/api/search?" + query)
    assert status == 400 and needle in data["error"]


def test_guide_uses_repo_seen_in_ranking(server):
    get_json(server, "/api/search?mode=top&category=image")
    before = sum("search/repositories" in u for u, _ in server.transport.requests)
    status, data = get_json(server, "/api/guide?repo=https://github.com/a/sd-ui/tree/main")
    assert status == 200
    assert data["guide"]["install"][0]["code"] == "pip install sd-ui"
    assert data["guide"]["usage"][0]["code"] == "sd-ui --port 7860"
    assert sum("search/repositories" in u for u, _ in server.transport.requests) == before  # 검색 API 재호출 없음


def test_guide_unknown_repo_and_bad_input():
    t = FakeTransport()
    t.add("search/repositories", search_page([]))
    app = App(make_client(t), CATS)
    with pytest.raises(BadRequest):
        app.guide({"repo": "not a repo"})
    from ghrank.github import NotFoundError

    with pytest.raises(NotFoundError):
        app.guide({"repo": "o/missing"})


def test_guide_http_status_codes(server):
    server.transport.routes["search/repositories"] = [search_page([])]
    assert request(server, "/api/guide?repo=o/missing")[0].status == 404
    assert request(server, "/api/guide?repo=bad")[0].status == 400


def test_guide_readme_failure_becomes_note():
    t = FakeTransport()
    t.add("search/repositories", search_page([api_repo("a/x", 1)]))
    t.add("raw.githubusercontent.com", Response(500, {}, b"boom"))
    data = App(make_client(t), CATS).guide({"repo": "a/x"})
    assert "README 조회 실패" in data["guide"]["notes"][0]


def test_rate_limit_maps_to_429(server):
    server.transport.routes["search/repositories"] = [
        Response(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999"}, b"{}")
    ]
    status, data = get_json(server, "/api/guide?repo=z/z")
    assert status == 429 and "한도" in data["error"]


def test_github_error_maps_to_502(server):
    server.transport.routes["search/repositories"] = [Response(500, {}, b"down")]
    status, data = get_json(server, "/api/guide?repo=z/z")
    assert status == 502 and "500" in data["error"]


def test_unexpected_error_maps_to_500(server, monkeypatch):
    def boom(_params):
        raise RuntimeError("bug")

    monkeypatch.setattr(server.app, "guide", boom)
    status, data = get_json(server, "/api/guide?repo=a/b")
    assert status == 500 and "예기치 않은" in data["error"]


def test_report_markdown_download(server):
    resp, body = request(server, "/api/report?mode=top&category=image&n=3")
    assert resp.status == 200 and resp.getheader("Content-Type").startswith("text/markdown")
    assert "attachment" in resp.getheader("Content-Disposition")
    text = body.decode("utf-8")
    assert "# GitHub 분야별 저장소 순위" in text and "pip install sd-ui" in text


def test_shutdown_stops_server():
    app = App(make_client(image_transport()), CATS)
    srv = bind(app, 0, log=lambda m: None)
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    resp, body = request(srv, "/api/shutdown", method="POST")
    assert resp.status == 200 and json.loads(body) == {"ok": True}
    thread.join(timeout=5)
    assert not thread.is_alive()
    srv.server_close()


def test_shutdown_requires_header():
    app = App(make_client(image_transport()), CATS)
    srv = bind(app, 0, log=lambda m: None)
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        assert request(srv, "/api/shutdown", method="POST", api=False)[0].status == 403
        assert thread.is_alive()
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------
# 실행 도우미
# ---------------------------------------------------------------------------
def test_find_running_detects_ghrank(server):
    port = server.server_address[1]
    assert find_running(port, tries=1) == f"http://127.0.0.1:{port}/"


def test_find_running_none_when_closed():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert find_running(free, tries=1, timeout=0.2) is None


def test_bind_skips_busy_port():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        srv = bind(App(make_client(FakeTransport()), CATS), busy, log=lambda m: None)
        try:
            assert srv.server_address[1] != busy
            assert f"127.0.0.1:{srv.server_address[1]}" in srv.allowed_hosts
        finally:
            srv.server_close()


def test_idle_watch_shuts_down():
    clock = [0.0]
    app = App(make_client(FakeTransport()), CATS, clock=lambda: clock[0])
    app.touch()
    clock[0] = 31 * 60
    calls = []
    stop = threading.Event()
    fake_server = types.SimpleNamespace(shutdown=lambda: calls.append("down"))
    web._watch_idle(app, fake_server, 30, lambda m: None, stop, interval=0.01)  # type: ignore[arg-type]
    assert calls == ["down"]


def test_idle_watch_stops_on_event():
    app = App(make_client(FakeTransport()), CATS, clock=lambda: 0.0)
    stop = threading.Event()
    stop.set()
    fake_server = types.SimpleNamespace(shutdown=lambda: pytest.fail("should not shut down"))
    web._watch_idle(app, fake_server, 30, lambda m: None, stop, interval=0.01)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Comfy-Org/ComfyUI", "Comfy-Org/ComfyUI"),
        ("https://github.com/Comfy-Org/ComfyUI", "Comfy-Org/ComfyUI"),
        ("https://github.com/Comfy-Org/ComfyUI.git", "Comfy-Org/ComfyUI"),
        ("github.com/a/b/tree/main/docs?x=1#y", "a/b"),
        ("  a/b/  ", "a/b"),
        ("octo/.github", "octo/.github"),
    ],
)
def test_normalize_repo(text, expected):
    assert normalize_repo(text) == expected


@pytest.mark.parametrize("text", ["", "justname", "a/b c", "../../etc", "a/..", "a/.", ".x/y", "https://evil.com/a/b"])
def test_normalize_repo_rejects(text):
    with pytest.raises(BadRequest):
        normalize_repo(text)


def test_shortcut_script_quotes_paths():
    script = shortcut_script(r"C:\Users\O'Brien\pythonw.exe", "-m ghrank web", r"C:\Users\O'Brien")
    assert r"$link.TargetPath = 'C:\Users\O''Brien\pythonw.exe'" in script
    assert "$link.Arguments = '-m ghrank web'" in script
    assert "GetFolderPath('Desktop')" in script and "Write-Output $path" in script


def test_create_shortcut_non_windows(monkeypatch):
    monkeypatch.setattr(web.sys, "platform", "linux")
    logs = []
    assert web.create_shortcut(logs.append) == 1 and "Windows 전용" in logs[0]


def test_create_shortcut_windows_invocation(monkeypatch, tmp_path):
    python = tmp_path / "python.exe"
    python.write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    monkeypatch.setattr(web.sys, "platform", "win32")
    monkeypatch.setattr(web.sys, "executable", str(python))
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout="C:\\Users\\Win\\Desktop\\ghrank.lnk\n", stderr="")

    monkeypatch.setattr(web.subprocess, "run", fake_run)
    logs = []
    assert web.create_shortcut(logs.append) == 0
    assert seen["cmd"][:4] == ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand"]
    import base64

    script = base64.b64decode(seen["cmd"][4]).decode("utf-16-le")
    assert "pythonw.exe" in script and "--idle-minutes 30" in script
    assert "ghrank.lnk" in logs[0]


def test_create_shortcut_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(web.sys, "platform", "win32")
    monkeypatch.setattr(web.sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr(web.subprocess, "run",
                        lambda cmd, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr="COM error"))
    logs = []
    assert web.create_shortcut(logs.append) == 1 and "COM error" in logs[0]


def test_cli_web_dispatch(monkeypatch):
    from ghrank import cli

    called = {}
    monkeypatch.setattr(web, "serve", lambda args, cats, client, log: called.setdefault("port", args.port) and 0)
    assert cli.main(["web", "-q", "--no-browser", "--port", "9999"], client=make_client(FakeTransport()), now=NOW) == 0
    assert called["port"] == 9999


def test_cli_web_shortcut_dispatch(monkeypatch):
    from ghrank import cli

    monkeypatch.setattr(web, "create_shortcut", lambda log: 7)
    assert cli.main(["web", "--shortcut"]) == 7


def test_serve_reuses_running_instance(monkeypatch):
    opened = []
    monkeypatch.setattr(web, "find_running", lambda port: "http://127.0.0.1:8765/")
    monkeypatch.setattr(web.webbrowser, "open", opened.append)
    args = types.SimpleNamespace(port=8765, no_browser=False, idle_minutes=0)
    assert web.serve(args, CATS, make_client(FakeTransport()), lambda m: None) == 0  # type: ignore[arg-type]
    assert opened == ["http://127.0.0.1:8765/"]


def test_serve_runs_until_shutdown(monkeypatch):
    monkeypatch.setattr(web, "find_running", lambda port: None)
    logs: list[str] = []
    args = types.SimpleNamespace(port=0, no_browser=True, idle_minutes=0.0001)
    client = make_client(image_transport())
    result = {}
    monkeypatch.setattr(web, "_watch_idle", lambda app, server, minutes, log, stop, interval=30.0: server.shutdown())
    thread = threading.Thread(target=lambda: result.setdefault("code", web.serve(args, CATS, client, logs.append)), daemon=True)
    thread.start()
    thread.join(timeout=5)
    assert result.get("code") == 0
    assert any(m.startswith("ghrank 화면: http://127.0.0.1:") for m in logs)


def test_background_log_writes_file(monkeypatch, tmp_path):
    monkeypatch.setattr(web.sys, "stderr", None)
    monkeypatch.setattr(web.FileCache, "default_dir", staticmethod(lambda: tmp_path))
    log = web._background_log(lambda m: None)
    log("안녕")
    assert "안녕" in (tmp_path / "web.log").read_text(encoding="utf-8")


def test_now_is_timezone_aware():
    assert App(make_client(FakeTransport()), CATS).now().tzinfo is not None
    assert datetime.now(UTC).tzinfo is UTC
