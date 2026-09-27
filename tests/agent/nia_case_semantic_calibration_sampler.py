"""전체 calibration 후보 풀에서 판정 경계를 검토할 블라인드 표본을 만든다."""

import argparse
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


class CalibrationSampleStratum(StrEnum):
    DENSE_LIKELY = "dense_likely"
    OFF_RANK_ALTERNATIVE = "off_rank_alternative"
    LOW_SIGNAL_CONTRAST = "low_signal_contrast"


class CalibrationSampleManifestEntry(RagModel):
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    stratum: CalibrationSampleStratum


class CalibrationSampleManifestItem(RagModel):
    evaluation_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    entries: list[CalibrationSampleManifestEntry] = Field(min_length=1)


class CalibrationSampleResult(RagModel):
    manifest_items: list[CalibrationSampleManifestItem] = Field(min_length=1)
    blind_items: list[BlindCandidatePoolItem] = Field(min_length=1)


class CalibrationSampleArguments(RagModel):
    calibration_path: Path
    internal_pool_path: Path
    blind_pool_path: Path
    manifest_output_path: Path
    blind_output_path: Path


class CalibrationSampleArgumentParser:
    DEFAULT_CALIBRATION_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_calibration_v1.jsonl"
    )
    DEFAULT_INTERNAL_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_calibration_pool_v1.jsonl"
    )
    DEFAULT_BLIND_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_calibration_blind_v1.jsonl"
    )
    DEFAULT_MANIFEST_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_calibration_sample_manifest_v1.jsonl"
    )
    DEFAULT_BLIND_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_calibration_sample_blind_v1.jsonl"
    )

    def parse(self) -> CalibrationSampleArguments:
        parser = argparse.ArgumentParser(
            description="calibration 판정 기준 검토용 층화 블라인드 표본을 만듭니다."
        )
        parser.add_argument(
            "--calibration", type=Path, default=self.DEFAULT_CALIBRATION_PATH
        )
        parser.add_argument(
            "--internal-pool", type=Path, default=self.DEFAULT_INTERNAL_POOL_PATH
        )
        parser.add_argument(
            "--blind-pool", type=Path, default=self.DEFAULT_BLIND_POOL_PATH
        )
        parser.add_argument(
            "--manifest-output", type=Path, default=self.DEFAULT_MANIFEST_OUTPUT_PATH
        )
        parser.add_argument(
            "--blind-output", type=Path, default=self.DEFAULT_BLIND_OUTPUT_PATH
        )
        parsed = parser.parse_args()
        return CalibrationSampleArguments(
            calibration_path=parsed.calibration,
            internal_pool_path=parsed.internal_pool,
            blind_pool_path=parsed.blind_pool,
            manifest_output_path=parsed.manifest_output,
            blind_output_path=parsed.blind_output,
        )


