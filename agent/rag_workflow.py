"""Claim 탐색과 Evidence 검증을 분리한 LangGraph 노드 모음."""

from agent.claim_verification import ClaimEvidenceVerifier, IngredientRecommendationSelector
from agent.evidence_query_policy import EvidenceQueryPolicy
from agent.rag.claim_anchor_adapter import ClaimHitToEvidenceQueryAnchorAdapter
from agent.rag.claim_schemas import (
    ClaimBundle,
    ClaimIngestionDecision,
    ClaimIngredientMatchingStatus,
    ClaimSearchRequest,
    ClaimSearchResult,
    ClaimVerificationBundle,
    ClaimVerificationRequest,
    ClaimVerificationResult,
    ClaimVerificationStatus,
    UnresolvedClaimAnchor,
)
from agent.rag.pipeline import EvidencePipeline
from agent.rag.ports import ClaimRetriever
from agent.rag.schemas import (
    EvidenceConditions,
    EvidenceQueryAnchor,
    EvidenceSearchRequest,
    LookupStatus,
    ProductCandidate,
    ProductRecord,
)
from agent.rag_response import RagResponseAssembler
from agent.runtime import AgentRuntime
from agent.schemas import AgentState, ChatStatus, GraphNode, RagRoute


class RagWorkflowNodes:
    """2-Layer RAG의 단계별 상태 변경을 일반 작업 노드에서 격리한다."""

    _EVIDENCE_REFERENCES = ("이 성분", "그 성분", "해당 성분", "이 제품", "그 제품")

    def __init__(
        self,
        claim_retriever: ClaimRetriever,
        claim_annotation_version: str,
        evidence_pipeline: EvidencePipeline,
        response_assembler: RagResponseAssembler,
        runtime: AgentRuntime,
        query_policy: EvidenceQueryPolicy,
        claim_verifier: ClaimEvidenceVerifier,
        recommendation_selector: IngredientRecommendationSelector,
    ) -> None:
        self._claim_retriever = claim_retriever
        self._claim_annotation_version = claim_annotation_version
        self._claim_anchor_adapter = ClaimHitToEvidenceQueryAnchorAdapter()
        self._evidence_pipeline = evidence_pipeline
        self._response_assembler = response_assembler
        self._runtime = runtime
        self._query_policy = query_policy
        self._claim_verifier = claim_verifier
        self._recommendation_selector = recommendation_selector

    async def route_rag(self, state: AgentState) -> AgentState:
        parsed = self._runtime.require_parsed(state)
        # 기존 호출자가 rag_route를 아직 보내지 않아도 명시 성분 질의의 동작은 유지한다.
        state.rag_route = parsed.rag_route or RagRoute.EVIDENCE_ONLY
        self._runtime.record_node(state, GraphNode.ROUTE_RAG, "RAG 탐색 경로를 선택했습니다.")
        return state

    async def search_claims(self, state: AgentState) -> AgentState:
        parsed = self._runtime.require_parsed(state)
        if not self._runtime.reserve_tool_call(state, GraphNode.SEARCH_CLAIMS):
            return state
        result = await self._claim_retriever.search(
            ClaimSearchRequest(
                query=parsed.query,
                annotation_version=self._claim_annotation_version,
                skin_concerns=list(
                    dict.fromkeys(
                        parsed.skin_concerns
                        + [concern.value for concern in state.profile.concerns]
                    )
                ),
            )
        )
        self._validate_claim_result(result)
        state.claim_bundle = ClaimBundle(search=result)
        if result.status is LookupStatus.ERROR:
            self._runtime.add_tool_failure(state, result.error_message)
        self._runtime.record_node(state, GraphNode.SEARCH_CLAIMS, "탐색용 Claim 조회를 마쳤습니다.")
        return state

    async def resolve_claim_ingredients(self, state: AgentState) -> AgentState:
        bundle = state.claim_bundle
        if bundle is None or bundle.search.status is not LookupStatus.SUCCESS:
            self._runtime.record_node(
                state,
                GraphNode.RESOLVE_CLAIM_INGREDIENTS,
                "확정할 Claim 성분이 없어 식별 단계를 건너뛰었습니다.",
            )
            return state

        target_ids: list[str] = []
        evidence_anchors: list[EvidenceQueryAnchor] = []
        unresolved: list[UnresolvedClaimAnchor] = []
        request_id = self._runtime.require_turn(state).request_id
        for hit in bundle.search.hits:
            evidence_anchor = self._claim_anchor_adapter.adapt(hit, request_id=request_id)
            if evidence_anchor is not None:
                evidence_anchors.append(evidence_anchor)
                target_ids.extend(evidence_anchor.ingredient_refs)
            unresolved.extend(
                UnresolvedClaimAnchor(
                    statement_id=hit.statement_id,
                    raw_name=ingredient.raw_name or "성분명 미제공",
                )
                for ingredient in hit.ingredient_refs
                if ingredient.matching_status is not ClaimIngredientMatchingStatus.MATCHED
            )

        unique_target_ids = list(dict.fromkeys(target_ids))
        state.claim_bundle = bundle.model_copy(
            deep=True,
            update={
                "target_ids": unique_target_ids,
                "evidence_anchors": evidence_anchors,
                "unresolved_anchors": unresolved,
            },
        )
        state.resolved_entities = state.resolved_entities.model_copy(
            deep=True,
            update={
                "ingredient_ids": list(
                    dict.fromkeys(state.resolved_entities.ingredient_ids + unique_target_ids)
                )
            },
        )
        self._runtime.record_node(
            state,
            GraphNode.RESOLVE_CLAIM_INGREDIENTS,
            "Claim의 성분 표준 ID를 확정했습니다.",
        )
        return state

    async def verify_claims(self, state: AgentState) -> AgentState:
        bundle = state.claim_bundle
        if bundle is None or not bundle.evidence_anchors:
            state.claim_verification_bundle = ClaimVerificationBundle()
            self._runtime.record_node(
                state,
                GraphNode.VERIFY_CLAIMS,
                "Evidence로 확인할 Claim 대상이 없어 검증 단계를 건너뛰었습니다.",
            )
            return state

        parsed = self._runtime.require_parsed(state)
        results: list[ClaimVerificationResult] = []
        for anchor in bundle.evidence_anchors:
            if not self._runtime.reserve_tool_call(state, GraphNode.VERIFY_CLAIMS):
                break
            result = await self._claim_verifier.verify(
                ClaimVerificationRequest(
                    anchor=anchor,
                    known_conditions=parsed.known_conditions,
                )
            )
            results.append(result)
            if result.status is ClaimVerificationStatus.ERROR:
                self._runtime.add_tool_failure(state, "; ".join(result.reasons))

        state.claim_verification_bundle = ClaimVerificationBundle(results=results)
        self._runtime.record_node(
            state,
            GraphNode.VERIFY_CLAIMS,
            "Claim별 공인 Evidence 확인을 마쳤습니다.",
        )
        return state

    async def build_recommendation_candidates(self, state: AgentState) -> AgentState:
        verification = state.claim_verification_bundle or ClaimVerificationBundle()
        state.recommendation_ingredients = self._recommendation_selector.select(verification)
        self._runtime.record_node(
            state,
            GraphNode.BUILD_RECOMMENDATION_CANDIDATES,
            "Evidence 상태에 따라 추천 성분 후보를 분류했습니다.",
        )
        return state

    async def search_evidence(self, state: AgentState) -> AgentState:
        parsed = self._runtime.require_parsed(state)
        if self._query_policy.has_lookup_failure(state):
            self._runtime.record_node(
                state,
                GraphNode.SEARCH_EVIDENCE,
                "앞 단계 조회 실패로 Evidence 검증을 건너뛰었습니다.",
            )
            return state
        if (
            state.rag_route is RagRoute.CLAIM_THEN_EVIDENCE
            and (state.claim_bundle is None or not state.claim_bundle.target_ids)
        ):
            self._runtime.record_node(
                state,
                GraphNode.SEARCH_EVIDENCE,
                "Claim에서 검증할 성분 ID를 확정하지 못했습니다.",
            )
            return state
        if not self._runtime.reserve_tool_call(state, GraphNode.SEARCH_EVIDENCE):
            return state

        products = self._evidence_products(state)
        target_ids = list(
            dict.fromkeys(
                state.resolved_entities.ingredient_ids
                + [product.product_id for product in products]
                + [ingredient for product in products for ingredient in product.ingredient_ids]
            )
        )
        combination_target_ids = (
            [product.product_id for product in products]
            if products
            else list(state.resolved_entities.ingredient_ids)
        )
        known_conditions = parsed.known_conditions.model_copy(deep=True)
        if (
            not target_ids
            and not parsed.ingredient_mentions
            and any(word in parsed.query for word in self._EVIDENCE_REFERENCES)
        ):
            target_ids = list(state.task_context.evidence_target_ids)
            combination_target_ids = list(state.task_context.evidence_combination_target_ids)
            known_conditions = self._merged_conditions(state, parsed.known_conditions)

        request = self._query_policy.search_request(
            state,
            EvidenceSearchRequest(
                query=parsed.query,
                target_ids=target_ids,
                known_conditions=known_conditions,
                combination_target_ids=combination_target_ids,
            ),
        )
        if self._query_policy.allows_fallback(state):
            limitation = self._query_policy.limitation(state)
            state.status = ChatStatus.PARTIAL
            state.unresolved.append(limitation)
            state.response_parts.append(limitation.detail)
        # 후속 지시어가 일부 ID만 복원하지 않도록 실제 검색 요청의 대상을 함께 저장한다.
        state.task_context.evidence_target_ids = list(request.target_ids)
        state.task_context.evidence_combination_target_ids = list(request.combination_target_ids)
        state.task_context.evidence_conditions = known_conditions.model_copy(deep=True)
        state.evidence_bundle = await self._evidence_pipeline.run(request)
        if state.evidence_bundle.search.status is LookupStatus.ERROR:
            self._runtime.add_tool_failure(state, state.evidence_bundle.search.error_message)
        self._runtime.record_node(state, GraphNode.SEARCH_EVIDENCE, "공인 Evidence 검증을 마쳤습니다.")
        return state

    async def assemble_rag_response(self, state: AgentState) -> AgentState:
        self._response_assembler.append(state)
        state.current_intent = None
        self._runtime.record_node(
            state,
            GraphNode.ASSEMBLE_RAG_RESPONSE,
            "Claim과 Evidence를 구분해 응답을 조립했습니다.",
        )
        return state

    def _validate_claim_result(self, result: ClaimSearchResult) -> None:
        if result.status is not LookupStatus.SUCCESS:
            return
        statement_ids = [hit.statement_id for hit in result.hits]
        if len(statement_ids) != len(set(statement_ids)):
            raise ValueError("Claim 검색 결과에 동일 statement_id가 중복되었습니다.")
        allowed_decisions = {
            ClaimIngestionDecision.INGESTIBLE_STRUCTURED,
            ClaimIngestionDecision.INGESTIBLE_FREE_TEXT,
        }
        if any(hit.decision not in allowed_decisions for hit in result.hits):
            raise ValueError("운영 검색이 허용되지 않은 Claim이 검색 결과에 포함되었습니다.")
        if any(
            hit.annotation_version != self._claim_annotation_version for hit in result.hits
        ):
            raise ValueError("요청한 annotation_version과 다른 Claim이 검색되었습니다.")

    def _evidence_products(self, state: AgentState) -> list[ProductRecord]:
        products = list(state.resolved_entities.products)
        parsed = self._runtime.require_parsed(state)
        if parsed.referenced_candidate_number is None:
            return products
        candidate = self._candidate_by_rank(state, parsed.referenced_candidate_number)
        if candidate is not None:
            products.append(candidate.product)
        return products

    def _candidate_by_rank(self, state: AgentState, rank: int) -> ProductCandidate | None:
        if state.candidate_set is None:
            return None
        return next(
            (candidate for candidate in state.candidate_set.candidates if candidate.rank == rank),
            None,
        )

    def _merged_conditions(
        self,
        state: AgentState,
        current: EvidenceConditions,
    ) -> EvidenceConditions:
        known = state.task_context.evidence_conditions.model_copy(deep=True)
        for field in EvidenceConditions.model_fields:
            value = getattr(current, field)
            if value is not None:
                setattr(known, field, value)
        return known
