from datetime import UTC, datetime

import pytest
from conftest import NOW, api_repo

from ghrank.guide import (
    MAX_BLOCK_LINES,
    build_guide,
    code_blocks,
    extract_install_usage,
    license_caveat,
    readme_caveats,
    repo_caveats,
    split_sections,
)
from ghrank.ranking import Repo

README = """# Tool

Intro paragraph.

## Installation

```bash
pip install tool
```

### From source

```sh
git clone https://github.com/o/tool
cd tool && pip install -e .
```

```python
import tool  # 설치 절이지만 셸 명령이 아니므로 제외
```

## Usage

```python
import tool
tool.run()
```

## Contributing

```bash
pip install -r dev-requirements.txt
```
"""


def repo(**over) -> Repo:
    return Repo.from_api(api_repo("o/tool", **over))


def test_split_sections_ignores_hash_inside_code():
    md = "# A\n```bash\n# not a heading\n```\nB title\n---\ntext\n<h2 align=center>C <b>x</b></h2>\n"
    titles = [(s.level, s.title) for s in split_sections(md)]
    assert titles == [(0, ""), (1, "A"), (2, "B title"), (2, "C x")]


def test_split_sections_strips_links_comments_and_tilde_fences():
    md = "<!-- ## hidden -->\n## [Quick Start](#qs) 🚀\n~~~\n## inside\n~~~\n"
    secs = split_sections(md)
    assert [s.title for s in secs] == ["", "Quick Start 🚀"]


def test_extract_install_usage_basic():
    install, usage, source = extract_install_usage(README)
    assert source == "section"
    assert [b.code for b in install] == ["pip install tool", "git clone https://github.com/o/tool\ncd tool && pip install -e ."]
    assert install[0].source == "Installation" and install[0].lang == "bash"
    assert [b.code for b in usage] == ["import tool\ntool.run()"]
    # Contributing 절의 개발용 설치 명령은 가져오지 않는다
    assert all("dev-requirements" not in b.code for b in install + usage)


@pytest.mark.parametrize("heading", ["快速开始", "安装", "설치 방법", "Getting Started", "インストール", "Setup"])
def test_install_heading_variants(heading):
    install, _, source = extract_install_usage(f"## {heading}\n```\nnpm i -g tool\n```\n")
    assert source == "section" and install[0].code == "npm i -g tool"


def test_fallback_when_no_install_section():
    md = "# T\nSome text\n```js\nconsole.log(1)\n```\n## Docker\n```\ndocker run -p 80:80 o/tool\n```\n"
    install, usage, source = extract_install_usage(md)
    assert source == "fallback"
    assert install[0].code == "docker run -p 80:80 o/tool"
    assert usage == []


def test_nothing_found():
    assert extract_install_usage("# Title\nJust prose.\n") == ([], [], "")


def test_code_block_truncate_and_dedent():
    body = "\n".join(f"   echo {i}" for i in range(MAX_BLOCK_LINES + 5))
    (block,) = code_blocks(["   ```bash", body, "   ```"])
    assert block.truncated
    assert block.code.split("\n")[0] == "echo 0"
    assert len(block.code.split("\n")) == MAX_BLOCK_LINES


def test_unclosed_fence_is_dropped():
    assert code_blocks(["```", "pip install x"]) == []


@pytest.mark.parametrize(
    ("spdx", "needle"),
    [
        (None, "미표기"),
        ("NOASSERTION", "비표준"),
        ("AGPL-3.0", "네트워크"),
        ("GPL-3.0", "카피레프트"),
        ("LGPL-2.1", "라이브러리"),
        ("MPL-2.0", "파일 단위"),
        ("CC-BY-NC-4.0", "비상업"),
    ],
)
def test_license_caveats(spdx, needle):
    msg = license_caveat(spdx)
    assert msg is not None and needle in msg


@pytest.mark.parametrize("spdx", ["MIT", "Apache-2.0", "BSD-3-Clause", "Unlicense"])
def test_permissive_license_no_caveat(spdx):
    assert license_caveat(spdx) is None


def test_repo_caveats_metadata():
    r = repo(
        archived=True, fork=True, pushed_at="2024-01-01T00:00:00Z", created_at="2026-10-20T00:00:00Z",
        license=None, size=2 * 1024 * 1024, description="DEPRECATED: moved",
    )
    text = " | ".join(repo_caveats(r, NOW))
    for needle in ("보관", "포크", "마지막 푸시", "생성 16일", "미표기", "2.0GB", "지원 종료"):
        assert needle in text, needle


