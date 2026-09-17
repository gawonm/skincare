"""LLM이 제안한 RAG 경로를 실행 전에 결정적 규칙으로 검증한다."""

from enum import StrEnum

from pydantic import Field

from agent.schemas import AgentModel, Intent, ParsedRequest, RagRoute


class RagRouteReason(StrEnum):
    CONCERN_DISCOVERY = "concern_discovery"
    UNCONSTRAINED_DISCOVERY = "unconstrained_discovery"
    EXPLICIT_EVIDENCE_REQUEST = "explicit_evidence_request"
    EXPLICIT_INGREDIENT_PRODUCT = "explicit_ingredient_product"
    PRODUCT_FILTER_ONLY = "product_filter_only"
    NO_RAG_TASK = "no_rag_task"


class RagRouteDecision(AgentModel):
    route: RagRoute | None = None
    reason: RagRouteReason
    normalized_skin_concerns: list[str] = Field(default_factory=list)


class RagRoutePolicy:
    """LLM 누락이 사용자 사례만으로 상품을 추천하는 우회 경로가 되지 않게 한다."""

    def decide(self, request: ParsedRequest) -> RagRouteDecision:
        concerns = list(dict.fromkeys(request.skin_concerns))
        product_requested = Intent.PRODUCT_DISCOVERY in request.intents
        evidence_requested = Intent.EVIDENCE_QA in request.intents
        has_ingredients = bool(request.ingredient_mentions)
        has_product_filters = any((request.category, request.texture, request.skin_feel))

        if product_requested and not has_ingredients:
            if concerns or request.rag_route is RagRoute.CLAIM_THEN_EVIDENCE:
                return RagRouteDecision(
                    route=RagRoute.CLAIM_THEN_EVIDENCE,
                    reason=RagRouteReason.CONCERN_DISCOVERY,
                    normalized_skin_concerns=concerns,
                )
            if not has_product_filters:
                # 아무 탐색 기준도 없는데 상품부터 조회하면 LLM의 암묵적 추측이 추천 조건이 된다.
                return RagRouteDecision(
                    route=RagRoute.CLAIM_THEN_EVIDENCE,
                    reason=RagRouteReason.UNCONSTRAINED_DISCOVERY,
                )
            return RagRouteDecision(reason=RagRouteReason.PRODUCT_FILTER_ONLY)

        if evidence_requested:
            return RagRouteDecision(
                route=RagRoute.EVIDENCE_ONLY,
                reason=RagRouteReason.EXPLICIT_EVIDENCE_REQUEST,
                normalized_skin_concerns=concerns,
            )

        if product_requested and has_ingredients:
            return RagRouteDecision(reason=RagRouteReason.EXPLICIT_INGREDIENT_PRODUCT)

        return RagRouteDecision(reason=RagRouteReason.NO_RAG_TASK)
