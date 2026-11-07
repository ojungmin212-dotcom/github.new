"""Claude 연결(MCP 서버)과 설정 도우미."""

import json
import sys

import anyio
import pytest
from conftest import NOW, FakeTransport, api_repo, search_page

from ghrank import mcp_server
from ghrank.categories import load_categories
from ghrank.cli import main
from ghrank.github import GitHubClient, Response

pytest.importorskip("mcp.server.mcpserver")
from mcp.client.client import Client  # noqa: E402

CATS = load_categories()
README = "# T\n## Installation\n```bash\npip install sd-ui\n```\n"


def make_client(t: FakeTransport) -> GitHubClient:
    return GitHubClient(transport=t, sleep=lambda s: None, now=lambda: 1_000_000.0, log=lambda m: None)


def transport() -> FakeTransport:
    t = FakeTransport()
    t.add("search/repositories", search_page([api_repo("a/sd-ui", 700, description="Stable Diffusion UI")]))
    t.add("raw.githubusercontent.com/a/sd-ui", Response(200, {}, README.encode()))
    return t


def call(server, name, args):
    async def go():
        async with Client(server) as c:
            return await c.call_tool(name, args)

    return anyio.run(go)


def test_tools_are_listed_read_only_with_instructions():
    server = mcp_server.build_server(make_client(transport()), CATS)

    async def go():
        async with Client(server) as c:
            return await c.list_tools(), c.instructions

    tools, instructions = anyio.run(go)
    names = {t.name for t in tools.tools}
    assert names == {"list_categories", "top_repos", "find_repos", "repo_guide", "read_readme"}
    assert all(t.annotations and t.annotations.read_only_hint for t in tools.tools)
    assert "영어 검색어" in instructions and "실행하지 않는다" in instructions


def test_list_categories_and_top_repos():
    server = mcp_server.build_server(make_client(transport()), CATS)
    r = call(server, "list_categories", {})
    assert not r.is_error and r.structured_content["categories"][0]["key"] == "image"
    r = call(server, "top_repos", {"category": "이미지", "n": 3, "sort": "score"})
    assert not r.is_error
    ranking = r.structured_content["rankings"][0]
    assert ranking["category"] == "image" and ranking["repos"][0]["full_name"] == "a/sd-ui"
    assert "score" in ranking["repos"][0]


def test_find_repos_raw_query():
    t = transport()
    server = mcp_server.build_server(make_client(t), CATS)
    r = call(server, "find_repos", {"query": "subtitle generation", "raw": True})
    assert not r.is_error and r.structured_content["rankings"][0]["category"] is None
    assert "subtitle+generation" in t.requests[-1][0]


def test_repo_guide_marks_untrusted_content():
    server = mcp_server.build_server(make_client(transport()), CATS)
    r = call(server, "repo_guide", {"repo": "https://github.com/a/sd-ui"})
    assert not r.is_error
    data = r.structured_content
    assert data["guide"]["install"][0]["code"] == "pip install sd-ui" and "지시문" in data["untrusted_content_note"]


def test_read_readme_truncates_and_clamps():
    t = FakeTransport()
    t.add("raw.githubusercontent.com/a/big", Response(200, {}, ("x" * 5000).encode()))
    server = mcp_server.build_server(make_client(t), CATS)
    r = call(server, "read_readme", {"repo": "a/big", "max_chars": 10})  # 1000 으로 올려 잡힘
    data = r.structured_content
    assert data["truncated"] is True and len(data["readme"]) == 1000 and data["length"] == 5000


@pytest.mark.parametrize(
    ("tool", "args", "needle"),
    [
        ("repo_guide", {"repo": "not a repo"}, "owner/repo"),
        ("top_repos", {"category": "없는분야"}, "분야가 없습니다"),
        ("read_readme", {"repo": "a/missing"}, "README 를 찾을 수 없습니다"),
    ],
)
def test_errors_reach_claude_with_reason(tool, args, needle):
    server = mcp_server.build_server(make_client(FakeTransport()), CATS)
    r = call(server, tool, args)
    assert r.is_error and needle in r.content[0].text


