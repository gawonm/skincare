"""동결 평가 질의별 relevant Case anchor 발견용 블라인드 표본을 만든다."""

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
)


class EvaluationAnchorStratum(StrEnum):
    DENSE_PROBE = "dense_probe"
    OFF_RANK_ANCHOR = "off_rank_anchor"


class EvaluationAnchorManifestEntry(RagModel):
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    stratum: EvaluationAnchorStratum


class EvaluationAnchorManifestItem(RagModel):
    evaluation_id: str = Field(min_length=1)
    entries: list[EvaluationAnchorManifestEntry] = Field(min_length=1)


class NiaCaseSemanticEvaluationAnchorSampler:
    DENSE_PROBE_COUNT: ClassVar[int] = 5
    OFF_RANK_ANCHOR_COUNT: ClassVar[int] = 10

    def sample(
        self,
        queries: list[NiaCaseSemanticEvaluationQuery],
        internal_items: list[InternalCandidatePoolItem],
        blind_items: list[BlindCandidatePoolItem],
    ) -> tuple[list[EvaluationAnchorManifestItem], list[BlindCandidatePoolItem]]:
        queries_by_id = {item.evaluation_id: item for item in queries}
        blind_by_id = {item.evaluation_id: item for item in blind_items}
        manifests: list[EvaluationAnchorManifestItem] = []
        samples: list[BlindCandidatePoolItem] = []
        for internal in internal_items:
            query = queries_by_id[internal.evaluation_id]
            entries = self._select(query, internal)
            blind = blind_by_id[internal.evaluation_id]
            candidates_by_key = {item.review_key: item for item in blind.candidates}
            candidates = [candidates_by_key[item.review_key] for item in entries]
            candidates.sort(key=lambda item: item.review_key)
            manifests.append(
                EvaluationAnchorManifestItem(
                    evaluation_id=internal.evaluation_id,
                    entries=entries,
                )
            )
            samples.append(
                BlindCandidatePoolItem(
                    evaluation_id=blind.evaluation_id,
                    query=blind.query,
                    candidate_count=len(candidates),
                    candidates=candidates,
                )
            )
        return manifests, samples

    def _select(
        self,
        query: NiaCaseSemanticEvaluationQuery,
        internal: InternalCandidatePoolItem,
    ) -> list[EvaluationAnchorManifestEntry]:
        dense = [
            item
            for item in internal.candidates
            if item.dense_rank is not None and item.dense_rank <= 40
        ]
        dense.sort(key=lambda item: (item.dense_rank or 10_000, item.review_key))
        selected_dense = self._take_unique(dense, self.DENSE_PROBE_COUNT, set())
        selected_keys = {item.review_key for item in selected_dense}
        selected_content = {(item.question, item.answer) for item in selected_dense}
        concerns = {
            item.value for item in [*query.primary_concerns, *query.secondary_concerns]
        }
        off_rank = [
            item
            for item in internal.candidates
            if item.review_key not in selected_keys
            and (item.dense_rank is None or item.dense_rank > 40)
        ]
        off_rank.sort(
            key=lambda item: (
                item.target_concern not in concerns,
                -item.clinical_lexical_score,
                -item.query_lexical_score,
                item.review_key,
            )
        )
        selected_off_rank = self._take_unique(
            off_rank,
            self.OFF_RANK_ANCHOR_COUNT,
            selected_content,
        )
        if len(selected_off_rank) != self.OFF_RANK_ANCHOR_COUNT:
            raise RuntimeError(
                f"평가 anchor 후보가 부족합니다: evaluation_id={query.evaluation_id}"
            )
        return [
            *[
                EvaluationAnchorManifestEntry(
                    review_key=item.review_key,
                    stratum=EvaluationAnchorStratum.DENSE_PROBE,
                )
                for item in selected_dense
            ],
            *[
                EvaluationAnchorManifestEntry(
                    review_key=item.review_key,
                    stratum=EvaluationAnchorStratum.OFF_RANK_ANCHOR,
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


class NiaCaseSemanticEvaluationAnchorCli:
    QUERY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_queries_v1.jsonl"
    )
    INTERNAL_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_pool_v1.jsonl"
    )
    BLIND_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_blind_v1.jsonl"
    )
    MANIFEST_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_anchor_manifest_v1.jsonl"
    )
    BLIND_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_anchor_blind_v1.jsonl"
    )

    @classmethod
    def main(cls) -> None:
        loader = CandidatePoolArtifactLoader()
        manifests, samples = NiaCaseSemanticEvaluationAnchorSampler().sample(
            queries=NiaCaseSemanticEvaluationQueryLoader().load(cls.QUERY_PATH).items,
            internal_items=loader.load_internal(cls.INTERNAL_POOL_PATH),
            blind_items=loader.load_blind(cls.BLIND_POOL_PATH),
        )
        writer = CandidatePoolJsonlWriter()
        writer.write(cls.MANIFEST_OUTPUT_PATH, list(manifests))
        writer.write(cls.BLIND_OUTPUT_PATH, list(samples))
        print(
            f"evaluation anchor sample: queries={len(samples)}, "
            f"candidates={sum(item.candidate_count for item in samples)}"
        )


if __name__ == "__main__":
    NiaCaseSemanticEvaluationAnchorCli.main()
