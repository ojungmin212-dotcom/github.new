# ghrank: GitHub 분야별 저장소 순위·검색·설치 가이드

GitHub **스타 순위**를 기준으로 분야별 상위 저장소(기본 12개)를 뽑아 주고, 사용자가 찾는 분야·키워드의 저장소도 찾아 줍니다.
저장소마다 **설치법·사용법(README에서 자동 추출)** 과 **주의점(라이선스·유지보수·위험한 설치 명령 등)** 을 정리해서 보여 줍니다.

```text
$ ghrank top 이미지 -n 3
[이미지 생성·편집 스타 순] (image) - 상위 3개 · 조회 2026-11-05 19:16 UTC
  GitHub 검색 결과 20,667개 중 상위 3개 검토
   1. AUTOMATIC1111/stable-diffusion-webui  ★165,254 · Python · AGPL-3.0 · 마지막 푸시 2026-03-02
      Stable Diffusion web UI
      https://github.com/AUTOMATIC1111/stable-diffusion-webui
      주의: AGPL-3.0: 수정본을 네트워크 서비스로만 제공해도 소스 공개 의무가 있습니다
   2. Comfy-Org/ComfyUI  ★145,208 · Python · GPL-3.0 · 마지막 푸시 2026-11-05
   ...
```

- 외부 패키지 없이 Python 표준 라이브러리만 사용합니다.
- 기본 분야는 15개입니다: 이미지, 영상, 음성·오디오, LLM, 에이전트·MCP, RAG, 컴퓨터 비전·OCR, 3D, 프론트엔드, 백엔드, 데이터 시각화, 크롤링·자동화, 개발 도구, 게임, 모바일.

---

## 0. 화면으로 쓰기 (터미널 없이)

브라우저에서 클릭만으로 분야별 순위·찾기·설치법을 볼 수 있습니다. 화면은 **내 PC 안에서만** 열립니다(127.0.0.1).

**처음 한 번만 (Windows):** 설치(아래 1번) 후 PowerShell 에서 바탕화면 아이콘을 만듭니다.

```powershell
python -m ghrank web --shortcut
```

이제부터는 **바탕화면의 `ghrank` 아이콘을 더블클릭**하면 브라우저에 화면이 열립니다.

| 화면 | 하는 일 |
|---|---|
| 분야별 순위 | 분야 버튼을 누르면 스타 순 상위 저장소 + 주의점 |
| 찾기 | 한글·영어 검색어로 찾기 |
| 저장소 가이드 | `owner/repo` 나 GitHub 주소를 넣으면 설치·사용 명령과 주의점 |
| 설치·사용법 보기 | 카드마다 README 에서 뽑은 명령(복사 버튼 포함) |
| 보고서 저장(.md) | 현재 결과를 설치법까지 담아 파일로 저장 |
| 조건 | 개수·정렬·최근 활동·최소 스타·주 언어 (다음에도 기억) |

- 오른쪽 위 **종료**를 누르면 꺼집니다. 아이콘으로 켠 화면은 검은 창이 없고, **30분 동안 쓰지 않으면 저절로 꺼집니다**.
- 아이콘을 두 번 눌러도 이미 켜진 화면을 다시 엽니다(중복 실행 안 됨).
- macOS·Linux 나 터미널에서는 `ghrank web` 으로 켭니다(Ctrl+C 로 종료).
- 화면 기록은 아이콘 실행 시 `%LOCALAPPDATA%\ghrank\web.log` 에 남습니다(검색어는 남기지 않음).

**보안:** 화면은 127.0.0.1 에만 열리고, 다른 웹사이트가 이 화면의 기능을 몰래 호출하지 못하도록 막혀 있습니다(전용 헤더 + 접속 주소 검사).
README·설명 같은 외부 글은 화면에 글자로만 표시하므로 그 안의 스크립트가 실행되지 않습니다.

---

## 1. 설치

**필요 조건:** Python 3.11 이상 (`python --version`으로 확인)

```bash
git clone https://github.com/ojungmin212-dotcom/github.new.git
cd github.new
python -m venv .venv
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
# macOS / Linux:          source .venv/bin/activate
pip install .
ghrank --version          # ghrank 0.1.0
```

> 클론 없이 바로 설치: `pip install git+https://github.com/ojungmin212-dotcom/github.new.git`
> (명령줄 도구만 따로 설치하려면 `pipx install git+https://github.com/ojungmin212-dotcom/github.new.git`)

### GitHub 토큰 설정 (선택, 권장)

토큰 없이도 동작합니다. 다만 GitHub 호출 한도가 낮아 전체 분야를 조회할 때 기다리는 시간이 생깁니다.

