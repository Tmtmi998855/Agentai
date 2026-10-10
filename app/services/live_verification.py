"""실제(live) 모드 전용: 기업 식별과 원문 대조 사실 확인.

사실 확인 원칙은 Mock과 같다 — 원문 페이지에 글자 그대로 있는 문장만 FACT_CONFIRMED가 된다.
검색 스니펫을 문장 단위로 나눠 원문에서 찾고, 찾은 문장을 그대로 claim으로 삼는다.
(검색엔진이 요약·변형한 문장은 원문에 없으므로 자동으로 탈락한다.)
"""

import re
from urllib.parse import urlparse

from app.domain.models import CompanyEntity, Evidence

MIN_SENTENCE_CHARS = 20
MIN_TITLE_CHARS = 12
_SPLIT = re.compile(r"(?<=[.!?。])\s+|\.{3}|…|\s[|·]\s")
_LEADING_INDEX = re.compile(r"^\d{1,4}\s+")
# 게시판·메뉴 문구처럼 원문에 있어도 '사실'이 아닌 문장 (짧은 문장에만 적용)
_BOILERPLATE = re.compile(
    r"no posts|there are no|views|list number|total \d+|등록된 게시물|게시물이 없|로그인|copyright|all rights reserved",
    re.IGNORECASE,
)
BOILERPLATE_MAX_CHARS = 60


def is_meaningful(sentence: str) -> bool:
    if len(sentence) < BOILERPLATE_MAX_CHARS and _BOILERPLATE.search(sentence):
        return False
    letters = sum(ch.isalpha() for ch in sentence)
    return letters >= len(sentence) * 0.5


def website_domain(url: str | None) -> str | None:
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host or None


def build_live_company_entity(company_name: str, website: str | None, industry: str | None) -> CompanyEntity:
    """홈페이지를 사용자가 직접 준 경우에만 HIGH. 없으면 동명 기업 위험을 경고로 남긴다(호출부)."""
    return CompanyEntity(
        name=company_name,
        resolved_name=company_name,
        entity_confidence="HIGH",
        website=website,
        industry=industry,
    )


def candidate_sentences(evidence: Evidence, title: str | None = None) -> list[str]:
    text = evidence.claim
    pieces = [p.strip(" .\"'“”") for p in _SPLIT.split(text)]
    normalized = [_LEADING_INDEX.sub("", re.sub(r"\s+", " ", p)) for p in pieces]
    candidates = [p for p in normalized if len(p) >= MIN_SENTENCE_CHARS and is_meaningful(p)]
    if title and len(title.strip()) >= MIN_TITLE_CHARS and is_meaningful(title.strip()):
        candidates.append(re.sub(r"\s+", " ", title.strip()))
    # 긴 문장일수록 정보량이 많으므로 먼저 시도
    return sorted(set(candidates), key=len, reverse=True)


def confirm_from_raw_excerpt(evidence: Evidence, title: str | None = None) -> bool:
    """RAW_VERIFIED 근거에서 원문에 그대로 있는 가장 긴 문장으로 사실 확인. 성공 시 True."""
    raw = evidence.verified_raw_content
    if evidence.status != "RAW_VERIFIED" or not raw:
        return False
    for sentence in candidate_sentences(evidence, title):
        if sentence in raw:
            evidence.confirm_fact(
                target_claim=sentence,
                supporting_excerpt=sentence,
                verification_method="EXACT_EXCERPT_MATCH",
            )
            return evidence.is_confirmed_fact
    return False
