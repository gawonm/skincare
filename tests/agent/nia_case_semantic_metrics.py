"""NIA Case 검색 단계별 성능과 코퍼스 상한을 분리해 계산한다."""

from enum import StrEnum
from math import log2
from typing import ClassVar

from pydantic import Field, model_validator

from agent.rag.schemas import RagModel
from tests.agent.nia_case_semantic_golden_schemas import FinalRelevanceGrade


class SemanticRetrievalStage(StrEnum):
    DENSE_TOP_40 = "dense_top_40"
    METADATA_TOP_20 = "metadata_top_20"
    RERANKER_TOP_3 = "reranker_top_3"


class RankedSemanticCase(RagModel):
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    rank: int = Field(ge=1)
    relevance_grade: FinalRelevanceGrade


class SemanticStageRanking(RagModel):
    stage: SemanticRetrievalStage
    items: list[RankedSemanticCase]

    @model_validator(mode="after")
    def validate_ranks(self) -> "SemanticStageRanking":
        ranks = [item.rank for item in self.items]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError(f"순위는 1부터 연속이어야 합니다: stage={self.stage}")
        if len({item.review_key for item in self.items}) != len(self.items):
            raise ValueError(f"단계 안에 중복 후보가 있습니다: stage={self.stage}")
        return self


class SemanticStageMetric(RagModel):
    stage: SemanticRetrievalStage
    retrieved_count: int = Field(ge=0)
    best_retrieved_grade: FinalRelevanceGrade
    corpus_ceiling_grade: FinalRelevanceGrade
    ceiling_hit: bool
    ndcg: float | None = Field(default=None, ge=0.0, le=1.0)


class NiaCaseSemanticMetricScorer:
    RERANK_LIMIT: ClassVar[int] = 3

    def score_stage(
        self,
        ranking: SemanticStageRanking,
        all_judged_grades: list[FinalRelevanceGrade],
    ) -> SemanticStageMetric:
        ceiling = self._max_grade(all_judged_grades)
        retrieved_grades = [item.relevance_grade for item in ranking.items]
        best_retrieved = self._max_grade(retrieved_grades)
        ndcg = None
        if ranking.stage is SemanticRetrievalStage.RERANKER_TOP_3:
            ndcg = self._ndcg_at_three(retrieved_grades, all_judged_grades)
        return SemanticStageMetric(
            stage=ranking.stage,
            retrieved_count=len(ranking.items),
            best_retrieved_grade=best_retrieved,
            corpus_ceiling_grade=ceiling,
            ceiling_hit=best_retrieved is ceiling,
            ndcg=ndcg,
        )

    def _max_grade(
        self, grades: list[FinalRelevanceGrade]
    ) -> FinalRelevanceGrade:
        if not grades:
            return FinalRelevanceGrade.NOT_RELEVANT
        return max(grades, key=lambda grade: grade.value)

    def _ndcg_at_three(
        self,
        retrieved_grades: list[FinalRelevanceGrade],
        all_judged_grades: list[FinalRelevanceGrade],
    ) -> float:
        actual = retrieved_grades[: self.RERANK_LIMIT]
        ideal = sorted(
            all_judged_grades,
            key=lambda grade: grade.value,
            reverse=True,
        )[: self.RERANK_LIMIT]
        ideal_score = self._discounted_gain(ideal)
        if ideal_score == 0.0:
            return 1.0
        return self._discounted_gain(actual) / ideal_score

    def _discounted_gain(self, grades: list[FinalRelevanceGrade]) -> float:
        return sum(
            ((2**grade.value) - 1) / log2(rank + 1)
            for rank, grade in enumerate(grades, start=1)
        )
