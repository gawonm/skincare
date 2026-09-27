"""24개 대표 질의의 NIA Case 코퍼스 상대 검색 골든셋 후보를 만든다."""

from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from pydantic import Field

from agent.rag.schemas import RagModel
from tests.agent.nia_case_semantic_candidate_pool import (
    BlindCandidatePoolItem,
    CandidatePoolArtifactLoader,
    CandidatePoolJsonlWriter,
    InternalCandidatePoolEntry,
    InternalCandidatePoolItem,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQuery,
    NiaCaseSemanticEvaluationQueryLoader,
    SemanticEvaluationCohort,
)


class CorpusRelativeEvaluationId(StrEnum):
    CORE_PORES_01 = "evaluation_core_pores_01"
    CORE_PORES_02 = "evaluation_core_pores_02"
    CORE_PORES_03 = "evaluation_core_pores_03"
    CORE_PORES_05 = "evaluation_core_pores_05"
    CORE_PORES_08 = "evaluation_core_pores_08"
    CORE_PIGMENT_01 = "evaluation_core_pigment_01"
    CORE_PIGMENT_02 = "evaluation_core_pigment_02"
    CORE_PIGMENT_04 = "evaluation_core_pigment_04"
    CORE_PIGMENT_05 = "evaluation_core_pigment_05"
    CORE_PIGMENT_08 = "evaluation_core_pigment_08"
    CORE_ACNE_01 = "evaluation_core_acne_01"
    CORE_ACNE_03 = "evaluation_core_acne_03"
    CORE_ACNE_04 = "evaluation_core_acne_04"
    CORE_ACNE_05 = "evaluation_core_acne_05"
    CORE_ACNE_08 = "evaluation_core_acne_08"
    CORE_COMPOSITE_01 = "evaluation_core_composite_01"
    CORE_COMPOSITE_02 = "evaluation_core_composite_02"
    CORE_COMPOSITE_06 = "evaluation_core_composite_06"
    RARE_DRY_02 = "evaluation_rare_dry_02"
    RARE_DRY_03 = "evaluation_rare_dry_03"
    RARE_REDNESS_02 = "evaluation_rare_redness_02"
    RARE_WRINKLES_02 = "evaluation_rare_wrinkles_02"
    RARE_SENSITIVE_01 = "evaluation_rare_sensitive_01"
    RARE_SAGGING_01 = "evaluation_rare_sagging_01"


class CorpusRelativeAnchorStratum(StrEnum):
    DENSE_TOP_40 = "dense_top_40"
    OFF_RANK_QUERY_MATCH = "off_rank_query_match"


class CorpusRelativeAnchorManifestEntry(RagModel):
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    stratum: CorpusRelativeAnchorStratum


class CorpusRelativeAnchorManifestItem(RagModel):
    evaluation_id: CorpusRelativeEvaluationId
    entries: list[CorpusRelativeAnchorManifestEntry] = Field(min_length=1)


class NiaCaseCorpusRelativeQuerySelector:
    EXPECTED_CORE_COUNT: ClassVar[int] = 18
    EXPECTED_RARE_STRESS_COUNT: ClassVar[int] = 6

    def select(
        self,
        queries: list[NiaCaseSemanticEvaluationQuery],
    ) -> list[NiaCaseSemanticEvaluationQuery]:
        selected_ids = {item.value for item in CorpusRelativeEvaluationId}
        queries_by_id = {item.evaluation_id: item for item in queries}
        missing_ids = selected_ids - set(queries_by_id)
        if missing_ids:
            raise RuntimeError(
                "활성 골든셋으로 선택한 질의가 원본 동결 질의에 없습니다: "
                f"{sorted(missing_ids)}"
            )
        selected = [
            item for item in queries if item.evaluation_id in selected_ids
        ]
        if len(selected) != len(CorpusRelativeEvaluationId):
            raise RuntimeError("활성 골든셋 질의 수가 선택 목록과 다릅니다.")
        core_count = sum(
            item.cohort is SemanticEvaluationCohort.CORE for item in selected
        )
        rare_count = sum(
            item.cohort is SemanticEvaluationCohort.RARE_STRESS for item in selected
        )
        if core_count != self.EXPECTED_CORE_COUNT or rare_count != self.EXPECTED_RARE_STRESS_COUNT:
            raise RuntimeError(
                "활성 골든셋 cohort 수가 합의한 구성과 다릅니다: "
                f"core={core_count}, rare_stress={rare_count}"
            )
        return selected


