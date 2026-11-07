# ghrank 정확도 측정 결과

측정 2026-11-07 07:28 UTC · 정답 데이터는 README·메타데이터만 보고 표시(ghrank 코드 미참조)

## 분야 분류 (15개 분야 × 검색 후보 24개, 오프라인)

| 지표 | 값 | 뜻 |
|---|---:|---|
| 상위 12개 정확도 | **79.3%** | 보여 준 저장소 중 분야에 맞는 소프트웨어 비율 |
| 〃 (경계 사례 제외) | 84.7% | 정답이 확실한 항목만 |
| 필터 없을 때(스타 순 그대로) | 56.7% | 비교 기준 |
| 좋은 저장소 보존율 | 83.0% | 분야에 맞는 저장소가 필터에 살아남은 비율 |
| 링크 모음 제거율 | 88.0% | awesome·목록형을 걸러 낸 비율 |

| 분야 | 상위12 정확 | 기준 | 잘못 보여 준 것 | 잘못 거른 것 |
|---|---:|---:|---|---|
| image | 8/12 | 7/12 | unslothai/unsloth, mudler/LocalAI, ATH-MaaS/Pixelle-Video, op7418/guizang-ppt-skill | TencentARC/GFPGAN, sczhou/CodeFormer |
| video | 12/12 | 12/12 | - | - |
| audio | 10/12 | 7/12 | huggingface/transformers, mudler/LocalAI | - |
| llm | 7/11 | 6/12 | Significant-Gravitas/AutoGPT, harry0703/MoneyPrinterTurbo, TauricResearch/TradingAgents, OpenHands/OpenHands | langgenius/dify, langchain-ai/langchain |
| agent | 11/12 | 8/12 | firecrawl/firecrawl | farion1231/cc-switch, Shubhamsaboo/awesome-llm-apps |
| rag | 3/9 | 2/12 | Graphify-Labs/graphify, datawhalechina/hello-agents, dair-ai/Prompt-Engineering-Guide, headroomlabs-ai/headroom, toeverything/AFFiNE, jeecgboot/JeecgBoot | Shubhamsaboo/awesome-llm-apps, mem0ai/mem0, Mintplex-Labs/anything-llm, run-llama/llama_index |
| vision | 11/12 | 7/12 | mudler/LocalAI | opendatalab/MinerU, google-ai-edge/mediapipe |
| 3d | 11/12 | 9/12 | 4ian/GDevelop | pmndrs/react-three-fiber, BabylonJS/Babylon.js, ssloy/tinyrenderer, blender/blender, aframevr/aframe, playcanvas/engine |
| frontend | 10/12 | 5/12 | nextlevelbuilder/ui-ux-pro-max-skill, react/react-native | - |
| backend | 7/10 | 6/12 | gatsbyjs/gatsby, expo/expo, TanStack/query | goldbergyoni/nodebestpractices, strapi/strapi, appwrite/appwrite, karanpratapsingh/system-design |
| data | 8/11 | 5/12 | koala73/worldmonitor, SimplifyJobs/Summer2027-Internships, ColorlibHQ/AdminLTE | - |
| automation | 10/12 | 8/12 | harry0703/MoneyPrinterTurbo, ToolJet/ToolJet | firecrawl/firecrawl, huginn/huginn, dgtlmoon/changedetection.io, cheeriojs/cheerio |
| devtools | 10/12 | 7/12 | yt-dlp/yt-dlp, Panniantong/Agent-Reach | morluto/rea, DietrichGebert/ponytail, stablyai/orca, OpenHands/OpenHands |
| game | 10/12 | 9/12 | emilk/egui, game1024/OpenSpeedy | ocornut/imgui, raysan5/raylib, clockworklabs/SpacetimeDB, mxgmn/WaveFunctionCollapse |
| mobile | 6/8 | 4/12 | laurent22/joplin, google/material-design-icons | - |

## 설치법 추출 · 개발용 (40개 저장소, README 커밋 고정)

| 지표 | 값 | 뜻 |
|---|---:|---|
| 설치 방식 판정 정확도 | **90.0%** | 명령형·다운로드형·문서 링크형·없음 구분 |
| 정답 명령을 하나 이상 찾음 | **100.0%** | 명령형 저장소 기준 |
| 정답 명령 재현율 | 89.9% | 정답 명령 중 찾아낸 비율 |
| 명령 없는데 명령이라 함 | 7.7% | 낮을수록 좋음 |

