"""agent 패키지(`agent/service.py`, `agent/graph.py`, `agent/factory.py`)의 실제 대화 워크플로우를 테스트하는 CLI.

LangGraph 기반의 의도 해석, 성분 매핑, RAG 근거 검색, 답변 생성 및 세션 히스토리를
실제 PostgreSQL DB(pgvector + BM25), 설정된 임베더 및 로컬 리랭커와 연동한다.
제품·분류·루틴은 개발 fixture이며, 히스토리는 실행 중 메모리에만 유지한다.
문서 적재·청킹과 운영 DB 히스토리 저장은 이 CLI의 검증 범위가 아니다.

단일 질의 실행:
    uv run python -m tests.agent.interactive_rag_cli "나이아신아마이드와 비타민C의 효능과 주의사항을 알려줘"

대화형 프롬프트 실행:
    uv run python -m tests.agent.interactive_rag_cli
"""

import asyncio
import sys
import traceback
from enum import StrEnum
from typing import Final

from openai import APIError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from agent.factory import DevelopmentAgentApplication, DevelopmentAgentFactory
from agent.llm import OpenAiLlmClient
from agent.ports import IngredientRepository
from agent.rag.embedding.factory import TextEmbedderFactory
from agent.rag.generation.answer_generator import AnswerGenerator
from agent.rag.generation.openai_generator import OpenAiClaimGenerator
from agent.rag.ports import EvidenceRetriever, HybridSearchBackend
from agent.rag.retrieval.hybrid_retriever import HybridEvidenceRetriever
from agent.rag.retrieval.local_reranker import LocalBgeRerankerV2M3
from agent.rag.schemas import (
    EvidenceSearchRequest,
    EvidenceSearchResult,
    HybridSearchRequest,
    HybridSearchResult,
    IngredientRecord,
    IngredientResolveRequest,
    IngredientResolveResult,
    LookupStatus,
    RetrievedChunk,
)
from agent.schemas import (
    AuthenticatedChatContext,
    ChatServiceRequest,
    ChatTurnInput,
    ChatTurnOutput,
    RegisterRoomRequest,
)
from backend.services.agent_configuration import AgentConfigurationAssembler
from backend.services.rag_search_backend import SqlAlchemyHybridSearchBackend
from core.config import settings
from core.database import Database
from models.ingredient import IngredientMaster

DIVIDER_LINE: Final[str] = "=" * 70
SUB_DIVIDER_LINE: Final[str] = "-" * 70


class CliCommand(StrEnum):
    """대화형 인터페이스 제어 명령어."""

    EXIT = "exit"
    QUIT = "quit"
    Q = "q"


class DbIngredientRepository(IngredientRepository):
    """실제 PostgreSQL `ingredient_master` 테이블을 조회하여 UUID를 제공하는 성분 저장소 어댑터.

    기본 `FixtureIngredientRepository`의 임의 ID("ingredient:niacinamide") 대신
    실제 DB의 UUID를 반환해야 Backend의 `SqlAlchemyHybridSearchBackend`가 DB 레벨에서
    정상적으로 대상 성분 ID(`target_ids`) 필터링을 수행할 수 있다.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    async def resolve(self, request: IngredientResolveRequest) -> IngredientResolveResult:
        # 대화 상태와 DB 세션 수명을 분리해 입력 대기 중 트랜잭션을 붙잡지 않는다.
        async with self._database.session_factory() as session:
            return await self._resolve(session, request)

    async def _resolve(
        self, session: AsyncSession, request: IngredientResolveRequest
    ) -> IngredientResolveResult:
        name = request.name.strip()
        # 1. 표준명/영문명/정규화명 완전 일치 우선 조회
        stmt = (
            select(IngredientMaster)
            .where(
                or_(
                    IngredientMaster.standard_name_ko == name,
                    IngredientMaster.standard_name_en.ilike(name),
                    IngredientMaster.normalized_name_ko == name,
                )
            )
            .limit(2)
        )
        res = await session.execute(stmt)
        rows = res.scalars().all()

        # 2. 완전 일치가 없으면 부분 일치로 후보 검색
        if not rows:
            stmt = (
                select(IngredientMaster)
                .where(
                    or_(
                        IngredientMaster.standard_name_ko.ilike(f"%{name}%"),
                        IngredientMaster.standard_name_en.ilike(f"%{name}%"),
                    )
                )
                .limit(5)
            )
            res = await session.execute(stmt)
            rows = res.scalars().all()

        if not rows:
            return IngredientResolveResult(status=LookupStatus.NO_RESULTS)

        candidates = [
            IngredientRecord(
                ingredient_id=str(row.id),
                canonical_name=row.standard_name_ko,
                aliases=[row.standard_name_en] if row.standard_name_en else [],
                source_version=row.source_version,
                is_demo=False,
            )
            for row in rows
        ]

        if len(candidates) == 1:
            return IngredientResolveResult(status=LookupStatus.SUCCESS, ingredient=candidates[0])
        return IngredientResolveResult(status=LookupStatus.SUCCESS, ambiguous_candidates=candidates)


class SessionSearchBackend(HybridSearchBackend):
    """서비스는 재사용하되 DB 검색마다 독립 세션을 사용한다."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def search(self, request: HybridSearchRequest) -> HybridSearchResult:
        async with self._database.session_factory() as session:
            return await SqlAlchemyHybridSearchBackend(session).search(request)


