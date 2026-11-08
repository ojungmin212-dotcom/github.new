"""README 에서 설치·사용법 추출 + 메타데이터·README 기반 주의점 판정.

추출은 규칙 기반(제목 키워드 → 그 절의 코드 블록)이라 README 구성에 따라 틀릴 수 있다.
결과에는 항상 '어느 절에서 가져왔는지'를 함께 남겨 사용자가 원문과 대조할 수 있게 한다.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ghrank.ranking import Repo

MAX_INSTALL_BLOCKS = 5
MAX_USAGE_BLOCKS = 3
MAX_BLOCK_LINES = 12
STALE_DAYS = 365
NEW_REPO_DAYS = 90
# 생성 1년 안에 연 환산 스타 5만 개 이상이면 '급성장' 주의(추천 순이 이런 저장소를 위로 올리므로 함께 경고)
FAST_GROWTH_DAYS = 365
FAST_GROWTH_STARS_PER_YEAR = 50_000
LARGE_REPO_KB = 1024 * 1024  # 1GB (GitHub API size 단위는 KB)

# 목록 항목 안의 코드 펜스는 4칸 이상 들여쓰는 경우가 많아 들여쓰기를 제한하지 않는다
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*([^`\s]*)[^`]*$")
_ATX = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_HTML_H = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.I)
_SETEXT = re.compile(r"^\s{0,3}(=+|-+)\s*$")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"<[^>]+>")
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")

INSTALL_HEAD = re.compile(
    r"install|set ?up\b|getting started|get started|quick ?start|build from source|\bdeploy|"
    r"\bdownloads?\b|\bget (?:the )?app\b|"  # 'Download' 절에 OS 별 설치 명령을 두는 README 가 많다(정답 데이터로 확인)
    r"\bbuild(?:ing)?\b(?!\s+status)|\bcompil(?:e|ing)\b|"  # 'Building X' 절에 빌드 명령만 있는 경우
    r"설치|시작하기|다운로드|安装|快速开始|快速上手|部署|下载|インストール|導入|環境構築",
    re.I,
)
USAGE_HEAD = re.compile(
    r"\busage\b|how to use|\bexamples?\b|\brun(ning)?\b|tutorial|\binference\b|basic use|\bcli\b|"
    r"사용법|사용 방법|사용하기|예제|실행|用法|使用方法|使用说明|运行|推理|使い方",
    re.I,
)
SKIP_HEAD = re.compile(
    r"contribut|\btests?\b|testing|\bdevelop(ment|ers?)\b|licen[cs]e|\bfaq\b|changelog|citation|\bcite\b|"
    r"acknowledg|star history|sponsor|roadmap|\bnews\b|release notes|기여|라이선스|贡献|许可|致谢|引用",
    re.I,
)
SHELL_LANGS = {
    "bash", "sh", "shell", "console", "zsh", "fish", "powershell", "ps", "ps1", "pwsh", "cmd", "bat",
    "batch", "terminal", "shell-session", "shellsession", "sh-session", "commandline",
}
DOWNLOAD_HEAD = re.compile(r"\bdownloads?\b|\breleases?\b|\bget (?:the )?app\b|다운로드|下载|ダウンロード", re.I)
DOCS_HEAD = re.compile(r"\bdocumentation\b|\bdocs\b|문서|文档|ドキュメント", re.I)
_DOWNLOAD_WORDS = re.compile(
    r"\bdownload|\breleases?\b|installer|\.(?:exe|dmg|msi|appimage|apk|zip)\b|app store|google play|microsoft store|"
    r"f-droid|다운로드|下载",
    re.I,
)
# 이런 절의 명령은 핵심 설치법이 아니므로 마지막에 고른다(ChatTTS 의 선택 설치가 기본 설치를 밀어내던 문제)
_SIDE_HEAD = re.compile(r"optional|unrecommended|not recommended|advanced|experimental|troubleshoot|\bfaq\b|선택|고급|可选|高级", re.I)
_HAS_LINK = re.compile(r"\]\([^)]+\)|https?://|<a\s", re.I)
_INLINE_CODE = re.compile(r"``([^`\n]+?)``|`([^`\n]+?)`")
_INSTALL_CMD = re.compile(
    r"^\s*(?:\$\s*|>\s*|PS>\s*)?(?:sudo\s+)?(?:pip3?|pipx|uv|uvx|poetry|conda|mamba|micromamba|npm|npx|pnpm|yarn|bun|"
    r"brew|apt(?:-get)?|dnf|yum|pacman|winget|choco|scoop|cargo|go|docker|docker-compose|podman|git|curl|wget|"
    r"make|cmake|gem|composer|dotnet|helm|kubectl|nix|snap|flatpak|python3?|py)\b",
    re.M | re.I,
)
# 섹션을 못 찾았을 때 README 전체에서 '설치 명령'으로 볼 만한 줄
_FALLBACK_CMD = re.compile(
    r"\b(?:pip3?|pipx|uv pip|uv tool|uv add|conda|mamba)\s+(?:install|create)\b|\buv\s+tool\s+install\b|"
    r"\b(?:npm|pnpm|bun)\s+(?:install|i|add)\b|\byarn\s+(?:add|global|install)\b|\bnpx\s+\S+|"
    r"\b(?:brew|cargo|go|gem|winget|choco|scoop|snap|flatpak|apt|apt-get|dnf|pacman)\s+install\b|"
    r"\bdocker(?:-compose|\s+compose)?\s+(?:run|pull|up)\b|\bgit\s+clone\b|\b(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?\w*sh\b",
    re.I,
)
# '확실한' 설치 명령: 패키지 관리자 설치·원격 설치 스크립트·컨테이너 실행. git clone 은 빌드 명령이 함께 있을 때만 인정
# (three.js 처럼 저장소 용량 안내용 git clone 을 설치법으로 오인하던 문제 - 정답 데이터로 확인)
_STRONG_CMD = re.compile(
    r"\b(?:pip3?|pipx|uv pip|uv tool|uv add|conda|mamba)\s+(?:install|create)\b|"
    r"\b(?:npm|pnpm|bun)\s+(?:install|i|add)\s+-?\S|\byarn\s+(?:add|global)\b|\bnpx\s+\S+|"
    r"\b(?:brew|cargo|go|gem|winget|choco|scoop|snap|flatpak|apt|apt-get|dnf|yum|pacman|port|pkg)\s+install\b|"
    r"\bnix-env\s+-i|\bpkg_add\b|"
    r"\bdocker(?:-compose|\s+compose)?\s+(?:run|pull|up)\b",
    re.I,
)
_GIT_CLONE = re.compile(r"\bgit\s+clone\b", re.I)
_BUILD_CMD = re.compile(
    r"\b(?:make|cmake|ninja|meson|cargo\s+build|go\s+build|npm\s+(?:ci|install|run\s+build)|pnpm\s+install|"
    r"yarn\s+install|pip3?\s+install|python3?\s+setup\.py|\./configure|\./install\w*|uv\s+sync)\b",
    re.I,
)

_PIPE_SH = re.compile(
    r"\b(?:curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba|z|fi|da)?sh\b|\|\s*iex\b",
    re.I,
)
_SUDO = re.compile(r"(?:^|[\s;&|$])sudo\s", re.M)
# "GPU" 단어만으로는 경고하지 않는다("No GPU required" 같은 문구 오탐 방지) - 요구사항성 표현만 본다
_GPU = re.compile(
    r"\b(?:cuda|nvidia|vram|rocm)\b|(?<!n't )(?<!not )\b(?:requires?|needs?)\s+(?:an?\s+)?(?:\w+\s+)?gpu\b|"
    r"(?<!no )(?<!non-)\bgpu\s+(?:is\s+)?required\b|显存|显卡",
    re.I,
)
_VRAM = re.compile(
    r"(\d{1,3}(?:\.\d+)?)\s?gb\s*(?:of\s+)?(?:vram|gpu\s+memory|gpu\s+ram|显存)|(?:vram|显存)\D{0,20}?(\d{1,3})\s?gb",
    re.I,
)
_API_KEY = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_API_KEY\b|\bapi[ _-]?keys?\b|API\s?키", re.I)
_NONCOMMERCIAL = re.compile(
    r"non[- ]?commercial|research (?:purposes? |use )?only|not (?:be )?(?:used )?for commercial|"
    r"academic (?:use|purposes?) only|비상업|仅供(?:学术|研究)|禁止商用|非商用|商用不可",
    re.I,
)
_DEPRECATED = re.compile(
    r"\bdeprecated\b|no longer (?:actively )?maintained|\bunmaintained\b|not (?:being )?maintained|"
    r"this (?:project|repo(?:sitory)?) (?:has )?moved|superseded by|已废弃|不再维护|유지보수 중단",
    re.I,
)

_EDUCATIONAL = re.compile(
    r"\b(?:lessons?|courses?|tutorials?|curriculum|textbook|book|step[- ]by[- ]step|for[- ]beginners|from[- ]scratch|"
    r"interview|roadmap)\b|教程|课程|教材|面试|강좌|강의|튜토리얼",
    re.I,
)


@dataclass(frozen=True)
class CodeBlock:
    lang: str
    code: str
    truncated: bool = False
    source: str = ""  # 가져온 README 절 제목


@dataclass
class Section:
    level: int
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class Guide:
    repo: Repo
    readme_found: bool
    install: list[CodeBlock] = field(default_factory=list)
    usage: list[CodeBlock] = field(default_factory=list)
    install_from: str = ""  # 'section' | 'fallback' | ''
    caveats: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def blocks(bs: list[CodeBlock]) -> list[dict]:
            return [{"lang": b.lang, "code": b.code, "truncated": b.truncated, "source": b.source} for b in bs]

        return {
            "readme_found": self.readme_found,
            "install": blocks(self.install),
            "install_from": self.install_from,
            "usage": blocks(self.usage),
            "caveats": self.caveats,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# README 파싱
# ---------------------------------------------------------------------------
def _clean_title(raw: str) -> str:
    text = _MD_LINK.sub(r"\1", raw)
    text = _TAG.sub("", text)
    text = re.sub(r"[*_`]+", "", text)
    return " ".join(text.split()).strip()


def split_sections(markdown: str) -> list[Section]:
    """README 를 제목 기준 절 목록으로 나눈다. 코드 블록 안의 '#' 은 제목으로 보지 않는다."""
    text = _HTML_COMMENT.sub("", markdown.replace("\r\n", "\n"))
    lines = text.split("\n")
    sections = [Section(level=0, title="")]
    fence: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _FENCE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not m.group(2):
                fence = None
            sections[-1].lines.append(line)
            i += 1
            continue
        if fence is not None:
            sections[-1].lines.append(line)
            i += 1
            continue
        atx = _ATX.match(line)
        html = _HTML_H.search(line) if atx is None else None
        if atx:
            sections.append(Section(level=len(atx.group(1)), title=_clean_title(atx.group(2))))
        elif html:
            sections.append(Section(level=int(html.group(1)), title=_clean_title(html.group(2))))
        elif (
            i + 1 < len(lines)
            and line.strip()
            and _SETEXT.match(lines[i + 1])
            and not line.lstrip().startswith(("-", "*", "+", ">", "|", "<", "!"))
            and "|" not in line
        ):
            level = 1 if lines[i + 1].strip().startswith("=") else 2
            sections.append(Section(level=level, title=_clean_title(line)))
            i += 2
            continue
        else:
            sections[-1].lines.append(line)
        i += 1
    return sections


def section_body(sections: list[Section], index: int) -> list[str]:
    """index 절의 본문 + 그 아래 하위 절(더 깊은 제목)까지."""
    base = sections[index]
    out = list(base.lines)
    for sec in sections[index + 1 :]:
        if base.level and sec.level <= base.level:
            break
        if not base.level:  # 머리말(제목 이전)은 첫 제목에서 끝난다
            break
        out.append(sec.title)
        out.extend(sec.lines)
    return out


def code_blocks(lines: list[str], source: str = "") -> list[CodeBlock]:
    blocks: list[CodeBlock] = []
    fence: str | None = None
    lang = ""
    buf: list[str] = []
    for line in lines:
        m = _FENCE.match(line)
        if fence is None:
            if m:
                fence, lang, buf = m.group(1), m.group(2).lower(), []
            continue
        if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2):
            code = textwrap.dedent("\n".join(buf)).strip("\n")
            if code.strip():
                blocks.append(_truncate(CodeBlock(lang=lang, code=code, source=source)))
            fence = None
            continue
        buf.append(line)
    return blocks


def _truncate(block: CodeBlock) -> CodeBlock:
    lines = block.code.split("\n")
    if len(lines) <= MAX_BLOCK_LINES:
        return block
    return CodeBlock(block.lang, "\n".join(lines[:MAX_BLOCK_LINES]), True, block.source)


def _is_install_block(block: CodeBlock) -> bool:
    # 셸 언어가 명시된 블록은 채택, 언어 표기가 없거나 text 인 블록은 명령어 모양일 때만(프롬프트 예시 문장 등 제외)
    return block.lang in SHELL_LANGS or bool(_INSTALL_CMD.search(block.code))


def _is_strong(code: str) -> bool:
    return bool(_STRONG_CMD.search(code) or _PIPE_SH.search(code) or (_GIT_CLONE.search(code) and _BUILD_CMD.search(code)))


def _dedupe_add(target: list[CodeBlock], items: list[CodeBlock], limit: int) -> None:
    seen = {b.code for b in target}
    for b in items:
        if len(target) >= limit:
            return
        if b.code not in seen:
            target.append(b)
            seen.add(b.code)


def _dedupe(blocks: list[CodeBlock]) -> list[CodeBlock]:
    seen: set[str] = set()
    out = []
    for b in blocks:
        if b.code not in seen:
            out.append(b)
            seen.add(b.code)
    return out


def _pick(blocks: list[CodeBlock], limit: int) -> list[CodeBlock]:
    """핵심 절의 확실한 설치 명령 → 핵심 절의 다른 셸 블록 → 선택·고급 절 순으로 고른다. 결과는 README 순서 유지."""
    blocks = _dedupe(blocks)

    def priority(i: int) -> tuple[int, int, int]:
        b = blocks[i]
        return (1 if _SIDE_HEAD.search(b.source) else 0, 0 if _is_strong(b.code) else 1, i)

    chosen = sorted(range(len(blocks)), key=priority)[:limit]
    return [blocks[i] for i in sorted(chosen)]


def _subsections(sections: list[Section], index: int) -> list[Section]:
    """index 절과 그 하위 절들(각자 자기 제목을 유지)."""
    base = sections[index]
    out = [base]
    for sec in sections[index + 1 :]:
        if not base.level or sec.level <= base.level:
            break
        out.append(sec)
    return out


def _prose(lines: list[str]) -> list[str]:
    """코드 펜스 밖의 줄만."""
    out, fence = [], None
    for line in lines:
        m = _FENCE.match(line)
        if m:
            fence = None if fence is not None and m.group(1)[0] == fence[0] and not m.group(2) else (fence or m.group(1))
            continue
        if fence is None:
            out.append(line)
    return out


def inline_commands(lines: list[str], source: str) -> list[CodeBlock]:
    """표·본문 속 `인라인 코드` 로 적힌 설치 명령(예: OS 별 설치 표)을 한 블록으로 모은다."""
    cmds: list[str] = []
    for line in _prose(lines):
        for m in _INLINE_CODE.finditer(line):
            cmd = (m.group(1) or m.group(2) or "").strip()
            if cmd and _is_strong(cmd) and cmd not in cmds:
                cmds.append(cmd)
    if not cmds:
        return []
    return [_truncate(CodeBlock(lang="", code="\n".join(cmds), source=source))]


def extract_install_usage(markdown: str) -> tuple[list[CodeBlock], list[CodeBlock], str]:
    markdown = normalize_readme(markdown)
    sections = split_sections(markdown)
    candidates: list[CodeBlock] = []
    usage: list[CodeBlock] = []
    for idx, sec in enumerate(sections):
        if not sec.title or SKIP_HEAD.search(sec.title):
            continue
        if INSTALL_HEAD.search(sec.title):
            # 하위 절마다 자기 제목을 출처로 남긴다(예: 'Install from conda'). 상위 절이 선택·고급이면 하위도 그렇게 본다
            side = bool(_SIDE_HEAD.search(sec.title))
            for sub in _subsections(sections, idx):
                if SKIP_HEAD.search(sub.title):
                    continue
                label = sub.title if not side or _SIDE_HEAD.search(sub.title) else f"{sec.title} > {sub.title}"
                candidates += [b for b in code_blocks(sub.lines, label) if _is_install_block(b)]
                candidates += inline_commands(sub.lines, label)
        elif USAGE_HEAD.search(sec.title):
            _dedupe_add(usage, code_blocks(section_body(sections, idx), sec.title), MAX_USAGE_BLOCKS)
    install = _pick(candidates, MAX_INSTALL_BLOCKS)
    usage = [b for b in usage if b.code not in {i.code for i in install}]
    source = "section" if install else ""
    if not install:
        cands: list[CodeBlock] = []
        for sec in sections:
            if sec.title and SKIP_HEAD.search(sec.title):
                continue
            cands += [b for b in code_blocks(sec.lines, sec.title or "(머리말)") if _is_strong(b.code)]
        install = _dedupe(cands)[:3]
        source = "fallback" if install else ""
    return install, usage, source


# ---------------------------------------------------------------------------
# reStructuredText(README.rst) → 마크다운 근사 변환
# ---------------------------------------------------------------------------
_RST_ADORN = re.compile(r"^([=\-~^\"'`#*+<>:._])\1{2,}\s*$")
_RST_DIRECTIVE = re.compile(r"^\.\.\s+(?:([\w-]+)::\s*(.*)|_|\|)")
_RST_CODE = {"code-block", "code", "sourcecode"}


def looks_like_rst(text: str) -> bool:
    if "```" in text or re.search(r"^#{1,6}\s", text, re.M):
        return False
    return bool(re.search(r"^\.\.\s+[\w|_-]", text, re.M) or re.search(r"::\s*$", text, re.M))


def rst_to_markdown(text: str) -> str:
    """제목·코드 블록·인라인 코드만 옮긴다(설치법 추출에 필요한 만큼). 나머지 지시문은 버린다."""
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    levels: list[str] = []
    i = 0

    def take_indented(j: int) -> tuple[list[str], int]:
        block: list[str] = []
        while j < len(lines) and (not lines[j].strip() or lines[j][:1] in (" ", "\t")):
            block.append(lines[j])
            j += 1
        while block and not block[-1].strip():
            block.pop()
        return [ln for ln in block if not re.match(r"^\s+:[\w-]+:", ln)], j

    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        # 윗줄·아랫줄 장식이 있는 제목
        if _RST_ADORN.match(line) and nxt.strip() and i + 2 < len(lines) and lines[i + 2].strip() == line.strip():
            style = line.strip()[0] + "o"
            if style not in levels:
                levels.append(style)
            out.append("#" * min(levels.index(style) + 1, 6) + " " + nxt.strip())
            i += 3
            continue
        if line.strip() and not _RST_ADORN.match(line) and _RST_ADORN.match(nxt) and len(nxt.strip()) >= len(line.strip()):
            style = nxt.strip()[0]
            if style not in levels:
                levels.append(style)
            out.append("#" * min(levels.index(style) + 1, 6) + " " + line.strip())
            i += 2
            continue
        d = _RST_DIRECTIVE.match(line)
        if d:
            body, i = take_indented(i + 1)
            if d.group(1) in _RST_CODE:
                out += ["```" + (d.group(2) or "").strip(), *body, "```"]
            continue
        if line.rstrip().endswith("::") and i + 1 < len(lines) and not nxt.strip():
            text_part = line.rstrip()[:-2].rstrip()
            if text_part:
                out.append(text_part + ":")
            body, i = take_indented(i + 1)
            if body:
                out += ["```", *body, "```"]
            continue
        out.append(line.replace("``", "`"))
        i += 1
    return "\n".join(out)


def normalize_readme(text: str) -> str:
    return rst_to_markdown(text) if looks_like_rst(text) else text


# ---------------------------------------------------------------------------
# 주의점
# ---------------------------------------------------------------------------
def license_caveat(spdx: str | None) -> str | None:
    if spdx is None:
        return "라이선스 미표기 - 기본 저작권이 적용되어 복제·수정·재배포 권리가 보장되지 않습니다"
    s = spdx.upper()
    if s in {"NOASSERTION", "OTHER"}:
        return "GitHub 가 판별하지 못한 비표준 라이선스 - LICENSE 파일에서 비상업·연구용 제한 여부를 확인하세요"
    if s.startswith("AGPL"):
        return f"{spdx}: 수정본을 네트워크 서비스로만 제공해도 소스 공개 의무가 있습니다"
    if s.startswith("LGPL"):
        return f"{spdx}: 라이브러리 자체를 수정해 배포하면 수정분 소스 공개 의무가 있습니다"
    if s.startswith("GPL"):
        return f"{spdx}: 이 코드를 포함해 배포하는 프로그램도 GPL 로 소스를 공개해야 합니다(카피레프트)"
    if s.startswith("MPL"):
        return f"{spdx}: 수정한 파일은 소스 공개 의무가 있습니다(파일 단위 카피레프트)"
    if s.startswith(("CC-BY-NC", "CC-BY-NC-SA", "CC-BY-NC-ND")):
        return f"{spdx}: 비상업 라이선스 - 상업적 사용 불가"
    return None


def repo_caveats(repo: Repo, now: datetime | None = None) -> list[str]:
    """메타데이터만으로 판정하는 주의점(README 조회 없이 계산 가능)."""
    now = now or datetime.now(UTC)
    out: list[str] = []
    if repo.archived:
        out.append("보관(archived)된 저장소 - 더 이상 업데이트·보안 수정이 없습니다")
    if repo.fork:
        out.append("포크 저장소 - 원본 저장소도 함께 확인하세요")
    if repo.pushed_at is not None:
        days = (now - repo.pushed_at).days
        if days > STALE_DAYS:
            out.append(f"마지막 푸시 {days}일 전({repo.pushed_at.date().isoformat()}) - 유지보수가 멈췄을 수 있습니다")
    if repo.created_at is not None:
        age = (now - repo.created_at).days
        if 0 <= age < NEW_REPO_DAYS:
            out.append(f"생성 {age}일 된 저장소 - 사용 이력이 짧아 안정성·스타 수의 신뢰도를 따로 확인하세요")
        elif age < FAST_GROWTH_DAYS and repo.stars / (age / 365.25) >= FAST_GROWTH_STARS_PER_YEAR:
            months = max(1, round(age / 30.44))
            out.append(f"생성 약 {months}개월 만에 스타 {repo.stars:,}개 - 매우 빠른 급성장입니다. 일시적 화제이거나 스타 조작일 수도 "
                       "있으니 커밋·이슈 활동과 사용 후기를 함께 확인하세요")
    lic = license_caveat(repo.license_spdx)
    if lic:
        out.append(lic)
    if repo.size_kb >= LARGE_REPO_KB:
        out.append(f"저장소 용량 약 {repo.size_kb / 1024 / 1024:.1f}GB - 클론 시간·디스크 공간 주의")
    if _DEPRECATED.search(repo.description):
        out.append("설명에 지원 종료·이전 안내 문구가 있습니다 - 후속 저장소를 확인하세요")
    if _EDUCATIONAL.search(" ".join([repo.description, *repo.topics])):
        out.append("강좌·튜토리얼·책 예제 성격의 저장소로 보입니다 - 바로 쓰는 도구가 아니라 학습 자료일 수 있습니다")
    return out


def readme_caveats(markdown: str, install: list[CodeBlock], already: list[str]) -> list[str]:
    out: list[str] = []
    install_text = "\n".join(b.code for b in install)
    if _PIPE_SH.search(install_text):
        out.append("원격 스크립트를 내려받아 바로 실행하는 설치 명령(curl … | sh 등) - 실행 전에 스크립트 내용을 확인하세요")
    if _SUDO.search(install_text):
        out.append("관리자 권한(sudo) 명령이 포함된 설치 절차")
    vram = sorted({float(a or b) for a, b in _VRAM.findall(markdown) if (a or b)})
    if vram:
        shown = "·".join(f"{v:g}GB" for v in vram[:4])
        out.append(f"README 에 VRAM {shown} 언급 - GPU 메모리 요구사항을 확인하세요")
    elif _GPU.search(markdown):
        out.append("README 에 CUDA·NVIDIA·GPU 요구 언급 - 하드웨어 요구사항을 확인하세요")
    if _NONCOMMERCIAL.search(markdown):
        out.append("README 에 비상업·연구용 제한 문구 - 상업적으로 쓰기 전에 라이선스를 확인하세요")
    if _API_KEY.search(markdown):
        out.append("README 에 API 키 언급 - 외부 유료 서비스 연동·과금 여부를 확인하세요")
    if not any("지원 종료" in c for c in already) and _DEPRECATED.search(markdown[:3000]):
        out.append("README 앞부분에 지원 종료·이전 안내 문구가 있습니다")
    return out


def _no_command_note(readme: str) -> str:
    """설치 명령이 없을 때 README 가 어떤 방식으로 안내하는지(다운로드형·문서 링크형·없음)."""
    sections = split_sections(normalize_readme(readme))
    for idx, sec in enumerate(sections):
        if not sec.title or SKIP_HEAD.search(sec.title) or not INSTALL_HEAD.search(sec.title):
            continue
        body = "\n".join(_prose(section_body(sections, idx)))
        if DOWNLOAD_HEAD.search(sec.title) or _DOWNLOAD_WORDS.search(body):
            return f"README '{sec.title}' 절 안내대로 설치 파일을 내려받는 방식으로 보입니다 - 원문의 링크를 확인하세요"
        return f"README '{sec.title}' 절에 명령어 없이 링크·설명만 있습니다 - 원문(공식 문서)을 확인하세요"
    for idx, sec in enumerate(sections):
        if sec.title and DOCS_HEAD.search(sec.title) and _HAS_LINK.search("\n".join(section_body(sections, idx))):
            return f"README '{sec.title}' 절의 공식 문서 링크로 설치법을 안내합니다(명령어 없이 링크·설명만) - 문서를 확인하세요"
    return "README 에서 설치 명령을 찾지 못했습니다 - 원문을 확인하세요"


def build_guide(repo: Repo, readme: str | None, now: datetime | None = None) -> Guide:
    caveats = repo_caveats(repo, now)
    if readme is None:
        guide = Guide(repo=repo, readme_found=False, caveats=caveats)
        guide.notes.append("README 를 찾지 못했습니다 - 저장소 페이지에서 직접 확인하세요")
        return guide
    install, usage, source = extract_install_usage(readme)
    guide = Guide(repo=repo, readme_found=True, install=install, usage=usage, install_from=source)
    guide.caveats = caveats + readme_caveats(readme, install, caveats)
    if not install:
        guide.notes.append(_no_command_note(readme))
    elif source == "fallback":
        guide.notes.append("'설치' 절이 없어 README 전체에서 설치 명령으로 보이는 코드를 추정했습니다")
    if not usage:
        guide.notes.append("README 에서 별도 사용법 절을 찾지 못했습니다(설치 절에 실행 명령이 함께 있을 수 있음)")
    if repo.homepage:
        guide.notes.append(f"공식 문서/홈페이지: {repo.homepage}")
    return guide
