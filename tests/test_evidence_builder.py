import pytest
from app.domain.search_models import RawSearchItem
from app.domain.source_tier import classify_source_tier
from app.services.evidence_builder import EvidenceBuilder


def test_evidence_builder_transform():
    """Part G-9: RawSearchItem → Evidence 변환 및 상태 전이 검증."""
    raw = RawSearchItem(
        item_id="r1",
        query="테스트 쿼리",
        title="테스트기업 강남 사옥 이전 공시",
        snippet="테스트기업이 사옥 이전을 완료했습니다.",
        url="https://dart.fss.or.kr/example/001",
        publisher="금융감독원",
        published_at="2026-09-01"
    )

    pack = EvidenceBuilder.build_evidences("테스트기업", [raw])
    assert len(pack.evidences) == 1
    ev = pack.evidences[0]
    assert ev.claim.startswith("테스트기업 강남 사옥 이전 공시")
    assert ev.publisher == "금융감독원"
    assert ev.source_tier == "A"
    assert ev.status == "CLASSIFIED"
    # Crucial rule: source_tier A alone DOES NOT grant is_confirmed_fact=True!
    assert ev.is_confirmed_fact is False

    # Fact confirmation without the required verification data raises ValueError
    with pytest.raises(ValueError):
        ev.confirm_fact(
            target_claim=ev.claim,
            supporting_excerpt="원문 구절",
            verification_method="MANUAL_REVIEW",
        )

    # Fact confirmation explicitly matches an excerpt in verified raw content
    ev.verify_raw("테스트기업 강남 사옥 이전 공시 원문 텍스트 확인 완료")
    ev.confirm_fact(
        target_claim=ev.claim,
        supporting_excerpt="테스트기업 강남 사옥 이전 공시 원문 텍스트 확인 완료",
        verification_method="EXACT_EXCERPT_MATCH",
    )
    assert ev.status == "FACT_CONFIRMED"
    assert ev.is_confirmed_fact is True
    assert ev.verified_raw_content == "테스트기업 강남 사옥 이전 공시 원문 텍스트 확인 완료"
    assert ev.verified_at is not None


def test_malformed_url_blocked_from_evidence():
    """Part G-10: 잘못된 URL 차단."""
    raw_invalid = RawSearchItem(
        item_id="r_bad",
        query="쿼리",
        title="무효 URL 기사",
        snippet="스니펫",
        url="not-a-valid-http-url",
        publisher="무효"
    )

    pack = EvidenceBuilder.build_evidences("테스트기업", [raw_invalid])
    assert len(pack.evidences) == 0  # Dropped completely
    assert pack.excluded_items[0].reason == "URL_INVALID"


def test_missing_url_blocked_and_reason_recorded():
    raw_missing = RawSearchItem(
        item_id="r_missing",
        query="쿼리",
        title="URL 없는 검색결과",
        snippet="스니펫",
        url=None,
        publisher="출처미상",
    )

    pack = EvidenceBuilder.build_evidences("테스트기업", [raw_missing])

    assert pack.evidences == []
    assert [(item.item_id, item.reason) for item in pack.excluded_items] == [("r_missing", "URL_MISSING")]


def test_unconfirmed_published_at_remains_none():
    """Part G-11: 게시일 미확인 시 'None' (현재 날짜로 채우지 않음)."""
    raw_no_date = RawSearchItem(
        item_id="r_nodate",
        query="쿼리",
        title="게시일 없는 뉴스",
        snippet="스니펫 내용",
        url="https://www.mk.co.kr/news/123",
        publisher="매일경제",
        published_at=None  # Unconfirmed published date
    )

    pack = EvidenceBuilder.build_evidences("테스트기업", [raw_no_date])
    assert len(pack.evidences) == 1
    assert pack.evidences[0].published_at is None  # MUST remain None


def test_source_tier_classification_rules():
    """Part G-12: Source Tier A/B/C 분류."""
    res_gov = classify_source_tier("https://dart.fss.or.kr/dsaf001/main.do")
    assert res_gov.tier == "A"

    res_news = classify_source_tier("https://www.mk.co.kr/news/economy/12345")
    assert res_news.tier == "B"

    res_blog = classify_source_tier("https://blog.naver.com/myblog/2200000")
    assert res_blog.tier == "C"