class RagSearchTrace(BaseModel):
    """재검색 없이 실제 파이프라인 요청·결과를 보존한다."""

    request: EvidenceSearchRequest
    result: EvidenceSearchResult | None = None


class RecordingEvidenceRetriever(EvidenceRetriever):
    def __init__(self, retriever: EvidenceRetriever, limit: int | None = None) -> None:
        if limit is not None and limit < 1:
            raise ValueError("검색 개수는 1 이상이어야 합니다.")
        self._retriever = retriever
        self._limit = limit
        self._traces: list[RagSearchTrace] = []

    def reset(self) -> None:
        self._traces.clear()

    def snapshot(self) -> list[RagSearchTrace]:
        return [trace.model_copy(deep=True) for trace in self._traces]

    async def search(self, request: EvidenceSearchRequest) -> EvidenceSearchResult:
        effective_request = request.model_copy(deep=True)
        if self._limit is not None:
            effective_request.limit = self._limit
        trace = RagSearchTrace(request=effective_request.model_copy(deep=True))
        # 호출 전에 기록해야 예외·취소로 결과가 없는 검색도 무결과와 구분할 수 있다.
        self._traces.append(trace)
        result = await self._retriever.search(effective_request)
        trace.result = result.model_copy(deep=True)
        return result


class AgentTurnResult(BaseModel):
    """한 번의 대화 턴에 대한 LangGraph 실행 출력 및 RAG 검색 상세 정보."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    turn_output: ChatTurnOutput
    rag_chunks: list[RetrievedChunk] = Field(default_factory=list)
    searches: list[RagSearchTrace] = Field(default_factory=list)


class InteractiveAgentCli:
    """`agent` 디렉토리의 LangGraph 워크플로우와 `ChatService`를 직접 가동하는 대화형 테스트 클래스.

    모든 상태(LLM, 임베더, 세션, DB 연결)를 클래스 내부에 캡슐화한다.
    """

    def __init__(self, limit: int | None = None) -> None:
        self._actor_id = "cli-user"
        self._chat_room_id = "cli-chat-room"
        self._thread_id = "cli-thread"
        self._turn_sequence = 0
        self._turn_lock = asyncio.Lock()
        self._closed = False
        # 운영과 같은 설정 변환을 사용해 기본 임계값·키 누락·DB 차원 검사를 공유한다.
        self._config = AgentConfigurationAssembler().create(settings.openai, settings.agent)
        self._llm = OpenAiLlmClient(self._config.openai)
        self._embedder = TextEmbedderFactory().create(self._config.embedding)
        self._reranker = LocalBgeRerankerV2M3(self._config.reranker)
        self._database = Database(settings.database)
        self._retriever = RecordingEvidenceRetriever(
            HybridEvidenceRetriever(
                backend=SessionSearchBackend(self._database),
                embedder=self._embedder,
                policy=self._config.retrieval_policy,
                reranker=self._reranker,
            ),
            limit=limit,
        )
        self._app: DevelopmentAgentApplication = DevelopmentAgentFactory(
            llm=self._llm,
            ingredient_repository=DbIngredientRepository(self._database),
            evidence_retriever=self._retriever,
            answer_generator=AnswerGenerator(OpenAiClaimGenerator(self._config.openai)),
        ).create()
        self._app.history.register_room(
            RegisterRoomRequest(
                actor_id=self._actor_id,
                chat_room_id=self._chat_room_id,
                thread_id=self._thread_id,
            )
        )

    async def handle_message(self, user_message: str) -> AgentTurnResult:
        """한 번의 사용자 메시지를 `ChatService`로 보내고 실제 LangGraph를 통과시킨다."""
        async with self._turn_lock:
            if self._closed:
                raise RuntimeError("종료된 CLI에서는 새 대화를 처리할 수 없습니다.")
            self._turn_sequence += 1
            request_id = f"cli-req-{self._turn_sequence}"
            self._retriever.reset()
            request = ChatServiceRequest(
                auth=AuthenticatedChatContext(
                    actor_id=self._actor_id,
                    chat_room_id=self._chat_room_id,
                ),
                turn=ChatTurnInput(
                    chat_room_id=self._chat_room_id,
                    request_id=request_id,
                    message=user_message,
                ),
            )
            turn_output = await self._app.service.handle_turn(request)
            searches = self._retriever.snapshot()
            return AgentTurnResult(
                turn_output=turn_output,
                searches=searches,
                rag_chunks=[
                    hit
                    for trace in searches
                    if trace.result is not None
                    for hit in trace.result.chunks
                ],
            )

    def print_turn(self, result: AgentTurnResult, user_message: str) -> None:
        """LangGraph 실행 결과(의도, 메시지, 인용, RAG 검색 청크)를 명확히 출력한다."""
        output = result.turn_output

        print(f"\n{DIVIDER_LINE}")
        print(f" 사용자 입력: {user_message}")
        intents_str = ", ".join(intent.value for intent in output.intents)
        print(f"🧠 LangGraph 의도 판정: [{intents_str}] | 상태: {output.status.value}")
        print(DIVIDER_LINE)

        if not result.searches:
            print("\n[검색 미실행] 이번 턴은 RAG 검색을 호출하지 않았습니다.")
        for index, trace in enumerate(result.searches, 1):
            print(f"\n[검색 {index}] 질의: {trace.request.query}")
            print(f"    - 대상 ID: {trace.request.target_ids}")
            print(f"    - 병용 대상 ID: {trace.request.combination_target_ids}")
            print(f"    - 조건: {trace.request.known_conditions.model_dump_json()}")
            print(f"    - 대상별 검색 개수: {trace.request.limit}")
            if trace.result is None:
                print("    - 결과 미수신: 검색이 예외 또는 취소로 중단되었습니다.")
                continue
            print(f"    - 상태: {trace.result.status.value}")
            print(f"    - 반환 청크: {[hit.chunk.chunk_id for hit in trace.result.chunks]}")
            print(f"    - 실행된 리랭커: {trace.result.reranker_model or '없음 (실행 안 됨)'}")
            if trace.result.error_message:
                print(f"    - 검색 오류/미지원 사유: {trace.result.error_message}")

        # 검색 후보와 인용 채택을 구분해야 검수·조건 검사로 제외된 자료를 오해하지 않는다.
        if result.rag_chunks:
            print("\n[📚 실제 검색 반환 청크 — 최종 답변 채택 여부는 인용과 대조]")
            for i, hit in enumerate(result.rag_chunks, 1):
                vec_sim = (
                    f"{hit.vector_similarity:.4f}" if hit.vector_similarity is not None else "N/A"
                )
                bm25 = f"{hit.bm25_relevance:.4f}" if hit.bm25_relevance is not None else "N/A"
                rerank = f"{hit.reranker_score:.4f}" if hit.reranker_score is not None else "N/A"
                print(f"\n({i}) 출처: {hit.chunk.evidence.source_title}")
                print(f"    - 청크 ID: {hit.chunk.chunk_id}")
                print(f"    - 근거 ID: {hit.chunk.evidence.evidence_id}")
                print(f"    - 검수 상태: {hit.chunk.evidence.review_status.value}")
                print(f"    - 점수: RRF={hit.fused_score:.5f} | 벡터유사도={vec_sim} | BM25={bm25}")
                print(f"    - 리랭커 점수: {rerank}")
                print(f"    - 내용: {hit.chunk.content.strip()[:140]}...")

        # 2. Agent의 최종 응답 메시지 출력
        print(f"\n{SUB_DIVIDER_LINE}")
        print("[🤖 Agent 최종 응답]")
        print(output.message)
        if output.error_code is not None:
            print(f"오류 코드: {output.error_code.value} | 재시도 가능: {output.retryable}")
        if output.follow_up_question:
            print(f"추가 질문: {output.follow_up_question}")

        # 3. 인용 문헌이 있는 경우 출력
        if output.citations:
            print("\n[📖 인용된 근거 목록]")
            for citation in output.citations:
                print(f" - {citation.source_title} | 근거 ID: {citation.evidence_id}")
                print(f"   출처 ID: {citation.source_id} | 위치: {citation.locator}")
                if citation.url:
                    print(f"   URL: {citation.url}")

        # 4. 미해결 항목(가드레일 알림 등)이 있는 경우 출력
        if output.unresolved:
            print("\n[⚠️ 미해결/보류 사유]")
            for item in output.unresolved:
                print(f" - [{item.kind.value}] {item.detail}")

        print(DIVIDER_LINE)

    def print_runtime(self) -> None:
        """실제 연결 범위를 표시해 개발용 응답을 운영 검증으로 오인하지 않게 한다."""
        print(f"\n{DIVIDER_LINE}")
        print(" 스킨케어 Agent & RAG 대화형 CLI 도구")
        print(f"Intent·답변 모델: {self._config.openai.model.value}")
        print(f"임베딩 provider: {self._config.embedding.provider.value}")
        print(f"임베딩 차원: {self._config.embedding.output_dimensions()}")
        print(f"로컬 리랭커: {self._config.reranker.model.value}")
        print("성분·RAG: 실제 DB / 제품·분류·루틴: 개발 fixture")
        print("히스토리·체크포인터: 실행 중 메모리 유지, 종료 시 소멸")
        print("문서 적재·청킹·운영 저장은 검증하지 않습니다.")
        print("실제 API 호출 비용이 발생하며, 첫 리랭킹 때 모델 로드/다운로드가 필요합니다.")
        print(DIVIDER_LINE)

    async def run_loop(self) -> None:
        """대화형 프롬프트 루프를 실행한다."""
        print("`agent/service.py`의 `ChatService`와 LangGraph 워크플로우를 직접 실행합니다.")
        print("성분 문의, 제품 추천, 루틴 상담 등을 자유롭게 입력해보세요.")
        print("종료하려면 'exit', 'quit', 또는 'q'를 입력하세요.")
        print(DIVIDER_LINE)

        try:
            while True:
                try:
                    user_input = input("\n사용자 입력 > ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n대화를 종료합니다.")
                    break

                if not user_input:
                    continue

                if user_input.casefold() in {CliCommand.EXIT, CliCommand.QUIT, CliCommand.Q}:
                    print("대화를 종료합니다.")
                    break

                print("⚙️  LangGraph 워크플로우 실행 중...")
                try:
                    result = await self.handle_message(user_input)
                    self.print_turn(result, user_input)
                except (APIError, SQLAlchemyError, OSError, RuntimeError, TypeError, ValueError):
                    # 예상 가능한 외부 실패는 원인을 남기고 다음 입력을 받을 수 있게 한다.
                    traceback.print_exc()
        finally:
            await self.close()

    async def close(self) -> None:
        """리소스 정리."""
        async with self._turn_lock:
            if not self._closed:
                await self._database.dispose()
                self._closed = True

    @classmethod
    async def main(cls) -> None:
        cli = cls()
        try:
            cli.print_runtime()
            if len(sys.argv) > 1:
                user_message = " ".join(sys.argv[1:]).strip()
                result = await cli.handle_message(user_message)
                cli.print_turn(result, user_message)
            else:
                await cli.run_loop()
        finally:
            await cli.close()


if __name__ == "__main__":
    asyncio.run(InteractiveAgentCli.main())
