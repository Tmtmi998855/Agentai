# 내 PC에서 실제 브리핑 1건 돌려보기 (써니웨이브텍)

목표: 내 PC에서 실제 데이터로 브리핑을 한 번 만들어 본다. Perplexity로 검색하고, 원문 페이지에서 문장을 확인하고, Codex CLI(GPT-6 Luna)로 질문 3선을 만든다.

## 0. 준비물

- Python 3.11 이상 (Windows: python.org 설치 시 "Add python.exe to PATH" 체크)
- Git
- Codex CLI 설치 + 로그인 완료 (`codex login status` 실행 시 로그인 상태가 출력되면 OK)
- 새로 발급한 Perplexity API 키

## 1. 코드 받기 (처음 한 번)

Windows (PowerShell):

```powershell
cd $HOME\Documents
git clone https://github.com/tmtmi998855/agentai.git
cd agentai
git checkout ccr-f6c9bfdf-jjjahe
```

Mac (터미널):

```bash
cd ~/Documents && git clone https://github.com/tmtmi998855/agentai.git && cd agentai && git checkout ccr-f6c9bfdf-jjjahe
```

이미 받아 둔 폴더가 있으면 `git pull`만 실행합니다.

## 2. 가상환경과 패키지 설치 (처음 한 번)

가상환경은 이 프로젝트 전용 파이썬 공간입니다. 다른 프로그램과 패키지가 섞이지 않게 해 줍니다.

Windows:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev,agent]"
```

Mac:

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -e ".[dev,agent]"
```

## 3. `.env` 만들기 (키 입력)

Windows:

```powershell
copy .env.example .env
notepad .env
```

Mac: `cp .env.example .env && open -e .env`

메모장에서 아래 값만 바꾸고 저장합니다. 나머지는 그대로 두세요.

```
PERPLEXITY_API_KEY="새로 발급한 키"
```

`.env`는 Git에 올라가지 않도록 막혀 있습니다. 키는 채팅이나 문서에 붙여넣지 마세요.

## 4. 실행

Windows:

```powershell
.venv\Scripts\python.exe -m scripts.run_live_briefing --company 써니웨이브텍 --website https://sunnywt.com/ --industry "산업용 무선통신 IoT"
```

Mac:

```bash
.venv/bin/python -m scripts.run_live_briefing --company 써니웨이브텍 --website https://sunnywt.com/ --industry "산업용 무선통신 IoT"
```

- 이 스크립트는 `.env`의 `PIPELINE_MODE`와 상관없이 항상 실제 모드로 돈다.
- GPT 호출이 5번(P1~P5) 있어서 3~10분 정도 걸릴 수 있습니다.
- 끝나면 텔레그램 답장 미리보기가 화면에 나오고, 전체 결과가 `output\briefing_날짜.json`에 저장됩니다.
- 내 영업 템플릿 기본값은 "법인 모빌리티 / 신차 장기렌터카 / 취득세 절감·손비 처리"입니다. 바꾸려면 `--category`, `--product`, `--value-props`를 지정합니다. ID 목록은 `app/data/sales_templates.json`에 있습니다.

## 5. 문제 해결

화면에 나온 메시지별로 아래 순서대로 확인하세요.

1. "PERPLEXITY_API_KEY가 비어 있습니다"
   - 원인: `.env`가 없거나, 다른 폴더에서 실행했습니다.
   - 확인: `dir .env`(Mac: `ls .env`)로 파일이 있는지 봅니다.
   - 해결: 3단계를 다시 하고, 프로젝트 폴더에서 실행합니다.
2. "'codex' 명령을 찾을 수 없습니다"
   - 원인: Codex CLI가 설치된 터미널이 아니거나, PATH에 등록되지 않았습니다.
   - 확인: 같은 창에서 `codex --version`을 실행합니다.
   - 해결: Codex가 동작하는 터미널에서 실행합니다. 경로가 다르면 `.env`의 `CODEX_COMMAND`에 전체 경로를 적습니다.
3. "Codex CLI 로그인이 필요합니다"
   - 해결: `codex login`을 실행한 뒤 다시 시도합니다.
4. `[PROVIDER_ERROR]` 또는 모델 관련 오류
   - 원인: Codex가 `gpt-6-luna`라는 모델 이름을 인식하지 못할 수 있습니다.
   - 해결: `.env`에서 `CODEX_MODEL=""`로 비우면 Codex에 설정된 기본 모델을 씁니다.
5. `[INVALID_CITATION]`
   - 의미: GPT가 확인되지 않은 근거를 인용했거나, 서버가 만든 가설을 고쳐 썼습니다. 서버가 일부러 막은 것입니다.
   - 해결: 다시 한 번 실행해 봅니다. 반복되면 `output` 폴더 결과와 화면 메시지를 Claude에게 전달해 주세요.
6. "확인된 출처 0건"
   - 원인: 검색 결과 페이지를 가져오지 못했습니다. 회사망·보안 프로그램이 HTTPS를 중계하는 경우입니다.
   - 해결: 회사망 관리자에게 받은 CA 파일 경로를 `.env`의 `RAW_FETCH_CA_BUNDLE`에 적습니다. 집 인터넷이면 보통 해당하지 않습니다.

## 참고: 클라우드 세션에서 미리 확인한 결과 (2026-10-10)

- Perplexity 검색 30건 중 원문과 글자 그대로 맞은 사실 5건이 확정됐습니다. 이 단계에는 GPT가 쓰이지 않습니다.
- 대표 사례: ZDNet 기사 "써니웨이브텍은 … 함부르크 'SMM 2026'에서 스웨덴 콘실리움 세이프티 그룹과 무선 선박안전 시스템 공동개발을 위한 업무협약을 체결했다고 밝혔다"
- 산업 근거 중 일부는 2018년 기사여서 오래됐습니다. 산업 트렌드 질문(Q2)의 최신성은 결과를 보고 판단해야 합니다.