| 한도 | 토큰 없음 | 토큰 있음 |
|---|---|---|
| 검색 API (분야 순위, `guide`의 저장소 정보) | 분당 10회 | 분당 30회 |
| 일반 API (README 조회 대체 경로) | 시간당 60회 | 시간당 5,000회 |

1. GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token
2. Repository access에서 **Public repositories**(공개 저장소 읽기 전용)를 고르고, 권한(Permissions)은 하나도 추가하지 않습니다.
3. 발급한 토큰을 환경변수에 넣습니다.

```powershell
# Windows PowerShell: 현재 창에서만
$env:GITHUB_TOKEN = "github_pat_..."
# 영구 저장(새 터미널부터 적용)
setx GITHUB_TOKEN "github_pat_..."
```

```bash
# macOS / Linux
export GITHUB_TOKEN="github_pat_..."
```

`GH_TOKEN`도 인식합니다. 토큰은 `api.github.com`에만 보내고, README 원문을 받는 `raw.githubusercontent.com`에는 보내지 않습니다.

---

## 2. 사용법

### 2-1. 분야 목록 보기

```bash
ghrank categories
```

| key | 분야 | 입력 가능한 별칭(예) |
|---|---|---|
| `image` | 이미지 생성·편집 | 이미지, 그림, 사진, image |
| `video` | 영상 생성·편집 | 영상, 동영상, 비디오, 쇼츠, video |
| `audio` | 음성·오디오 (TTS·STT·음악) | 음성, 목소리, 음악, tts, stt |
| `llm` | LLM·챗봇 | 챗봇, 언어모델, llm, gpt |
| `agent` | AI 에이전트·MCP | 에이전트, agent, mcp |
| `rag` | RAG·검색·벡터DB | 벡터db, 임베딩, 문서검색, rag |
| `vision` | 컴퓨터 비전·OCR | 비전, 객체인식, 문자인식, ocr, yolo |
| `3d` | 3D 생성·재구성 | 3d, 3d모델, nerf |
| `frontend` | 웹 프론트엔드·UI | 프론트엔드, react, vue, ui |
| `backend` | 백엔드·API 서버 | 백엔드, 서버, api서버 |
| `data` | 데이터 분석·시각화 | 데이터, 시각화, 차트, 대시보드 |
| `automation` | 웹 크롤링·업무 자동화 | 크롤링, 스크래핑, 자동화, rpa |
| `devtools` | 개발 도구·CLI | 개발도구, 터미널, cli |
| `game` | 게임 개발 | 게임, 게임엔진, gamedev |
| `mobile` | 모바일 앱 | 모바일, 안드로이드, 아이폰, flutter |

### 2-2. 분야별 상위 12개

```bash
ghrank top                      # 15개 분야 전부 (토큰 없으면 1~2분 걸림)
ghrank top 이미지 영상           # 한글 별칭 사용 가능
ghrank top image -n 20          # 20개
ghrank top audio --lang python  # 주 언어가 Python 인 것만
ghrank top video --active-days 90 --min-stars 1000   # 최근 90일 안에 푸시, 스타 1,000 이상
ghrank top llm --sort updated   # 최근 업데이트 순
```

### 2-3. 원하는 저장소 찾기

```bash
ghrank find 영상 만들기          # 한글이면 분야로 해석 → video 분야 순위
ghrank find "pdf ocr"           # 영어 키워드는 GitHub 자유 검색(이름·설명·토픽), 스타 순
ghrank find 자막 --raw          # 분야로 해석하지 않고 검색어 그대로 검색
ghrank find "background removal" --lang python -n 5
```

GitHub 검색 문법도 그대로 쓸 수 있습니다. 예: `ghrank find "tts language:rust"`

### 2-4. 설치법·사용법·주의점 정리

```bash
ghrank guide Comfy-Org/ComfyUI                 # 저장소 하나 (URL을 붙여 넣어도 됨)
ghrank guide mifi/lossless-cut ollama/ollama   # 여러 개
ghrank top 영상 -n 5 --guide                   # 순위 + 저장소마다 설치·사용·주의
```

출력 구성은 다음과 같습니다.

- **[설치]**: README의 설치 관련 절(Install, Setup, Quick Start, 설치, 安装, 快速开始 등)에 있는 명령어 코드 블록
- **[사용]**: Usage, Example, Run, 사용법, 使用方法 등의 절에 있는 코드 블록
- **[주의]**: 아래 "3. 자동 판정하는 주의 항목" 참고
- **[참고]**: 공식 문서 주소, 추출하지 못한 항목 안내