class NiaCaseCorpusRelativeAnchorSampler:
    DENSE_TOP_K: ClassVar[int] = 40
    DENSE_PROBE_COUNT: ClassVar[int] = 3
    OFF_RANK_PROBE_COUNT: ClassVar[int] = 3

    def sample(
        self,
        queries: list[NiaCaseSemanticEvaluationQuery],
        internal_items: list[InternalCandidatePoolItem],
        blind_items: list[BlindCandidatePoolItem],
    ) -> tuple[
        list[CorpusRelativeAnchorManifestItem],
        list[BlindCandidatePoolItem],
    ]:
        query_ids = {item.evaluation_id for item in queries}
        internal_by_id = {item.evaluation_id: item for item in internal_items}
        blind_by_id = {item.evaluation_id: item for item in blind_items}
        self._validate_id_set("내부 후보 풀", query_ids, set(internal_by_id))
        self._validate_id_set("블라인드 후보 풀", query_ids, set(blind_by_id))

        manifests: list[CorpusRelativeAnchorManifestItem] = []
        samples: list[BlindCandidatePoolItem] = []
        for query in queries:
            internal = internal_by_id[query.evaluation_id]
            entries = self._select(query, internal)
            blind = blind_by_id[query.evaluation_id]
            candidates_by_key = {item.review_key: item for item in blind.candidates}
            candidates = [candidates_by_key[item.review_key] for item in entries]
            candidates.sort(key=lambda item: item.review_key)
            manifests.append(
                CorpusRelativeAnchorManifestItem(
                    evaluation_id=CorpusRelativeEvaluationId(query.evaluation_id),
                    entries=entries,
                )
            )
            samples.append(
                BlindCandidatePoolItem(
                    evaluation_id=query.evaluation_id,
                    query=query.query,
                    candidate_count=len(candidates),
                    candidates=candidates,
                )
            )
        return manifests, samples

    def _select(
        self,
        query: NiaCaseSemanticEvaluationQuery,
        internal: InternalCandidatePoolItem,
    ) -> list[CorpusRelativeAnchorManifestEntry]:
        dense = sorted(
            [
                item
                for item in internal.candidates
                if item.dense_rank is not None and item.dense_rank <= self.DENSE_TOP_K
            ],
            key=lambda item: (item.dense_rank or self.DENSE_TOP_K, item.review_key),
        )
        selected_dense = self._take_unique(dense, self.DENSE_PROBE_COUNT, set())
        selected_keys = {item.review_key for item in selected_dense}
        selected_content = {(item.question, item.answer) for item in selected_dense}
        concerns = {
            item.value for item in [*query.primary_concerns, *query.secondary_concerns]
        }
        off_rank = sorted(
            [
                item
                for item in internal.candidates
                if item.review_key not in selected_keys
                and (item.dense_rank is None or item.dense_rank > self.DENSE_TOP_K)
            ],
            key=lambda item: (
                item.target_concern not in concerns,
                -item.query_lexical_score,
                item.review_key,
            ),
        )
        selected_off_rank = self._take_unique(
            off_rank,
            self.OFF_RANK_PROBE_COUNT,
            selected_content,
        )
        if len(selected_dense) != self.DENSE_PROBE_COUNT:
            raise RuntimeError(
                f"dense Top-40 후보가 부족합니다: evaluation_id={query.evaluation_id}"
            )
        if len(selected_off_rank) != self.OFF_RANK_PROBE_COUNT:
            raise RuntimeError(
                f"Top-40 밖 query-match 후보가 부족합니다: evaluation_id={query.evaluation_id}"
            )
        return [
            *[
                CorpusRelativeAnchorManifestEntry(
                    review_key=item.review_key,
                    stratum=CorpusRelativeAnchorStratum.DENSE_TOP_40,
                )
                for item in selected_dense
            ],
            *[
                CorpusRelativeAnchorManifestEntry(
                    review_key=item.review_key,
                    stratum=CorpusRelativeAnchorStratum.OFF_RANK_QUERY_MATCH,
                )
                for item in selected_off_rank
            ],
        ]

    def _take_unique(
        self,
        candidates: list[InternalCandidatePoolEntry],
        count: int,
        excluded_content: set[tuple[str, str]],
    ) -> list[InternalCandidatePoolEntry]:
        selected: list[InternalCandidatePoolEntry] = []
        seen = set(excluded_content)
        for candidate in candidates:
            content = (candidate.question, candidate.answer)
            if content in seen:
                continue
            selected.append(candidate)
            seen.add(content)
            if len(selected) == count:
                break
        return selected

    def _validate_id_set(
        self,
        label: str,
        expected_ids: set[str],
        actual_ids: set[str],
    ) -> None:
        if expected_ids != actual_ids:
            raise RuntimeError(
                f"{label} evaluation_id 구성이 활성 골든셋 질의와 다릅니다: "
                f"missing={sorted(expected_ids - actual_ids)}, "
                f"unexpected={sorted(actual_ids - expected_ids)}"
            )

class NiaCaseCorpusRelativeGoldenCli:
    QUERY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_queries_v1.jsonl"
    )
    INTERNAL_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_pool_v1.jsonl"
    )
    BLIND_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_blind_v1.jsonl"
    )
    QUERY_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_queries_v1.jsonl"
    )
    MANIFEST_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_anchor_manifest_v1.jsonl"
    )
    BLIND_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relative_anchor_blind_v1.jsonl"
    )

    @classmethod
    def main(cls) -> None:
        loader = CandidatePoolArtifactLoader()
        queries = NiaCaseCorpusRelativeQuerySelector().select(
            NiaCaseSemanticEvaluationQueryLoader().load(cls.QUERY_PATH).items
        )
        query_ids = {item.evaluation_id for item in queries}
        internal_items = [
            item
            for item in loader.load_internal(cls.INTERNAL_POOL_PATH)
            if item.evaluation_id in query_ids
        ]
        blind_items = [
            item
            for item in loader.load_blind(cls.BLIND_POOL_PATH)
            if item.evaluation_id in query_ids
        ]
        manifests, samples = NiaCaseCorpusRelativeAnchorSampler().sample(
            queries=queries,
            internal_items=internal_items,
            blind_items=blind_items,
        )
        writer = CandidatePoolJsonlWriter()
        writer.write(cls.QUERY_OUTPUT_PATH, list(queries))
        writer.write(cls.MANIFEST_OUTPUT_PATH, list(manifests))
        writer.write(cls.BLIND_OUTPUT_PATH, list(samples))
        print(
            "corpus-relative anchor sample: "
            f"queries={len(queries)}, candidates={sum(item.candidate_count for item in samples)}"
        )


if __name__ == "__main__":
    NiaCaseCorpusRelativeGoldenCli.main()
