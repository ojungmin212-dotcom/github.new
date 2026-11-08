"""브라우저 화면: ghrank web

보안 원칙
- 127.0.0.1 에만 열어 같은 PC 에서만 접속된다. Host 헤더를 검사해 DNS 리바인딩 공격을 막는다.
- /api/* 는 X-Ghrank 헤더가 있어야 응답한다. 다른 사이트가 이 헤더를 붙여 호출하려면 브라우저 사전 요청(CORS
  preflight)을 통과해야 하는데 이 서버는 CORS 를 허용하지 않으므로, 남의 사이트가 내 토큰 한도를 몰래 쓰지 못한다.
- 화면은 패키지 안의 정적 파일만 쓰고(외부 CDN 없음) CSP 로 외부 스크립트를 막는다.
  README·설명 같은 외부 텍스트는 화면에서 텍스트로만 넣는다(app.js 는 innerHTML 을 쓰지 않음).
- 접속 로그를 남기지 않는다(검색어·토큰 노출 방지).
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse

from ghrank import __version__, render
from ghrank.categories import Category
from ghrank.cli import DEFAULT_TOP, Report, cmd_find, cmd_top, render_report
from ghrank.github import FileCache, GitHubClient, GitHubError, NotFoundError, RateLimitError
from ghrank.guide import build_guide
from ghrank.ranking import SORT_KEYS, Repo

API_HEADER = "X-Ghrank"
PORT_TRIES = 10
SHORTCUT_IDLE_MINUTES = 30  # 아이콘으로 켠 화면은 창이 없으므로, 30분간 안 쓰면 스스로 꺼진다
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
}
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
# owner 는 영문·숫자로 시작, repo 는 .github 처럼 점으로 시작할 수 있지만 "." ".." 는 안 됨
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/(?!\.\.?$)[A-Za-z0-9_.-]{1,100}$")
_LANG_RE = re.compile(r"^[\w+#. -]{1,40}$")
MAX_REMEMBERED = 2000


class BadRequest(ValueError):
    """화면에서 넘어온 값이 잘못되었을 때(400)."""


# ---------------------------------------------------------------------------
# 입력 검사
# ---------------------------------------------------------------------------
def _flag(params: dict[str, str], name: str) -> bool:
    return params.get(name, "").strip().lower() in ("1", "true", "on", "yes")


def _int(params: dict[str, str], name: str, label: str, lo: int, hi: int) -> int | None:
    raw = params.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise BadRequest(f"{label}은(는) 숫자여야 합니다") from None
    if not lo <= value <= hi:
        raise BadRequest(f"{label}은(는) {lo:,}~{hi:,} 사이여야 합니다")
    return value


def normalize_repo(text: str) -> str:
    """'owner/repo', GitHub 주소(…/tree/main 포함), .git 주소를 'owner/repo' 로 바꾼다."""
    name = text.strip()
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if name.lower().startswith(prefix):
            name = name[len(prefix) :]
            break
    name = name.split("?", 1)[0].split("#", 1)[0].strip("/")
    name = "/".join(name.split("/")[:2]).removesuffix(".git")
    if not _REPO_RE.match(name):
        raise BadRequest("'owner/repo' 형식이나 GitHub 저장소 주소를 입력하세요")
    return name


# ---------------------------------------------------------------------------
# 화면이 쓰는 기능
# ---------------------------------------------------------------------------
class App:
    def __init__(
        self,
        client: GitHubClient,
        categories: list[Category],
        log: Callable[[str], None] = lambda _m: None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.categories = categories
        self.log = log
        self.now = now
        self.clock = clock
        self.lock = threading.Lock()  # GitHub 호출을 한 번에 하나씩(한도 대기·캐시 경합 방지)
        self.repos: dict[str, Repo] = {}  # 순위에서 본 저장소 → 가이드 조회 때 검색 API 한 번 절약
        self.last_seen = clock()

    def touch(self) -> None:
        self.last_seen = self.clock()

    def idle_seconds(self) -> float:
        return self.clock() - self.last_seen

    # ---- 정보 -----------------------------------------------------------------
    def status(self) -> dict:
        info: dict = {"app": "ghrank", "version": __version__, "token": bool(self.client.token), "limits": None, "error": None}
        try:
            info["limits"] = self.client.rate_limit()
        except GitHubError as exc:
            info["error"] = str(exc)
        return info

    def categories_payload(self) -> list[dict]:
        return [{"key": c.key, "name": c.name, "aliases": list(c.aliases)} for c in self.categories]

    # ---- 순위·찾기 ---------------------------------------------------------------
    def _ranking_args(self, params: dict[str, str]) -> argparse.Namespace:
        sort = params.get("sort") or "stars"
        if sort not in SORT_KEYS:
            raise BadRequest("정렬 기준이 올바르지 않습니다")
        lang = (params.get("lang") or "").strip() or None
        if lang is not None and not _LANG_RE.match(lang):
            raise BadRequest("언어 이름이 올바르지 않습니다")
        return argparse.Namespace(
            top=_int(params, "n", "개수", 1, 100) or DEFAULT_TOP,
            sort=sort,
            lang=lang,
            min_stars=_int(params, "min_stars", "최소 스타", 0, 10_000_000),
            active_days=_int(params, "active_days", "최근 기간(일)", 1, 36_500),
            include_archived=_flag(params, "include_archived"),
            include_lists=_flag(params, "include_lists"),
            loose=_flag(params, "loose"),
            guide=_flag(params, "guide"),
        )

    def _run(self, params: dict[str, str]) -> tuple[Report, datetime]:
        mode = params.get("mode") or "top"
        args = self._ranking_args(params)
        now = self.now()
        if mode == "top":
            category = (params.get("category") or "").strip()
            if not category:
                raise BadRequest("분야를 고르세요")
            args.categories = [category]
            with self.lock:
                report = cmd_top(args, self.categories, self.client, now, self.log)
        elif mode == "find":
            query = " ".join((params.get("q") or "").split())
            if not query:
                raise BadRequest("검색어를 입력하세요")
            if len(query) > 200:
                raise BadRequest("검색어는 200자 이하로 입력하세요")
            args.query, args.raw = [query], _flag(params, "raw")
            with self.lock:
                report = cmd_find(args, self.categories, self.client, now, self.log)
        else:
            raise BadRequest("조회 방식이 올바르지 않습니다")
        report.notes = [n.replace("--raw 를 붙이세요", "'검색어 그대로' 를 켜세요") for n in report.notes]
        for ranking in report.rankings:
            ranking.notes = [n.replace("--loose 를 붙이세요", "조건의 '관련성 필터 끄기'를 켜세요") for n in ranking.notes]
        for ranking in report.rankings:
            for repo in ranking.repos:
                self._remember(repo)
        return report, now

    def search(self, params: dict[str, str]) -> dict:
        report, now = self._run(params)
        return {
            "generated_at": now.isoformat(),
            "notes": report.notes,
            "errors": report.errors,
            "rankings": [render.ranking_dict(r, report.guides, now) for r in report.rankings],
        }

    def report_markdown(self, params: dict[str, str]) -> str:
        report, now = self._run({**params, "guide": "1"})
        return render_report(report, "md", now)

    # ---- 저장소 하나 ---------------------------------------------------------------
    def _remember(self, repo: Repo) -> None:
        if len(self.repos) >= MAX_REMEMBERED:
            self.repos.clear()
        self.repos[repo.full_name.lower()] = repo

    def guide(self, params: dict[str, str]) -> dict:
        name = normalize_repo(params.get("repo") or "")
        now = self.now()
        with self.lock:
            repo = self.repos.get(name.lower())
            if repo is None:
                repo = Repo.from_api(self.client.get_repository(name))
                self._remember(repo)
            try:
                guide = build_guide(repo, self.client.get_readme(repo.full_name), now)
            except RateLimitError:
                raise
            except GitHubError as exc:
                guide = build_guide(repo, None, now)
                guide.notes = [f"README 조회 실패: {exc}"]
        return {**repo.to_dict(), "caveats": guide.caveats, "guide": guide.to_dict()}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allowed_hosts: frozenset[str] = frozenset()
    log: Callable[[str], None] = staticmethod(lambda _m: None)

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001 - 표준 시그니처
        exc = sys.exc_info()[1]
        if isinstance(exc, ConnectionError):
            return  # 브라우저가 요청을 취소한 경우 — 정상
        self.log(f"[화면] 처리 중 오류: {exc!r}")


def _static(name: str) -> bytes:
    return resources.files("ghrank").joinpath("web", name).read_bytes()


def make_handler(app: App, on_shutdown: Callable[[], None]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"ghrank/{__version__}"
        sys_version = ""

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - 표준 시그니처
            pass  # 접속 로그를 남기지 않는다

        # ---- 응답 ----
        def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload: object) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _error(self, status: int, message: str) -> None:
            self._json(status, {"error": message})

        def _guard(self, api: bool) -> bool:
            if (self.headers.get("Host") or "").lower() not in cast(_Server, self.server).allowed_hosts:
                self._error(403, "허용되지 않은 접속 주소입니다")
                return False
            if api and self.headers.get(API_HEADER) != "1":
                self._error(403, "ghrank 화면에서만 호출할 수 있습니다")
                return False
            return True

        # ---- 요청 ----
        def do_GET(self) -> None:  # noqa: N802 - 표준 이름
            url = urlparse(self.path)
            is_api = url.path.startswith("/api/")
            if not self._guard(api=is_api):
                return
            if url.path in STATIC:
                name, ctype = STATIC[url.path]
                self._send(200, _static(name), ctype)
                return
            if url.path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
                return
            if not is_api:
                self._error(404, "없는 주소입니다")
                return
            app.touch()
            params = {k: v[-1] for k, v in parse_qs(url.query).items()}
            try:
                if url.path == "/api/ping":
                    self._json(200, {"app": "ghrank", "version": __version__})
                elif url.path == "/api/status":
                    self._json(200, app.status())
                elif url.path == "/api/categories":
                    self._json(200, app.categories_payload())
                elif url.path == "/api/search":
                    self._json(200, app.search(params))
                elif url.path == "/api/guide":
                    self._json(200, app.guide(params))
                elif url.path == "/api/report":
                    stamp = app.now().strftime("%Y%m%d-%H%M")
                    self._send(200, app.report_markdown(params).encode("utf-8"), "text/markdown; charset=utf-8",
                               {"Content-Disposition": f'attachment; filename="ghrank-{stamp}.md"'})
                else:
                    self._error(404, "없는 기능입니다")
            except ValueError as exc:  # BadRequest, CategoryError, 빈 검색어 등
                self._error(400, str(exc))
            except NotFoundError as exc:
                self._error(404, str(exc))
            except RateLimitError as exc:
                self._error(429, str(exc))
            except GitHubError as exc:
                self._error(502, str(exc))
            except Exception as exc:  # noqa: BLE001 - 화면에는 짧게, 기록에는 자세히
                app.log(f"[화면] 예기치 않은 오류: {exc!r}")
                self._error(500, "예기치 않은 오류가 났습니다. 다시 시도하거나 ghrank 를 다시 실행하세요")

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        def do_POST(self) -> None:  # noqa: N802
            if not self._guard(api=True):
                return
            if urlparse(self.path).path != "/api/shutdown":
                self._error(404, "없는 기능입니다")
                return
            self._json(200, {"ok": True})
            on_shutdown()

    return Handler


def bind(app: App, port: int, log: Callable[[str], None]) -> _Server:
    """port 부터 차례로 빈 포트를 찾아 127.0.0.1 에 연다(port=0 이면 운영체제가 고름)."""
    holder: dict[str, _Server] = {}

    def shutdown() -> None:
        threading.Thread(target=holder["server"].shutdown, daemon=True).start()

    handler = make_handler(app, shutdown)
    last_error: OSError | None = None
    for candidate in ([0] if port == 0 else range(port, port + PORT_TRIES)):
        try:
            server = _Server(("127.0.0.1", candidate), handler)
        except OSError as exc:
            last_error = exc
            continue
        actual = server.server_address[1]
        server.allowed_hosts = frozenset({f"127.0.0.1:{actual}", f"localhost:{actual}"})
        server.log = log
        holder["server"] = server
        return server
    raise OSError(f"{port}~{port + PORT_TRIES - 1} 포트를 모두 쓸 수 없습니다: {last_error}")


def find_running(port: int, tries: int = PORT_TRIES, timeout: float = 0.5) -> str | None:
    """이미 켜져 있는 ghrank 화면이 있으면 그 주소. 프록시를 거치지 않고 127.0.0.1 로만 확인한다."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for candidate in range(port, port + tries):
        url = f"http://127.0.0.1:{candidate}/"
        req = urllib.request.Request(url + "api/ping", headers={API_HEADER: "1"})
        try:
            with opener.open(req, timeout=timeout) as resp:
                if json.loads(resp.read().decode("utf-8")).get("app") == "ghrank":
                    return url
        except (OSError, ValueError):
            continue
    return None


