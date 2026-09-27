"""동결 질의의 cached dense Top-40을 현재 metadata selector와 BGE reranker로 점검한다."""

import asyncio
from pathlib import Path
from typing import ClassVar

from pydantic import Field, FiniteFloat

from agent.rag.case_schemas import (
    DEFAULT_CASE_CANDIDATE_LIMIT,
    CaseDatasetSplit,
    CaseMetadata,
    CaseProvenance,
    CaseRerankRequest,
    CaseSearchHit,
)
from agent.rag.retrieval.case_candidate_selector import (
    CaseCandidateSelectionRequest,
    CaseMetadataCandidateSelector,
)
from agent.rag.retrieval.case_reranker import LocalBgeCaseRerankerV2M3
from agent.rag.retrieval.cross_encoder import LocalBgeCrossEncoderScorer
from agent.rag.schemas import RagModel
from tests.agent.interactive_two_layer_rag_cli import TwoLayerAgentModelConfigFactory
from tests.agent.nia_case_semantic_candidate_pool import (
    BlindCandidatePoolEntry,
    BlindCandidatePoolItem,
    CandidatePoolArtifactLoader,
    CandidatePoolJsonlWriter,
    InternalCandidatePoolEntry,
    InternalCandidatePoolItem,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQuery,
    NiaCaseSemanticEvaluationQueryLoader,
)
from tests.agent.nia_case_semantic_final_golden import (
    NiaCaseSemanticGoldenArtifact,
    NiaCaseSemanticGoldenCase,
)
from tests.agent.nia_case_semantic_golden_schemas import FinalRelevanceGrade


class NiaCaseSemanticRerankProbeHit(RagModel):
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    case_id: str = Field(min_length=1)
    dense_rank: int = Field(ge=1, le=DEFAULT_CASE_CANDIDATE_LIMIT)
    metadata_rank: int = Field(ge=1)
    rerank_rank: int = Field(ge=1, le=3)
    rerank_score: FiniteFloat
    anchor_grade: FinalRelevanceGrade | None = None


class NiaCaseSemanticRerankProbeItem(RagModel):
    evaluation_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    direct_match_count: int = Field(ge=0)
    metadata_candidate_count: int = Field(ge=1)
    hits: list[NiaCaseSemanticRerankProbeHit] = Field(min_length=3, max_length=3)


class NiaCaseSemanticRerankProbeResult(RagModel):
    items: list[NiaCaseSemanticRerankProbeItem] = Field(min_length=1)
    unjudged_items: list[BlindCandidatePoolItem]


