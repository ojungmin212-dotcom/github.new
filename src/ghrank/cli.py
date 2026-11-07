"""명령줄 진입점: ghrank categories | top | find | guide | web | mcp"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ghrank import __version__, render
from ghrank.categories import Category, CategoryError, compact, has_non_ascii, load_categories, match_categories, resolve_category
from ghrank.github import FileCache, GitHubClient, GitHubError, RateLimitError
from ghrank.guide import Guide, build_guide
from ghrank.ranking import SORT_KEYS, Filters, Ranking, Repo, apply_comparison, category_query, free_query, rank

DEFAULT_TOP = 12
DEFAULT_CACHE_HOURS = 6.0


@dataclass
class Report:
    rankings: list[Ranking] = field(default_factory=list)
    guides: dict[str, Guide] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 인자
# ---------------------------------------------------------------------------
def _positive(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("1 이상이어야 합니다")
    return n


def _top(value: str) -> int:
    n = _positive(value)
    if n > 100:
        raise argparse.ArgumentTypeError("최대 100까지 지정할 수 있습니다")
    return n


def build_parser() -> argparse.ArgumentParser:
    base = argparse.ArgumentParser(add_help=False)
    b = base.add_argument_group("공통 옵션")
    b.add_argument("--categories-file", type=Path, help="분야 정의 TOML 파일(기본: 내장 categories.toml)")
    b.add_argument("-q", "--quiet", action="store_true", help="진행 메시지를 숨김")

    net = argparse.ArgumentParser(add_help=False)
    n = net.add_argument_group("조회 옵션")
    n.add_argument("--no-cache", action="store_true", help="디스크 캐시를 쓰지 않음")
    n.add_argument("--cache-hours", type=float, default=DEFAULT_CACHE_HOURS, help="캐시 유효 시간(기본 6시간)")
    n.add_argument("--max-wait", type=float, default=90.0, help="호출 한도에 걸렸을 때 최대 대기 초(기본 90)")

    out = argparse.ArgumentParser(add_help=False)
    o = out.add_argument_group("출력 옵션")
    o.add_argument("--format", choices=("text", "md", "json"), default="text", help="출력 형식 (기본 text)")
    o.add_argument("-o", "--output", type=Path, help="결과를 파일로 저장(UTF-8)")

    ranking = argparse.ArgumentParser(add_help=False)
    r = ranking.add_argument_group("순위 옵션")
    r.add_argument("-n", "--top", type=_top, default=DEFAULT_TOP, help=f"분야별 개수(기본 {DEFAULT_TOP}, 최대 100)")
    r.add_argument("--sort", choices=SORT_KEYS, default="stars",
                   help="정렬 기준: stars(기본)·forks·updated·score(추천 순: 인기·증가세·최근성)")
    r.add_argument("--lang", help="주 언어 한정 (예: python, typescript)")
    r.add_argument("--min-stars", type=int, help="최소 스타 수")
    r.add_argument("--active-days", type=_positive, help="최근 N일 안에 푸시된 저장소만")
    r.add_argument("--include-archived", action="store_true", help="보관(archived)된 저장소도 포함")
    r.add_argument("--include-lists", action="store_true", help="awesome-* 같은 링크 모음 저장소도 포함")
    r.add_argument("--loose", action="store_true", help="분야 관련성 필터를 끔(토픽만 맞으면 포함)")
    r.add_argument("--guide", action="store_true", help="저장소마다 README 에서 설치·사용법·주의점을 추출")
    r.add_argument("--compare", type=Path, metavar="이전.json",
                   help="이전 --format json 결과와 비교해 신규 진입(NEW)·상승(▲)·하락(▼)·이탈을 표시")

    p = argparse.ArgumentParser(
        prog="ghrank",
        description="GitHub 스타 순위 기반 분야별 저장소 추천 · 검색 · 설치/사용/주의점 요약",
        epilog="예) ghrank web   |   ghrank top 이미지 영상   |   ghrank find \"pdf ocr\" --guide   |   ghrank guide comfy-org/ComfyUI",
    )
    p.add_argument("--version", action="version", version=f"ghrank {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="명령")

    sub.add_parser("categories", parents=[base, out], help="분야 목록과 별칭 보기")

    t = sub.add_parser("top", parents=[base, net, out, ranking], help="분야별 상위 저장소 (분야 생략 시 전체 분야)")
    t.add_argument("categories", nargs="*", metavar="분야", help="분야 key 또는 별칭 (예: image, 이미지, 영상)")

    f = sub.add_parser("find", parents=[base, net, out, ranking], help="찾고 싶은 분야·키워드로 저장소 찾기")
    f.add_argument("query", nargs="+", metavar="검색어")
    f.add_argument("--raw", action="store_true", help="분야로 해석하지 않고 검색어 그대로 GitHub 검색")

    gd = sub.add_parser("guide", parents=[base, net, out], help="특정 저장소의 설치·사용법·주의점")
    gd.add_argument("repos", nargs="+", metavar="owner/repo")

    w = sub.add_parser("web", parents=[base, net], help="브라우저 화면으로 쓰기 (내 PC 에서만 접속)")
    w.add_argument("--port", type=int, default=8765, help="사용할 포트(기본 8765, 사용 중이면 다음 번호)")
    w.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    w.add_argument("--idle-minutes", type=float, default=0, help="화면을 N분 동안 안 쓰면 자동 종료(기본 0 = 끄지 않음)")
    w.add_argument("--shortcut", action="store_true", help="(Windows) 바탕화면에 실행 아이콘을 만들고 끝냄")

    m = sub.add_parser("mcp", parents=[base, net], help="Claude 와 연결하는 MCP 서버(Claude Desktop·Claude Code 용)")
    mg = m.add_mutually_exclusive_group()
    mg.add_argument("--install", action="store_true", help="Claude Desktop 설정에 ghrank 를 등록하고 끝냄")
    mg.add_argument("--install-skill", action="store_true", help="Claude Code 개인 스킬 폴더에 ghrank 스킬을 넣고 끝냄")
    mg.add_argument("--print-config", action="store_true", help="연결 방법과 설정 예시를 보여 주고 끝냄")
    return p


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def _filters(args: argparse.Namespace) -> Filters:
    return Filters(
        language=args.lang,
        min_stars=args.min_stars,
        active_days=args.active_days,
        include_archived=args.include_archived,
        include_lists=args.include_lists,
        loose=args.loose,
        sort=args.sort,
    )


def _sort_label(sort: str) -> str:
    return {"stars": "스타 순", "forks": "포크 순", "updated": "최근 업데이트 순", "score": "추천 순"}[sort]


def load_previous(path: Path) -> dict[str, dict[str, int]]:
    """이전 --format json 결과 → {분야 key 또는 제목: {full_name: 순위}}."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"비교할 이전 결과를 읽을 수 없습니다: {path} ({exc})") from exc
    rankings = data.get("rankings") if isinstance(data, dict) else None
    if not isinstance(rankings, list):
        raise ValueError(f"이전 결과 형식이 아닙니다(--format json 결과가 필요): {path}")
    out: dict[str, dict[str, int]] = {}
    for r in rankings:
        if not isinstance(r, dict):
            continue
        key = r.get("category") or r.get("title")
        raw = r.get("repos")
        repos = raw if isinstance(raw, list) else []
        out[str(key)] = {str(x["full_name"]): int(x["rank"]) for x in repos if isinstance(x, dict) and "full_name" in x}
    return out


