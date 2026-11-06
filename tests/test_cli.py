import json

import pytest
from conftest import NOW, FakeTransport, api_repo, search_page

from ghrank.cli import main
from ghrank.github import GitHubClient, Response

README = "## Installation\n```bash\npip install sd-ui\n```\n## Usage\n```bash\nsd-ui --port 7860\n```\n"


def make_client(transport: FakeTransport) -> GitHubClient:
    return GitHubClient(transport=transport, sleep=lambda s: None, now=lambda: 1_000_000.0, log=lambda m: None)


def image_transport() -> FakeTransport:
    t = FakeTransport()
    items = [
        api_repo("a/sd-ui", 700, description="Stable Diffusion | web UI", license={"spdx_id": "AGPL-3.0"}),
        api_repo("a/upscaler", 600, description="image upscaler", pushed_at="2023-01-01T00:00:00Z"),
        api_repo("a/awesome-image", 500, description="curated list"),
    ]
    t.add("search/repositories", search_page(items))
    t.add("raw.githubusercontent.com/a/sd-ui", Response(200, {}, README.encode()))
    return t


def run_cmd(argv, transport, capsys):
    cmd, *rest = argv
    code = main([cmd, "-q", *rest], client=make_client(transport), now=NOW)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_top_text(capsys):
    code, out, _ = run_cmd(["top", "이미지", "-n", "5"], image_transport(), capsys)
    assert code == 0
    assert "[이미지 생성·편집 스타 순] (image)" in out
    assert "1. a/sd-ui" in out and "2. a/upscaler" in out and "awesome" not in out
    assert "AGPL-3.0" in out and "마지막 푸시 1404일 전" in out
    assert "※ 유의사항" in out


def test_top_with_guide_markdown(capsys):
    code, out, _ = run_cmd(["top", "image", "--guide", "--format", "md"], image_transport(), capsys)
    assert code == 0
    assert out.startswith("# GitHub 분야별 저장소 순위")
    assert "| 1 | [a/sd-ui](https://github.com/a/sd-ui) | 700 |" in out
    assert "Stable Diffusion \\| web UI" in out  # 표 안의 | 는 이스케이프
    assert "```bash\npip install sd-ui\n```" in out and "sd-ui --port 7860" in out
    assert "README 를 찾지 못했습니다" in out  # a/upscaler 는 README 없음


def test_top_json_to_file(tmp_path, capsys):
    path = tmp_path / "out" / "r.json"
    code, _, _ = run_cmd(["top", "image", "--guide", "--format", "json", "-o", str(path)], image_transport(), capsys)
    assert code == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    (ranking,) = data["rankings"]
    assert ranking["category"] == "image" and ranking["dropped_lists"] == 1
    first = ranking["repos"][0]
    assert first["rank"] == 1 and first["guide"]["install"][0]["code"] == "pip install sd-ui"
    assert any("AGPL" in c for c in first["caveats"])


def test_top_all_categories_by_default(capsys):
    t = FakeTransport()
    t.add("search/repositories", search_page([]))
    code, out, _ = run_cmd(["top", "-n", "1"], t, capsys)
    assert code == 0
    assert out.count("결과가 없습니다") >= 12


def test_top_unknown_category(capsys):
    code, _, err = run_cmd(["top", "없는분야"], FakeTransport(), capsys)
    assert code == 1 and "분야가 없습니다" in err


def test_find_korean_maps_to_category(capsys):
    t = image_transport()
    code, out, _ = run_cmd(["find", "이미지", "만들기"], t, capsys)
    assert code == 0 and "분야 [이미지 생성·편집(image)] 로 해석" in out
    assert "in%3Atopics" in t.requests[0][0]


def test_find_english_free_search_with_hint(capsys):
    t = FakeTransport()
    t.add("search/repositories", search_page([api_repo("p/ocr", 9, description="pdf ocr")]))
    code, out, _ = run_cmd(["find", "pdf", "ocr"], t, capsys)
    assert code == 0
    assert "'pdf ocr' 검색 결과 스타 순" in out and "ghrank top vision" in out
    assert "in%3Aname%2Cdescription%2Ctopics" in t.requests[0][0]


def test_find_raw_and_korean_warning(capsys):
    t = FakeTransport()
    t.add("search/repositories", search_page([]))
    code, out, _ = run_cmd(["find", "자막", "--raw"], t, capsys)
    assert code == 0 and "영어 키워드를 권장" in out


def test_guide_command(capsys):
    t = FakeTransport()
    t.add("search/repositories", search_page([api_repo("a/sd-ui", 7, description="web UI")]))
    t.add("raw.githubusercontent.com", Response(200, {}, README.encode()))
    code, out, _ = run_cmd(["guide", "https://github.com/a/sd-ui.git"], t, capsys)
    assert code == 0
    assert "a/sd-ui" in out and "[설치]" in out and "pip install sd-ui" in out and "[사용]" in out


def test_guide_command_error_exit_code(capsys):
    t = FakeTransport()
    t.add("search/repositories", search_page([]))
    code, out, _ = run_cmd(["guide", "o/missing", "--format", "json"], t, capsys)
    assert code == 1
    assert json.loads(out)["errors"][0].startswith("o/missing")


def test_rate_limit_keeps_partial_results(capsys):
    t = FakeTransport()
    t.add("search/repositories",
          search_page([api_repo("a/sd-ui", 7, description="image ui")]),
          Response(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999"}, b"{}"))
    code, out, _ = run_cmd(["top", "image", "video", "audio"], t, capsys)
    assert code == 1
    assert "a/sd-ui" in out and "호출 한도" in out and "나머지 조회를 중단" in out


def test_categories_command(capsys):
    code = main(["categories", "--format", "md"])
    out = capsys.readouterr().out
    assert code == 0 and "| `image` | 이미지 생성·편집 |" in out


def test_bad_categories_file(tmp_path, capsys):
    bad = tmp_path / "c.toml"
    bad.write_text("x = 1", encoding="utf-8")
    assert main(["categories", "--categories-file", str(bad)]) == 1
    assert "category" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0", "101"])
def test_top_bounds(value):
    with pytest.raises(SystemExit):
        main(["top", "-n", value])


def test_output_is_cp949_safe(capsys):
    # Windows 콘솔(cp949)로 리디렉션해도 프로그램이 만든 문구는 깨지지 않아야 한다
    _, out, _ = run_cmd(["top", "image", "--guide"], image_transport(), capsys)
    out.encode("cp949")


def test_readme_server_error_becomes_note(capsys):
    t = FakeTransport()
    t.add("search/repositories", search_page([api_repo("a/sd-ui", 7, description="image ui")]))
    t.add("raw.githubusercontent.com", Response(500, {}, b"boom"))
    code, out, _ = run_cmd(["top", "image", "--guide"], t, capsys)
    assert code == 0 and "README 조회 실패" in out


def test_rejected_query_continues_with_other_categories(capsys):
    t = FakeTransport()
    t.add("search/repositories",
          Response(422, {}, b'{"message": "Validation Failed"}'),
          search_page([api_repo("v/cut", 5, description="video editor")]))
    code, out, _ = run_cmd(["top", "image", "video"], t, capsys)
    assert code == 1
    assert "Validation Failed" in out and "v/cut" in out


def test_guide_command_stops_on_rate_limit(capsys):
    t = FakeTransport()
    t.add("search/repositories", Response(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999"}, b"{}"))
    code, out, _ = run_cmd(["guide", "a/one", "b/two"], t, capsys)
    assert code == 1 and "호출 한도" in out and "b/two" not in out