def test_unconfirmed_domain_not_classified_as_tier_a():
    """Part G-13: 확인되지 않은 공식 도메인을 A로 분류하지 않음."""
    # Arbitrary .com site containing company name in URL
    unconfirmed_url = "https://hyundairental-fan-blog.com/news/1"

    # 1. Without confirmed_official_domains
    res1 = classify_source_tier(unconfirmed_url)
    assert res1.tier != "A"
    assert res1.tier == "C"

    # 2. With different confirmed_official_domains
    res2 = classify_source_tier(
        unconfirmed_url,
        confirmed_official_domains={"hyundairentalcare.co.kr"}
    )
    assert res2.tier != "A"

    # 3. Only exact confirmed domain gets Tier A
    res3 = classify_source_tier(
        "https://hyundairentalcare.co.kr/about/ir",
        confirmed_official_domains={"hyundairentalcare.co.kr"}
    )
    assert res3.tier == "A"
    assert res3.rule_id == "RULE_CONFIRMED_CORP_DOMAIN"


def test_duplicate_normalized_urls_deduplicated():
    """Part G-14: 동일 URL 중복 제거 & E-4 Tracking parameter stripping."""
    raw1 = RawSearchItem(
        item_id="r1",
        query="쿼리",
        title="기사 제목 1",
        snippet="스니펫 1",
        url="https://www.mk.co.kr/news/123?utm_source=naver&utm_medium=news",
        publisher="매일경제"
    )
    raw2 = RawSearchItem(
        item_id="r2",
        query="쿼리",
        title="기사 제목 2 (동일 기사, 다른 utm 파라미터)",
        snippet="스니펫 2",
        url="https://www.mk.co.kr/news/123?utm_source=facebook&fbclid=xyz",
        publisher="매일경제"
    )

    pack = EvidenceBuilder.build_evidences("테스트기업", [raw1, raw2])
    # Both URLs normalize to https://www.mk.co.kr/news/123 -> exactly 1 Evidence created
    assert len(pack.evidences) == 1
    assert pack.evidences[0].url == "https://www.mk.co.kr/news/123"
    assert pack.evidences[0].raw_url == "https://www.mk.co.kr/news/123?utm_source=naver&utm_medium=news"


def test_independent_sources_preserved_with_duplicate_group_id():
    """Part G-15: 서로 다른 독립 출처 보존 (duplicate_group_id로 연관 부여)."""
    # Same story reported by 2 independent publishers (매일경제 vs 연합뉴스)
    raw_mk = RawSearchItem(
        item_id="r_mk",
        query="쿼리",
        title="테스트기업 강남 사옥 이전 완료 발표",
        snippet="테스트기업이 강남 사옥으로 이전했습니다.",
        url="https://www.mk.co.kr/news/100",
        publisher="매일경제"
    )
    raw_yna = RawSearchItem(
        item_id="r_yna",
        query="쿼리",
        title="테스트기업 강남 사옥 이전 완료 발표",
        snippet="테스트기업이 강남 사옥으로 이전했습니다.",
        url="https://www.yna.co.kr/view/200",
        publisher="연합뉴스"
    )

    pack = EvidenceBuilder.build_evidences("테스트기업", [raw_mk, raw_yna])

    # Both independent sources are preserved!
    assert len(pack.evidences) == 2
    assert pack.evidences[0].publisher == "매일경제"
    assert pack.evidences[1].publisher == "연합뉴스"

    # Both share the same duplicate_group_id to group identical story
    assert pack.evidences[0].duplicate_group_id is not None
    assert pack.evidences[0].duplicate_group_id == pack.evidences[1].duplicate_group_id


def test_evidence_id_uniqueness():
    """Part G-16: evidence_id 결정성 및 유일성."""
    raw_items = [
        RawSearchItem(item_id=f"r{i}", query="q", title=f"제목 {i}", snippet=f"스니펫 {i}", url=f"https://example{i}.com/a", publisher="pub")
        for i in range(5)
    ]

    pack = EvidenceBuilder.build_evidences("테스트", raw_items)
    evidence_ids = [e.evidence_id for e in pack.evidences]

    assert len(evidence_ids) == 5
    assert len(set(evidence_ids)) == 5  # Completely unique!
    assert evidence_ids == ["E01", "E02", "E03", "E04", "E05"]
