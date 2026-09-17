"""NIA statement를 Claim RAG index에 넣을지 결정하는 정책. `review_queue`(사람이 볼
사유 목록)와 ingestion 가부는 서로 다른 축이다 — review_queue에 들어간 것 중 상당수는
그대로 ingestible이어야 한다(예: ingredient unresolved도 raw_name으로 free-text 검색은
가능하다). 이 모듈은 "왜 review 대상인가"가 아니라 "지금 바로 Claim RAG에 써도 되는가"
만 판단한다.

판단 기준(사용자 지정):

    annotation_status == rejected  → BLOCKED
    semantic verdict == mismatch   → BLOCKED
    semantic verdict == low_confidence
      또는 span 복원 신뢰도가 fuzzy → HUMAN_REVIEW (ingest 보류)
    나머지                          → ingredient_id 있으면 STRUCTURED,
                                       없으면 FREE_TEXT anchor로 ingest 가능

ingredient unresolved/reference unverified/parser의 soft warning은 여기서 아예
blocking 조건으로 취급하지 않는다 — non-blocking 품질 메타데이터일 뿐이다.
"""

from enum import StrEnum

CORE_STATEMENT_TYPES = frozenset(
    {"case_observation", "ingredient_effect_claim", "precaution", "usage_instruction"}
)
SECONDARY_STATEMENT_TYPES = frozenset({"cause_claim", "contextual_factor", "combination_claim"})


class NiaClaimIngestionDecision(StrEnum):
    BLOCKED = "blocked"
    HUMAN_REVIEW = "human_review"
    INGESTIBLE_STRUCTURED = "ingestible_structured"
    INGESTIBLE_FREE_TEXT = "ingestible_free_text"


class NiaClaimPriority(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class NiaClaimIngestionPolicy:
    def decide(
        self,
        statement: dict,
        *,
        semantic_verdict: str,
        has_low_confidence_span: bool,
    ) -> NiaClaimIngestionDecision:
        if statement["annotation_status"] == "rejected":
            return NiaClaimIngestionDecision.BLOCKED
        if semantic_verdict == "mismatch":
            return NiaClaimIngestionDecision.BLOCKED
        if semantic_verdict == "low_confidence" or has_low_confidence_span:
            return NiaClaimIngestionDecision.HUMAN_REVIEW
        if self._has_matched_ingredient(statement):
            return NiaClaimIngestionDecision.INGESTIBLE_STRUCTURED
        return NiaClaimIngestionDecision.INGESTIBLE_FREE_TEXT

    def priority(self, statement: dict) -> NiaClaimPriority:
        if statement["statement_type"] in CORE_STATEMENT_TYPES:
            return NiaClaimPriority.PRIMARY
        return NiaClaimPriority.SECONDARY

    def _has_matched_ingredient(self, statement: dict) -> bool:
        stype = statement["statement_type"]
        if stype == "ingredient_effect_claim":
            return statement["subject"]["matching_status"] == "matched"
        if stype == "combination_claim":
            return any(s["matching_status"] == "matched" for s in statement["subjects"])
        return False