class NiaCaseSemanticRerankProbe:
    TEXT_VERSION: ClassVar[str] = "nia_case_text/v1"
    PROVENANCE_ARCHIVE: ClassVar[str] = "semantic_evaluation_cached_pool"

    def __init__(self) -> None:
        reranker_config = TwoLayerAgentModelConfigFactory().create_reranker()
        scorer = LocalBgeCrossEncoderScorer(reranker_config)
        self._reranker = LocalBgeCaseRerankerV2M3(reranker_config, scorer=scorer)
        self._selector = CaseMetadataCandidateSelector()

    async def run(
        self,
        queries: list[NiaCaseSemanticEvaluationQuery],
        internal_items: list[InternalCandidatePoolItem],
        golden_items: list[NiaCaseSemanticGoldenCase],
    ) -> NiaCaseSemanticRerankProbeResult:
        internal_by_id = {item.evaluation_id: item for item in internal_items}
        golden_by_id = {item.evaluation_id: item for item in golden_items}
        results: list[NiaCaseSemanticRerankProbeItem] = []
        unjudged: list[BlindCandidatePoolItem] = []
        for query in queries:
            result, missing = await self._run_query(
                query=query,
                internal=internal_by_id[query.evaluation_id],
                golden=golden_by_id[query.evaluation_id],
            )
            results.append(result)
            if missing is not None:
                unjudged.append(missing)
            print(
                f"{query.evaluation_id}: top3={len(result.hits)}, "
                f"unjudged={0 if missing is None else missing.candidate_count}"
            )
        return NiaCaseSemanticRerankProbeResult(
            items=results,
            unjudged_items=unjudged,
        )

    async def _run_query(
        self,
        query: NiaCaseSemanticEvaluationQuery,
        internal: InternalCandidatePoolItem,
        golden: NiaCaseSemanticGoldenCase,
    ) -> tuple[NiaCaseSemanticRerankProbeItem, BlindCandidatePoolItem | None]:
        dense = [
            item
            for item in internal.candidates
            if item.dense_rank is not None
            and item.dense_rank <= DEFAULT_CASE_CANDIDATE_LIMIT
        ]
        dense.sort(key=lambda item: (item.dense_rank or DEFAULT_CASE_CANDIDATE_LIMIT, item.case_id))
        hits_by_id = {item.case_id: self._to_search_hit(item) for item in dense}
        selection = self._selector.select(
            CaseCandidateSelectionRequest(
                query=query.query,
                skin_concerns=[
                    concern.value
                    for concern in [*query.primary_concerns, *query.secondary_concerns]
                ],
                candidates=[hits_by_id[item.case_id] for item in dense],
            )
        )
        reranked = await self._reranker.rerank(
            CaseRerankRequest(query=query.query, candidates=selection.candidates)
        )
        internal_by_id = {item.case_id: item for item in dense}
        metadata_ranks = {
            item.case_id: rank for rank, item in enumerate(selection.candidates, start=1)
        }
        grades_by_key = {
            item.review_key: item.relevance_grade for item in golden.graded_qrels
        }
        probe_hits = [
            NiaCaseSemanticRerankProbeHit(
                review_key=internal_by_id[hit.case_id].review_key,
                case_id=hit.case_id,
                dense_rank=internal_by_id[hit.case_id].dense_rank or 1,
                metadata_rank=metadata_ranks[hit.case_id],
                rerank_rank=rank,
                rerank_score=hit.rerank_score or 0.0,
                anchor_grade=grades_by_key.get(internal_by_id[hit.case_id].review_key),
            )
            for rank, hit in enumerate(reranked.hits, start=1)
        ]
        missing_candidates = [
            self._to_blind_entry(internal_by_id[item.case_id])
            for item in probe_hits
            if item.anchor_grade is None
        ]
        missing = (
            BlindCandidatePoolItem(
                evaluation_id=query.evaluation_id,
                query=query.query,
                candidate_count=len(missing_candidates),
                candidates=missing_candidates,
            )
            if missing_candidates
            else None
        )
        return (
            NiaCaseSemanticRerankProbeItem(
                evaluation_id=query.evaluation_id,
                query=query.query,
                direct_match_count=selection.direct_match_count,
                metadata_candidate_count=len(selection.candidates),
                hits=probe_hits,
            ),
            missing,
        )

    def _to_search_hit(self, item: InternalCandidatePoolEntry) -> CaseSearchHit:
        if item.dense_similarity is None:
            raise RuntimeError(f"dense 후보에 similarity가 없습니다: {item.case_id}")
        return CaseSearchHit(
            case_id=item.case_id,
            page_content=f"[질문]\n{item.question}\n\n[답변]\n{item.answer}",
            text_version=self.TEXT_VERSION,
            dataset_split=CaseDatasetSplit(item.dataset_split),
            metadata=CaseMetadata(
                target_concern=item.target_concern,
                gender=item.gender,
                age=item.age,
                skin_type=item.skin_type,
                skin_concerns=item.skin_concerns,
            ),
            # 리랭커는 provenance를 읽지 않으며, cached pool 출처임을 명시해 실제 원본과 혼동하지 않는다.
            provenance=CaseProvenance(
                archive_name=self.PROVENANCE_ARCHIVE,
                line_number=1,
            ),
            vector_similarity=item.dense_similarity,
        )

    def _to_blind_entry(
        self,
        item: InternalCandidatePoolEntry,
    ) -> BlindCandidatePoolEntry:
        return BlindCandidatePoolEntry(
            review_key=item.review_key,
            gender=item.gender,
            age=item.age,
            skin_type=item.skin_type,
            question=item.question,
            answer=item.answer,
        )


class NiaCaseSemanticRerankProbeWriter:
    def write(
        self,
        internal_path: Path,
        blind_path: Path,
        result: NiaCaseSemanticRerankProbeResult,
    ) -> None:
        try:
            with internal_path.open("w", encoding="utf-8", newline="\n") as destination:
                for item in result.items:
                    destination.write(item.model_dump_json())
                    destination.write("\n")
        except OSError as error:
            raise RuntimeError(f"reranker probe 결과를 쓰지 못했습니다: {internal_path}") from error
        CandidatePoolJsonlWriter().write(blind_path, list(result.unjudged_items))


class NiaCaseSemanticRerankProbeCli:
    QUERY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_evaluation_queries_v1.jsonl"
    )
    INTERNAL_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_evaluation_pool_v1.jsonl"
    )
    GOLDEN_PATH: ClassVar[Path] = Path("tests/agent/nia_case_eval_data/nia_case_semantic_golden_v1.jsonl")
    OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_rerank_probe_v1.jsonl"
    )
    UNJUDGED_BLIND_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_rerank_unjudged_blind_v1.jsonl"
    )

    @classmethod
    async def main(cls) -> None:
        result = await NiaCaseSemanticRerankProbe().run(
            queries=NiaCaseSemanticEvaluationQueryLoader().load(cls.QUERY_PATH).items,
            internal_items=CandidatePoolArtifactLoader().load_internal(
                cls.INTERNAL_POOL_PATH
            ),
            golden_items=NiaCaseSemanticGoldenArtifact().load(cls.GOLDEN_PATH).items,
        )
        NiaCaseSemanticRerankProbeWriter().write(
            internal_path=cls.OUTPUT_PATH,
            blind_path=cls.UNJUDGED_BLIND_PATH,
            result=result,
        )
        print(
            f"rerank probe: queries={len(result.items)}, "
            f"unjudged={sum(item.candidate_count for item in result.unjudged_items)}"
        )


if __name__ == "__main__":
    asyncio.run(NiaCaseSemanticRerankProbeCli.main())
