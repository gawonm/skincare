"""LLM이 제안한 RAG 경로를 실행 전에 결정적 규칙으로 검증한다."""

from enum import StrEnum

from pydantic import Field

from agent.schemas import AgentModel, Intent, ParsedRequest, RagRoute


class RagRouteReason(StrEnum):
    CONCERN_DISCOVERY = "concern_discovery"
    NORMALIZED_PRODUCT_DISCOVERY = "normalized_product_discovery"
    UNCONSTRAINED_DISCOVERY = "unconstrained_discovery"
    EXPLICIT_EVIDENCE_REQUEST = "explicit_evidence_request"
    EXPLICIT_INGREDIENT_PRODUCT = "explicit_ingredient_product"
    PRODUCT_FILTER_ONLY = "product_filter_only"
    NO_RAG_TASK = "no_rag_task"


class ProductDiscoveryCue(StrEnum):
    WHAT_TO_USE = "뭘 써"
    WHAT_USE = "뭐 써"
    WHAT_SHOULD_I_USE = "무엇을 써"
    WHAT_TO_APPLY = "뭘 발라"
    WHAT_APPLY = "뭐 발라"
    WHAT_SHOULD_I_APPLY = "무엇을 발라"
    WHICH_INGREDIENT = "어떤 성분"
    RECOMMEND = "추천"


class RagRouteDecision(AgentModel):
    route: RagRoute | None = None
    reason: RagRouteReason
    normalized_intents: list[Intent] = Field(min_length=1)
    normalized_skin_concerns: list[str] = Field(default_factory=list)


class RagRoutePolicy:
    """LLM 누락이 사용자 사례만으로 상품을 추천하는 우회 경로가 되지 않게 한다."""

    def decide(self, request: ParsedRequest) -> RagRouteDecision:
        concerns = list(dict.fromkeys(request.skin_concerns))
        intents = list(dict.fromkeys(request.intents))
        has_ingredients = bool(request.ingredient_mentions)
        has_product_filters = bool(
            any((request.category, request.texture, request.skin_feel))
            or request.unsupported_product_conditions
            or request.referenced_candidate_number is not None
        )
        normalized_product_discovery = (
            not has_ingredients and self._has_product_discovery_cue(request.query)
        )
        if normalized_product_discovery:
            # 무엇을 사용할지 묻는 요청은 근거 설명이 아니라 후보 탐색이므로 실행 Intent도 보정한다.
            intents = [intent for intent in intents if intent is not Intent.EVIDENCE_QA]
            if Intent.PRODUCT_DISCOVERY not in intents:
                intents.append(Intent.PRODUCT_DISCOVERY)

        product_requested = Intent.PRODUCT_DISCOVERY in intents
        evidence_requested = Intent.EVIDENCE_QA in intents

        if product_requested and not has_ingredients:
            if concerns or request.rag_route is RagRoute.CLAIM_THEN_EVIDENCE:
                return RagRouteDecision(
                    route=RagRoute.CLAIM_THEN_EVIDENCE,
                    reason=(
                        RagRouteReason.NORMALIZED_PRODUCT_DISCOVERY
                        if normalized_product_discovery
                        else RagRouteReason.CONCERN_DISCOVERY
                    ),
                    normalized_intents=intents,
                    normalized_skin_concerns=concerns,
                )
            if not has_product_filters:
                # 아무 탐색 기준도 없는데 상품부터 조회하면 LLM의 암묵적 추측이 추천 조건이 된다.
                return RagRouteDecision(
                    route=RagRoute.CLAIM_THEN_EVIDENCE,
                    reason=(
                        RagRouteReason.NORMALIZED_PRODUCT_DISCOVERY
                        if normalized_product_discovery
                        else RagRouteReason.UNCONSTRAINED_DISCOVERY
                    ),
                    normalized_intents=intents,
                )
            return RagRouteDecision(
                reason=RagRouteReason.PRODUCT_FILTER_ONLY,
                normalized_intents=intents,
            )

        if evidence_requested:
            return RagRouteDecision(
                route=RagRoute.EVIDENCE_ONLY,
                reason=RagRouteReason.EXPLICIT_EVIDENCE_REQUEST,
                normalized_intents=intents,
                normalized_skin_concerns=concerns,
            )

        if product_requested and has_ingredients:
            return RagRouteDecision(
                reason=RagRouteReason.EXPLICIT_INGREDIENT_PRODUCT,
                normalized_intents=intents,
            )

        return RagRouteDecision(
            reason=RagRouteReason.NO_RAG_TASK,
            normalized_intents=intents,
        )

    def _has_product_discovery_cue(self, query: str) -> bool:
        normalized_query = " ".join(query.casefold().split())
        return any(cue.value in normalized_query for cue in ProductDiscoveryCue)
