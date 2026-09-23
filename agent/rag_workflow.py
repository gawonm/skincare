"""Claim 탐색과 Evidence 검증을 분리한 LangGraph 노드 모음."""

from uuid import NAMESPACE_URL, uuid5

from agent.claim_verification import ClaimEvidenceVerifier, IngredientRecommendationSelector
from agent.evidence_query_policy import EvidenceQueryPolicy
from agent.ports import IngredientRepository
from agent.rag.case_claim_anchor_adapter import CaseClaimToEvidenceQueryAnchorAdapter
from agent.rag.case_claim_schemas import (
    CaseClaimBundle,
    CaseClaimExtractionRequest,
    CaseClaimExtractionResult,
    CaseClaimIngredientResolutionStatus,
    CaseClaimValidationRequest,
    ExtractedCaseClaim,
    ResolvedCaseClaim,
    ResolvedCaseClaimIngredient,
)
from agent.rag.case_claim_validator import CaseClaimValidator
from agent.rag.case_schemas import (
    CaseBundle,
    CaseRerankRequest,
    CaseSearchRequest,
    CaseSearchResult,
)
from agent.rag.case_usage_guidance import CaseUsageGuidanceExtractor
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
from agent.rag.ports import (
    CaseClaimExtractor,
    CaseReranker,
    CaseRetriever,
    ClaimRetriever,
    TextEmbedder,
)
from agent.rag.retrieval.case_result_fusion import (
    CaseSearchContribution,
    CaseSearchFusionRequest,
    CaseSearchResultFusion,
)
from agent.rag.retrieval.ingredient_alias_mapper import CommonIngredientAliasMapper
from agent.rag.schemas import (
    BGE_M3_EMBEDDING_DIMENSIONS,
    EmbeddingRequest,
    EvidenceConditions,
    EvidenceQueryAnchor,
    EvidenceSearchRequest,
    IngredientResolveRequest,
    LocalEmbeddingModel,
    LookupStatus,
    ProductCandidate,
    ProductRecord,
)
from agent.rag_response import RagResponseAssembler
from agent.runtime import AgentRuntime
from agent.schemas import (
    AgentState,
    CaseRetrievalQuery,
    CaseRetrievalQueryKind,
    ChatStatus,
    GraphNode,
    RagRoute,
)