def apply_previous(report: Report, previous: dict[str, dict[str, int]]) -> None:
    for r in report.rankings:
        key = r.category.key if r.category else r.title
        apply_comparison(r, previous.get(key))
        if key not in previous:
            r.notes.append("이전 결과에 이 분야가 없어 모두 NEW 로 표시합니다")


def _fetch_guides(client: GitHubClient, repos: list[Repo], report: Report, now: datetime, log: Callable[[str], None]) -> None:
    for repo in repos:
        if repo.full_name in report.guides:
            continue
        log(f"[README] {repo.full_name}")
        try:
            readme = client.get_readme(repo.full_name)
        except RateLimitError:
            raise
        except GitHubError as exc:
            guide = build_guide(repo, None, now)
            guide.notes = [f"README 조회 실패: {exc}"]
            report.guides[repo.full_name] = guide
            continue
        report.guides[repo.full_name] = build_guide(repo, readme, now)


Job = tuple[str, str, Category | None]  # (제목, 검색어, 분야)


def _run_rankings(
    client: GitHubClient, jobs: Sequence[Job], args: argparse.Namespace, now: datetime, log: Callable[[str], None]
) -> Report:
    report = Report()
    filters = _filters(args)
    for title, query, cat in jobs:
        log(f"[조회] {title}")
        try:
            result = rank(client, query, args.top, filters, title=title, category=cat, now=now)
            report.rankings.append(result)
            if args.guide:
                _fetch_guides(client, result.repos, report, now, log)
        except RateLimitError as exc:
            report.errors.append(f"{title}: {exc}")
            report.errors.append("호출 한도 때문에 나머지 조회를 중단했습니다")
            break
        except GitHubError as exc:
            report.errors.append(f"{title}: {exc}")
    return report