def test_healthy_repo_has_no_caveats():
    assert repo_caveats(repo(), NOW) == []


def test_readme_caveats_detects_risky_install_and_requirements():
    md = "Needs 24GB VRAM (or 12 GB of VRAM). Set OPENAI_API_KEY. For non-commercial use only."
    blocks = extract_install_usage("## Install\n```bash\ncurl -fsSL https://x.sh | sudo bash\n```\n")[0]
    text = " | ".join(readme_caveats(md, blocks, []))
    for needle in ("원격 스크립트", "sudo", "VRAM 12GB·24GB", "비상업", "API 키"):
        assert needle in text, needle


def test_readme_caveats_powershell_pipe_and_cuda():
    blocks = extract_install_usage("## Install\n```powershell\nirm https://x/install.ps1 | iex\n```\n")[0]
    text = " | ".join(readme_caveats("Requires CUDA 12.", blocks, []))
    assert "원격 스크립트" in text and "CUDA" in text


@pytest.mark.parametrize("text", ["Runs anywhere. No GPU required.", "It doesn't require a GPU.", "Does not need a GPU"])
def test_gpu_negations_are_not_flagged(text):
    assert readme_caveats(text, [], []) == []


@pytest.mark.parametrize("text", ["Requires an NVIDIA GPU", "This needs a modern GPU.", "GPU is required", "CUDA 12.1"])
def test_gpu_requirements_are_flagged(text):
    assert any("하드웨어" in c for c in readme_caveats(text, [], []))


def test_deprecated_in_readme_not_duplicated():
    md = "This project is no longer maintained."
    assert any("지원 종료" in c for c in readme_caveats(md, [], []))
    assert readme_caveats(md, [], ["설명에 지원 종료 문구"]) == []


def test_build_guide_without_readme():
    g = build_guide(repo(), None, NOW)
    assert not g.readme_found and "README" in g.notes[0]


def test_build_guide_notes_and_homepage():
    g = build_guide(repo(homepage="https://docs.example"), "# T\n```\npip install t\n```\n", NOW)
    assert g.install_from == "fallback"
    notes = " ".join(g.notes)
    assert "추정" in notes and "사용법" in notes and "https://docs.example" in notes
    d = g.to_dict()
    assert d["install"][0]["code"] == "pip install t" and d["readme_found"]


def test_build_guide_full():
    g = build_guide(repo(), README, datetime(2026, 11, 5, tzinfo=UTC))
    assert g.install and g.usage and g.install_from == "section"
    assert not any("설치 명령을 찾지" in n for n in g.notes)


@pytest.mark.parametrize(
    ("desc", "topics", "expected"),
    [
        ("21 Lessons, Get Started Building with Generative AI", [], True),
        ("Implement a ChatGPT-like LLM in PyTorch from scratch, step by step", [], True),
        ("从零开始的智能体原理与实践教程", [], True),
        ("Fast inference engine", ["tutorial"], True),
        ("Stable Diffusion web UI", ["ui"], False),
        ("A Bookmark manager", [], False),
    ],
)
def test_educational_caveat(desc, topics, expected):
    cav = repo_caveats(repo(description=desc, topics=topics), NOW)
    assert any("학습 자료" in c for c in cav) is expected


def test_plain_text_block_in_install_needs_command_shape():
    md = '## Quick Start\n```\n"Make a 60-second explainer video"\n```\n```\npip install tool\n```\n```text\nuv tool install x\n```\n'
    install, _, _ = extract_install_usage(md)
    assert [b.code for b in install] == ["pip install tool", "uv tool install x"]


def test_download_section_note():
    g = build_guide(repo(), "# App\n## Download\nGet it from [releases](https://x).\n", NOW)
    assert any("'Download' 절" in n for n in g.notes)
    assert not any("설치 명령을 찾지" in n for n in g.notes)


def test_fence_inside_list_item_with_deep_indent():
    md = "## Installation\n1. Clone\n\n    ```bash\n    git clone https://x/y\n    pip install -r requirements.txt\n    ```\n"
    install, _, source = extract_install_usage(md)
    assert source == "section"
    assert install[0].code == "git clone https://x/y\npip install -r requirements.txt"


def test_install_section_with_links_only_note():
    g = build_guide(repo(), "# App\n## Installation\nSee the [docs](https://docs.example/install).\n", NOW)
    assert any("'Installation' 절에 명령어 없이" in n for n in g.notes)
