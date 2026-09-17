"""최신 dump와 실제 모델을 연결한 2-Layer LangGraph 대화형 CLI.

단일 질의:
    uv run python -m tests.agent.interactive_two_layer_rag_cli \
        "피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?"

대화형 실행:
    uv run python -m tests.agent.interactive_two_layer_rag_cli
"""

import asyncio
import sys
from typing import ClassVar

from sqlalchemy.engine import make_url

from agent.adapters import FixtureProductTaxonomy
from agent.factory import DevelopmentAgentApplication, DevelopmentAgentFactory
from agent.llm import LlmClientFactory
from agent.rag.embedding.factory import TextEmbedderFactory
from agent.rag.generation.answer_generator import AnswerGenerator
from agent.rag.generation.evidence_statement_generator import EvidenceStatementGeneratorFactory
from agent.rag.retrieval.hybrid_retriever import HybridEvidenceRetriever
from agent.rag.retrieval.local_reranker import LocalBgeRerankerV2M3
from agent.rag.schemas import (
    ChatModelConfig,
    EmbeddingProvider,
    LocalEmbeddingConfig,
    LocalEmbeddingModel,
    LocalModelDevice,
    LocalRerankerConfig,
    LocalRerankerModel,
    RagRetrievalPolicy,
    TextEmbeddingConfig,
)
from agent.schemas import ExecutionLimits, RegisterRoomRequest
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

    def __init__(self, limit: int | None = None) -> None:
        Utf8ConsoleConfigurator().configure()
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
        print(DIVIDER_LINE)


if __name__ == "__main__":
    asyncio.run(InteractiveTwoLayerRagCli.main())
