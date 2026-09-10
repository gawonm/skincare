"""저장소를 선택하지 않는 운영 조립과 DB 없는 개발용 조립.

운영 조립은 GPT-4o mini 기반 Intent·답변 생성과 로컬 BGE 검색 모델을 연결한다.
검색 임계값과 API 키는 호출자가 구조화 설정으로 전달하며 이 모듈은 설정 파일을 읽지 않는다.
외부 체크포인터에는 CheckpointSerializerFactory의 직렬화 허용 타입을 적용해야 한다.
"""

import inspect
from types import ModuleType

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import ConfigDict, Field

import agent.rag.schemas as rag_schemas
import agent.schemas as agent_schemas
from agent.adapters import (
    FakeLlmClient,
    FixtureEvidenceRetriever,
    FixtureIngredientRepository,
    FixtureProductRepository,
    FixtureProductTaxonomy,
    FixtureRoutinePlanner,
    InMemoryChatHistoryRepository,
)
from agent.context import ContextBuilder, ConversationSummarizer
from agent.graph import AgentGraphFactory, AgentGraphRouter
from agent.llm import OpenAiLlmClient
from agent.nodes import AgentNodes
from agent.ports import (
    ChatHistoryRepository,
    IngredientRepository,
    LlmClient,
    ProductRepository,
    RoutinePlanner,
)
from agent.prompts import PromptCatalog
from agent.rag.embedding.local_embedder import LocalBgeM3Embedder
from agent.rag.generation.answer_generator import AnswerGenerator
from agent.rag.generation.openai_generator import OpenAiClaimGenerator
from agent.rag.pipeline import EvidenceApplicabilityEvaluator, EvidencePipeline
from agent.rag.ports import EvidenceReranker, EvidenceRetriever, HybridSearchBackend, TextEmbedder
from agent.rag.retrieval.hybrid_retriever import HybridEvidenceRetriever
from agent.rag.retrieval.local_reranker import LocalBgeRerankerV2M3
from agent.rag.schemas import (
    LocalEmbeddingConfig,
    LocalRerankerConfig,
    OpenAiChatConfig,
    ProductTaxonomy,
    RagRetrievalPolicy,
)
from agent.schemas import AgentModel, ContextLimits, ExecutionLimits
from agent.service import ChatService, RequestIdentityFactory


class CheckpointSerializerFactory:
    """체크포인트에서 복원할 수 있는 프로젝트 타입을 명시적으로 제한한다."""

    def create(self) -> JsonPlusSerializer:
        allowed_types = self._module_types(agent_schemas) + self._module_types(rag_schemas)
        return JsonPlusSerializer(allowed_msgpack_modules=allowed_types)

    def _module_types(self, module: ModuleType) -> list[type[object]]:
        return [
            member
            for _, member in inspect.getmembers(module, inspect.isclass)
            if member.__module__ == module.__name__
        ]


class AgentDependencies(AgentModel):
    """DB 스키마·세션·체크포인트 저장소를 agent가 결정하지 않도록 조립 시 전달받는다."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    llm: LlmClient
    history: ChatHistoryRepository
    products: ProductRepository
    product_taxonomy: ProductTaxonomy
    ingredients: IngredientRepository
    routine_planner: RoutinePlanner
    evidence_pipeline: EvidencePipeline
    checkpointer: BaseCheckpointSaver


class AgentFactory:
    def create(
        self,
        dependencies: AgentDependencies,
        execution_limits: ExecutionLimits | None = None,
        context_limits: ContextLimits | None = None,
    ) -> ChatService:
        nodes = AgentNodes(
            llm=dependencies.llm,
            product_repository=dependencies.products,
            ingredient_repository=dependencies.ingredients,
            evidence_pipeline=dependencies.evidence_pipeline,
            routine_planner=dependencies.routine_planner,
            context_builder=ContextBuilder(ConversationSummarizer()),
            prompt_catalog=PromptCatalog(),
            product_taxonomy=dependencies.product_taxonomy,
        )
        graph = AgentGraphFactory(
            nodes=nodes,
            router=AgentGraphRouter(),
            checkpointer=dependencies.checkpointer,
        ).create()
        return ChatService(
            graph=graph,
            history=dependencies.history,
            identity_factory=RequestIdentityFactory(),
            execution_limits=execution_limits or ExecutionLimits(),
            context_limits=context_limits or ContextLimits(),
        )


class ProductionAgentConfig(AgentModel):
    """운영 모델 선택과 검색 정책. OpenAI 키는 SecretStr 상태로만 전달한다."""

    openai: OpenAiChatConfig
    embedding: LocalEmbeddingConfig = Field(default_factory=LocalEmbeddingConfig)
    reranker: LocalRerankerConfig = Field(default_factory=LocalRerankerConfig)
    retrieval_policy: RagRetrievalPolicy


class ProductionAgentDependencies(AgentModel):
    """운영 조립이 소유하지 않는 저장소·검색 백엔드·체크포인터 계약."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    history: ChatHistoryRepository
    products: ProductRepository
    product_taxonomy: ProductTaxonomy
    ingredients: IngredientRepository
    routine_planner: RoutinePlanner
    search_backend: HybridSearchBackend
    checkpointer: BaseCheckpointSaver