def _watch_idle(app: App, server: _Server, minutes: float, log: Callable[[str], None], stop: threading.Event,
                interval: float = 30.0) -> None:
    while not stop.wait(interval):
        if app.idle_seconds() > minutes * 60:
            log(f"[화면] {minutes:g}분 동안 사용하지 않아 종료합니다")
            server.shutdown()
            return


def _background_log(log: Callable[[str], None]) -> Callable[[str], None]:
    """pythonw(창 없음)로 실행되면 화면 기록을 파일로 남긴다."""
    if sys.stderr is not None:
        return log
    path = FileCache.default_dir() / "web.log"

    def to_file(msg: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
        except OSError:
            pass

    return to_file


def serve(args: argparse.Namespace, categories: list[Category], client: GitHubClient, log: Callable[[str], None]) -> int:
    log = _background_log(log)
    client.log = log
    running = find_running(args.port)
    if running:
        log(f"이미 켜져 있는 화면을 엽니다: {running}")
        if not args.no_browser:
            webbrowser.open(running)
        return 0
    app = App(client, categories, log=log)
    try:
        server = bind(app, args.port, log)
    except OSError as exc:
        log(f"화면을 열 수 없습니다: {exc}")
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    log(f"ghrank 화면: {url}")
    log("끝내려면 화면 오른쪽 위 [종료] 를 누르거나 이 창에서 Ctrl+C")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    stop = threading.Event()
    if args.idle_minutes and args.idle_minutes > 0:
        threading.Thread(target=_watch_idle, args=(app, server, args.idle_minutes, log, stop), daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        log("종료합니다")
    finally:
        stop.set()
        server.server_close()
    return 0


# ---------------------------------------------------------------------------
# Windows 바탕화면 아이콘
# ---------------------------------------------------------------------------
def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def shortcut_script(target: str, arguments: str, workdir: str, name: str = "ghrank") -> str:
    """바탕화면(.lnk) 아이콘을 만드는 PowerShell 스크립트. 바탕화면이 OneDrive 로 옮겨져 있어도 찾는다."""
    return "; ".join([
        "$ErrorActionPreference = 'Stop'",
        "$desktop = [Environment]::GetFolderPath('Desktop')",
        f"$path = Join-Path $desktop {_ps_quote(name + '.lnk')}",
        "$link = (New-Object -ComObject WScript.Shell).CreateShortcut($path)",
        f"$link.TargetPath = {_ps_quote(target)}",
        f"$link.Arguments = {_ps_quote(arguments)}",
        f"$link.WorkingDirectory = {_ps_quote(workdir)}",
        "$link.Description = 'ghrank - GitHub repository ranking'",
        "$link.Save()",
        "Write-Output $path",
    ])


def create_shortcut(log: Callable[[str], None]) -> int:
    if sys.platform != "win32":
        log("바탕화면 아이콘 만들기는 Windows 전용입니다. 이 컴퓨터에서는 'ghrank web' 으로 실행하세요.")
        return 1
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    target = pythonw if pythonw.exists() else python  # pythonw 는 검은 창 없이 실행된다
    script = shortcut_script(str(target), f"-m ghrank web --idle-minutes {SHORTCUT_IDLE_MINUTES}", str(Path.home()))
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, errors="replace", timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"아이콘을 만들지 못했습니다: {exc}")
        return 1
    if result.returncode != 0:
        log(f"아이콘을 만들지 못했습니다: {result.stderr.strip() or result.stdout.strip()}")
        return 1
    log(f"바탕화면에 아이콘을 만들었습니다: {result.stdout.strip()}")
    if target == python:
        log("참고: pythonw.exe 를 찾지 못해 python.exe 로 연결했습니다(실행 중 검은 창이 함께 뜹니다).")
    log(f"아이콘을 더블클릭하면 브라우저에 화면이 열립니다. 화면을 {SHORTCUT_IDLE_MINUTES}분 동안 안 쓰면 저절로 꺼집니다.")
    return 0