def cmd_top(
    args: argparse.Namespace, categories: list[Category], client: GitHubClient, now: datetime, log: Callable[[str], None]
) -> Report:
    chosen = [resolve_category(c, categories) for c in args.categories] if args.categories else list(categories)
    unique = list(dict.fromkeys(chosen))
    filters = _filters(args)
    jobs = [(f"{c.name} {_sort_label(args.sort)}", category_query(c, filters, now.date()), c) for c in unique]
    return _run_rankings(client, jobs, args, now, log)


def cmd_find(
    args: argparse.Namespace, categories: list[Category], client: GitHubClient, now: datetime, log: Callable[[str], None]
) -> Report:
    query = " ".join(args.query).strip()
    filters = _filters(args)
    matched = [] if args.raw else match_categories(query, categories)
    exact = any(compact(query) in {compact(a) for a in (c.key, *c.aliases)} for c in matched)
    notes: list[str] = []
    if matched and (exact or has_non_ascii(query)):
        names = ", ".join(f"{c.name}({c.key})" for c in matched)
        notes.append(f"'{query}' 을(를) 분야 [{names}] 로 해석했습니다. 검색어 그대로 찾으려면 --raw 를 붙이세요.")
        jobs: list[Job] = [(f"{c.name} {_sort_label(args.sort)}", category_query(c, filters, now.date()), c) for c in matched]
    else:
        if has_non_ascii(query):
            notes.append("GitHub 저장소 설명은 대부분 영어라 한글 검색은 결과가 적을 수 있습니다 - 영어 키워드를 권장합니다.")
        if matched:
            notes.append("분야 순위로 보려면: " + " | ".join(f"ghrank top {c.key}" for c in matched))
        jobs = [(f"'{query}' 검색 결과 {_sort_label(args.sort)}", free_query(query, filters, now.date()), None)]
    report = _run_rankings(client, jobs, args, now, log)
    report.notes = notes + report.notes
    return report


def cmd_guide(args: argparse.Namespace, client: GitHubClient, now: datetime, log: Callable[[str], None]) -> list[Guide | str]:
    out: list[Guide | str] = []
    for name in args.repos:
        name = name.strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
        log(f"[조회] {name}")
        try:
            repo = Repo.from_api(client.get_repository(name))
            out.append(build_guide(repo, client.get_readme(repo.full_name), now))
        except RateLimitError as exc:
            out.append(f"{name}: {exc}")
            break
        except GitHubError as exc:
            out.append(f"{name}: {exc}")
    return out


def render_report(report: Report, fmt: str, now: datetime) -> str:
    if fmt == "json":
        return render.to_json({
            "generated_at": now.isoformat(),
            "notes": report.notes,
            "errors": report.errors,
            "rankings": [render.ranking_dict(r, report.guides, now) for r in report.rankings],
        })
    if fmt == "md":
        parts = [f"# GitHub 분야별 저장소 순위 (ghrank {__version__})", ""]
        parts += [f"> {n}" for n in report.notes] + ([""] if report.notes else [])
        parts += [render.md_ranking(r, report.guides, now) for r in report.rankings]
        parts += [f"> 오류: {e}" for e in report.errors]
        parts.append(render.md_footer())
        return "\n".join(parts)
    parts = [f"참고: {n}" for n in report.notes]
    parts += [render.text_ranking(r, report.guides, now) for r in report.rankings]
    parts += [f"오류: {e}" for e in report.errors]
    parts.append(render.text_footer())
    return "\n\n".join(parts)


