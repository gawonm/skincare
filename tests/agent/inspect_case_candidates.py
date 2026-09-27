"""외부 LLM 호출 없이 NIA Case 검색·선별·리랭크 후보를 점검한다."""

import argparse
import asyncio
import re
from typing import ClassVar

from pydantic import Field

from agent.rag.case_schemas import (
    DEFAULT_CASE_CANDIDATE_LIMIT,
    CaseRerankRequest,
    CaseRerankResult,
    CaseSearchRequest,
    CaseSearchResult,
)
from agent.rag.embedding.factory import TextEmbedderFactory
from agent.rag.retrieval.case_candidate_selector import (
    CaseCandidateSelectionRequest,
    CaseCandidateSelectionResult,
    CaseMetadataCandidateSelector,
)
from agent.rag.retrieval.case_reranker import LocalBgeCaseRerankerV2M3
from agent.rag.retrieval.cross_encoder import LocalBgeCrossEncoderScorer
from agent.rag.schemas import EmbeddingRequest, LookupStatus, RagModel
from backend.services.two_layer_rag_adapters import BackendNiaCaseRetriever
from core.database import Database
from tests.agent.interactive_two_layer_rag_cli import (
    ConfiguredDatabaseFactory,
    TwoLayerAgentModelConfigFactory,
    Utf8ConsoleConfigurator,
)


class CaseCandidateInspectionArguments(RagModel):
    query: str = Field(min_length=1)
    skin_concerns: list[str] = Field(default_factory=list)


class CaseCandidateInspectionResult(RagModel):
    search: CaseSearchResult
    selection: CaseCandidateSelectionResult
    rerank: CaseRerankResult


class CaseCandidateInspectionArgumentParser:
    def parse(self) -> CaseCandidateInspectionArguments:
        parser = argparse.ArgumentParser(
            description="로컬 모델과 DB만 사용해 NIA Case 후보를 상세 점검합니다."
        )
        parser.add_argument("query", type=str)
        parser.add_argument(
            "--concern",
            action="append",
            default=[],
            dest="skin_concerns",
            help="구조화된 피부 고민. 여러 개면 --concern을 반복합니다.",
        )
        parsed = parser.parse_args()
        return CaseCandidateInspectionArguments(
            query=parsed.query,
            skin_concerns=parsed.skin_concerns,
        )


class LocalCaseCandidateInspector:
    TEXT_VERSION: ClassVar[str] = "nia_case_text/v1"

    def __init__(self, database: Database) -> None:
        config = TwoLayerAgentModelConfigFactory()
        embedding_config = config.create_embedding()
        reranker_config = config.create_reranker()
        self._embedder = TextEmbedderFactory().create(embedding_config)
        self._retriever = BackendNiaCaseRetriever(database.session_factory)
        self._selector = CaseMetadataCandidateSelector()
        self._reranker = LocalBgeCaseRerankerV2M3(
            reranker_config,
            scorer=LocalBgeCrossEncoderScorer(reranker_config),
        )

    async def inspect(
        self,
        arguments: CaseCandidateInspectionArguments,
    ) -> CaseCandidateInspectionResult:
        embedding = await self._embedder.embed(EmbeddingRequest(texts=[arguments.query]))
        search = await self._retriever.search(
            CaseSearchRequest(
                query=arguments.query,
                query_embedding=embedding.vectors[0],
                text_version=self.TEXT_VERSION,
                embedding_model=embedding.model,
                candidate_limit=DEFAULT_CASE_CANDIDATE_LIMIT,
            )
        )
        if search.status is not LookupStatus.SUCCESS:
            raise RuntimeError(
                "NIA Case 로컬 진단 검색에 실패했습니다: "
                f"status={search.status.value}, detail={search.error_message or '없음'}"
            )
        selection = self._selector.select(
            CaseCandidateSelectionRequest(
                query=arguments.query,
                skin_concerns=arguments.skin_concerns,
                candidates=search.hits,
            )
        )
        rerank = await self._reranker.rerank(
            CaseRerankRequest(
                query=arguments.query,
                candidates=selection.candidates,
            )
        )
        return CaseCandidateInspectionResult(
            search=search,
            selection=selection,
            rerank=rerank,
        )


class CaseCandidateInspectionPresenter:
    QUESTION_PREVIEW_LENGTH: ClassVar[int] = 240
    _QUESTION_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"\[질문\]\s*(.*?)(?=\n\s*\[(?:답변|추론)\]|\Z)",
        re.DOTALL,
    )

    def print(
        self,
        arguments: CaseCandidateInspectionArguments,
        result: CaseCandidateInspectionResult,
    ) -> None:
        selected_ids = {candidate.case_id for candidate in result.selection.candidates}
        rerank_positions = {
            candidate.case_id: rank
            for rank, candidate in enumerate(result.rerank.hits, start=1)
        }
        print(f"질의: {arguments.query}")
        print(
            "감지 고민 범주: "
            + ", ".join(category.value for category in result.selection.detected_categories)
        )
        print(
            f"검색 {len(result.search.hits)}건 → 직접 일치 "
            f"{result.selection.direct_match_count}건 → 리랭커 입력 "
            f"{len(result.selection.candidates)}건"
        )
        print("\n[Top-40 후보]")
        for rank, candidate in enumerate(result.search.hits, start=1):
            metadata = candidate.metadata
            selected = "yes" if candidate.case_id in selected_ids else "no"
            rerank_rank = rerank_positions.get(candidate.case_id)
            print(
                f"{rank:02d}. {candidate.case_id} | vec={candidate.vector_similarity:.4f} "
                f"| selected={selected} | rerank_top3={rerank_rank or '-'}"
            )
            print(
                f"    target={metadata.target_concern} | concerns={metadata.skin_concerns} | "
                f"profile={metadata.age}세 {metadata.gender} {metadata.skin_type}"
            )
            print(f"    question={self.question(candidate.page_content)}")

        print("\n[선별 후보 및 리랭크 결과]")
        scores = {candidate.case_id: candidate.rerank_score for candidate in result.rerank.hits}
        for vector_rank, candidate in enumerate(result.selection.candidates, start=1):
            print(
                f"{vector_rank:02d}. {candidate.case_id} | vec={candidate.vector_similarity:.4f} "
                f"| rerank_score={scores.get(candidate.case_id)} "
                f"| rerank_top3={rerank_positions.get(candidate.case_id, '-')}"
            )
            print(f"    question={self.question(candidate.page_content)}")

    def question(self, page_content: str) -> str:
        match = self._QUESTION_PATTERN.search(page_content)
        question = match.group(1) if match is not None else page_content
        normalized = " ".join(question.split())
        suffix = "..." if len(normalized) > self.QUESTION_PREVIEW_LENGTH else ""
        return normalized[: self.QUESTION_PREVIEW_LENGTH] + suffix


class CaseCandidateInspectionCli:
    @classmethod
    async def main(cls) -> None:
        Utf8ConsoleConfigurator().configure()
        arguments = CaseCandidateInspectionArgumentParser().parse()
        database = ConfiguredDatabaseFactory().create()
        try:
            result = await LocalCaseCandidateInspector(database).inspect(arguments)
            CaseCandidateInspectionPresenter().print(arguments, result)
        finally:
            await database.dispose()


if __name__ == "__main__":
    asyncio.run(CaseCandidateInspectionCli.main())