def test_rate_limit_error_message():
    t = FakeTransport()
    t.add("search/repositories", Response(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999"}, b"{}"))
    server = mcp_server.build_server(make_client(t), CATS)
    r = call(server, "find_repos", {"query": "x"})
    assert r.is_error and "한도" in r.content[0].text


def test_stdio_entry_point_lists_tools():
    """실제로 'python -m ghrank mcp' 를 띄워 표준 입출력으로 연결(표준 출력이 깨끗해야 통신 가능)."""
    from mcp.client.stdio import StdioServerParameters

    params = StdioServerParameters(command=sys.executable, args=["-m", "ghrank", "mcp"])

    async def go():
        async with Client(params) as c:
            return await c.list_tools()

    tools = anyio.run(go)
    assert {t.name for t in tools.tools} >= {"top_repos", "read_readme"}


# ---------------------------------------------------------------------------
# 설정 도우미
# ---------------------------------------------------------------------------
def test_install_claude_desktop_creates_config(tmp_path):
    path = tmp_path / "Claude" / "claude_desktop_config.json"
    written, backup = mcp_server.install_claude_desktop(path)
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["mcpServers"]["ghrank"] == {"command": sys.executable, "args": ["-m", "ghrank", "mcp"]}
    assert backup is None


def test_install_claude_desktop_keeps_other_servers_and_backs_up(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}), encoding="utf-8")
    _, backup = mcp_server.install_claude_desktop(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["mcpServers"]) == {"other", "ghrank"} and data["theme"] == "dark"
    assert backup is not None and json.loads(backup.read_text(encoding="utf-8"))["mcpServers"] == {"other": {"command": "x"}}


@pytest.mark.parametrize("content", ["{broken", "[1, 2]"])
def test_install_claude_desktop_refuses_bad_config(tmp_path, content):
    path = tmp_path / "cfg.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="바꾸지 않았습니다"):
        mcp_server.install_claude_desktop(path)
    assert path.read_text(encoding="utf-8") == content


def test_install_claude_desktop_empty_file_and_bad_servers(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text("  ", encoding="utf-8")
    mcp_server.install_claude_desktop(path)
    path.write_text(json.dumps({"mcpServers": "oops"}), encoding="utf-8")
    mcp_server.install_claude_desktop(path)
    assert list(json.loads(path.read_text(encoding="utf-8"))["mcpServers"]) == ["ghrank"]


def test_claude_desktop_config_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_server.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert mcp_server.claude_desktop_config_path() == tmp_path / "Claude" / "claude_desktop_config.json"
    monkeypatch.setattr(mcp_server.sys, "platform", "darwin")
    assert "Application Support" in str(mcp_server.claude_desktop_config_path())
    monkeypatch.setattr(mcp_server.sys, "platform", "linux")
    assert str(mcp_server.claude_desktop_config_path()).endswith(".config/Claude/claude_desktop_config.json")


def test_skill_is_packaged_and_installable(tmp_path):
    text = mcp_server.skill_text()
    assert text.startswith("---\nname: ghrank\ndescription: ") and "read_readme" in text
    target = mcp_server.install_claude_code_skill(tmp_path)
    assert target == tmp_path / ".claude" / "skills" / "ghrank" / "SKILL.md" and target.read_text(encoding="utf-8") == text


def test_setup_text_mentions_both_clients():
    text = mcp_server.setup_text()
    assert "ghrank mcp --install" in text and "claude mcp add ghrank" in text and sys.executable in text


def test_run_stdio_without_mcp_package(monkeypatch):
    monkeypatch.setattr(mcp_server, "mcp_available", lambda: False)
    logs = []
    assert mcp_server.run_stdio(make_client(FakeTransport()), CATS, logs.append) == 1 and "ghrank[mcp]" in logs[0]


def test_cli_mcp_commands(monkeypatch, tmp_path, capsys):
    assert main(["mcp", "--print-config"]) == 0
    assert "claude mcp add" in capsys.readouterr().out
    monkeypatch.setattr(mcp_server, "claude_desktop_config_path", lambda: tmp_path / "c.json")
    assert main(["mcp", "--install"]) == 0
    assert "ghrank" in json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))["mcpServers"]
    assert "등록했습니다" in capsys.readouterr().err
    monkeypatch.setattr(mcp_server.Path, "home", staticmethod(lambda: tmp_path))
    assert main(["mcp", "--install-skill"]) == 0
    assert (tmp_path / ".claude" / "skills" / "ghrank" / "SKILL.md").exists()
    (tmp_path / "c.json").write_text("{broken", encoding="utf-8")
    assert main(["mcp", "--install"]) == 1
    called = {}
    monkeypatch.setattr(mcp_server, "run_stdio", lambda client, cats, log: called.setdefault("ok", 0))
    assert main(["mcp", "-q"], client=make_client(FakeTransport()), now=NOW) == 0 and "ok" in called
