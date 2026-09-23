"""복수 NIA Case 벡터 검색 결과를 순위 기반으로 결정적으로 합친다."""

from collections import defaultdict
from typing import Self

from pydantic import Field, FiniteFloat, model_validator

from agent.rag.case_schemas import (
    DEFAULT_CASE_CANDIDATE_LIMIT,
    CaseSearchHit,
    CaseSearchResult,
)
from agent.rag.schemas import LookupStatus, RagModel

DEFAULT_RRF_RANK_CONSTANT = 60


class CaseSearchContribution(RagModel):
    query: str = Field(min_length=1)
    result: CaseSearchResult


class CaseSearchFusionRequest(RagModel):
    contributions: list[CaseSearchContribution] = Field(min_length=1)
    limit: int = Field(default=DEFAULT_CASE_CANDIDATE_LIMIT, ge=1)
    rank_constant: int = Field(default=DEFAULT_RRF_RANK_CONSTANT, ge=1)


class CaseSearchFusionFailure(RagModel):
    query: str = Field(min_length=1)
    status: LookupStatus
    message: str = Field(min_length=1)


class FusedCaseCandidate(RagModel):
    hit: CaseSearchHit
    reciprocal_rank_score: FiniteFloat
    max_vector_similarity: FiniteFloat
    matched_queries: list[str] = Field(min_length=1)


class CaseSearchFusionResult(RagModel):
    search_result: CaseSearchResult
    candidates: list[FusedCaseCandidate] = Field(default_factory=list)
    failures: list[CaseSearchFusionFailure] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_candidates(self) -> Self:
        if self.search_result.status is LookupStatus.SUCCESS:
            if not self.candidates:
                raise ValueError("성공한 Case 융합 결과에는 후보가 필요합니다.")
            if self.search_result.hits != [candidate.hit for candidate in self.candidates]:
                raise ValueError("Case 융합 후보와 최종 검색 hit 순서가 다릅니다.")
        elif self.candidates:
            raise ValueError("성공하지 않은 Case 융합 결과에는 후보를 넣을 수 없습니다.")
        return self


class CaseSearchResultFusion:
    """질의별 점수 분포를 직접 섞지 않고 RRF로 Case 후보를 융합한다."""

    def fuse(self, request: CaseSearchFusionRequest) -> CaseSearchFusionResult:
        scores: defaultdict[str, float] = defaultdict(float)
        best_hits: dict[str, CaseSearchHit] = {}
        matched_queries: defaultdict[str, list[str]] = defaultdict(list)
        failures: list[CaseSearchFusionFailure] = []
        processed_queries: set[str] = set()

        for contribution in request.contributions:
            normalized_query = " ".join(contribution.query.casefold().split())
            if normalized_query in processed_queries:
                continue
            processed_queries.add(normalized_query)
            result = contribution.result
            if result.status in (LookupStatus.ERROR, LookupStatus.UNSUPPORTED):
                failures.append(self._failure(contribution))
                continue
            if result.status is not LookupStatus.SUCCESS:
                continue

            seen_case_ids: set[str] = set()
            for rank, hit in enumerate(result.hits, start=1):
                if hit.case_id in seen_case_ids:
                    continue
                seen_case_ids.add(hit.case_id)
                scores[hit.case_id] += 1.0 / (request.rank_constant + rank)
                matched_queries[hit.case_id].append(contribution.query)
                previous = best_hits.get(hit.case_id)
                if previous is None or hit.vector_similarity > previous.vector_similarity:
                    best_hits[hit.case_id] = hit.model_copy(deep=True)

        if not scores:
            return CaseSearchFusionResult(
                search_result=self._terminal_result(request),
                failures=failures,
            )

        candidates = [
            FusedCaseCandidate(
                hit=best_hits[case_id],
                reciprocal_rank_score=score,
                max_vector_similarity=best_hits[case_id].vector_similarity,
                matched_queries=matched_queries[case_id],
            )
            for case_id, score in scores.items()
        ]
        candidates.sort(
            key=lambda candidate: (
                -candidate.reciprocal_rank_score,
                -candidate.max_vector_similarity,
                candidate.hit.case_id,
            )
        )
        selected = candidates[: request.limit]
        return CaseSearchFusionResult(
            search_result=CaseSearchResult(
                status=LookupStatus.SUCCESS,
                hits=[candidate.hit for candidate in selected],
            ),
            candidates=selected,
            failures=failures,
        )

    def _failure(
        self,
        contribution: CaseSearchContribution,
    ) -> CaseSearchFusionFailure:
        return CaseSearchFusionFailure(
            query=contribution.query,
            status=contribution.result.status,
            message=contribution.result.error_message or contribution.result.status.value,
        )

    def _terminal_result(self, request: CaseSearchFusionRequest) -> CaseSearchResult:
        errors = [
            contribution
            for contribution in request.contributions
            if contribution.result.status is LookupStatus.ERROR
        ]
        if errors:
            details = "; ".join(
                f"{contribution.query}: "
                f"{contribution.result.error_message or LookupStatus.ERROR.value}"
                for contribution in errors
            )
            return CaseSearchResult(
                status=LookupStatus.ERROR,
                error_message=f"모든 NIA Case 검색이 실패했습니다: {details}",
            )
        unsupported = [
            contribution
            for contribution in request.contributions
            if contribution.result.status is LookupStatus.UNSUPPORTED
        ]
        if unsupported:
            details = "; ".join(
                f"{contribution.query}: "
                f"{contribution.result.error_message or LookupStatus.UNSUPPORTED.value}"
                for contribution in unsupported
            )
            return CaseSearchResult(
                status=LookupStatus.UNSUPPORTED,
                error_message=f"지원하지 않는 NIA Case 검색입니다: {details}",
            )
        return CaseSearchResult(status=LookupStatus.NO_RESULTS)
