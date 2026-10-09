from datetime import datetime, timezone
import re
import hashlib
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from typing import Any

from app.domain.models import Evidence, EvidenceExclusion, EvidencePack, current_iso_time
from app.domain.search_models import RawSearchItem
from app.domain.source_tier import classify_source_tier, SourceTier


TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "ref", "s", "ncid", "rss"
}


class EvidenceBuilder:
    """Service to process RawSearchItems into validated, deduplicated, and Tier-classified EvidencePack."""

    @staticmethod
    def build_evidences(
        company_name: str,
        raw_items: list[RawSearchItem],
        confirmed_official_domains: set[str] | list[str] | None = None
    ) -> EvidencePack:
        evidences: list[Evidence] = []
        excluded_items: list[EvidenceExclusion] = []
        seen_normalized_urls: set[str] = set()
        topic_groups: dict[str, str] = {}  # topic_hash -> duplicate_group_id
        evidence_counter = 1

        for item in raw_items:
            raw_url = item.url
            clean_url = EvidenceBuilder._normalize_url(raw_url)
            if not clean_url:
                reason = "URL_MISSING" if not raw_url or not raw_url.strip() else "URL_INVALID"
                excluded_items.append(EvidenceExclusion(item_id=item.item_id, reason=reason))
                continue

            # E-4: Deduplicate exact same normalized URL
            if clean_url in seen_normalized_urls:
                continue

            # Claim Sanitization
            claim_text = EvidenceBuilder._extract_clean_claim(item.title, item.snippet)
            if not claim_text:
                continue

            # E-5: Grouping duplicate/syndicated topics across independent sources
            topic_key = EvidenceBuilder._generate_topic_key(claim_text)
            if topic_key in topic_groups:
                group_id = topic_groups[topic_key]
            else:
                group_id = f"grp_{hashlib.md5(topic_key.encode()).hexdigest()[:8]}"
                topic_groups[topic_key] = group_id

            # Source Tier Classification (E-2 & Official domain rule)
            tier_result = classify_source_tier(
                url=clean_url,
                publisher=item.publisher,
                confirmed_official_domains=confirmed_official_domains
            )
            source_tier: SourceTier = tier_result.tier

            # Publisher Fallback
            publisher_name = item.publisher or EvidenceBuilder._extract_publisher_from_url(clean_url)

            # E-3: Published date validation - if unknown, keep None (DO NOT default to current date)
            published_date = EvidenceBuilder._validate_date(item.published_at)

            # Tags & Review Required Handling
            tags = ["검색수집"]
            if tier_result.requires_manual_review or source_tier == "REVIEW_REQUIRED":
                tags.append("REVIEW_REQUIRED")
                tags.append(f"rule:{tier_result.rule_id}")
                evidence_status = "REVIEW_REQUIRED"
            else:
                evidence_status = "CLASSIFIED"

            evidence_id = f"E{evidence_counter:02d}"
            evidence = Evidence(
                evidence_id=evidence_id,
                claim=claim_text,
                published_at=published_date,  # E-3: None if unconfirmed
                publisher=publisher_name,
                url=clean_url,  # E-4: Normalized URL
                raw_url=raw_url,  # E-4: Preserved raw URL for audit
                source_tier=source_tier,
                status=evidence_status,
                retrieved_at=item.retrieved_at or current_iso_time(),
                relevance_tags=tags,
                duplicate_group_id=group_id,  # E-5: Duplicate group ID for independent sources
            )

            evidences.append(evidence)
            seen_normalized_urls.add(clean_url)
            evidence_counter += 1

        return EvidencePack(
            company_name=company_name,
            evidences=evidences,
            excluded_items=excluded_items,
            retrieved_at=current_iso_time(),
        )

    @staticmethod
    def _normalize_url(url: str | None) -> str | None:
        """E-4: Normalizes HTTP/HTTPS URLs and strips tracking parameters (utm_*, gclid, fbclid, etc.)."""
        if not url:
            return None
        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return None

        try:
            parsed = urlparse(url)
            if not parsed.hostname:
                return None

            scheme = parsed.scheme.lower()
            netloc = parsed.hostname.lower()
            if parsed.port and parsed.port not in (80, 443):
                netloc = f"{netloc}:{parsed.port}"

            path = parsed.path or "/"
            if len(path) > 1 and path.endswith("/"):
                path = path.rstrip("/")

            # Filter out tracking query parameters
            query_params = parse_qs(parsed.query, keep_blank_values=False)
            filtered_params = {
                k: v for k, v in query_params.items()
                if k.lower() not in TRACKING_PARAMS
            }

            clean_query = urlencode(filtered_params, doseq=True) if filtered_params else ""
            clean_url = urlunparse((scheme, netloc, path, parsed.params, clean_query, ""))
            return clean_url
        except Exception:
            return None

    @staticmethod
    def _extract_clean_claim(title: str, snippet: str) -> str:
        text = f"{title}. {snippet}".strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) > 300:
            text = text[:297] + "..."
        return text

    @staticmethod
    def _extract_publisher_from_url(url: str) -> str:
        try:
            parsed = urlparse(url)
            return parsed.hostname or "출처미상"
        except Exception:
            return "출처미상"

    @staticmethod
    def _validate_date(date_str: str | None) -> str | None:
        """E-3: Validates and returns YYYY-MM-DD date format. Returns None if invalid or unconfirmed."""
        if not date_str:
            return None
        date_str = date_str.strip()
        match = re.search(r"\d{4}-\d{2}-\d{2}", date_str)
        if match:
            return match.group(0)
        return None

    @staticmethod
    def _generate_topic_key(claim_text: str) -> str:
        """Generates a simplified topic key for grouping independent news articles covering the same story."""
        words = re.findall(r"[가-힣a-zA-Z0-9]+", claim_text.lower())
        keywords = sorted(list(set([w for w in words if len(w) > 1])))[:5]
        return "_".join(keywords)
