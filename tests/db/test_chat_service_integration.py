"""Agent `ChatService`에 실제 DB 히스토리 구현을 끼워 한 턴을 끝까지 돌려 검증한다.

`tests/db/test_chat_history.py`는 포트 메서드를 하나씩 직접 부른다. 여기서는 Agent가 정한
호출 순서(방 확인, 턴 시작, 문맥 복원, 그래프 실행, 임시 저장, 확정)로 우리 구현이 동작하는지 본다.

Agent 코드는 수정하지 않는다. `DevelopmentAgentFactory`는 히스토리를 인메모리 타입으로 고정해 두어
그 아래 단계인 `AgentFactory`에 개발용 부품을 직접 조립한다. `session` 픽스처의 SAVEPOINT 위에서
돌아 로컬 DB에 데이터가 남지 않는다.
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.adapters import (
    FakeLlmClient,
    FixtureClaimRetriever,
    FixtureEvidenceRetriever,
    FixtureIngredientRepository,
    FixtureProductRepository,
    FixtureProductTaxonomy,
    FixtureRoutinePlanner,
)
from agent.factory import AgentDependencies, AgentFactory, CheckpointSerializerFactory
from agent.rag.claim_schemas import DEVELOPMENT_CLAIM_ANNOTATION_VERSION
from agent.rag.pipeline import EvidenceApplicabilityEvaluator, EvidencePipeline
from agent.rag.schemas import ProductCandidateSet, RoutinePlan
from agent.schemas import (
    ArtifactLookupRequest,
    AuthenticatedChatContext,
    AuthorizedRoom,
    ChatServiceRequest,
    ChatStatus,
    ChatTurnInput,
    ChatTurnOutput,
    ErrorCode,
    MessagePageRequest,
    MessageRole,
    SessionContextRequest,
)
from agent.service import ChatService
from backend.repositories.chat_room_repository import ChatRoomRepository
from backend.services.chat_history import SqlAlchemyChatHistoryRepository
from models.chat_room import ChatRoom
from tests.db.test_chat_history import ChatHistoryFixtures


class SqlHistoryAgentFactory:
    """개발용 부품 위에 DB 히스토리만 바꿔 끼운 `ChatService`를 만든다."""

    def create(self, history: SqlAlchemyChatHistoryRepository) -> ChatService:
        evidence_pipeline = EvidencePipeline(
            retriever=FixtureEvidenceRetriever(),
            evaluator=EvidenceApplicabilityEvaluator(),
            generator=None,
        )
        return AgentFactory().create(
            AgentDependencies(
                llm=FakeLlmClient(),
                history=history,
                products=FixtureProductRepository(),
                product_taxonomy=FixtureProductTaxonomy().create(),
                ingredients=FixtureIngredientRepository(),
                claim_retriever=FixtureClaimRetriever(),
                claim_annotation_version=DEVELOPMENT_CLAIM_ANNOTATION_VERSION,
                evidence_pipeline=evidence_pipeline,
                routine_planner=FixtureRoutinePlanner(),
                checkpointer=InMemorySaver(serde=CheckpointSerializerFactory().create()),
            )
        )


class ChatRequestFactory:
    def create(
        self, room: AuthorizedRoom, request_id: str, message: str, *, actor_id: str | None = None
    ) -> ChatServiceRequest:
        return ChatServiceRequest(
            auth=AuthenticatedChatContext(
                actor_id=actor_id or room.actor_id, chat_room_id=room.chat_room_id
            ),
            turn=ChatTurnInput(
                chat_room_id=room.chat_room_id, request_id=request_id, message=message
            ),
        )


@pytest_asyncio.fixture
async def chat_room(session: AsyncSession) -> ChatRoom:
    user = await ChatHistoryFixtures().create_user(session)
    return await ChatRoomRepository(session).get_or_create_for_user(user.id)


@pytest.fixture
def history(session: AsyncSession) -> SqlAlchemyChatHistoryRepository:
    factory = async_sessionmaker(
        bind=session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    return SqlAlchemyChatHistoryRepository(factory)


@pytest.fixture
def service(history: SqlAlchemyChatHistoryRepository) -> ChatService:
    return SqlHistoryAgentFactory().create(history)


@pytest.fixture
def room(chat_room: ChatRoom) -> AuthorizedRoom:
    return ChatHistoryFixtures().room(chat_room)


class TestChatServiceWithDatabaseHistory:
    requests = ChatRequestFactory()

    async def test_turn_completes_and_persists_both_messages(
        self,
        service: ChatService,
        history: SqlAlchemyChatHistoryRepository,
        room: AuthorizedRoom,
    ) -> None:
        output = await service.handle_turn(
            self.requests.create(room, "r1", "가벼운 보습 크림 추천해줘")
        )

        page = await history.get_messages(MessagePageRequest(room=room))
        assert output.status is ChatStatus.COMPLETED
        assert any(isinstance(artifact, ProductCandidateSet) for artifact in output.artifacts)
        assert [message.role for message in page.messages] == [
            MessageRole.USER,
            MessageRole.ASSISTANT,
        ]
        assert page.messages[1].message_id == output.assistant_message_id

    async def test_same_request_returns_stored_output_without_duplicate_messages(
        self,
        service: ChatService,
        history: SqlAlchemyChatHistoryRepository,
        room: AuthorizedRoom,
    ) -> None:
        request = self.requests.create(room, "r1", "가벼운 보습 크림 추천해줘")
        first = await service.handle_turn(request)

        replay = await service.handle_turn(request)

        page = await history.get_messages(MessagePageRequest(room=room))
        assert replay == first
        assert len(page.messages) == 2

    async def test_pending_question_survives_database_round_trip(
        self, service: ChatService, room: AuthorizedRoom
    ) -> None:
        question = await service.handle_turn(
            self.requests.create(room, "q1", "이 제품들 어떻게 써?")
        )
        answer = await service.handle_turn(
            self.requests.create(room, "q2", "데모 세라마이드 크림과 데모 판테놀 젤 크림이야")
        )

        assert question.status is ChatStatus.NEEDS_INPUT
        assert answer.status is ChatStatus.COMPLETED
        assert any(isinstance(artifact, RoutinePlan) for artifact in answer.artifacts)

    async def test_session_snapshot_is_restored_for_next_turn(
        self,
        service: ChatService,
        history: SqlAlchemyChatHistoryRepository,
        room: AuthorizedRoom,
    ) -> None:
        await service.handle_turn(self.requests.create(room, "r1", "가벼운 보습 크림 추천해줘"))

        context = await history.get_session_context(SessionContextRequest(room=room))

        assert context.snapshot is not None
        assert context.snapshot.source_revision == 1
        assert context.snapshot.candidate_set is not None

    async def test_completed_artifact_can_be_found_by_id_later(
        self,
        service: ChatService,
        history: SqlAlchemyChatHistoryRepository,
        room: AuthorizedRoom,
    ) -> None:
        output = await service.handle_turn(
            self.requests.create(room, "r1", "가벼운 보습 크림 추천해줘")
        )
        candidate_set = next(
            artifact for artifact in output.artifacts if isinstance(artifact, ProductCandidateSet)
        )

        found = await history.get_artifacts(
            ArtifactLookupRequest(room=room, candidate_set_id=candidate_set.candidate_set_id)
        )

        assert found.artifacts == [candidate_set]

    async def test_other_users_room_is_forbidden(
        self, service: ChatService, room: AuthorizedRoom
    ) -> None:
        output: ChatTurnOutput = await service.handle_turn(
            self.requests.create(room, "r1", "안녕", actor_id=str(uuid4()))
        )

        assert output.status is ChatStatus.ERROR
        assert output.error_code is ErrorCode.ROOM_FORBIDDEN
