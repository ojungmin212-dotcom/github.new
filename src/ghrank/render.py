"""출력: 터미널 텍스트 · 마크다운 · JSON.

Windows 콘솔(cp949)에서도 깨지지 않도록 이모지는 쓰지 않는다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from ghrank.guide import CodeBlock, Guide, repo_caveats
from ghrank.ranking import Ranking, Repo, recommend_score

DISCLAIMER = [
    "순위는 GitHub 스타 수(또는 지정한 정렬 기준) 그대로이며 품질·보안·적합성을 보장하지 않습니다. 스타는 조작될 수 있습니다.",
    "분야 분류는 저장소가 스스로 붙인 토픽·설명에 의존합니다 - 관련 없는 저장소가 섞이거나 빠질 수 있습니다.",
    "설치·사용법은 README 에서 규칙으로 자동 추출한 것입니다. 실행 전에 반드시 원문과 대조하세요.",
]


TEXT_DESC_MAX = 220
MD_DESC_MAX = 160


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _date(dt: datetime | None) -> str:
    return dt.date().isoformat() if dt else "-"


def _stamp(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _summary(r: Ranking) -> str:
    dropped = []
    if r.dropped_lists:
        dropped.append(f"목록형 {r.dropped_lists}개")
    if r.dropped_irrelevant:
        dropped.append(f"관련성 낮음 {r.dropped_irrelevant}개")
    tail = f", 제외: {', '.join(dropped)}" if dropped else ""
    return f"GitHub 검색 결과 {r.total_count:,}개 중 상위 {r.scanned}개 검토{tail}"


def change_label(change: dict | None) -> str:
    """이전 보고서 대비 변동: NEW · ▲3 · ▼1 · =."""
    if not change:
        return ""
    if change.get("new"):
        return "NEW"
    delta = change.get("delta") or 0
    return f"▲{delta}" if delta > 0 else (f"▼{-delta}" if delta < 0 else "=")


def _badges(r: Ranking, repo: Repo, now: datetime | None) -> str:
    parts = []
    if r.changes is not None:
        parts.append(change_label(r.changes.get(repo.full_name)))
    if r.sort == "score":
        parts.append(f"추천 {recommend_score(repo, now or r.fetched_at)['score']:g}")
    return "".join(f" [{p}]" for p in parts if p)


def _meta_line(repo: Repo) -> str:
    parts = [f"★{repo.stars:,}", repo.language or "언어 미표기", repo.license_spdx or "라이선스 없음",
             f"마지막 푸시 {_date(repo.pushed_at)}"]
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# 텍스트
# ---------------------------------------------------------------------------
def _indent(text: str, prefix: str) -> str:
    return "\n".join(prefix + line if line else prefix.rstrip() for line in text.split("\n"))


def _text_blocks(label: str, blocks: list[CodeBlock], pad: str) -> list[str]:
    if not blocks:
        return []
    out = [f"{pad}[{label}]"]
    for b in blocks:
        src = f"  (README '{b.source}' 절)" if b.source else ""
        out.append(f"{pad}  ---{(' ' + b.lang) if b.lang else ''}{src}")
        out.append(_indent(b.code, pad + "  "))
        if b.truncated:
            out.append(f"{pad}  … (길어서 생략 - 원문 참고)")
    return out


def text_guide(guide: Guide, pad: str = "     ") -> list[str]:
    out = _text_blocks("설치", guide.install, pad) + _text_blocks("사용", guide.usage, pad)
    if guide.caveats:
        out.append(f"{pad}[주의]")
        out += [f"{pad}  - {c}" for c in guide.caveats]
    if guide.notes:
        out.append(f"{pad}[참고]")
        out += [f"{pad}  - {n}" for n in guide.notes]
    return out


def text_ranking(r: Ranking, guides: dict[str, Guide] | None = None, now: datetime | None = None) -> str:
    key = f" ({r.category.key})" if r.category else ""
    lines = [f"[{r.title}]{key} - 상위 {len(r.repos)}개 · 조회 {_stamp(r.fetched_at)}", f"  {_summary(r)}"]
    lines += [f"  참고: {n}" for n in r.notes]
    if not r.repos:
        lines.append("  결과가 없습니다. 조건(--lang, --min-stars, --active-days)을 줄이거나 --loose 를 써 보세요.")
    for i, repo in enumerate(r.repos, 1):
        lines.append(f"  {i:>2}. {repo.full_name}{_badges(r, repo, now)}  {_meta_line(repo)}")
        if repo.description:
            lines.append(f"      {_clip(repo.description, TEXT_DESC_MAX)}")
        lines.append(f"      {repo.html_url}")
        guide = (guides or {}).get(repo.full_name)
        if guide is not None:
            lines += text_guide(guide, pad="      ")
        else:
            cav = repo_caveats(repo, now)
            if cav:
                lines.append("      주의: " + " / ".join(cav))
    if r.dropped_out:
        lines.append("  지난 보고서 대비 순위에서 빠짐: " + ", ".join(r.dropped_out))
    return "\n".join(lines)


def text_single_guide(guide: Guide) -> str:
    repo = guide.repo
    lines = [f"{repo.full_name}  {_meta_line(repo)}"]
    if repo.description:
        lines.append(f"  {_clip(repo.description, TEXT_DESC_MAX)}")
    lines.append(f"  {repo.html_url}")
    lines += text_guide(guide, pad="  ")
    return "\n".join(lines)


def text_footer() -> str:
    return "\n".join(["", "※ 유의사항"] + [f"  - {d}" for d in DISCLAIMER])


# ---------------------------------------------------------------------------
# 마크다운
# ---------------------------------------------------------------------------
def _md_cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())


def _md_fence(code: str) -> str:
    fence = "```"
    while fence in code:
        fence += "`"
    return fence


def md_guide(guide: Guide, heading: str = "####") -> list[str]:
    out: list[str] = []
    for label, blocks in (("설치", guide.install), ("사용", guide.usage)):
        if not blocks:
            continue
        out.append(f"**{label}**")
        out.append("")
        for b in blocks:
            if b.source:
                out.append(f"<sub>README '{_md_cell(b.source)}' 절</sub>")
                out.append("")
            fence = _md_fence(b.code)
            out += [f"{fence}{b.lang}", b.code, fence]
            if b.truncated:
                out.append("_… 길어서 생략 - 원문 참고_")
            out.append("")
    if guide.caveats:
        out += ["**주의**", ""] + [f"- {c}" for c in guide.caveats] + [""]
    if guide.notes:
        out += ["**참고**", ""] + [f"- {n}" for n in guide.notes] + [""]
    return out


def md_ranking(r: Ranking, guides: dict[str, Guide] | None = None, now: datetime | None = None) -> str:
    key = f" (`{r.category.key}`)" if r.category else ""
    lines = [f"## {r.title}{key} - 상위 {len(r.repos)}", "", f"조회 {_stamp(r.fetched_at)} · {_summary(r)}", ""]
    lines += [f"> 참고: {n}" for n in r.notes]
    if not r.repos:
        return "\n".join(lines + ["결과가 없습니다.", ""])
    compared, scored = r.changes is not None, r.sort == "score"
    head = ["#"] + (["변동"] if compared else []) + ["저장소", "★"] + (["추천점수"] if scored else [])
    head += ["언어", "라이선스", "마지막 푸시", "설명"]
    align = ["---:"] + ([":---:"] if compared else []) + ["---", "---:"] + (["---:"] if scored else []) + ["---"] * 4
    lines += ["| " + " | ".join(head) + " |", "|" + "|".join(align) + "|"]
    for i, repo in enumerate(r.repos, 1):
        cells = [str(i)]
        if compared:
            cells.append(change_label((r.changes or {}).get(repo.full_name)))
        cells += [f"[{repo.full_name}]({repo.html_url})", f"{repo.stars:,}"]
        if scored:
            cells.append(f"{recommend_score(repo, now or r.fetched_at)['score']:g}")
        cells += [repo.language or "-", repo.license_spdx or "없음", _date(repo.pushed_at),
                  _md_cell(_clip(repo.description, MD_DESC_MAX))]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    if r.dropped_out:
        lines += ["지난 보고서 대비 순위에서 빠짐: " + ", ".join(f"`{n}`" for n in r.dropped_out), ""]
    for i, repo in enumerate(r.repos, 1):
        guide = (guides or {}).get(repo.full_name)
        cav = guide.caveats if guide else repo_caveats(repo, now)
        if guide is None and not cav:
            continue
        lines += [f"### {i}. {repo.full_name}", ""]
        if guide is not None:
            lines += md_guide(guide)
        else:
            lines += ["**주의**", ""] + [f"- {c}" for c in cav] + [""]
    return "\n".join(lines)


def md_single_guide(guide: Guide) -> str:
    repo = guide.repo
    lines = [f"## [{repo.full_name}]({repo.html_url})", "", _meta_line(repo), ""]
    if repo.description:
        lines += [f"> {_md_cell(repo.description)}", ""]
    return "\n".join(lines + md_guide(guide))


def md_footer() -> str:
    return "\n".join(["---", "", "**유의사항**", ""] + [f"- {d}" for d in DISCLAIMER] + [""])


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
def ranking_dict(r: Ranking, guides: dict[str, Guide] | None = None, now: datetime | None = None) -> dict:
    repos = []
    for i, repo in enumerate(r.repos, 1):
        item = {"rank": i, **repo.to_dict()}
        if r.sort == "score":
            item["score"] = recommend_score(repo, now or r.fetched_at)
        if r.changes is not None:
            item["change"] = r.changes.get(repo.full_name)
        guide = (guides or {}).get(repo.full_name)
        item["caveats"] = guide.caveats if guide else repo_caveats(repo, now)
        if guide is not None:
            item["guide"] = guide.to_dict()
        repos.append(item)
    return {
        "title": r.title,
        "category": r.category.key if r.category else None,
        "query": r.query,
        "fetched_at": r.fetched_at.isoformat(),
        "total_count": r.total_count,
        "scanned": r.scanned,
        "dropped_lists": r.dropped_lists,
        "dropped_irrelevant": r.dropped_irrelevant,
        "sort": r.sort,
        "notes": r.notes,
        "dropped_out": r.dropped_out,
        "repos": repos,
    }


def to_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
