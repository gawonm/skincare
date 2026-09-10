"""DB와 API 키 없이 실행할 개발용 에이전트 조립."""

import inspect
from types import ModuleType

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
from agent.ports import IngredientRepository, LlmClient
from agent.prompts import PromptCatalog
from agent.rag.pipeline import EvidenceApplicabilityEvaluator, EvidencePipeline
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


class DevelopmentAgentApplication(AgentModel):
    """데모와 테스트에서 상태 주입을 확인할 수 있는 조립 결과."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    service: ChatService
    history: InMemoryChatHistoryRepository
    evidence_retriever: FixtureEvidenceRetriever
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
    ) -> None:
        self._execution_limits = execution_limits or ExecutionLimits()
        self._context_limits = context_limits or ContextLimits()
        self._history = history
        self._llm = llm
        self._ingredient_repository = ingredient_repository

    def create(self) -> DevelopmentAgentApplication:
        history = self._history or InMemoryChatHistoryRepository()
        evidence_retriever = FixtureEvidenceRetriever()
        checkpointer = InMemorySaver(serde=CheckpointSerializerFactory().create())
        evidence_pipeline = EvidencePipeline(
            retriever=evidence_retriever,
            evaluator=EvidenceApplicabilityEvaluator(),
        )
        nodes = AgentNodes(
            llm=self._llm or FakeLlmClient(),
            product_repository=FixtureProductRepository(),
            ingredient_repository=self._ingredient_repository or FixtureIngredientRepository(),
            evidence_pipeline=evidence_pipeline,
            routine_planner=FixtureRoutinePlanner(),
            context_builder=ContextBuilder(ConversationSummarizer()),
            prompt_catalog=PromptCatalog(),
        )
        graph = AgentGraphFactory(
            nodes=nodes,
            router=AgentGraphRouter(),
            checkpointer=checkpointer,
        ).create()
        service = ChatService(
            graph=graph,
            history=history,
            identity_factory=RequestIdentityFactory(),
            execution_limits=self._execution_limits,
            context_limits=self._context_limits,
        )
        return DevelopmentAgentApplication(
            service=service,
            history=history,
            evidence_retriever=evidence_retriever,
            checkpointer=checkpointer,
        )