블록마다 어느 README 절에서 가져왔는지 표시되므로 원문과 대조할 수 있습니다.

### 2-5. 보고서로 저장

```bash
ghrank top --guide --format md -o report.md      # 마크다운(표 + 저장소별 설치·주의)
ghrank top 이미지 --format json -o image.json    # JSON(다른 프로그램에서 가공)
```

### 2-6. 전체 옵션

| 옵션 | 설명 | 기본 |
|---|---|---|
| `-n`, `--top` | 분야별 개수 (1~100) | 12 |
| `--sort` | `stars` / `forks` / `updated` | stars |
| `--lang` | 주 언어 한정 | - |
| `--min-stars` | 최소 스타 수 | - |
| `--active-days` | 최근 N일 안에 푸시된 저장소만 | - |
| `--guide` | README에서 설치·사용·주의 추출 | 끔 |
| `--include-archived` | 보관(archived) 저장소 포함 | 제외 |
| `--include-lists` | awesome-* 같은 링크 모음 포함 | 제외 |
| `--loose` | 분야 관련성 필터 끄기 | 켬 |
| `--format` | `text` / `md` / `json` | text |
| `-o`, `--output` | 파일로 저장(UTF-8) | 화면 |
| `--no-cache` / `--cache-hours` | 캐시 끄기 / 유효 시간 | 6시간 |
| `--categories-file` | 직접 만든 분야 정의 파일 | 내장 |
| `--max-wait` | 호출 한도에 걸렸을 때 최대 대기 초 | 90 |
| `-q`, `--quiet` | 진행 메시지 숨김 | - |

종료 코드: `0` 정상, `1` 일부 또는 전체 실패(한도 초과·검색어 거부·저장소 없음 등, 성공한 부분은 출력됨), `2` 잘못된 인자.

---

## 3. 자동 판정하는 주의 항목

| 항목 | 판정 근거 | 표시 예 |
|---|---|---|
| 라이선스 없음 | GitHub 라이선스 정보 없음 | 기본 저작권 적용, 재사용 권리 보장 안 됨 |
| 카피레프트 | AGPL / GPL / LGPL / MPL | AGPL: 네트워크 서비스로만 제공해도 소스 공개 의무 |
| 비표준 라이선스 | GitHub 판별 불가(NOASSERTION) | LICENSE 파일에서 비상업·연구용 제한 확인 |
| 유지보수 중단 의심 | 마지막 푸시가 365일 넘음 | 마지막 푸시 821일 전 |
| 보관됨 | archived 상태 (`--include-archived`를 쓸 때만 나옴) | 업데이트·보안 수정 없음 |
| 신생 저장소 | 생성된 지 90일 미만 | 사용 이력이 짧음, 스타 신뢰도 확인 |
| 학습 자료 | 설명·토픽에 lessons, tutorial, from scratch, 教程 등 | 바로 쓰는 도구가 아닐 수 있음 |
| 대용량 | 저장소 1GB 이상 | 클론 시간·디스크 주의 |
| 위험한 설치 명령 | 설치 명령에 `curl … \| sh`, `irm … \| iex`, `sudo` | 실행 전 스크립트 내용 확인 |
| 하드웨어 | README에 VRAM nGB, CUDA, NVIDIA, "requires a GPU" | GPU 메모리 요구사항 확인 |
| 비상업 제한 | README에 non-commercial, research only, 禁止商用 | 상업적 사용 전 확인 |
| 유료 API | README에 `*_API_KEY`, API key | 외부 서비스 과금 여부 확인 |
| 지원 종료 | 설명이나 README 앞부분에 deprecated, no longer maintained | 후속 저장소 확인 |

---

## 4. 주의점 (꼭 읽어 주세요)

