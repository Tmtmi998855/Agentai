"""live 모드 구성요소: Codex CLI 공급자, 원문 대조 사실 확인, live 오케스트레이터 경로."""

import os
import stat
import sys

import pytest

from app.domain.job_models import BriefingCreateRequest
from app.domain.models import Evidence
from app.domain.sales_templates import SalesTemplateSelection
from app.domain.search_models import RawSearchItem, SearchRequest, SearchResult
from app.providers.codex_cli import CodexCliReasoningProvider, extract_json_object
from app.services.live_verification import candidate_sentences, confirm_from_raw_excerpt, website_domain
from app.services.web_raw_fetcher import RawFetchResult
from app.services.orchestrator import BriefingOrchestrator

TEMPLATE = SalesTemplateSelection(
    category_id="mobility", product_id="long_term_rental", value_prop_ids=["mobility_expense"]
)


# ---------- Codex CLI 공급자 ----------

def test_extract_json_object_handles_fences_and_noise():
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object("결과입니다: {\"a\": {\"b\": 2}} 끝") == {"a": {"b": 2}}
    assert extract_json_object("JSON 없음") is None
    assert extract_json_object("[1, 2]") is None


def test_codex_args_are_sandboxed_and_read_prompt_from_stdin(tmp_path):
    provider = CodexCliReasoningProvider(default_model="gpt-6-luna")
    args = provider.build_args("/usr/bin/codex", "gpt-6-luna", tmp_path / "out.txt")
    assert args[:2] == ["/usr/bin/codex", "exec"]
    assert ["--sandbox", "read-only"] == args[2:4]
    assert "--ephemeral" in args and "--skip-git-repo-check" in args
    assert args[args.index("--model") + 1] == "gpt-6-luna"
    assert args[-1] == "-"


def _fake_codex(tmp_path, body: str) -> str:
    """-o 경로에 응답을 쓰는 가짜 codex 실행 파일."""
    script = tmp_path / "codex"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "sys.stdin.read()\n"
        "out = sys.argv[sys.argv.index('-o') + 1]\n"
        f"open(out, 'w', encoding='utf-8').write({body!r})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.mark.skipif(os.name == "nt", reason="POSIX 실행 파일 기반 테스트")
async def test_codex_provider_parses_structured_output(tmp_path):
    exe = _fake_codex(tmp_path, '응답:\n{"status": "SUCCESS", "drafts": []}')
    provider = CodexCliReasoningProvider(command=exe, timeout_s=30)
    result = await provider.generate_structured(
        task="p3", messages=[{"role": "user", "content": "x"}], response_schema={}, model="mock-model"
    )
    assert result.success and result.structured_data == {"status": "SUCCESS", "drafts": []}
    assert result.actual_model == "gpt-6-luna"


@pytest.mark.skipif(os.name == "nt", reason="POSIX 실행 파일 기반 테스트")
async def test_codex_provider_reports_invalid_json(tmp_path):
    provider = CodexCliReasoningProvider(command=_fake_codex(tmp_path, "모르겠습니다"), timeout_s=30)
    result = await provider.generate_structured(task="p3", messages=[], response_schema={})
    assert not result.success and result.error_code == "PROVIDER_INVALID_JSON"


async def test_codex_provider_missing_command():
    provider = CodexCliReasoningProvider(command="definitely-not-installed-codex")
    result = await provider.generate_structured(task="p1", messages=[], response_schema={})
    assert not result.success and "찾을 수 없습니다" in result.error


# ---------- 원문 대조 사실 확인 ----------

def _raw_verified(claim: str, raw: str) -> Evidence:
    ev = Evidence(evidence_id="E01", claim=claim, publisher="ZDNet", url="https://zdnet.co.kr/a", source_tier="B")
    ev.verify_raw(raw)
    return ev


def test_confirms_only_sentence_present_in_raw_page():
    ev = _raw_verified(
        "선박 철판으로 통신. 써니웨이브텍은 SMM 2026에서 업무협약을 체결했다고 밝혔다. 검색엔진이 요약한 문장입니다 추가 내용",
        "기사 본문 써니웨이브텍은 SMM 2026에서 업무협약을 체결했다고 밝혔다. 이하 생략",
    )
    assert confirm_from_raw_excerpt(ev)
    assert ev.verification_record.target_claim == "써니웨이브텍은 SMM 2026에서 업무협약을 체결했다고 밝혔다"