| 저장소 | 정답 방식 | 판정 | 찾은 명령 | 놓친 명령 |
|---|---|---|---:|---|
| AUTOMATIC1111/stable-diffusion-webui | commands | commands | 2/3 | `git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git` |
| Comfy-Org/ComfyUI | commands | commands | 3/4 | `pip install -r requirements.txt` |
| xinntao/Real-ESRGAN | commands | commands | 4/4 | - |
| invoke-ai/InvokeAI | download | download | 0/0 | - |
| huggingface/diffusers | commands | commands | 2/2 | - |
| mifi/lossless-cut | download | download | 0/0 | - |
| Wan-Video/Wan2.2 | commands | commands | 2/2 | - |
| KlingAIResearch/LivePortrait | commands | commands | 4/4 | - |
| heygen-com/hyperframes | commands | commands | 2/3 | `npx hyperframes init my-video` |
| RVC-Boss/GPT-SoVITS | commands | commands | 4/4 | - |
| ggml-org/whisper.cpp | commands | commands | 4/4 | - |
| coqui-ai/TTS | commands | commands | 1/2 | `docker run --rm -it -p 5002:5002 --entrypoint /bin/bash ghcr.io/coqui-ai/tts-cpu` |
| 2noise/ChatTTS | commands | commands | 2/3 | `git clone https://github.com/2noise/ChatTTS` |
| myshell-ai/OpenVoice | docs_link | none ✗ | 0/0 | - |
| ollama/ollama | commands | commands | 2/2 | - |
| open-webui/open-webui | commands | commands | 3/3 | - |
| vllm-project/vllm | commands | commands | 2/2 | - |
| browser-use/browser-use | commands | commands | 1/1 | - |
| langgenius/dify | commands | commands | 3/3 | - |
| infiniflow/ragflow | commands | commands | 3/3 | - |
| meilisearch/meilisearch | commands | commands | 2/2 | - |
| ultralytics/ultralytics | commands | commands | 1/1 | - |
| tesseract-ocr/tesseract | docs_link | docs_link | 0/0 | - |
| ocrmypdf/OCRmyPDF | commands | commands | 2/2 | - |
| PaddlePaddle/PaddleOCR | docs_link | docs_link | 0/0 | - |
| mrdoob/three.js | docs_link | none ✗ | 0/0 | - |
| NVlabs/instant-ngp | commands | commands | 1/3 | `cmake . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo`<br>`cmake --build build --config RelWithDebInfo -j` |
| shadcn-ui/ui | docs_link | docs_link | 0/0 | - |
| tailwindlabs/tailwindcss | docs_link | docs_link | 0/0 | - |
| pallets/flask | none | none | 0/0 | - |
| gofiber/fiber | commands | commands | 2/2 | - |
| apache/superset | docs_link | docs_link | 0/0 | - |
| streamlit/streamlit | commands | commands | 2/2 | - |
| n8n-io/n8n | commands | commands | 3/3 | - |
| scrapy/scrapy | commands | commands | 1/1 | - |
| junegunn/fzf | commands | commands | 2/2 | - |
| jesseduffield/lazygit | commands | commands | 2/2 | - |
| yt-dlp/yt-dlp | download | commands ✗ | 0/0 | - |
| godotengine/godot | download | download | 0/0 | - |
| Genymobile/scrcpy | docs_link | download ✗ | 0/0 | - |

## 설치법 추출 · 홀드아웃(규칙 수정 때 안 본 저장소) (24개 저장소, README 커밋 고정)

| 지표 | 값 | 뜻 |
|---|---:|---|
| 설치 방식 판정 정확도 | **75.0%** | 명령형·다운로드형·문서 링크형·없음 구분 |
| 정답 명령을 하나 이상 찾음 | **100.0%** | 명령형 저장소 기준 |
| 정답 명령 재현율 | 71.9% | 정답 명령 중 찾아낸 비율 |
| 명령 없는데 명령이라 함 | 25.0% | 낮을수록 좋음 |

| 저장소 | 정답 방식 | 판정 | 찾은 명령 | 놓친 명령 |
|---|---|---|---:|---|
| lllyasviel/Fooocus | commands | commands | 1/4 | `git clone https://github.com/lllyasviel/Fooocus.git`<br>`conda env create -f environment.yaml`<br>`conda activate fooocus` |
| upscayl/upscayl | commands | commands | 1/1 | - |
| obsproject/obs-studio | docs_link | none ✗ | 0/0 | - |
| openai/whisper | commands | commands | 1/3 | `pip install -U openai-whisper`<br>`pip install git+https://github.com/openai/whisper.git` |
| fishaudio/fish-speech | docs_link | download ✗ | 0/0 | - |
| ggml-org/llama.cpp | commands | commands | 2/2 | - |
| nomic-ai/gpt4all | commands | commands | 1/1 | - |
| crewAIInc/crewAI | commands | commands | 2/2 | - |
| microsoft/autogen | commands | commands | 2/2 | - |
| chroma-core/chroma | commands | commands | 1/1 | - |
| qdrant/qdrant | commands | commands | 1/1 | - |
| JaidedAI/EasyOCR | commands | commands | 2/2 | - |
| graphdeco-inria/gaussian-splatting | commands | commands | 2/3 | `git clone https://github.com/graphdeco-inria/gaussian-splatting --recursive` |
| vitejs/vite | docs_link | none ✗ | 0/0 | - |
| fastapi/fastapi | commands | commands | 1/1 | - |
| django/django | docs_link | none ✗ | 0/0 | - |
| pandas-dev/pandas | commands | commands | 2/2 | - |
| microsoft/playwright | commands | commands | 2/3 | `npm init playwright@latest` |
| BurntSushi/ripgrep | commands | commands | 1/2 | `cargo install ripgrep` |
| sharkdp/bat | commands | commands | 1/2 | `brew install bat` |
| cli/cli | docs_link | commands ✗ | 0/0 | - |
| bevyengine/bevy | docs_link | commands ✗ | 0/0 | - |
| raysan5/raylib | download | download | 0/0 | - |
| flutter/flutter | docs_link | docs_link | 0/0 | - |

## 버전 비교 (같은 정답 데이터, 2026-11-07)

| 측정 | v0.1 개발용 | v0.2 개발용 | v0.1 홀드아웃 | v0.2 홀드아웃 |
|---|---:|---:|---:|---:|
| 설치 방식 판정 | 80.0% | 90.0% | 66.7% | 75.0% |
| 정답 명령 1개 이상 | 92.6% | 100% | 87.5% | 100% |
| 정답 명령 재현율 | 79.7% | 89.9% | 65.6% | 71.9% |
| 명령 없는데 명령이라 함 | 15.4% | 7.7% | 25.0% | 25.0% |

홀드아웃은 v0.2 규칙을 고칠 때 보지 않은 저장소입니다. 개발용과 홀드아웃의 차이만큼은 개발용 데이터에 맞춘 효과로 봐야 합니다.
