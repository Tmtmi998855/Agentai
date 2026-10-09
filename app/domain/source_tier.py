from urllib.parse import urlparse
from typing import Literal
from app.domain.models import StrictBaseModel

SourceTier = Literal["A", "B", "C", "REVIEW_REQUIRED"]


class SourceTierResult(StrictBaseModel):
    """Result of source tier classification containing rule details."""
    tier: SourceTier
    rule_id: str
    reason: str
    requires_manual_review: bool = False


# Public Regulatory and Government Domains (Tier A)
TIER_A_REGULATORY_DOMAINS = {
    "dart.fss.or.kr",
    "kind.krx.co.kr",
    "korea.kr",
    "fss.or.kr",
    "krx.co.kr",
    "ftc.go.kr",
    "moel.go.kr",
    "nts.go.kr",
    "kisa.or.kr",
}

# Mainstream Verified News & Media (Tier B)
TIER_B_DOMAINS = {
    "yna.co.kr",
    "mk.co.kr",
    "hankyung.com",
    "chosun.com",
    "donga.com",
    "joongang.co.kr",
    "etnews.com",
    "sedaily.com",
    "bloter.net",
    "zdnet.co.kr",
    "mt.co.kr",
    "moneytoday.co.kr",
    "edaily.co.kr",
    "newsis.com",
    "reuters.com",
    "bloomberg.com",
}

# UGC and Blogs (Tier C)
TIER_C_DOMAINS = {
    "blog.naver.com",
    "tistory.com",
    "brunch.co.kr",
    "velog.io",
    "medium.com",
    "post.naver.com",
    "cafe.naver.com",
    "cafe.daum.net",
}


def classify_source_tier(
    url: str,
    publisher: str | None = None,
    confirmed_official_domains: set[str] | list[str] | None = None
) -> SourceTierResult:
    """
    Classifies a URL into Source Tier A, B, C, or REVIEW_REQUIRED.
    
    Tier A is ONLY granted if:
    1. The domain is a verified government/regulatory domain (e.g. dart.fss.or.kr, .go.kr), OR
    2. The domain EXACTLY matches the company's verified official domain in confirmed_official_domains.
    Simply containing the company name or '.com' does NOT grant Tier A.
    """
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
    except Exception:
        return SourceTierResult(
            tier="REVIEW_REQUIRED",
            rule_id="RULE_MALFORMED_URL",
            reason=f"Invalid URL structure: {url}",
            requires_manual_review=True,
        )

    if not hostname:
        return SourceTierResult(
            tier="REVIEW_REQUIRED",
            rule_id="RULE_EMPTY_HOSTNAME",
            reason="Missing hostname in URL",
            requires_manual_review=True,
        )

    # 1. Government & Regulatory Domains (Tier A)
    if hostname.endswith(".go.kr") or hostname.endswith(".gov") or hostname.endswith(".re.kr"):
        return SourceTierResult(
            tier="A",
            rule_id="RULE_GOV_PUBLIC_DOMAIN",
            reason=f"Government or public research domain: {hostname}",
            requires_manual_review=False,
        )

    for domain in TIER_A_REGULATORY_DOMAINS:
        if hostname == domain or hostname.endswith("." + domain):
            return SourceTierResult(
                tier="A",
                rule_id="RULE_TIER_A_OFFICIAL_DOMAIN",
                reason=f"Official regulatory / disclosure domain: {domain}",
                requires_manual_review=False,
            )

    # 2. Confirmed Official Corporate Domain (Tier A)
    if confirmed_official_domains:
        normalized_official = set()
        for d in confirmed_official_domains:
            if not d:
                continue
            clean_d = d.lower().strip()
            if clean_d.startswith("http://"):
                clean_d = clean_d[7:]
            elif clean_d.startswith("https://"):
                clean_d = clean_d[8:]
            clean_d = clean_d.split("/")[0].split(":")[0]
            normalized_official.add(clean_d)

        for off_domain in normalized_official:
            if hostname == off_domain or hostname.endswith("." + off_domain):
                return SourceTierResult(
                    tier="A",
                    rule_id="RULE_CONFIRMED_CORP_DOMAIN",
                    reason=f"Matches verified company official domain: {off_domain}",
                    requires_manual_review=False,
                )

    # 3. Mainstream News & Press (Tier B)
    for domain in TIER_B_DOMAINS:
        if hostname == domain or hostname.endswith("." + domain):
            return SourceTierResult(
                tier="B",
                rule_id="RULE_TIER_B_MAINSTREAM_NEWS",
                reason=f"Major mainstream news publisher: {domain}",
                requires_manual_review=False,
            )

    # 4. Blog & User Generated Content (Tier C)
    for domain in TIER_C_DOMAINS:
        if hostname == domain or hostname.endswith("." + domain):
            return SourceTierResult(
                tier="C",
                rule_id="RULE_TIER_C_UGC_BLOG",
                reason=f"Blog or user generated content platform: {domain}",
                requires_manual_review=False,
            )

    # 5. Unclassified Domain Fallback (Tier C + Manual Review Flag)
    return SourceTierResult(
        tier="C",
        rule_id="RULE_UNVERIFIED_DOMAIN_FALLBACK",
        reason=f"Unverified external domain ({hostname}) - not eligible for Tier A",
        requires_manual_review=True,
    )
