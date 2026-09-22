"""운영용 Agent `ChatService`를 조립한다.

Agent는 DB 세션과 저장소를 모르고, Backend가 구현한 어댑터를 주입받는다. 여기서는 그 어댑터들을
모아 `ProductionAgentFactory`에 넘긴다. 설정(OpenAI 키, 로컬 임베딩·리랭커)은
`AgentConfigurationAssembler`가 Agent 설정으로 바꾼다.

주입하지 않는 것:
- 루틴 계획기: Agent가 채팅 모델 설정으로 직접 만든다(기본 LLM 플래너로 충분하다는 합의 전까지
  별도 구현을 만들지 않는다).
- Claim 검색기: 피부 고민형 기본 경로는 NIA Case 검색을 쓰고, 오프라인 Claim index는 별도 승인된
  비교 경로에서만 쓴다(`docs/contracts/backend-to-agent.md` 10.7절).
"""

from datetime import timedelta

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.factory import (
    CheckpointSerializerFactory,
    ProductionAgentDependencies,
    ProductionAgentFactory,
)
from agent.schemas import ExecutionLimits
from agent.service import ChatService
from backend.services.agent_configuration import AgentConfigurationAssembler
from backend.services.chat_history import SqlAlchemyChatHistoryRepository
from backend.services.two_layer_rag_adapters import (
    BackendNiaCaseRetriever,
    TwoLayerEvidenceSearchBackend,
    TwoLayerIngredientRepository,
    TwoLayerProductRepository,
    TwoLayerProductTaxonomyProvider,
)
from core.config import AgentSettings, OpenAiConfig

# Agent 기본 제한(10초)은 첫 요청에서 로컬 임베딩·리랭커 모델을 올리고 LLM을 여러 번 부르는
# 경로에는 항상 부족해 TimeoutError가 났다. Agent 파트 통합 CLI가 같은 경로로 검증한 값을 그대로
# 쓴다(`tests/agent/interactive_two_layer_rag_cli.py`).
EXECUTION_TIMEOUT_SECONDS = 180.0
EXECUTION_MAX_TOOL_CALLS = 50
EXECUTION_RECURSION_LIMIT = 80


class ChatAgentAssembler:
    """DB 어댑터와 설정으로 운영용 `ChatService`를 만든다. 모델 파일은 첫 사용 때 불러온다."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        openai: OpenAiConfig | None,
        agent: AgentSettings,
        configuration: AgentConfigurationAssembler | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._openai = openai
        self._agent = agent
        self._configuration = configuration or AgentConfigurationAssembler()

    async def create(self) -> ChatService:
        config = self._configuration.create(self._openai, self._agent)
        # 상품 분류는 DB에 적재된 값을 읽는다. 읽지 못하면 임의 분류로 대체하지 않고 실패한다.
        taxonomy = await TwoLayerProductTaxonomyProvider(self._session_factory).load()
        dependencies = ProductionAgentDependencies(
            # 진행 중인 턴을 실패로 보는 시간은 Agent 실행 제한 + 여유다. 제한을 늘렸는데 이 값을
            # 그대로 두면 정상 처리 중인 요청을 서버가 죽은 것으로 오판한다.
            history=SqlAlchemyChatHistoryRepository(
                self._session_factory,
                stale_after=timedelta(
                    seconds=EXECUTION_TIMEOUT_SECONDS
                    + SqlAlchemyChatHistoryRepository.STALE_MARGIN_SECONDS
                ),
            ),
            products=TwoLayerProductRepository(self._session_factory),
            product_taxonomy=taxonomy,
            ingredients=TwoLayerIngredientRepository(self._session_factory),
            case_retriever=BackendNiaCaseRetriever(self._session_factory),
            search_backend=TwoLayerEvidenceSearchBackend(self._session_factory),
            # 체크포인터 운영 저장소는 보류 결정에 따라 Agent가 쓰는 InMemorySaver를 그대로 쓴다.
            # 대화 기억은 체크포인트가 아니라 chat_room의 세션 스냅샷이 맡는다.
            checkpointer=InMemorySaver(serde=CheckpointSerializerFactory().create()),
        )
        limits = ExecutionLimits(
            max_tool_calls=EXECUTION_MAX_TOOL_CALLS,
            timeout_seconds=EXECUTION_TIMEOUT_SECONDS,
            recursion_limit=EXECUTION_RECURSION_LIMIT,
        )
        return (
            ProductionAgentFactory().create(dependencies, config, execution_limits=limits).service
        )