class NiaCaseCalibrationReviewSampler:
    ITEMS_PER_STRATUM: ClassVar[int] = 5

    def sample(
        self,
        references: list[NiaCaseSemanticQueryReference],
        internal_items: list[InternalCandidatePoolItem],
        blind_items: list[BlindCandidatePoolItem],
    ) -> CalibrationSampleResult:
        references_by_id = {reference.evaluation_id: reference for reference in references}
        blind_by_id = {item.evaluation_id: item for item in blind_items}
        manifest_results: list[CalibrationSampleManifestItem] = []
        blind_results: list[BlindCandidatePoolItem] = []
        for internal in internal_items:
            reference = references_by_id.get(internal.evaluation_id)
            blind = blind_by_id.get(internal.evaluation_id)
            if reference is None or blind is None:
                raise RuntimeError(
                    f"calibration 표본 입력이 누락되었습니다: {internal.evaluation_id}"
                )
            selected = self._select(reference, internal)
            blind_candidates_by_key = {
                candidate.review_key: candidate for candidate in blind.candidates
            }
            selected_blind = [
                blind_candidates_by_key[entry.review_key]
                for entry in selected
                if entry.review_key in blind_candidates_by_key
            ]
            if len(selected_blind) != len(selected):
                raise RuntimeError(
                    f"블라인드 후보 매핑이 누락되었습니다: {internal.evaluation_id}"
                )
            # 표본 층을 유추하지 못하도록 블라인드 파일은 review_key 순서로만 정렬한다.
            selected_blind.sort(key=lambda candidate: candidate.review_key)
            manifest_results.append(
                CalibrationSampleManifestItem(
                    evaluation_id=internal.evaluation_id,
                    query=internal.query,
                    entries=selected,
                )
            )
            blind_results.append(
                BlindCandidatePoolItem(
                    evaluation_id=blind.evaluation_id,
                    query=blind.query,
                    candidate_count=len(selected_blind),
                    candidates=selected_blind,
                )
            )
        return CalibrationSampleResult(
            manifest_items=manifest_results,
            blind_items=blind_results,
        )

    def _select(
        self,
        reference: NiaCaseSemanticQueryReference,
        internal: InternalCandidatePoolItem,
    ) -> list[CalibrationSampleManifestEntry]:
        likely = [
            candidate
            for candidate in internal.candidates
            if candidate.dense_rank is not None and candidate.dense_rank <= 40
        ]
        likely.sort(key=self._likely_sort_key)
        selected_likely = likely[: self.ITEMS_PER_STRATUM]
        selected_keys = {candidate.review_key for candidate in selected_likely}

        alternatives = [
            candidate
            for candidate in internal.candidates
            if candidate.review_key not in selected_keys
            and (candidate.dense_rank is None or candidate.dense_rank > 40)
        ]
        alternatives.sort(key=self._alternative_sort_key)
        selected_alternatives = alternatives[: self.ITEMS_PER_STRATUM]
        selected_keys.update(candidate.review_key for candidate in selected_alternatives)

        contrast_candidates = [
            candidate
            for candidate in internal.candidates
            if candidate.review_key not in selected_keys
        ]
        contrast_candidates.sort(key=self._contrast_sort_key)
        selected_contrasts = contrast_candidates[: self.ITEMS_PER_STRATUM]

        strata = (
            (CalibrationSampleStratum.DENSE_LIKELY, selected_likely),
            (CalibrationSampleStratum.OFF_RANK_ALTERNATIVE, selected_alternatives),
            (CalibrationSampleStratum.LOW_SIGNAL_CONTRAST, selected_contrasts),
        )
        result = [
            CalibrationSampleManifestEntry(
                review_key=candidate.review_key,
                stratum=stratum,
            )
            for stratum, candidates in strata
            for candidate in candidates
        ]
        expected_count = self.ITEMS_PER_STRATUM * len(strata)
        if len(result) != expected_count:
            raise RuntimeError(
                "calibration 층화 표본 수가 부족합니다: "
                f"evaluation_id={reference.evaluation_id}, "
                f"expected={expected_count}, actual={len(result)}"
            )
        return result

    def _likely_sort_key(
        self,
        candidate: InternalCandidatePoolEntry,
    ) -> tuple[int, int, int, str]:
        return (
            -len(candidate.sources),
            -candidate.clinical_lexical_score,
            candidate.dense_rank or 10_000,
            candidate.review_key,
        )

    def _alternative_sort_key(
        self,
        candidate: InternalCandidatePoolEntry,
    ) -> tuple[int, int, int, str]:
        return (
            -candidate.clinical_lexical_score,
            -candidate.query_lexical_score,
            -len(candidate.sources),
            candidate.review_key,
        )

    def _contrast_sort_key(
        self,
        candidate: InternalCandidatePoolEntry,
    ) -> tuple[int, int, int, str]:
        return (
            candidate.query_lexical_score,
            candidate.clinical_lexical_score,
            -(candidate.dense_rank or 10_000),
            candidate.review_key,
        )


class NiaCaseCalibrationReviewSampleCli:
    @classmethod
    def main(cls) -> None:
        arguments = CalibrationSampleArgumentParser().parse()
        calibration = NiaCaseSemanticCalibrationLoader().load(arguments.calibration_path)
        loader = CandidatePoolArtifactLoader()
        result = NiaCaseCalibrationReviewSampler().sample(
            references=calibration.items,
            internal_items=loader.load_internal(arguments.internal_pool_path),
            blind_items=loader.load_blind(arguments.blind_pool_path),
        )
        writer = CandidatePoolJsonlWriter()
        writer.write(arguments.manifest_output_path, list(result.manifest_items))
        writer.write(arguments.blind_output_path, list(result.blind_items))
        print(
            f"calibration review sample: queries={len(result.blind_items)}, "
            f"candidates={sum(item.candidate_count for item in result.blind_items)}"
        )


if __name__ == "__main__":
    NiaCaseCalibrationReviewSampleCli.main()
