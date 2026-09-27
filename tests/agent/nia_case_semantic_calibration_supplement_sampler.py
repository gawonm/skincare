"""경계가 비어 있는 calibration 질의의 anchor와 명백한 대조군을 보완한다."""

import json
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
from tests.agent.nia_case_semantic_golden_schemas import (
    NiaCaseSemanticCalibrationLoader,
    NiaCaseSemanticQueryReference,
)


class CalibrationSupplementStratum(StrEnum):
    ANCHOR_PROBE = "anchor_probe"
    OTHER_CATEGORY_CONTRAST = "other_category_contrast"


class CalibrationSupplementManifestEntry(RagModel):
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    stratum: CalibrationSupplementStratum


class CalibrationSupplementManifestItem(RagModel):
    evaluation_id: str = Field(min_length=1)
    entries: list[CalibrationSupplementManifestEntry] = Field(min_length=1)


class NiaCaseCalibrationSupplementSampler:
    TARGET_EVALUATION_IDS: ClassVar[tuple[str, ...]] = (
        "calibration_melasma_sensitive_01",
        "calibration_sagging_expectation_01",
    )
    ITEMS_PER_STRATUM: ClassVar[int] = 5

    def sample(
        self,
        references: list[NiaCaseSemanticQueryReference],
        internal_items: list[InternalCandidatePoolItem],
        blind_items: list[BlindCandidatePoolItem],
        sampled_keys: set[str],
    ) -> tuple[list[CalibrationSupplementManifestItem], list[BlindCandidatePoolItem]]:
        references_by_id = {item.evaluation_id: item for item in references}
        internal_by_id = {item.evaluation_id: item for item in internal_items}
        blind_by_id = {item.evaluation_id: item for item in blind_items}
        manifests: list[CalibrationSupplementManifestItem] = []
        supplements: list[BlindCandidatePoolItem] = []
        for evaluation_id in self.TARGET_EVALUATION_IDS:
            reference = references_by_id[evaluation_id]
            internal = internal_by_id[evaluation_id]
            blind = blind_by_id[evaluation_id]
            entries = self._select(reference, internal, sampled_keys)
            blind_by_key = {item.review_key: item for item in blind.candidates}
            candidates = [blind_by_key[entry.review_key] for entry in entries]
            candidates.sort(key=lambda item: item.review_key)
            manifests.append(
                CalibrationSupplementManifestItem(
                    evaluation_id=evaluation_id,
                    entries=entries,
                )
            )
            supplements.append(
                BlindCandidatePoolItem(
                    evaluation_id=evaluation_id,
                    query=blind.query,
                    candidate_count=len(candidates),
                    candidates=candidates,
                )
            )
        return manifests, supplements

    def _select(
        self,
        reference: NiaCaseSemanticQueryReference,
        internal: InternalCandidatePoolItem,
        sampled_keys: set[str],
    ) -> list[CalibrationSupplementManifestEntry]:
        primary = {concern.value for concern in reference.primary_concerns}
        related = primary | {concern.value for concern in reference.secondary_concerns}
        unused = [
            candidate
            for candidate in internal.candidates
            if candidate.review_key not in sampled_keys
        ]
        anchors = [candidate for candidate in unused if candidate.target_concern in primary]
        anchors.sort(key=self._anchor_sort_key)
        if len(anchors) < self.ITEMS_PER_STRATUM:
            secondary = [
                candidate
                for candidate in unused
                if candidate.target_concern in related and candidate not in anchors
            ]
            secondary.sort(key=self._anchor_sort_key)
            anchors.extend(secondary[: self.ITEMS_PER_STRATUM - len(anchors)])
        anchors = anchors[: self.ITEMS_PER_STRATUM]

        contrasts = [
            candidate for candidate in unused if candidate.target_concern not in related
        ]
        contrasts.sort(key=self._contrast_sort_key)
        contrasts = contrasts[: self.ITEMS_PER_STRATUM]
        if len(anchors) != self.ITEMS_PER_STRATUM or len(contrasts) != self.ITEMS_PER_STRATUM:
            raise RuntimeError(f"보완 표본 수가 부족합니다: evaluation_id={internal.evaluation_id}")
        return [
            *[
                CalibrationSupplementManifestEntry(
                    review_key=candidate.review_key,
                    stratum=CalibrationSupplementStratum.ANCHOR_PROBE,
                )
                for candidate in anchors
            ],
            *[
                CalibrationSupplementManifestEntry(
                    review_key=candidate.review_key,
                    stratum=CalibrationSupplementStratum.OTHER_CATEGORY_CONTRAST,
                )
                for candidate in contrasts
            ],
        ]

    def _anchor_sort_key(
        self, candidate: InternalCandidatePoolEntry
    ) -> tuple[int, int, int, str]:
        return (
            candidate.dense_rank or 10_000,
            -candidate.query_lexical_score,
            -candidate.clinical_lexical_score,
            candidate.review_key,
        )

    def _contrast_sort_key(
        self, candidate: InternalCandidatePoolEntry
    ) -> tuple[int, int, str]:
        return (
            candidate.dense_rank or 10_000,
            -candidate.query_lexical_score,
            candidate.review_key,
        )


class NiaCaseCalibrationSupplementCli:
    CALIBRATION_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_v1.jsonl"
    )
    INTERNAL_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_pool_v1.jsonl"
    )
    BLIND_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_blind_v1.jsonl"
    )
    SAMPLE_MANIFEST_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_sample_manifest_v1.jsonl"
    )
    MANIFEST_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_supplement_manifest_v1.jsonl"
    )
    BLIND_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_supplement_blind_v1.jsonl"
    )

    @classmethod
    def main(cls) -> None:
        loader = CandidatePoolArtifactLoader()
        sampled_keys = {
            entry["review_key"]
            for line in cls.SAMPLE_MANIFEST_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
            for entry in json.loads(line)["entries"]
        }
        manifests, supplements = NiaCaseCalibrationSupplementSampler().sample(
            references=NiaCaseSemanticCalibrationLoader().load(cls.CALIBRATION_PATH).items,
            internal_items=loader.load_internal(cls.INTERNAL_POOL_PATH),
            blind_items=loader.load_blind(cls.BLIND_POOL_PATH),
            sampled_keys=sampled_keys,
        )
        writer = CandidatePoolJsonlWriter()
        writer.write(cls.MANIFEST_OUTPUT_PATH, list(manifests))
        writer.write(cls.BLIND_OUTPUT_PATH, list(supplements))
        print(f"calibration supplement: queries={len(supplements)}, candidates={sum(item.candidate_count for item in supplements)}")


if __name__ == "__main__":
    NiaCaseCalibrationSupplementCli.main()
