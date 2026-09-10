"""저장소를 선택하지 않는 에이전트 조립과 DB 없는 개발용 조립.

새 RAG(50ca083)의 검색·생성은 현재 EvidencePipeline 계약으로 연결한다.
HybridEvidenceRetriever(backend, embedder, policy)와 AnswerGenerator(claim_client)를
EvidencePipeline에 전달하고 AgentDependencies로 주입하면 동일한 멀티턴 그래프를 쓴다.
검색 정책의 관련성 임계값과 모델명은 호출자가 결정한다. 설정 파일은 읽지 않는다.
외부 체크포인터에는 CheckpointSerializerFactory의 직렬화 허용 타입을 적용해야 한다.
"""

import inspect
from types import ModuleType

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import ConfigDict

import agent.rag.schemas as rag_schemas
import agent.schemas as agent_schemas
from agent.adapters import (
    FakeLlmClient,
    FixtureEvidenceRetriever,
    FixtureIngredientRepository,
    FixtureProductRepository,
    FixtureRoutinePlanner,
    InMemoryChatHistoryRepository,
)
from agent.context import ContextBuilder, ConversationSummarizer
from agent.graph import AgentGraphFactory, AgentGraphRouter
from agent.nodes import AgentNodes
from agent.ports import (
    ChatHistoryRepository,
    IngredientRepository,
    LlmClient,
    ProductRepository,
    RoutinePlanner,
)
from agent.prompts import PromptCatalog
from agent.rag.generation.answer_generator import AnswerGenerator
from agent.rag.pipeline import EvidenceApplicabilityEvaluator, EvidencePipeline
from agent.rag.ports import EvidenceRetriever
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
    ) -> None:
        self._execution_limits = execution_limits or ExecutionLimits()
        self._context_limits = context_limits or ContextLimits()
        self._history = history
        self._llm = llm
        self._ingredient_repository = ingredient_repository
        self._evidence_retriever = evidence_retriever
        self._answer_generator = answer_generator

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
                products=FixtureProductRepository(),
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