def test_paraphrased_snippet_is_not_confirmed():
    ev = _raw_verified("요약된 문장으로 원문과 글자가 다른 스니펫입니다", "원문에는 전혀 다른 문장이 들어 있습니다 정말로")
    assert not confirm_from_raw_excerpt(ev)
    assert not ev.is_confirmed_fact


def test_boilerplate_and_list_numbers_are_ignored():
    ev = _raw_verified("x", "y")
    ev.claim = "JOB 1 페이지. Views Date There are no posts. 13 자기장통신 제품, 국가 테스트베드 기술마켓 등록 완료!"
    candidates = candidate_sentences(ev)
    assert "자기장통신 제품, 국가 테스트베드 기술마켓 등록 완료!" in candidates
    assert not any("no posts" in c for c in candidates)


def test_website_domain():
    assert website_domain("https://www.sunnywt.com/") == "sunnywt.com"
    assert website_domain(None) is None


# ---------- live 오케스트레이터 ----------

class FakeSearch:
    def __init__(self, items):
        self.items = items
        self.requests: list[SearchRequest] = []

    async def search(self, request: SearchRequest) -> SearchResult:
        self.requests.append(request)
        return SearchResult(provider="fake", query="q", items=self.items, total_count=len(self.items))


class FakeFetcher:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    async def fetch_and_verify_evidence(self, evidence):
        page = self.pages.get(evidence.url)
        if page is None:
            return RawFetchResult(url=evidence.url, status_code=404, success=False)
        evidence.verify_raw(page)
        return RawFetchResult(url=evidence.url, status_code=200, success=True, extracted_text=page)


async def test_live_orchestrator_uses_real_search_and_raw_pages():
    company_sentence = "써니웨이브텍은 함부르크 SMM 2026에서 무선 선박안전 시스템 업무협약을 체결했다"
    industry_sentence = "산업용 IoT 현장에서는 금속 차폐 공간의 통신 음영이 공통 과제로 꼽힌다"
    request = BriefingCreateRequest.from_template(
        "써니웨이브텍", TEMPLATE, target_industry="산업용 무선통신", company_website="https://sunnywt.com/"
    )
    # 산업 쿼리는 서버가 만든 문자열과 같아야 scope 태깅이 된다.
    from app.services.dual_research import build_industry_queries
    industry_query = build_industry_queries("산업용 무선통신")[0].query
    items = [
        RawSearchItem(query="써니웨이브텍 뉴스", title="선박 철판으로 통신", snippet=company_sentence + ".",
                      url="https://zdnet.co.kr/view?no=1", publisher="ZDNet"),
        RawSearchItem(query=industry_query, title="산업용 IoT 동향", snippet=industry_sentence + ".",
                      url="https://zdnet.co.kr/view?no=2", publisher="ZDNet"),
        RawSearchItem(query="써니웨이브텍 뉴스", title="원문 없는 기사", snippet="원문을 가져올 수 없는 기사 문장입니다.",
                      url="https://zdnet.co.kr/view?no=3", publisher="ZDNet"),
    ]
    search = FakeSearch(items)
    fetcher = FakeFetcher({
        "https://zdnet.co.kr/view?no=1": f"본문 {company_sentence}. 끝",
        "https://zdnet.co.kr/view?no=2": f"본문 {industry_sentence}. 끝",
    })
    briefing = await BriefingOrchestrator(search_provider=search, live=True, live_fetcher=fetcher).execute_pipeline(request)

    assert any(q.query == industry_query for q in search.requests[0].queries)
    claims = {s.claim: s.scope for s in briefing.sources}
    assert claims == {company_sentence: "COMPANY", industry_sentence: "INDUSTRY"}
    assert briefing.strategic_questions is not None
    # 추론은 테스트용 Mock이라 P4 경고문이 섞일 수 있으나, 홈페이지를 줬으므로 동명 기업 경고는 없어야 한다.
    assert not any("홈페이지 미입력" in w for w in briefing.warnings)


async def test_live_orchestrator_warns_without_website():
    request = BriefingCreateRequest.from_template("써니웨이브텍", TEMPLATE)
    briefing = await BriefingOrchestrator(
        search_provider=FakeSearch([]), live=True, live_fetcher=FakeFetcher({})
    ).execute_pipeline(request)
    assert any("홈페이지 미입력" in w for w in briefing.warnings)