class ProductionAgentApplication(AgentModel):
    """운영 상태 점검과 임베딩 적재에서 같은 모델 인스턴스를 재사용하는 조립 결과."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    service: ChatService
    embedder: TextEmbedder
    reranker: EvidenceReranker
    evidence_retriever: EvidenceRetriever


class ProductionAgentFactory:
    """GPT 호출과 로컬 검색 모델을 한 지점에서 명시적으로 조립한다."""

    def create(
        self,
        dependencies: ProductionAgentDependencies,
        config: ProductionAgentConfig,
        execution_limits: ExecutionLimits | None = None,
        context_limits: ContextLimits | None = None,
    ) -> ProductionAgentApplication:
        embedder = LocalBgeM3Embedder(config.embedding)
        reranker = LocalBgeRerankerV2M3(config.reranker)
        evidence_retriever = HybridEvidenceRetriever(
            backend=dependencies.search_backend,
            embedder=embedder,
            policy=config.retrieval_policy,
            reranker=reranker,
        )
        evidence_pipeline = EvidencePipeline(
            retriever=evidence_retriever,
            evaluator=EvidenceApplicabilityEvaluator(),
            generator=AnswerGenerator(OpenAiClaimGenerator(config.openai)),
        )
        service = AgentFactory().create(
            AgentDependencies(
                llm=OpenAiLlmClient(config.openai),
                history=dependencies.history,
                products=dependencies.products,
                product_taxonomy=dependencies.product_taxonomy,
                ingredients=dependencies.ingredients,
                routine_planner=dependencies.routine_planner,
                evidence_pipeline=evidence_pipeline,
                checkpointer=dependencies.checkpointer,
            ),
            execution_limits=execution_limits,
            context_limits=context_limits,
        )
        return ProductionAgentApplication(
            service=service,
            embedder=embedder,
            reranker=reranker,
            evidence_retriever=evidence_retriever,
        )


class DevelopmentAgentApplication(AgentModel):
    """데모와 테스트에서 상태 주입을 확인할 수 있는 조립 결과."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    service: ChatService
    history: InMemoryChatHistoryRepository
    evidence_retriever: EvidenceRetriever
    checkpointer: InMemorySaver


class DevelopmentAgentFactory:
    """실제 어댑터로 교체할 위치를 한 곳에 모은다."""

    def __init__(
        self,
        execution_limits: ExecutionLimits | None = None,
        context_limits: ContextLimits | None = None,
        history: InMemoryChatHistoryRepository | None = None,
        llm: LlmClient | None = None,
        ingredient_repository: IngredientRepository | None = None,
        evidence_retriever: EvidenceRetriever | None = None,
        answer_generator: AnswerGenerator | None = None,
        product_repository: ProductRepository | None = None,
        product_taxonomy: ProductTaxonomy | None = None,
    ) -> None:
        self._execution_limits = execution_limits or ExecutionLimits()
        self._context_limits = context_limits or ContextLimits()
        self._history = history
        self._llm = llm
        self._ingredient_repository = ingredient_repository
        self._evidence_retriever = evidence_retriever
        self._answer_generator = answer_generator
        self._product_repository = product_repository
        self._product_taxonomy = product_taxonomy
        if product_repository is not None and product_taxonomy is None:
            raise ValueError("상품 조회 구현을 교체할 때 지원 분류 목록도 함께 전달해야 합니다.")

    def create(self) -> DevelopmentAgentApplication:
        history = self._history or InMemoryChatHistoryRepository()
        evidence_retriever = self._evidence_retriever or FixtureEvidenceRetriever()
        checkpointer = InMemorySaver(serde=CheckpointSerializerFactory().create())
        evidence_pipeline = EvidencePipeline(
            retriever=evidence_retriever,
            evaluator=EvidenceApplicabilityEvaluator(),
            generator=self._answer_generator,
        )
        service = AgentFactory().create(
            AgentDependencies(
                llm=self._llm or FakeLlmClient(),
                history=history,
                products=self._product_repository or FixtureProductRepository(),
                product_taxonomy=self._product_taxonomy or FixtureProductTaxonomy().create(),
                ingredients=self._ingredient_repository or FixtureIngredientRepository(),
                evidence_pipeline=evidence_pipeline,
                routine_planner=FixtureRoutinePlanner(),
                checkpointer=checkpointer,
            ),
            execution_limits=self._execution_limits,
            context_limits=self._context_limits,
        )
        return DevelopmentAgentApplication(
            service=service,
            history=history,
            evidence_retriever=evidence_retriever,
            checkpointer=checkpointer,
        )
