"""최신 dump와 실제 모델을 연결한 2-Layer LangGraph 대화형 CLI.

단일 질의 (간략 모드):
    uv run python -m tests.agent.interactive_two_layer_rag_cli \
        "피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?"

단일 질의 (2-Layer RAG 상세 모드):
    uv run python -m tests.agent.interactive_two_layer_rag_cli \
        "피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?" --verbose

대화형 실행:
    uv run python -m tests.agent.interactive_two_layer_rag_cli
"""

import asyncio
import sys
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import make_url

from agent.factory import DevelopmentAgentApplication, DevelopmentAgentFactory
from agent.llm import LlmClientFactory
from agent.nodes import (
    CLAIM_ONLY_PRODUCT_LIMITATION,
    LIMITED_EVIDENCE_PRODUCT_LIMITATION,
    UNREVIEWED_EVIDENCE_PRODUCT_LIMITATION,
)
from agent.ports import IngredientRepository, ProductRepository
from agent.rag.case_claim_extractor import CaseClaimExtractorFactory
from agent.rag.case_claim_schemas import (
    CaseClaimExtractionRequest,
    CaseClaimExtractionResult,
)
from agent.rag.case_schemas import (
    CaseRerankRequest,
    CaseRerankResult,
    CaseSearchRequest,
    CaseSearchResult,
)
from agent.rag.embedding.factory import TextEmbedderFactory
from agent.rag.generation.answer_generator import AnswerGenerator
from agent.rag.generation.evidence_statement_generator import EvidenceStatementGeneratorFactory
from agent.rag.ports import CaseClaimExtractor, CaseReranker, CaseRetriever, EvidenceRetriever
from agent.rag.retrieval.case_reranker import LocalBgeCaseRerankerV2M3
from agent.rag.retrieval.cross_encoder import LocalBgeCrossEncoderScorer
from agent.rag.retrieval.hybrid_retriever import HybridEvidenceRetriever
from agent.rag.retrieval.ingredient_alias_mapper import CommonIngredientAliasMapper
from agent.rag.retrieval.local_reranker import LocalBgeRerankerV2M3
from agent.rag.routine_planner import RoutinePlannerFactory
from agent.rag.schemas import (
    ChatModelConfig,
    EmbeddingProvider,
    EvidenceReviewStatus,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    IngredientResolveRequest,
    IngredientResolveResult,
    LocalEmbeddingConfig,
    LocalEmbeddingModel,
    LocalModelDevice,
    LocalRerankerConfig,
    LocalRerankerModel,
    LookupStatus,
    ProductCandidateSet,
    ProductGetRequest,
    ProductGetResult,
    ProductSearchRequest,
    ProductSearchResult,
    ProductTaxonomy,
    RagRetrievalPolicy,
    TextEmbeddingConfig,
)
from agent.schemas import (
    ExecutionLimits,
    RegisterRoomRequest,
    UnresolvedKind,
)
from backend.services.agent_configuration import AgentConfigurationAssembler
from backend.services.two_layer_rag_adapters import (
    BackendNiaCaseRetriever,
    TwoLayerEvidenceSearchBackend,
    TwoLayerIngredientRepository,
    TwoLayerProductRepository,
    TwoLayerProductTaxonomyProvider,
)
from core.config import settings
from core.database import Database, DatabaseConfig
from tests.agent.interactive_rag_cli import (
    DIVIDER_LINE,
    SUB_DIVIDER_LINE,
    AgentTurnResult,
    InteractiveAgentCli,
    RecordingEvidenceRetriever,
)


class CliDisplayMode(StrEnum):
    """CLI 출력 모드."""

    COMPACT = "compact"
    VERBOSE = "verbose"


class ClaimEvidenceDisplay(BaseModel):
    """Claim 대비 Evidence 검색 집계 현황."""

    model_config = ConfigDict(frozen=True)

    subject: str
    claim_text: str | None = None
    retrieved_count: int
    verified_count: int
    unreviewed_count: int


