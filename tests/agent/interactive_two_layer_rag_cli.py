"""최신 dump와 실제 모델을 연결한 2-Layer LangGraph 대화형 CLI.

단일 질의:
    uv run python -m tests.agent.interactive_two_layer_rag_cli \
        "피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?"

대화형 실행:
    uv run python -m tests.agent.interactive_two_layer_rag_cli
"""

import asyncio
import sys
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field
from sqlalchemy.engine import make_url

from agent.adapters import FixtureProductTaxonomy
from agent.factory import DevelopmentAgentApplication, DevelopmentAgentFactory
from agent.llm import LlmClientFactory
from agent.nodes import CLAIM_ONLY_PRODUCT_LIMITATION
from agent.rag.embedding.factory import TextEmbedderFactory
from agent.rag.generation.answer_generator import AnswerGenerator
from agent.rag.generation.evidence_statement_generator import EvidenceStatementGeneratorFactory
from agent.rag.retrieval.hybrid_retriever import HybridEvidenceRetriever
from agent.rag.retrieval.local_reranker import LocalBgeRerankerV2M3
from agent.rag.schemas import (
    ChatModelConfig,
    EmbeddingProvider,
    EvidenceReviewStatus,
    LocalEmbeddingConfig,
    LocalEmbeddingModel,
    LocalModelDevice,
    LocalRerankerConfig,
    LocalRerankerModel,
    ProductCandidateSet,
    RagRetrievalPolicy,
    TextEmbeddingConfig,
)
from agent.schemas import ExecutionLimits, RegisterRoomRequest, UnresolvedKind
from backend.services.agent_configuration import AgentConfigurationAssembler
from backend.services.two_layer_rag_adapters import (
    TwoLayerClaimRetriever,
    TwoLayerEvidenceSearchBackend,
    TwoLayerIngredientRepository,
    TwoLayerProductRepository,
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


class LatestDumpDatabaseFactory:
    """공용 접속 정보는 유지하고 실행 대상만 최신 dump DB로 고정한다."""

    DATABASE_NAME: ClassVar[str] = "skincare_latest"

    def create(self) -> Database:
        url = make_url(settings.database.url).set(database=self.DATABASE_NAME)
        return Database(
            DatabaseConfig(
                url=url.render_as_string(hide_password=False),
                model_modules=settings.database.model_modules,
            )
        )


class Utf8ConsoleConfigurator:
    """Windows에서도 Agent 실행 결과를 손실 없이 출력하도록 콘솔 인코딩을 맞춘다."""

    ENCODING: ClassVar[str] = "utf-8"
    ERROR_POLICY: ClassVar[str] = "replace"

    def configure(self) -> None:
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                # 기존 CLI가 이모지를 출력하므로 cp949 콘솔에서는 결과 렌더링 전에 실패한다.
                reconfigure(encoding=self.ENCODING, errors=self.ERROR_POLICY)


class CliDisplayMode(StrEnum):
    COMPACT = "compact"
    VERBOSE = "verbose"


class ClaimEvidenceDisplay(BaseModel):
    """한 Claim의 Evidence 검색 결과를 사람이 빠르게 읽을 수 있는 형태로 제한한다."""

    subject: str = Field(min_length=1)
    claim_text: str | None = Field(default=None, min_length=1)
    retrieved_count: int = Field(ge=0)
    verified_count: int = Field(ge=0)
    unreviewed_count: int = Field(ge=0)


class CompactTwoLayerTurnPresenter:
    """디버그 세부정보 대신 2-Layer 판정 흐름을 먼저 보여준다."""

    CLAIM_SEPARATOR: ClassVar[str] = ":"

    def print_turn(self, result: AgentTurnResult, user_message: str) -> None:
        output = result.turn_output
        intents = ", ".join(intent.value for intent in output.intents)

        print(f"\n{DIVIDER_LINE}")
        print(f"질문: {user_message}")
        print(f"실행 결과: {output.status.value} | 의도: {intents}")
        print(SUB_DIVIDER_LINE)

        claim_rows = self._claim_rows(result)
        if claim_rows:
            print("[Claim → Evidence]")
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
                basis = (
                    "Claim 기반·근거 미확인"
                    if CLAIM_ONLY_PRODUCT_LIMITATION in candidate.unresolved
                    else "Evidence 기반"
                )
                print(f"{candidate.rank}. {candidate.product.name} [{basis}]")

        if output.citations:
            print("\n[채택된 공인 근거]")
            for citation in output.citations:
                print(f"- {citation.source_title} ({citation.locator})")

        # 상품 목록이 없는 효능·안전성 질의는 생성된 답변 문장 자체가 핵심 결과다.
        if not candidates:
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

        print("\n상세 검색 로그가 필요하면 명령 끝에 --verbose를 붙이세요.")
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

    MAX_TOOL_CALLS: ClassVar[int] = 20
    TIMEOUT_SECONDS: ClassVar[float] = 180.0
    RECURSION_LIMIT: ClassVar[int] = 80
    VERBOSE_FLAG: ClassVar[str] = "--verbose"

    def __init__(
        self,
        limit: int | None = None,
        display_mode: CliDisplayMode = CliDisplayMode.COMPACT,
    ) -> None:
        Utf8ConsoleConfigurator().configure()
        self._display_mode = display_mode
        self._compact_presenter = CompactTwoLayerTurnPresenter()
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
        self._database = LatestDumpDatabaseFactory().create()

        embedder = TextEmbedderFactory().create(self._embedding_config)
        claim_retriever = TwoLayerClaimRetriever(
            self._database.session_factory,
            embedder,
        )
        self._retriever = RecordingEvidenceRetriever(
            HybridEvidenceRetriever(
                backend=TwoLayerEvidenceSearchBackend(self._database.session_factory),
                embedder=embedder,
                policy=self._retrieval_policy,
                reranker=LocalBgeRerankerV2M3(self._reranker_config),
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
            ingredient_repository=TwoLayerIngredientRepository(
                self._database.session_factory
            ),
            claim_retriever=claim_retriever,
            evidence_retriever=self._retriever,
            answer_generator=AnswerGenerator(
                EvidenceStatementGeneratorFactory().create(self._chat_config)
            ),
            product_repository=TwoLayerProductRepository(
                self._database.session_factory
            ),
            product_taxonomy=FixtureProductTaxonomy().create(),
        ).create()
        self._app.history.register_room(
            RegisterRoomRequest(
                actor_id=self._actor_id,
                chat_room_id=self._chat_room_id,
                thread_id=self._thread_id,
            )
        )

    def print_turn(self, result: AgentTurnResult, user_message: str) -> None:
        if self._display_mode is CliDisplayMode.VERBOSE:
            super().print_turn(result, user_message)
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
        print(f"DB: {LatestDumpDatabaseFactory.DATABASE_NAME}")
        print(
            f"Intent·답변 모델: {self._chat_config.provider.value} / {chat_model}"
        )
        print(
            "Claim·Evidence 임베딩: "
            f"{self._embedding_config.local.model.value} / "
            f"{self._embedding_config.output_dimensions()}차원"
        )
        print(f"Evidence 리랭커: {self._reranker_config.model.value}")
        print("Claim·Evidence·성분·상품: skincare_latest 실제 DB")
        print("히스토리·체크포인터·루틴·상품 taxonomy: 개발용 메모리 구현")
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
        cli = cls(display_mode=display_mode)
        try:
            cli.print_runtime()
            if message_parts:
                user_message = " ".join(message_parts).strip()
                result = await cli.handle_message(user_message)
                cli.print_turn(result, user_message)
            else:
                await cli.run_loop()
        finally:
            await cli.close()


if __name__ == "__main__":
    asyncio.run(InteractiveTwoLayerRagCli.main())