def _render_guides(items: list[Guide | str], fmt: str, now: datetime) -> str:
    guides = [g for g in items if isinstance(g, Guide)]
    errors = [e for e in items if isinstance(e, str)]
    if fmt == "json":
        return render.to_json({
            "generated_at": now.isoformat(),
            "errors": errors,
            "guides": [{**g.repo.to_dict(), "guide": g.to_dict()} for g in guides],
        })
    if fmt == "md":
        body = [render.md_single_guide(g) for g in guides] + [f"> 오류: {e}" for e in errors]
        return "\n".join(body + [render.md_footer()])
    body = [render.text_single_guide(g) for g in guides] + [f"오류: {e}" for e in errors]
    return "\n\n".join(body + [render.text_footer()])


def _render_categories(categories: list[Category], fmt: str) -> str:
    if fmt == "json":
        return render.to_json([
            {"key": c.key, "name": c.name, "search_topics": list(c.search_topics), "aliases": list(c.aliases)}
            for c in categories
        ])
    if fmt == "md":
        rows = ["| key | 분야 | 별칭 | 검색 토픽 |", "|---|---|---|---|"]
        rows += [f"| `{c.key}` | {c.name} | {', '.join(c.aliases)} | {', '.join(c.search_topics)} |" for c in categories]
        return "\n".join(rows)
    lines = []
    for c in categories:
        lines.append(f"{c.key:<11} {c.name}")
        lines.append(f"{'':<11} 별칭: {', '.join(c.aliases)}")
        lines.append(f"{'':<11} 검색 토픽: {', '.join(c.search_topics)}")
    return "\n".join(lines)


def _emit(text: str, output: Path | None) -> None:
    if output is None:
        print(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n", encoding="utf-8")
    print(f"저장: {output}", file=sys.stderr)


def _harden_console() -> None:
    # Windows cp949 콘솔·리디렉션에서 인코딩 불가 문자로 죽지 않게 한다
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: Sequence[str] | None = None, client: GitHubClient | None = None, now: datetime | None = None) -> int:
    _harden_console()
    args = build_parser().parse_args(argv)
    now = now or datetime.now(UTC)

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, file=sys.stderr)

    try:
        categories = load_categories(args.categories_file)
    except CategoryError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    if args.command == "categories":
        _emit(_render_categories(categories, args.format), args.output)
        return 0

    if args.command == "web" and args.shortcut:
        from ghrank.web import create_shortcut

        return create_shortcut(log)

    if args.command == "mcp" and (args.install or args.install_skill or args.print_config):
        from ghrank import mcp_server

        if args.print_config:
            print(mcp_server.setup_text())
            return 0
        try:
            if args.install:
                path, backup = mcp_server.install_claude_desktop()
                log(f"Claude Desktop 설정에 ghrank 를 등록했습니다: {path}")
                if backup:
                    log(f"기존 설정은 {backup} 에 보관했습니다")
                log("Claude Desktop 을 완전히 종료했다가 다시 여세요.")
            else:
                log(f"Claude Code 스킬을 넣었습니다: {mcp_server.install_claude_code_skill()}")
        except (OSError, ValueError) as exc:
            print(f"오류: {exc}", file=sys.stderr)
            return 1
        return 0

    if client is None:
        cache = None if args.no_cache else FileCache(FileCache.default_dir(), args.cache_hours * 3600)
        client = GitHubClient.from_env(cache=cache, max_wait=args.max_wait, log=log)
        if not client.token:
            log("[안내] GITHUB_TOKEN 없이 실행 중 - 검색 분당 10회 한도라 전체 분야 조회 시 대기가 생길 수 있습니다")

    if args.command == "web":
        from ghrank.web import serve

        return serve(args, categories, client, log)

    if args.command == "mcp":
        from ghrank.mcp_server import run_stdio

        return run_stdio(client, categories, log)

    try:
        if args.command == "guide":
            items = cmd_guide(args, client, now, log)
            _emit(_render_guides(items, args.format, now), args.output)
            return 0 if all(isinstance(i, Guide) for i in items) else 1
        previous = load_previous(args.compare) if args.compare else None
        if args.command == "top":
            report = cmd_top(args, categories, client, now, log)
        else:
            report = cmd_find(args, categories, client, now, log)
        if previous is not None:
            apply_previous(report, previous)
    except (CategoryError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    _emit(render_report(report, args.format, now), args.output)
    return 1 if report.errors else 0