class FlowTraceModel(BaseModel):
    """흐름 추적용 Pydantic 베이스 모델."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CaseSearchTrace(FlowTraceModel):
    request: CaseSearchRequest
    result: CaseSearchResult | None = None


class CaseRerankTrace(FlowTraceModel):
    request: CaseRerankRequest
    result: CaseRerankResult | None = None


class CaseClaimExtractionTrace(FlowTraceModel):
    request: CaseClaimExtractionRequest
    result: CaseClaimExtractionResult | None = None


class IngredientResolutionTrace(FlowTraceModel):
    request: IngredientResolveRequest
    result: IngredientResolveResult | None = None


class EvidenceSearchTrace(FlowTraceModel):
    request: EvidenceSearchRequest
    result: EvidenceSearchResult | None = None


class ProductSearchTrace(FlowTraceModel):
    request: ProductSearchRequest
    result: ProductSearchResult | None = None


class TwoLayerFlowSnapshot(FlowTraceModel):
    """2-Layer RAG 파이프라인의 1턴 전체 추적 스냅샷."""

    case_searches: list[CaseSearchTrace] = Field(default_factory=list)
    case_reranks: list[CaseRerankTrace] = Field(default_factory=list)
    claim_extractions: list[CaseClaimExtractionTrace] = Field(default_factory=list)
    ingredient_resolutions: list[IngredientResolutionTrace] = Field(default_factory=list)
    evidence_searches: list[EvidenceSearchTrace] = Field(default_factory=list)
    product_searches: list[ProductSearchTrace] = Field(default_factory=list)


class TwoLayerFlowTraceCollector:
    """실제 포트 호출을 재실행하지 않고 한 턴의 단계별 입출력을 보존한다."""

    def __init__(self) -> None:
        self._snapshot = TwoLayerFlowSnapshot()

    def reset(self) -> None:
        self._snapshot = TwoLayerFlowSnapshot()

    def snapshot(self) -> TwoLayerFlowSnapshot:
        return self._snapshot.model_copy(deep=True)

    def case_search(self, request: CaseSearchRequest) -> CaseSearchTrace:
        trace = CaseSearchTrace(request=request.model_copy(deep=True))
        self._snapshot.case_searches.append(trace)
        return trace

    def case_rerank(self, request: CaseRerankRequest) -> CaseRerankTrace:
        trace = CaseRerankTrace(request=request.model_copy(deep=True))
        self._snapshot.case_reranks.append(trace)
        return trace

    def claim_extraction(
        self,
        request: CaseClaimExtractionRequest,
    ) -> CaseClaimExtractionTrace:
        trace = CaseClaimExtractionTrace(request=request.model_copy(deep=True))
        self._snapshot.claim_extractions.append(trace)
        return trace

    def ingredient_resolution(
        self,
        request: IngredientResolveRequest,
    ) -> IngredientResolutionTrace:
        trace = IngredientResolutionTrace(request=request.model_copy(deep=True))
        self._snapshot.ingredient_resolutions.append(trace)
        return trace

    def evidence_search(self, request: EvidenceSearchRequest) -> EvidenceSearchTrace:
        trace = EvidenceSearchTrace(request=request.model_copy(deep=True))
        self._snapshot.evidence_searches.append(trace)
        return trace

    def product_search(self, request: ProductSearchRequest) -> ProductSearchTrace:
        trace = ProductSearchTrace(request=request.model_copy(deep=True))
        self._snapshot.product_searches.append(trace)
        return trace


class RecordingCaseRetriever(CaseRetriever):
    def __init__(self, delegate: CaseRetriever, collector: TwoLayerFlowTraceCollector) -> None:
        self._delegate = delegate
        self._collector = collector

    async def search(self, request: CaseSearchRequest) -> CaseSearchResult:
        trace = self._collector.case_search(request)
        result = await self._delegate.search(request)
        trace.result = result.model_copy(deep=True)
        return result


class RecordingCaseReranker(CaseReranker):
    def __init__(self, delegate: CaseReranker, collector: TwoLayerFlowTraceCollector) -> None:
        self._delegate = delegate
        self._collector = collector

    async def rerank(self, request: CaseRerankRequest) -> CaseRerankResult:
        trace = self._collector.case_rerank(request)
        result = await self._delegate.rerank(request)
        trace.result = result.model_copy(deep=True)
        return result


class RecordingCaseClaimExtractor(CaseClaimExtractor):
    def __init__(
        self,
        delegate: CaseClaimExtractor,
        collector: TwoLayerFlowTraceCollector,
    ) -> None:
        self._delegate = delegate
        self._collector = collector

    async def extract(
        self,
        request: CaseClaimExtractionRequest,
    ) -> CaseClaimExtractionResult:
        trace = self._collector.claim_extraction(request)
        result = await self._delegate.extract(request)
        trace.result = result.model_copy(deep=True)
        return result


class RecordingIngredientRepository(IngredientRepository):
    def __init__(
        self,
        delegate: IngredientRepository,
        collector: TwoLayerFlowTraceCollector,
    ) -> None:
        self._delegate = delegate
        self._collector = collector

    async def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult:
        trace = self._collector.ingredient_resolution(request)
        result = await self._delegate.resolve(request)
        trace.result = result.model_copy(deep=True)
        return result


class RecordingFlowEvidenceRetriever(EvidenceRetriever):
    def __init__(
        self,
        delegate: EvidenceRetriever,
        collector: TwoLayerFlowTraceCollector,
    ) -> None:
        self._delegate = delegate
        self._collector = collector

    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        trace = self._collector.evidence_search(request)
        result = await self._delegate.search(request)
        trace.result = result.model_copy(deep=True)
        return result


class RecordingProductRepository(ProductRepository):
    def __init__(
        self,
        delegate: ProductRepository,
        collector: TwoLayerFlowTraceCollector,
    ) -> None:
        self._delegate = delegate
        self._collector = collector

    async def search(self, request: ProductSearchRequest) -> ProductSearchResult:
        trace = self._collector.product_search(request)
        result = await self._delegate.search(request)
        trace.result = result.model_copy(deep=True)
        return result

    async def get(self, request: ProductGetRequest) -> ProductGetResult:
        return await self._delegate.get(request)


class ConfiguredDatabaseFactory:
    """CLI도 애플리케이션과 동일한 `config.yaml` DB를 사용하도록 조립한다."""

    def create(self) -> Database:
        return Database(
            DatabaseConfig(
                url=settings.database.url,
                model_modules=settings.database.model_modules,
            )
        )

    def database_name(self) -> str:
        database_name = make_url(settings.database.url).database
        if database_name is None or not database_name.strip():
            raise RuntimeError("config.yaml의 database.url에 DB 이름이 없습니다.")
        return database_name


class Utf8ConsoleConfigurator:
    """Windows에서도 Agent 실행 결과를 손실 없이 출력하도록 콘솔 인코딩을 맞춘다."""

    ENCODING: ClassVar[str] = "utf-8"
    ERROR_POLICY: ClassVar[str] = "replace"

    def configure(self) -> None:
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                # 이모지 및 특수 기호 출력 시 cp949 콘솔 인코딩 오류를 방지한다.
                reconfigure(encoding=self.ENCODING, errors=self.ERROR_POLICY)


class ProductBasisPresenter:
    def label(self, limitations: list[str]) -> str:
        if CLAIM_ONLY_PRODUCT_LIMITATION in limitations:
            return "Claim 기반"
        if UNREVIEWED_EVIDENCE_PRODUCT_LIMITATION in limitations:
            return "미검수 근거"
        if LIMITED_EVIDENCE_PRODUCT_LIMITATION in limitations:
            return "제한 근거"
        return "성분 근거"


class CompactTwoLayerTurnPresenter:
    """간결한 최종 결과와 성분/근거 요약을 출력한다."""

    CLAIM_SEPARATOR: ClassVar[str] = "::"

    def __init__(self) -> None:
        self._product_basis = ProductBasisPresenter()

    def print_turn(self, result: AgentTurnResult, user_message: str) -> None:
        output = result.turn_output
        intents = ", ".join(intent.value for intent in output.intents)

        print(f"\n{DIVIDER_LINE}")
        print(f"질문: {user_message}")
        print(f"실행 결과: {output.status.value} | 의도: {intents}")
        print(SUB_DIVIDER_LINE)

        claim_rows = self._claim_rows(result)
        if claim_rows:
            print("[Claim → Evidence 요약]")
            for index, row in enumerate(claim_rows, start=1):
                print(f"{index}. {row.subject}")
                if row.claim_text:
                    print(f"   Claim: {row.claim_text}")
                if row.retrieved_count == 0:
                    print("   Evidence: 검색 결과 없음 → Claim-only 유지")
                else:
                    print(
                        "   Evidence: "
                        f"검색 {row.retrieved_count}건 "
                        f"(검수완료 {row.verified_count}, 미검수 {row.unreviewed_count})"
                    )
            print(f"최종 답변에 채택된 Citation: {len(output.citations)}건")

        candidate_sets = [
            artifact
            for artifact in output.artifacts
            if isinstance(artifact, ProductCandidateSet)
        ]
        candidates = [
            candidate
            for candidate_set in candidate_sets
            for candidate in candidate_set.candidates
        ]
        if candidates:
            print("\n[상품 후보]")
            for candidate in candidates:
                basis = self._product_basis.label(candidate.unresolved)
                print(f"{candidate.rank}. {candidate.product.name} [{basis}]")

        if output.citations:
            print("\n[채택된 근거]")
            for citation in output.citations:
                print(f"- {citation.source_title} ({citation.locator})")

        print("\n[Agent 최종 응답]")
        print(output.message)

        if output.unresolved:
            print("\n[보류 요약]")
            for kind in UnresolvedKind:
                count = sum(item.kind is kind for item in output.unresolved)
                if count:
                    print(f"- {self._unresolved_label(kind)}: {count}건")

        if output.error_code is not None:
            print(f"\n오류: {output.error_code.value} | 재시도 가능: {output.retryable}")
        if output.follow_up_question:
            print(f"\n추가 질문: {output.follow_up_question}")

        print("\n상세 2-Layer RAG 로그가 필요하면 명령 끝에 --verbose를 붙이세요.")
        print(DIVIDER_LINE)

    def _claim_rows(self, result: AgentTurnResult) -> list[ClaimEvidenceDisplay]:
        rows: list[ClaimEvidenceDisplay] = []
        for trace in result.searches:
            subject, separator, claim_text = trace.request.query.partition(self.CLAIM_SEPARATOR)
            chunks = trace.result.chunks if trace.result is not None else []
            rows.append(
                ClaimEvidenceDisplay(
                    subject=subject.strip() or trace.request.query,
                    claim_text=claim_text.strip() if separator and claim_text.strip() else None,
                    retrieved_count=len(chunks),
                    verified_count=sum(
                        hit.chunk.evidence.review_status is EvidenceReviewStatus.VERIFIED
                        for hit in chunks
                    ),
                    unreviewed_count=sum(
                        hit.chunk.evidence.review_status is EvidenceReviewStatus.UNREVIEWED
                        for hit in chunks
                    ),
                )
            )
        return rows

    def _unresolved_label(self, kind: UnresolvedKind) -> str:
        if kind is UnresolvedKind.NO_EVIDENCE:
            return "공인 근거 부족"
        if kind is UnresolvedKind.MISSING_INFORMATION:
            return "연결 정보 부족"
        if kind is UnresolvedKind.UNSUPPORTED_CONDITION:
            return "현재 미지원 조건"
        if kind is UnresolvedKind.TOOL_FAILURE:
            return "도구 실행 실패"
        return "근거 충돌"


class VerboseTwoLayerTurnPresenter:
    """2-Layer RAG 파이프라인의 모든 단계를 상세하게 출력한다."""

    QUOTE_PREVIEW_LENGTH: ClassVar[int] = 220
    CHUNK_CONTENT_PREVIEW_LENGTH: ClassVar[int] = 200
    PRODUCT_PREVIEW_LIMIT: ClassVar[int] = 10

    def __init__(self) -> None:
        self._aliases = CommonIngredientAliasMapper()
        self._product_basis = ProductBasisPresenter()

    def print_turn(
        self,
        snapshot: TwoLayerFlowSnapshot,
        result: AgentTurnResult,
        user_message: str,
    ) -> None:
        output = result.turn_output
        intents = ", ".join(intent.value for intent in output.intents)

        print(f"\n{DIVIDER_LINE}")
        print(f"질문: {user_message}")
        print(f"실행 결과: {output.status.value} | 의도: {intents}")
        print(DIVIDER_LINE)

        self._print_case_search(snapshot)
        self._print_case_rerank(snapshot)
        self._print_claim_extraction(snapshot)
        self._print_ingredient_resolution(snapshot)
        self._print_evidence_search(snapshot)
        self._print_product_search(snapshot)

        candidate_sets = [
            artifact
            for artifact in output.artifacts
            if isinstance(artifact, ProductCandidateSet)
        ]
        candidates = [
            candidate
            for candidate_set in candidate_sets
            for candidate in candidate_set.candidates
        ]
        if candidates:
            print("\n[상품 후보]")
            for candidate in candidates:
                basis = self._product_basis.label(candidate.unresolved)
                print(f"{candidate.rank}. {candidate.product.name} [{basis}]")

        if output.citations:
            print("\n[채택된 근거]")
            for citation in output.citations:
                print(f"- {citation.source_title} ({citation.locator})")

        print("\n[7. Agent 최종 응답]")
        print(output.message)

        if output.unresolved:
            print("\n[보류 요약]")
            for item in output.unresolved:
                print(f"- {item.kind.value}: {item.detail}")

        if output.error_code is not None:
            print(f"\n오류: {output.error_code.value} | 재시도 가능: {output.retryable}")
        if output.follow_up_question:
            print(f"\n추가 질문: {output.follow_up_question}")

        print(DIVIDER_LINE)

    def _print_case_search(self, snapshot: TwoLayerFlowSnapshot) -> None:
        print("\n[1. NIA Case Document 임베딩 검색]")
        if not snapshot.case_searches:
            print("- 실행되지 않음")
            return
        for trace in snapshot.case_searches:
            print(f"- 검색 질의: {trace.request.query}")
            print(f"- 후보 요청 수: {trace.request.candidate_limit}")
            if trace.result is None:
                print("- 결과 미수신")
                continue
            print(f"- 상태: {trace.result.status.value}, 반환: {len(trace.result.hits)}건")
            for index, hit in enumerate(trace.result.hits, start=1):
                print(
                    f"  {index}. case_id={hit.case_id} "
                    f"vector_similarity={hit.vector_similarity:.4f}"
                )

    def _print_case_rerank(self, snapshot: TwoLayerFlowSnapshot) -> None:
        print("\n[2. BGE 리랭커 Top-3 Case]")
        if not snapshot.case_reranks:
            print("- 실행되지 않음")
            return
        for trace in snapshot.case_reranks:
            print(f"- 리랭크 질의: {trace.request.query}")
            print(f"- 입력 후보: {len(trace.request.candidates)}건, 선택 상한: {trace.request.limit}건")
            if trace.result is None:
                print("- 결과 미수신")
                continue
            print(f"- 모델: {trace.result.model}")
            for index, hit in enumerate(trace.result.hits, start=1):
                print(
                    f"  {index}. case_id={hit.case_id} "
                    f"rerank_score={hit.rerank_score:.4f}"
                )

    def _print_claim_extraction(self, snapshot: TwoLayerFlowSnapshot) -> None:
        print("\n[3. Top-3 원문 LLM 관련 성분 선별]")
        if not snapshot.claim_extractions:
            print("- 실행되지 않음")
            return
        for trace in snapshot.claim_extractions:
            print(f"- LLM 입력 case_id: {[case.case_id for case in trace.request.cases]}")
            if trace.result is None:
                print("- 결과 미수신")
                continue
            print(
                f"- 상태: {trace.result.status.value}, model={trace.result.model}, "
                f"prompt={trace.result.prompt_version}"
            )
            for index, claim in enumerate(trace.result.claims, start=1):
                ingredients = [item.raw_name for item in claim.ingredients]
                quote = claim.source_quote[: self.QUOTE_PREVIEW_LENGTH]
                print(
                    f"  {index}. case_id={claim.case_id} ingredients={ingredients}"
                )
                print(f"     quote={quote}")

    def _print_ingredient_resolution(self, snapshot: TwoLayerFlowSnapshot) -> None:
        print("\n[4. Agent 별칭 처리 및 표준 ingredient_id 확정]")
        claims = [
            claim
            for extraction in snapshot.claim_extractions
            if extraction.result is not None
            for claim in extraction.result.claims
        ]
        if not claims:
            print("- 선별된 관련 성분 없음")
            return
        for claim in claims:
            for ingredient in claim.ingredients:
                request = IngredientResolveRequest(name=ingredient.raw_name)
                mapped = self._aliases.map_request(request)
                ambiguous = self._aliases.is_ambiguous_family(request)
                resolution = self._find_resolution(snapshot, request.name, mapped.name)
                if resolution is None or resolution.result is None:
                    resolved = "ingredient_id 미확정"
                elif resolution.result.ingredient is not None:
                    record = resolution.result.ingredient
                    resolved = f"{record.canonical_name} / {record.ingredient_id}"
                else:
                    resolved = resolution.result.status.value
                policy = "모호한 성분군" if ambiguous else mapped.name
                print(f"- {ingredient.raw_name} → {policy} → {resolved}")

    def _find_resolution(
        self,
        snapshot: TwoLayerFlowSnapshot,
        raw_name: str,
        mapped_name: str,
    ) -> IngredientResolutionTrace | None:
        matches = [
            trace
            for trace in snapshot.ingredient_resolutions
            if trace.request.name in {raw_name, mapped_name}
        ]
        successful = [
            trace
            for trace in matches
            if trace.result is not None and trace.result.status is LookupStatus.SUCCESS
        ]
        return successful[-1] if successful else (matches[-1] if matches else None)

    def _print_evidence_search(self, snapshot: TwoLayerFlowSnapshot) -> None:
        print("\n[5. 성분별 Evidence 검색 및 청크 상세]")
        if not snapshot.evidence_searches:
            print("- 실행되지 않음")
            return
        for index, trace in enumerate(snapshot.evidence_searches, start=1):
            print(f"{index}. Evidence 질의: {trace.request.query}")
            print(f"   ingredient_id: {trace.request.target_ids}")
            print(f"   Claim당 Evidence 반환 상한: {trace.request.limit}건")
            if trace.result is None:
                print("   결과 미수신")
                continue
            chunks = trace.result.chunks
            print(
                f"   상태: {trace.result.status.value}, "
                f"반환 Evidence: {len(chunks)}건"
            )
            for chunk_idx, hit in enumerate(chunks, start=1):
                chunk = hit.chunk
                evidence = chunk.evidence
                snippet = (
                    chunk.content[: self.CHUNK_CONTENT_PREVIEW_LENGTH].replace("\n", " ")
                    + ("..." if len(chunk.content) > self.CHUNK_CONTENT_PREVIEW_LENGTH else "")
                )
                print(
                    f"   [{chunk_idx}] {evidence.source_title} ({evidence.locator}) "
                    f"| 검수: {evidence.review_status.value} "
                    f"| RRF: {hit.fused_score:.4f}"
                    + (f", Vec: {hit.vector_similarity:.4f}" if hit.vector_similarity is not None else "")
                    + (f", Rerank: {hit.reranker_score:.4f}" if hit.reranker_score is not None else "")
                )
                print(f"       본문: {snippet}")

    def _print_product_search(self, snapshot: TwoLayerFlowSnapshot) -> None:
        print("\n[6. 상품 검색]")
        if not snapshot.product_searches:
            print("- 실행되지 않음")
            return
        for index, trace in enumerate(snapshot.product_searches, start=1):
            filters = trace.request.filters
            print(
                f"{index}. ingredient_ids={filters.ingredient_ids}, "
                f"category={filters.category.code if filters.category else None}"
            )
            if trace.result is None:
                print("   결과 미수신")
                continue
            print(f"   상태: {trace.result.status.value}, 반환 상품: {len(trace.result.products)}건")
            for product in trace.result.products[: self.PRODUCT_PREVIEW_LIMIT]:
                print(f"   - {product.name} ({product.category.name})")


class TwoLayerAgentModelConfigFactory:
    """구형 `rag_chunk` 차원 검증을 거치지 않고 2-Layer 모델 설정만 조립한다."""

    def create_chat(self) -> ChatModelConfig:
        return AgentConfigurationAssembler().create_chat(settings.openai, settings.agent)

    def create_embedding(self) -> TextEmbeddingConfig:
        source = settings.agent.embedding
        return TextEmbeddingConfig(
            provider=EmbeddingProvider.LOCAL,
            local=LocalEmbeddingConfig(
                model=LocalEmbeddingModel.BGE_M3,
                device=self._device(source.device),
                batch_size=source.batch_size,
                cache_folder=source.cache_folder,
                local_files_only=source.local_files_only,
            ),
        )

    def create_reranker(self) -> LocalRerankerConfig:
        source = settings.agent.reranker
        return LocalRerankerConfig(
            model=LocalRerankerModel.BGE_RERANKER_V2_M3,
            device=self._device(source.device),
            batch_size=source.batch_size,
            max_length=source.max_length,
            cache_folder=source.cache_folder,
            local_files_only=source.local_files_only,
        )

    def create_retrieval_policy(self) -> RagRetrievalPolicy:
        source = settings.agent.retrieval
        threshold = source.free_text_min_vector_similarity
        if threshold is None:
            raise RuntimeError(
                "2-Layer CLI 실행에는 BGE-M3 검색 임계값을 명시해야 합니다."
            )
        return RagRetrievalPolicy(
            free_text_min_vector_similarity=threshold,
            rrf_k=source.rrf_k,
            rerank_candidate_limit=source.rerank_candidate_limit,
        )

    def _device(self, device: object | None) -> LocalModelDevice | None:
        if device is None:
            return None
        value = getattr(device, "value", None)
        if not isinstance(value, str):
            raise TypeError("로컬 모델 device 설정은 문자열 Enum이어야 합니다.")
        return LocalModelDevice(value)


class InteractiveTwoLayerRagCli(InteractiveAgentCli):
    """실제 ChatService/LangGraph에 최신 dump 어댑터를 주입한다."""

    # Top-3에서 최대 10개 Claim을 얻으면 성분·Evidence·상품 호출이 연쇄되므로 여유를 둔다.
    MAX_TOOL_CALLS: ClassVar[int] = 50
    TIMEOUT_SECONDS: ClassVar[float] = 180.0
    RECURSION_LIMIT: ClassVar[int] = 80
    VERBOSE_FLAG: ClassVar[str] = "--verbose"

    def __init__(
        self,
        product_taxonomy: ProductTaxonomy,
        limit: int | None = None,
        display_mode: CliDisplayMode = CliDisplayMode.COMPACT,
        database: Database | None = None,
    ) -> None:
        Utf8ConsoleConfigurator().configure()
        self._display_mode = display_mode
        self._flow_trace = TwoLayerFlowTraceCollector()
        self._compact_presenter = CompactTwoLayerTurnPresenter()
        self._verbose_presenter = VerboseTwoLayerTurnPresenter()
        self._actor_id = "two-layer-cli-user"
        self._chat_room_id = "two-layer-cli-room"
        self._thread_id = "two-layer-cli-thread"
        self._turn_sequence = 0
        self._turn_lock = asyncio.Lock()
        self._closed = False

        config = TwoLayerAgentModelConfigFactory()
        self._chat_config = config.create_chat()
        self._embedding_config = config.create_embedding()
        self._reranker_config = config.create_reranker()
        self._retrieval_policy = config.create_retrieval_policy()
        database_factory = ConfiguredDatabaseFactory()
        self._database_name = database_factory.database_name()
        self._database = database or database_factory.create()
        self._product_taxonomy = product_taxonomy.model_copy(deep=True)

        embedder = TextEmbedderFactory().create(self._embedding_config)
        reranker_scorer = LocalBgeCrossEncoderScorer(self._reranker_config)
        self._retriever = RecordingEvidenceRetriever(
            self._configure_evidence_retriever(
                HybridEvidenceRetriever(
                    backend=TwoLayerEvidenceSearchBackend(self._database.session_factory),
                    embedder=embedder,
                    policy=self._retrieval_policy,
                    reranker=LocalBgeRerankerV2M3(
                        self._reranker_config,
                        scorer=reranker_scorer,
                    ),
                ),
            ),
            limit=limit,
        )
        self._app: DevelopmentAgentApplication = DevelopmentAgentFactory(
            execution_limits=ExecutionLimits(
                max_tool_calls=self.MAX_TOOL_CALLS,
                timeout_seconds=self.TIMEOUT_SECONDS,
                recursion_limit=self.RECURSION_LIMIT,
            ),
            llm=LlmClientFactory().create(self._chat_config),
            ingredient_repository=self._configure_ingredient_repository(
                TwoLayerIngredientRepository(self._database.session_factory)
            ),
            case_retriever=self._configure_case_retriever(
                BackendNiaCaseRetriever(self._database.session_factory)
            ),
            case_reranker=self._configure_case_reranker(
                LocalBgeCaseRerankerV2M3(
                    self._reranker_config,
                    scorer=reranker_scorer,
                )
            ),
            case_claim_extractor=self._configure_case_claim_extractor(
                CaseClaimExtractorFactory().create(self._chat_config)
            ),
            case_embedder=embedder,
            evidence_retriever=self._retriever,
            answer_generator=AnswerGenerator(
                EvidenceStatementGeneratorFactory().create(self._chat_config)
            ),
            product_repository=self._configure_product_repository(
                TwoLayerProductRepository(self._database.session_factory)
            ),
            product_taxonomy=self._product_taxonomy,
            routine_planner=RoutinePlannerFactory().create(self._chat_config),
        ).create()
        self._app.history.register_room(
            RegisterRoomRequest(
                actor_id=self._actor_id,
                chat_room_id=self._chat_room_id,
                thread_id=self._thread_id,
            )
        )

    def _configure_case_retriever(self, delegate: CaseRetriever) -> CaseRetriever:
        return RecordingCaseRetriever(delegate, self._flow_trace)

    def _configure_case_reranker(self, delegate: CaseReranker) -> CaseReranker:
        return RecordingCaseReranker(delegate, self._flow_trace)

    def _configure_case_claim_extractor(
        self,
        delegate: CaseClaimExtractor,
    ) -> CaseClaimExtractor:
        return RecordingCaseClaimExtractor(delegate, self._flow_trace)

    def _configure_ingredient_repository(
        self,
        delegate: IngredientRepository,
    ) -> IngredientRepository:
        return RecordingIngredientRepository(delegate, self._flow_trace)

    def _configure_evidence_retriever(
        self,
        delegate: EvidenceRetriever,
    ) -> EvidenceRetriever:
        return RecordingFlowEvidenceRetriever(delegate, self._flow_trace)

    def _configure_product_repository(
        self,
        delegate: ProductRepository,
    ) -> ProductRepository:
        return RecordingProductRepository(delegate, self._flow_trace)

    async def handle_message(self, user_message: str) -> AgentTurnResult:
        """한 번의 메시지 처리 시 2-Layer 흐름 스냅샷도 초기화한다."""
        self._flow_trace.reset()
        return await super().handle_message(user_message)

    def print_turn(self, result: AgentTurnResult, user_message: str) -> None:
        if self._display_mode is CliDisplayMode.VERBOSE:
            self._verbose_presenter.print_turn(
                self._flow_trace.snapshot(),
                result,
                user_message,
            )
            return
        self._compact_presenter.print_turn(result, user_message)

    def print_runtime(self) -> None:
        """실제 연결과 개발 fixture 경계를 실행 전에 표시한다."""
        chat_model = (
            self._chat_config.openai.model.value
            if self._chat_config.openai is not None
            else self._chat_config.local.model
        )
        print(f"\n{DIVIDER_LINE}")
        print(" 2-Layer 스킨케어 Agent LangGraph CLI")
        print(f"DB: {self._database_name}")
        print(
            f"Intent·답변 모델: {self._chat_config.provider.value} / {chat_model}"
        )
        print(
            "Claim·Evidence 임베딩: "
            f"{self._embedding_config.local.model.value} / "
            f"{self._embedding_config.output_dimensions()}차원"
        )
        print(f"Evidence 리랭커: {self._reranker_config.model.value}")
        print(f"Claim·Evidence·성분·상품: {self._database_name} 실제 DB")
        print(f"상품 taxonomy: {self._product_taxonomy.version}")
        print("히스토리·체크포인터·루틴: 개발용 메모리 구현")
        print("실제 OpenAI API 호출 비용이 발생합니다.")
        print(f"출력 모드: {self._display_mode.value}")
        print(DIVIDER_LINE)

    @classmethod
    async def main(cls) -> None:
        arguments = sys.argv[1:]
        display_mode = (
            CliDisplayMode.VERBOSE
            if cls.VERBOSE_FLAG in arguments
            else CliDisplayMode.COMPACT
        )
        message_parts = [argument for argument in arguments if argument != cls.VERBOSE_FLAG]
        database = ConfiguredDatabaseFactory().create()
        cli: InteractiveTwoLayerRagCli | None = None
        try:
            taxonomy = await TwoLayerProductTaxonomyProvider(
                database.session_factory
            ).load()
            cli = cls(
                display_mode=display_mode,
                database=database,
                product_taxonomy=taxonomy,
            )
            cli.print_runtime()
            if message_parts:
                user_message = " ".join(message_parts).strip()
                result = await cli.handle_message(user_message)
                cli.print_turn(result, user_message)
            else:
                await cli.run_loop()
        finally:
            if cli is not None:
                await cli.close()
            else:
                await database.dispose()


if __name__ == "__main__":
    asyncio.run(InteractiveTwoLayerRagCli.main())