class RagWorkflowNodes:
    """2-Layer RAG의 단계별 상태 변경을 일반 작업 노드에서 격리한다."""

    _EVIDENCE_REFERENCES = ("이 성분", "그 성분", "해당 성분", "이 제품", "그 제품")

    def __init__(
        self,
        case_retriever: CaseRetriever,
        case_reranker: CaseReranker,
        case_claim_extractor: CaseClaimExtractor,
        case_embedder: TextEmbedder,
        ingredient_repository: IngredientRepository,
        evidence_pipeline: EvidencePipeline,
        response_assembler: RagResponseAssembler,
        runtime: AgentRuntime,
        query_policy: EvidenceQueryPolicy,
        claim_verifier: ClaimEvidenceVerifier,
        recommendation_selector: IngredientRecommendationSelector,
        claim_retriever: ClaimRetriever | None = None,
        claim_annotation_version: str | None = None,
    ) -> None:
        self._case_retriever = case_retriever
        self._case_reranker = case_reranker
        self._case_claim_extractor = case_claim_extractor
        self._case_embedder = case_embedder
        self._ingredient_repository = ingredient_repository
        self._case_claim_validator = CaseClaimValidator()
        self._case_search_fusion = CaseSearchResultFusion()
        self._case_claim_anchor_adapter = CaseClaimToEvidenceQueryAnchorAdapter()
        self._case_usage_guidance = CaseUsageGuidanceExtractor()
        self._ingredient_aliases = CommonIngredientAliasMapper()
        self._claim_retriever = claim_retriever
        self._claim_annotation_version = claim_annotation_version
        self._claim_anchor_adapter = ClaimHitToEvidenceQueryAnchorAdapter()
        self._evidence_pipeline = evidence_pipeline
        self._response_assembler = response_assembler
        self._runtime = runtime
        self._query_policy = query_policy
        self._claim_verifier = claim_verifier
        self._recommendation_selector = recommendation_selector

    async def search_cases(self, state: AgentState) -> AgentState:
        if not self._runtime.reserve_tool_call(state, GraphNode.SEARCH_CASES):
            return state
        queries = self._case_retrieval_queries(state)
        try:
            embedding = await self._case_embedder.embed(
                EmbeddingRequest(texts=[query.text for query in queries])
            )
            if embedding.model != LocalEmbeddingModel.BGE_M3.value:
                result = CaseSearchResult(
                    status=LookupStatus.UNSUPPORTED,
                    error_message=(
                        "NIA Case 질의 임베딩 모델이 BGE-M3가 아닙니다: "
                        f"actual={embedding.model}"
                    ),
                )
            elif len(embedding.vectors) != len(queries):
                result = CaseSearchResult(
                    status=LookupStatus.ERROR,
                    error_message=(
                        "NIA Case 검색 질의 수와 임베딩 벡터 수가 다릅니다: "
                        f"queries={len(queries)}, vectors={len(embedding.vectors)}"
                    ),
                )
            elif any(
                len(vector.values) != BGE_M3_EMBEDDING_DIMENSIONS
                for vector in embedding.vectors
            ):
                invalid_dimensions = [
                    len(vector.values)
                    for vector in embedding.vectors
                    if len(vector.values) != BGE_M3_EMBEDDING_DIMENSIONS
                ]
                result = CaseSearchResult(
                    status=LookupStatus.UNSUPPORTED,
                    error_message=(
                        "NIA Case 질의 벡터 중 1,024차원이 아닌 값이 있습니다: "
                        f"actual={invalid_dimensions}"
                    ),
                )
            else:
                contributions: list[CaseSearchContribution] = []
                for query, vector in zip(queries, embedding.vectors, strict=True):
                    try:
                        search_result = await self._case_retriever.search(
                            CaseSearchRequest(
                                query=query.text,
                                query_embedding=vector,
                                text_version="nia_case_text/v1",
                                embedding_model=embedding.model,
                            )
                        )
                    except (OSError, RuntimeError, TypeError, ValueError) as error:
                        search_result = CaseSearchResult(
                            status=LookupStatus.ERROR,
                            error_message=(
                                "NIA Case 개별 질의 검색에 실패했습니다: "
                                f"kind={query.kind.value}, detail={error}"
                            ),
                        )
                    contributions.append(
                        CaseSearchContribution(
                            query=query.text,
                            result=search_result,
                        )
                    )
                fusion = self._case_search_fusion.fuse(
                    CaseSearchFusionRequest(contributions=contributions)
                )
                result = fusion.search_result
                if result.status is LookupStatus.SUCCESS:
                    for failure in fusion.failures:
                        self._runtime.add_tool_failure(
                            state,
                            "NIA Case 복수 질의 검색 일부 실패: "
                            f"query={failure.query}, status={failure.status.value}, "
                            f"detail={failure.message}",
                        )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            result = CaseSearchResult(
                status=LookupStatus.ERROR,
                error_message=f"NIA Case 질의 임베딩 또는 검색에 실패했습니다: {error}",
            )
        state.case_bundle = CaseBundle(search=result)
        if result.status in (LookupStatus.ERROR, LookupStatus.UNSUPPORTED):
            self._runtime.add_tool_failure(state, result.error_message)
        self._runtime.record_node(
            state,
            GraphNode.SEARCH_CASES,
            "NIA 유사 Case 1차 검색을 마쳤습니다.",
        )
        return state

    async def rerank_cases(self, state: AgentState) -> AgentState:
        bundle = state.case_bundle
        if bundle is None or bundle.search.status is not LookupStatus.SUCCESS:
            self._runtime.record_node(
                state,
                GraphNode.RERANK_CASES,
                "재정렬할 NIA Case가 없어 건너뛰었습니다.",
            )
            return state
        if not self._runtime.reserve_tool_call(state, GraphNode.RERANK_CASES):
            return state
        try:
            parsed = self._runtime.require_parsed(state)
            rerank = await self._case_reranker.rerank(
                CaseRerankRequest(
                    query=(
                        parsed.query_plan.case_rerank_query or self._case_query(state)
                    ),
                    candidates=bundle.search.hits,
                )
            )
            state.case_bundle = bundle.model_copy(update={"rerank": rerank})
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            # 재정렬 실패 시에도 RRF Top-3는 출처가 보존된 유효 후보이므로 명시적 fallback으로 쓴다.
            state.case_bundle = bundle.model_copy(update={"rerank_fallback_used": True})
            self._runtime.add_tool_failure(
                state,
                f"NIA Case rerank 실패로 RRF 융합 순위를 사용합니다: {error}",
            )
        self._runtime.record_node(
            state,
            GraphNode.RERANK_CASES,
            "NIA Case Top-3 선정을 마쳤습니다.",
        )
        return state

    async def extract_case_claims(self, state: AgentState) -> AgentState:
        cases = state.case_bundle.selected_hits() if state.case_bundle is not None else []
        if not cases:
            state.case_claim_bundle = CaseClaimBundle(
                extraction=CaseClaimExtractionResult(status=LookupStatus.NO_RESULTS)
            )
            self._runtime.record_node(
                state,
                GraphNode.EXTRACT_CASE_CLAIMS,
                "Claim을 추출할 NIA Case가 없어 건너뛰었습니다.",
            )
            return state
        if not self._runtime.reserve_tool_call(state, GraphNode.EXTRACT_CASE_CLAIMS):
            return state
        result = await self._case_claim_extractor.extract(
            CaseClaimExtractionRequest(query=self._case_query(state), cases=cases)
        )
        state.case_claim_bundle = CaseClaimBundle(extraction=result)
        if result.status is LookupStatus.ERROR:
            self._runtime.add_tool_failure(state, result.error_message)
        self._runtime.record_node(
            state,
            GraphNode.EXTRACT_CASE_CLAIMS,
            "NIA Case 원문에서 질문 관련 성분 선별을 마쳤습니다.",
        )
        return state

    async def validate_case_claims(self, state: AgentState) -> AgentState:
        bundle = state.case_claim_bundle
        cases = state.case_bundle.selected_hits() if state.case_bundle is not None else []
        if bundle is None or bundle.extraction.status is not LookupStatus.SUCCESS:
            self._runtime.record_node(
                state,
                GraphNode.VALIDATE_CASE_CLAIMS,
                "검증할 런타임 Claim이 없어 건너뛰었습니다.",
            )
            return state
        validation = self._case_claim_validator.validate(
            CaseClaimValidationRequest(cases=cases, claims=bundle.extraction.claims)
        )
        state.case_claim_bundle = bundle.model_copy(update={"validation": validation})
        self._runtime.record_node(
            state,
            GraphNode.VALIDATE_CASE_CLAIMS,
            "런타임 Claim의 Case ID와 exact quote를 검증했습니다.",
        )
        return state

    async def resolve_case_claim_ingredients(self, state: AgentState) -> AgentState:
        bundle = state.case_claim_bundle
        if bundle is None or bundle.validation is None:
            self._runtime.record_node(
                state,
                GraphNode.RESOLVE_CASE_CLAIM_INGREDIENTS,
                "식별할 Case 관련 성분이 없어 건너뛰었습니다.",
            )
            return state

        resolved_claims: list[ResolvedCaseClaim] = []
        evidence_anchors: list[EvidenceQueryAnchor] = []
        evidence_anchor_keys: set[tuple[tuple[str, ...], str]] = set()
        target_ids: list[str] = []
        request_id = self._runtime.require_turn(state).request_id
        for claim in bundle.validation.valid_claims:
            ingredients = [
                await self._resolve_case_ingredient(state, ingredient.raw_name)
                for ingredient in claim.ingredients
            ]
            resolved = ResolvedCaseClaim(
                statement_id=self._case_claim_statement_id(claim),
                claim=claim,
                ingredients=ingredients,
            )
            resolved_claims.append(resolved)
            anchor = self._case_claim_anchor_adapter.adapt(
                resolved,
                request_id=request_id,
                evidence_query=self._evidence_query(state),
            )
            if anchor is not None:
                anchor_key = (
                    tuple(sorted(anchor.ingredient_refs)),
                    anchor.claim_topic.value,
                )
                # 같은 성분이 여러 Case에 반복돼도 Evidence는 같은 사용자 질문으로 한 번만 조회한다.
                if anchor_key not in evidence_anchor_keys:
                    evidence_anchor_keys.add(anchor_key)
                    evidence_anchors.append(anchor)
                    target_ids.extend(anchor.ingredient_refs)

        unique_target_ids = list(dict.fromkeys(target_ids))
        selected_cases = state.case_bundle.selected_hits() if state.case_bundle is not None else []
        state.task_context.case_usage_guidance = self._case_usage_guidance.extract(
            selected_cases,
            resolved_claims,
        )
        state.case_claim_bundle = bundle.model_copy(
            deep=True,
            update={
                "resolved_claims": resolved_claims,
                "evidence_anchors": evidence_anchors,
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
            GraphNode.RESOLVE_CASE_CLAIM_INGREDIENTS,
            "Case 관련 성분의 표준 ID 식별과 사용법 구간 연결을 마쳤습니다.",
        )
        return state

    async def route_rag(self, state: AgentState) -> AgentState:
        parsed = self._runtime.require_parsed(state)
        # 기존 호출자가 rag_route를 아직 보내지 않아도 명시 성분 질의의 동작은 유지한다.
        state.rag_route = parsed.rag_route or RagRoute.EVIDENCE_ONLY
        self._runtime.record_node(state, GraphNode.ROUTE_RAG, "RAG 탐색 경로를 선택했습니다.")
        return state

    async def search_claims(self, state: AgentState) -> AgentState:
        if self._claim_retriever is None or self._claim_annotation_version is None:
            raise RuntimeError("offline Claim 검색기는 현재 기본 Case 경로에 주입되지 않았습니다.")
        parsed = self._runtime.require_parsed(state)
        if not self._runtime.reserve_tool_call(state, GraphNode.SEARCH_CLAIMS):
            return state
        result = await self._claim_retriever.search(
            ClaimSearchRequest(
                query=self._case_query(state),
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
        anchors = self._claim_evidence_anchors(state)
        if not anchors:
            state.claim_verification_bundle = ClaimVerificationBundle()
            self._runtime.record_node(
                state,
                GraphNode.VERIFY_CLAIMS,
                "Evidence로 확인할 Claim 대상이 없어 검증 단계를 건너뛰었습니다.",
            )
            return state

        parsed = self._runtime.require_parsed(state)
        results: list[ClaimVerificationResult] = []
        for anchor in anchors:
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
                query=self._evidence_query(state),
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

    def _case_query(self, state: AgentState) -> str:
        parsed = self._runtime.require_parsed(state)
        return parsed.query_plan.case_query or parsed.query

    def _case_retrieval_queries(self, state: AgentState) -> list[CaseRetrievalQuery]:
        parsed = self._runtime.require_parsed(state)
        if parsed.query_plan.case_retrieval_queries:
            return [
                query.model_copy(deep=True)
                for query in parsed.query_plan.case_retrieval_queries
            ]
        return [
            CaseRetrievalQuery(
                kind=CaseRetrievalQueryKind.NATURAL_QUESTION,
                text=self._case_query(state),
            )
        ]

    def _evidence_query(self, state: AgentState) -> str:
        parsed = self._runtime.require_parsed(state)
        return parsed.query_plan.evidence_query or parsed.query

    async def _resolve_case_ingredient(
        self,
        state: AgentState,
        raw_name: str,
    ) -> ResolvedCaseClaimIngredient:
        if not self._runtime.reserve_tool_call(
            state,
            GraphNode.RESOLVE_CASE_CLAIM_INGREDIENTS,
        ):
            return ResolvedCaseClaimIngredient(
                raw_name=raw_name,
                status=CaseClaimIngredientResolutionStatus.ERROR,
            )
        request = IngredientResolveRequest(name=raw_name)
        result = await self._ingredient_repository.resolve(request)
        if (
            result.status is LookupStatus.NO_RESULTS
            and self._ingredient_aliases.is_ambiguous_family(request)
        ):
            return ResolvedCaseClaimIngredient(
                raw_name=raw_name,
                status=CaseClaimIngredientResolutionStatus.AMBIGUOUS,
            )
        alias_request = self._ingredient_aliases.map_request(request)
        if result.status is LookupStatus.NO_RESULTS and alias_request.name != request.name:
            if not self._runtime.reserve_tool_call(
                state,
                GraphNode.RESOLVE_CASE_CLAIM_INGREDIENTS,
            ):
                return ResolvedCaseClaimIngredient(
                    raw_name=raw_name,
                    status=CaseClaimIngredientResolutionStatus.ERROR,
                )
            result = self._ingredient_aliases.validate_result(
                alias_request,
                await self._ingredient_repository.resolve(alias_request),
            )
        if result.status in (LookupStatus.ERROR, LookupStatus.UNSUPPORTED):
            self._runtime.add_tool_failure(
                state,
                result.error_message
                or f"Case 관련 성분을 조회하지 못했습니다: {raw_name}",
            )
            return ResolvedCaseClaimIngredient(
                raw_name=raw_name,
                status=CaseClaimIngredientResolutionStatus.ERROR,
            )
        if result.ambiguous_candidates:
            return ResolvedCaseClaimIngredient(
                raw_name=raw_name,
                status=CaseClaimIngredientResolutionStatus.AMBIGUOUS,
            )
        if result.status is LookupStatus.SUCCESS and result.ingredient is not None:
            return ResolvedCaseClaimIngredient(
                raw_name=raw_name,
                ingredient_id=result.ingredient.ingredient_id,
                canonical_name=result.ingredient.canonical_name,
                status=CaseClaimIngredientResolutionStatus.MATCHED,
            )
        return ResolvedCaseClaimIngredient(
            raw_name=raw_name,
            status=CaseClaimIngredientResolutionStatus.UNRESOLVED,
        )

    def _case_claim_statement_id(self, claim: ExtractedCaseClaim) -> str:
        names = "|".join(ingredient.raw_name.casefold() for ingredient in claim.ingredients)
        identity = (
            f"{claim.case_id}:{claim.claim_type.value}:{names}:{claim.source_quote}"
        )
        return f"case-claim:{uuid5(NAMESPACE_URL, identity)}"

    def _claim_evidence_anchors(self, state: AgentState) -> list[EvidenceQueryAnchor]:
        if state.case_claim_bundle is not None:
            return list(state.case_claim_bundle.evidence_anchors)
        if state.claim_bundle is not None:
            return list(state.claim_bundle.evidence_anchors)
        return []
