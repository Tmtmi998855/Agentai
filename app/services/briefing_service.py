from app.domain.models import BriefingObject, DemandHypothesisDraft, EvidencePack
from app.core.exceptions import CitationIntegrityException


class BriefingService:
    """Service layer for Briefing validation and business logic."""

    @staticmethod
    def validate_briefing_citations(briefing: BriefingObject) -> None:
        """
        Ensures all cited evidence_ids in snapshot, small_talk, and demand_hypotheses
        actually exist in the sources.
        """
        invalid_citations = briefing.validate_citations()
        if invalid_citations:
            raise CitationIntegrityException(
                message=f"Found {len(invalid_citations)} invalid citation(s)",
                detail={"invalid_citations": invalid_citations}
            )

    @staticmethod
    def verify_hypothesis_evidence_binding(
        hypothesis: DemandHypothesisDraft,
        evidence_pack: EvidencePack
    ) -> bool:
        """Verifies that all supporting and contradicting evidence exist in the EvidencePack."""
        valid_ids = evidence_pack.get_evidence_ids()
        for eid in hypothesis.supporting_evidence:
            if eid not in valid_ids:
                return False
        for eid in hypothesis.contradicting_evidence:
            if eid not in valid_ids:
                return False
        return True
