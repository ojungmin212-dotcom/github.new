"""ghrank 정확도 측정(F1).

정답 데이터(사람/에이전트가 README·메타데이터만 보고 표시, ghrank 코드를 보지 않음)와 ghrank 의 판단을 비교한다.

  python evals/run_eval.py            # 분야 분류(오프라인) + 설치법(고정 커밋 README 를 내려받음)
  python evals/run_eval.py --offline  # 분야 분류만
  python evals/run_eval.py -o evals/RESULTS.md

분야 분류: evals/category_snapshot.json(검색 후보 15×24, 2026-11-07 수집) + category_gold.json
설치법   : evals/install_targets.json(README 커밋 고정) + install_gold.json
홀드아웃 : evals/install_targets_holdout.json + install_gold_holdout.json — 추출 규칙을 고칠 때 보지 않은 저장소.
           개발용 세트 점수는 규칙을 맞춰 가며 본 데이터라 낙관적일 수 있으므로, 실제 성능은 홀드아웃 점수로 판단한다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ghrank.categories import load_categories
from ghrank.guide import build_guide
from ghrank.ranking import Repo, is_list_repo, is_relevant

HERE = Path(__file__).resolve().parent
TOP = 12


def load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 분야 분류
# ---------------------------------------------------------------------------
def _repo(c: dict) -> Repo:
    return Repo.from_api({
        "full_name": c["full_name"], "html_url": f"https://github.com/{c['full_name']}", "description": c.get("description"),
        "stargazers_count": c.get("stars"), "language": c.get("language"), "topics": c.get("topics"),
        "license": {"spdx_id": c.get("license")} if c.get("license") else None, "created_at": c.get("created_at"),
        "pushed_at": c.get("pushed_at"), "archived": c.get("archived"), "fork": c.get("fork"),
    })


@dataclass
class CategoryResult:
    key: str
    shown: int
    good_shown: int
    good_shown_sure: int      # 경계(borderline) 표시가 없는 항목만
    sure_shown: int
    baseline_good: int        # 필터 없이 스타 상위 12개였다면
    good_total: int
    good_kept: int            # 후보 중 '좋은' 저장소가 필터를 통과한 수(과잉 제거 확인)
    lists_total: int
    lists_dropped: int
    misses: list[str]         # 보여 줬지만 정답상 관련 없음
    wrong_drops: list[str]    # 정답상 좋은데 걸러짐


def good(label: dict) -> bool:
    """사용자에게 보여 줄 만한 저장소 = 분야에 맞고, 링크 모음이 아님."""
    return bool(label["relevant"]) and not label["is_list"]


def eval_categories() -> list[CategoryResult]:
    snap, gold = load("category_snapshot.json"), load("category_gold.json")["labels"]
    cats = {c.key: c for c in load_categories()}
    out = []
    for key, entry in snap["categories"].items():
        cat, labels = cats[key], gold[key]
        kept: list[str] = []
        lists_dropped = 0
        wrong_drops = []
        for c in entry["candidates"]:
            repo, lab = _repo(c), labels[c["full_name"]]
            if is_list_repo(repo):
                lists_dropped += lab["is_list"]
                if good(lab):
                    wrong_drops.append(repo.full_name)
                continue
            if not is_relevant(repo, cat):
                if good(lab):
                    wrong_drops.append(repo.full_name)
                continue
            kept.append(repo.full_name)
        shown = kept[:TOP]
        baseline = [c["full_name"] for c in entry["candidates"][:TOP]]
        out.append(CategoryResult(
            key=key, shown=len(shown),
            good_shown=sum(good(labels[n]) for n in shown),
            good_shown_sure=sum(good(labels[n]) for n in shown if not labels[n]["borderline"]),
            sure_shown=sum(not labels[n]["borderline"] for n in shown),
            baseline_good=sum(good(labels[n]) for n in baseline),
            good_total=sum(good(v) for v in labels.values()),
            good_kept=sum(good(labels[n]) for n in kept),
            lists_total=sum(v["is_list"] for v in labels.values()),
            lists_dropped=lists_dropped,
            misses=[n for n in shown if not good(labels[n])],
            wrong_drops=wrong_drops,
        ))
    return out


def category_summary(results: list[CategoryResult]) -> dict[str, float]:
    shown = sum(r.shown for r in results)
    return {
        "precision_at_12": sum(r.good_shown for r in results) / shown,
        "precision_at_12_sure": sum(r.good_shown_sure for r in results) / max(1, sum(r.sure_shown for r in results)),
        "baseline_precision_at_12": sum(r.baseline_good for r in results) / (TOP * len(results)),
        "good_recall": sum(r.good_kept for r in results) / max(1, sum(r.good_total for r in results)),
        "list_recall": sum(r.lists_dropped for r in results) / max(1, sum(r.lists_total for r in results)),
    }


# ---------------------------------------------------------------------------
# 설치법
# ---------------------------------------------------------------------------
_WS = re.compile(r"\s+")


def norm(cmd: str) -> str:
    return _WS.sub(" ", cmd.strip().removeprefix("$ ").strip())


def predicted_kind(guide) -> str:  # noqa: ANN001 - Guide
    if guide.install:
        return "commands"
    notes = " ".join(guide.notes)
    if "내려받는 방식" in notes:
        return "download"
    if "링크·설명만" in notes:
        return "docs_link"
    return "none"


@dataclass
class InstallResult:
    repo: str
    gold_kind: str
    pred_kind: str
    gold_cmds: int
    hit_cmds: int
    missed: list[str]


def fetch_readme(url: str) -> str:
    from ghrank.github import FileCache, GitHubClient

    client = GitHubClient(cache=FileCache(FileCache.default_dir() / "eval", 90 * 86400), log=lambda m: None)
    return client.get(url, accept="text/plain", api=False).decode("utf-8", "replace")


def eval_install(fetch=fetch_readme, suffix: str = "") -> list[InstallResult]:  # noqa: ANN001
    targets = {t["repo"]: t for t in load(f"install_targets{suffix}.json")["targets"]}
    now = datetime(2026, 11, 7, tzinfo=UTC)
    out = []
    for item in load(f"install_gold{suffix}.json")["items"]:
        t = targets[item["repo"]]
        readme = fetch(t["raw_url"])
        repo = Repo.from_api({"full_name": item["repo"], "html_url": f"https://github.com/{item['repo']}"})
        guide = build_guide(repo, readme, now)
        text = norm("\n".join(b.code for b in guide.install).replace("\n", " \n "))
        lines = {norm(line) for b in guide.install for line in b.code.splitlines()}
        gold = [norm(c) for c in item["install_commands"]]
        hits = [c for c in gold if c in lines or c in text]
        out.append(InstallResult(item["repo"], item["kind"], predicted_kind(guide), len(gold), len(hits),
                                 [c for c in gold if c not in hits]))
    return out


def install_summary(results: list[InstallResult]) -> dict[str, float]:
    cmd_repos = [r for r in results if r.gold_kind == "commands"]
    return {
        "kind_accuracy": sum(r.gold_kind == r.pred_kind for r in results) / len(results),
        "command_repos_any_hit": sum(r.hit_cmds > 0 for r in cmd_repos) / max(1, len(cmd_repos)),
        "command_recall": sum(r.hit_cmds for r in cmd_repos) / max(1, sum(r.gold_cmds for r in cmd_repos)),
        "false_commands": sum(r.gold_kind != "commands" and r.pred_kind == "commands" for r in results)
        / max(1, sum(r.gold_kind != "commands" for r in results)),
    }


# ---------------------------------------------------------------------------
# 보고
# ---------------------------------------------------------------------------
def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def report(cat: list[CategoryResult], inst: list[InstallResult] | None,
           holdout: list[InstallResult] | None = None) -> str:
    cs = category_summary(cat)
    lines = [
        "# ghrank 정확도 측정 결과", "",
        f"측정 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · 정답 데이터는 README·메타데이터만 보고 표시(ghrank 코드 미참조)", "",
        "## 분야 분류 (15개 분야 × 검색 후보 24개, 오프라인)", "",
        "| 지표 | 값 | 뜻 |", "|---|---:|---|",
        f"| 상위 12개 정확도 | **{pct(cs['precision_at_12'])}** | 보여 준 저장소 중 분야에 맞는 소프트웨어 비율 |",
        f"| 〃 (경계 사례 제외) | {pct(cs['precision_at_12_sure'])} | 정답이 확실한 항목만 |",
        f"| 필터 없을 때(스타 순 그대로) | {pct(cs['baseline_precision_at_12'])} | 비교 기준 |",
        f"| 좋은 저장소 보존율 | {pct(cs['good_recall'])} | 분야에 맞는 저장소가 필터에 살아남은 비율 |",
        f"| 링크 모음 제거율 | {pct(cs['list_recall'])} | awesome·목록형을 걸러 낸 비율 |",
        "", "| 분야 | 상위12 정확 | 기준 | 잘못 보여 준 것 | 잘못 거른 것 |", "|---|---:|---:|---|---|",
    ]
    for r in cat:
        lines.append(f"| {r.key} | {r.good_shown}/{r.shown} | {r.baseline_good}/{TOP} | {', '.join(r.misses) or '-'} | "
                     f"{', '.join(r.wrong_drops) or '-'} |")
    for title, rows in (("설치법 추출 · 개발용", inst), ("설치법 추출 · 홀드아웃(규칙 수정 때 안 본 저장소)", holdout)):
        if rows is None:
            continue
        lines += _install_section(title, rows)
    return "\n".join(lines) + "\n"


def _install_section(title: str, inst: list[InstallResult]) -> list[str]:
    lines: list[str] = []
    if inst:
        s = install_summary(inst)
        lines += [
            "", f"## {title} ({len(inst)}개 저장소, README 커밋 고정)", "",
            "| 지표 | 값 | 뜻 |", "|---|---:|---|",
            f"| 설치 방식 판정 정확도 | **{pct(s['kind_accuracy'])}** | 명령형·다운로드형·문서 링크형·없음 구분 |",
            f"| 정답 명령을 하나 이상 찾음 | **{pct(s['command_repos_any_hit'])}** | 명령형 저장소 기준 |",
            f"| 정답 명령 재현율 | {pct(s['command_recall'])} | 정답 명령 중 찾아낸 비율 |",
            f"| 명령 없는데 명령이라 함 | {pct(s['false_commands'])} | 낮을수록 좋음 |",
            "", "| 저장소 | 정답 방식 | 판정 | 찾은 명령 | 놓친 명령 |", "|---|---|---|---:|---|",
        ]
        for r in inst:
            mark = "" if r.gold_kind == r.pred_kind else " ✗"
            missed = "<br>".join(f"`{m}`" for m in r.missed) or "-"
            lines.append(f"| {r.repo} | {r.gold_kind} | {r.pred_kind}{mark} | {r.hit_cmds}/{r.gold_cmds} | {missed} |")
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ghrank 정확도 측정")
    p.add_argument("--offline", action="store_true", help="분야 분류만(네트워크 없음)")
    p.add_argument("-o", "--output", type=Path)
    args = p.parse_args(argv)
    cat = eval_categories()
    inst = None if args.offline or not (HERE / "install_gold.json").exists() else eval_install()
    hold = None if args.offline or not (HERE / "install_gold_holdout.json").exists() else eval_install(suffix="_holdout")
    text = report(cat, inst, hold)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"저장: {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