1. **순위는 스타 수입니다. 품질 순위가 아닙니다.** 스타는 인기 지표일 뿐이고 구매·조작 사례도 연구로 보고되었습니다. 오래된 저장소일수록 스타가 많아 유리합니다. 최신 위주로 보려면 `--active-days`나 `--sort updated`를 쓰세요.
2. **분야 분류는 휴리스틱입니다.** 저장소가 스스로 붙인 토픽과 설명으로 판단합니다. 노출을 위해 토픽을 수십 개 붙인 범용 저장소를 걸러 내는 필터가 있지만 완벽하지 않습니다. 실측(2026-11-05)에서도 `data` 분야에 인턴십 공고 목록이 섞였습니다. 반대로 관련 있는 저장소가 빠질 수도 있으니, 결과가 이상하면 `--loose`로 비교해 보세요.
3. **설치·사용법은 README 규칙 추출입니다.** README 구성이 특이하면 엉뚱한 블록을 가져오거나 아무것도 못 가져옵니다. 실측(2026-11-05, 15개 분야 상위 12개, 중복 뺀 162개 중 README를 받은 154개)에서 설치 명령 추출은 107개(69%), 별도 사용법 절 추출은 46개(30%)였습니다. 나머지는 다운로드형 앱(10개), 설치 절에 문서 링크만 있는 경우(18개), 아무것도 못 찾은 경우(19개)였고, 이때는 그 사실을 [참고]에 표시합니다. 명령을 실행하기 전에 반드시 원문(표시된 절)과 대조하세요. 특히 `curl … | sh` 형태는 원격 스크립트를 검토 없이 실행합니다.
4. **주의 판정은 법률·보안 감사가 아닙니다.** 라이선스는 GitHub가 판별한 값 기준이고, "README에 ~ 언급"은 해당 단어가 있다는 뜻일 뿐입니다. 상업적으로 쓸 때는 LICENSE 원문을 직접 확인하세요.
5. **결과는 캐시됩니다(기본 6시간).** 스타 수·날짜가 몇 시간 지난 값일 수 있습니다. 최신 값이 필요하면 `--no-cache`를 쓰세요. 캐시 위치는 Windows `%LOCALAPPDATA%\ghrank`, macOS/Linux `~/.cache/ghrank`이고, 지워도 됩니다.
6. **한글 검색은 결과가 적습니다.** GitHub 저장소 설명은 대부분 영어입니다. 한글 입력은 분야 별칭으로 해석하고, 분야에 없는 한글 단어는 그대로 검색하되 경고를 띄웁니다. 구체적인 주제는 영어 키워드(`find "subtitle generator"`)가 정확합니다.
7. **검토 범위에 상한이 있습니다.** 분야당 스타 상위 최대 300개(검색 3회)까지만 검토합니다. GitHub 검색 자체도 최대 1,000개까지만 돌려줍니다.
8. **호출 한도.** 토큰이 없으면 `ghrank top`(15개 분야)을 실행할 때 분당 10회 한도 때문에 중간에 최대 1분가량 기다립니다. 한도 해제까지 `--max-wait`(90초)보다 오래 걸리면 거기서 멈추고, 그때까지 받은 결과만 출력합니다.
9. **추천 저장소를 실행할 때는** 가상환경이나 컨테이너에서 먼저 시험하세요. 스타가 많아도 악성 의존성이나 공급망 공격이 생길 수 있습니다.
10. **토큰 관리.** 권한 없는 읽기 전용 토큰을 쓰고, 코드나 저장소에 커밋하지 마세요.

---

## 5. 동작 원리 (비유: 도서관 사서)

1. **분류표로 후보 찾기:** 분야마다 정해 둔 토픽(예: 이미지는 `text-to-image`, `stable-diffusion` …)으로 GitHub를 검색합니다. 서가 분류표로 책을 뽑는 단계입니다.
2. **대출 횟수로 줄 세우기:** GitHub가 스타 순으로 정렬해 돌려줍니다.
3. **엉뚱한 책 빼기:** 이름·설명에 분야 키워드가 없고 토픽도 분야와 거의 겹치지 않는 저장소, awesome-* 같은 링크 모음, 보관된 저장소를 뺍니다.
4. **'설치' 장만 옮겨 적기:** README에서 설치·사용 제목 아래의 명령어 블록만 가져옵니다.
5. **판권면 확인:** 라이선스, 마지막 푸시, 생성일, README의 위험 신호를 보고 주의 문구를 붙입니다.

---

## 6. 분야 추가·수정

내장 정의 파일 [`src/ghrank/categories.toml`](src/ghrank/categories.toml)을 복사해서 고친 뒤 지정하면 됩니다.

```bash
ghrank top --categories-file my_categories.toml
```

```toml
[[category]]
key = "subtitle"                     # 영문 소문자·숫자·하이픈
name = "자막 생성"
topics = ["subtitles", "whisper", "speech-to-text", "srt"]   # 앞 6개만 검색에 사용(GitHub 연산자 제한)
keywords = ["subtitle", "caption", "srt", "자막"]             # 이름·설명 일치 판정
aliases = ["자막", "subtitle"]                                # 입력 별칭
```

---

## 7. 개발

```bash
pip install -e ".[dev]"
ruff check src tests
pyright
python -m pytest -q
```

테스트는 네트워크 없이 가짜 응답으로 돌아갑니다(검색어 조립, 관련성 필터, README 추출, 주의 판정, 한도 대기·재시도, 캐시, CLI, cp949 출력 안전성).

---

## 라이선스

[MIT](LICENSE) © 2026 오정민
