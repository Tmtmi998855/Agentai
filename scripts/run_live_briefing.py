"""실제 데이터로 브리핑 1건을 만들어 보는 실행 스크립트.

사용 예 (프로젝트 폴더에서 실행):
    python -m scripts.run_live_briefing --company 써니웨이브텍 --website https://sunnywt.com/ --industry "산업용 무선통신 IoT"

하는 일
1. 사전 점검: Perplexity 키, Codex CLI 설치·로그인 여부
2. 실제 검색(Perplexity) → 원문 페이지 확인 → GPT-6 Luna(Codex CLI) 추론 → 질문 3선
3. 텔레그램 답장 미리보기를 화면에 출력하고, 전체 결과 JSON을 output/ 폴더에 저장
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# .env를 프로젝트 폴더 기준으로 읽게 하려고, 설정을 불러오기 전에 작업 폴더를 맞춘다.
os.chdir(ROOT)
# 이 스크립트는 '실제 실행' 전용이므로 .env에 mock으로 적혀 있어도 live로 고정한다.
os.environ["PIPELINE_MODE"] = "live"
os.environ.setdefault("REASONING_PROVIDER", "codex_cli")
os.environ.setdefault("SEARCH_PROVIDER", "perplexity")

from app.core.config import settings  # noqa: E402
from app.core.exceptions import AhThereException  # noqa: E402
from app.domain.job_models import BriefingCreateRequest  # noqa: E402
from app.domain.sales_templates import SalesTemplateSelection  # noqa: E402
from app.services.messenger_formatter import format_messenger_briefing  # noqa: E402
from app.services.orchestrator import create_orchestrator  # noqa: E402


def preflight() -> list[str]:
    """실행 전에 빠진 준비물을 한국어로 알려준다 (키 값 자체는 출력하지 않음)."""
    problems = []
    if settings.SEARCH_PROVIDER == "perplexity" and not settings.PERPLEXITY_API_KEY.get_secret_value():
        problems.append(".env의 PERPLEXITY_API_KEY가 비어 있습니다.")
    if settings.REASONING_PROVIDER == "codex_cli":
        exe = shutil.which(settings.CODEX_COMMAND)
        if exe is None:
            problems.append(f"'{settings.CODEX_COMMAND}' 명령을 찾을 수 없습니다. Codex CLI가 설치된 터미널에서 실행하세요.")
        else:
            status = subprocess.run([exe, "login", "status"], capture_output=True, text=True)
            if status.returncode != 0:
                problems.append("Codex CLI 로그인이 필요합니다. 터미널에서 'codex login'을 먼저 실행하세요.")
    return problems


async def main() -> int:
    parser = argparse.ArgumentParser(description="아데어 실제 브리핑 1건 실행")
    parser.add_argument("--company", required=True, help="고객사 이름")
    parser.add_argument("--website", help="고객사 홈페이지 (동명 기업 구분용, 권장)")
    parser.add_argument("--industry", help="고객사 산업 (산업 레벨 검색에 사용)")
    parser.add_argument("--category", default="mobility", help="내 영업 카테고리 ID")
    parser.add_argument("--product", default="long_term_rental", help="내 품목 ID")
    parser.add_argument("--value-props", default="mobility_acquisition_tax,mobility_expense",
                        help="내 소구점 ID (쉼표로 1~3개)")
    args = parser.parse_args()

    problems = preflight()
    if problems:
        print("실행 전 준비가 필요합니다:")
        for p in problems:
            print(f"  - {p}")
        return 1

    template = SalesTemplateSelection(
        category_id=args.category, product_id=args.product,
        value_prop_ids=[v.strip() for v in args.value_props.split(",") if v.strip()],
    )
    request = BriefingCreateRequest.from_template(
        args.company, template, target_industry=args.industry, company_website=args.website
    )

    print(f"[{datetime.now():%H:%M:%S}] '{args.company}' 실제 브리핑 생성 시작 (검색 → 원문 확인 → GPT 추론, 수 분 걸릴 수 있음)")
    try:
        briefing = await create_orchestrator().execute_pipeline(request)
    except AhThereException as exc:
        print(f"실패: [{exc.error_code}] {exc.message}")
        return 2

    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"briefing_{datetime.now():%Y%m%d_%H%M%S}.json"
    out_file.write_text(json.dumps(briefing.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 텔레그램 답장 미리보기 =====\n")
    print(format_messenger_briefing(briefing, report_url=None))
    print(f"\n상태: {briefing.status} / 확인된 출처 {len(briefing.sources)}건")
    print(f"전체 결과 저장: {out_file}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        # Windows 콘솔에서 한글이 깨지지 않게 UTF-8로 출력
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
