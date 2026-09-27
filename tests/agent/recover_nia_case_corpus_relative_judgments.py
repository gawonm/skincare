"""확정된 골든셋에서 유실된 NIA Case 판정 원본을 안전하게 복원한다."""

from enum import StrEnum
from pathlib import Path
from typing import ClassVar, TypeVar

from pydantic import Field

from agent.rag.schemas import RagModel
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeEvaluationCli,
    NiaCaseCorpusRelativeGoldenBuilder,
    NiaCaseCorpusRelativeGoldenCase,
    NiaCaseCorpusRelativeGoldenEvaluator,
    NiaCaseCorpusRelativeGradedQrel,
    NiaCaseCorpusRelativeJudgmentArtifactLoader,
    NiaCaseCorpusRelativeMarkdownReporter,
    NiaCaseCorpusRelativeQueryEvaluation,
)
from tests.agent.nia_case_corpus_relative_golden import (
    CorpusRelativeAnchorManifestItem,
)
from tests.agent.nia_case_corpus_relevance_schemas import (
    CorpusRelevanceJudgmentPolicy,
    NiaCaseCorpusRelevanceJudgment,
    NiaCaseCorpusRelevanceJudgmentBatch,
)
from tests.agent.nia_case_semantic_candidate_pool import (
    CandidatePoolArtifactLoader,
    CandidatePoolJsonlWriter,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQueryLoader,
)
from tests.agent.nia_case_semantic_rerank_probe import (
    NiaCaseSemanticRerankProbeItem,
)


class CorpusRelativeEvaluationIdPrefix(StrEnum):
    CORE = "evaluation_core_"
    RARE = "evaluation_rare_"


RecoveryModel = TypeVar("RecoveryModel", bound=RagModel)


class NiaCaseCorpusRelativeRecoveryResult(RagModel):
    anchor_batch_count: int = Field(ge=1)
    anchor_judgment_count: int = Field(ge=1)
    restored_anchor_file_count: int = Field(ge=0)
    preserved_anchor_file_count: int = Field(ge=0)
    rerank_batch_count: int = Field(ge=1)
    rerank_judgment_count: int = Field(ge=1)
    restored_rerank_file: bool


class NiaCaseCorpusRelativeVerificationResult(RagModel):
    golden_matches: bool
    evaluation_matches: bool
    report_matches: bool


class NiaCaseCorpusRelativeJudgmentRecovery:
    """최종 qrel을 판정 배치로 역변환하고 블라인드 후보와 대조한다."""

    JUDGMENT_FILE_PREFIX: ClassVar[str] = (
        "nia_case_corpus_relative_judgments_"
    )
    JUDGMENT_FILE_SUFFIX: ClassVar[str] = "_v1.jsonl"

    def recover(
        self,
        golden_path: Path,
        anchor_blind_path: Path,
        rerank_blind_path: Path,
        judgment_directory: Path,
        rerank_judgment_path: Path,
    ) -> NiaCaseCorpusRelativeRecoveryResult:
        golden_cases = self._load_golden(golden_path)
        anchor_batches, rerank_batches = self._build_batches(golden_cases)
        self._validate_blind_coverage(anchor_batches, anchor_blind_path)
        self._validate_blind_coverage(rerank_batches, rerank_blind_path)

        restored_anchor_count = 0
        preserved_anchor_count = 0
        for evaluation_id, batch in sorted(anchor_batches.items()):
            path = judgment_directory / self._anchor_filename(evaluation_id)
            if path.exists() and path.read_text(encoding="utf-8").strip():
                existing = NiaCaseCorpusRelevanceJudgmentBatch.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                if existing != batch:
                    raise RuntimeError(
                        "기존 anchor 판정과 최종 골든의 판정이 다릅니다. "
                        f"자동 복원을 중단합니다: {path}"
                    )
                preserved_anchor_count += 1
                continue
            CandidatePoolJsonlWriter().write(path, [batch])
            restored_anchor_count += 1

        restored_rerank = self._write_rerank_batches(
            rerank_judgment_path,
            rerank_batches,
        )
        return NiaCaseCorpusRelativeRecoveryResult(
            anchor_batch_count=len(anchor_batches),
            anchor_judgment_count=sum(
                len(batch.judgments) for batch in anchor_batches.values()
            ),
            restored_anchor_file_count=restored_anchor_count,
            preserved_anchor_file_count=preserved_anchor_count,
            rerank_batch_count=len(rerank_batches),
            rerank_judgment_count=sum(
                len(batch.judgments) for batch in rerank_batches.values()
            ),
            restored_rerank_file=restored_rerank,
        )

    def _load_golden(self, path: Path) -> list[NiaCaseCorpusRelativeGoldenCase]:
        return [
            NiaCaseCorpusRelativeGoldenCase.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _build_batches(
        self,
        golden_cases: list[NiaCaseCorpusRelativeGoldenCase],
    ) -> tuple[
        dict[str, NiaCaseCorpusRelevanceJudgmentBatch],
        dict[str, NiaCaseCorpusRelevanceJudgmentBatch],
    ]:
        anchor_batches: dict[str, NiaCaseCorpusRelevanceJudgmentBatch] = {}
        rerank_batches: dict[str, NiaCaseCorpusRelevanceJudgmentBatch] = {}
        for golden in golden_cases:
            evaluation_id = golden.evaluation_id.value
            anchors = [
                self._to_judgment(qrel)
                for qrel in golden.graded_qrels
                if qrel.is_initial_anchor
            ]
            supplements = [
                self._to_judgment(qrel)
                for qrel in golden.graded_qrels
                if not qrel.is_initial_anchor
            ]
            anchor_batches[evaluation_id] = self._batch(evaluation_id, anchors)
            if supplements:
                rerank_batches[evaluation_id] = self._batch(
                    evaluation_id,
                    supplements,
                )
        return anchor_batches, rerank_batches

    def _to_judgment(
        self,
        qrel: NiaCaseCorpusRelativeGradedQrel,
    ) -> NiaCaseCorpusRelevanceJudgment:
        # case_id와 검색 순위는 판정 시 보이지 않았으므로 판정 필드만 복원한다.
        return NiaCaseCorpusRelevanceJudgment.model_validate(
            qrel.model_dump(
                include={
                    "review_key",
                    "concern_fit",
                    "context_fit",
                    "request_fit",
                    "direction_conflicts",
                    "reason_codes",
                    "relevance_grade",
                    "note",
                }
            )
        )

    def _batch(
        self,
        evaluation_id: str,
        judgments: list[NiaCaseCorpusRelevanceJudgment],
    ) -> NiaCaseCorpusRelevanceJudgmentBatch:
        return NiaCaseCorpusRelevanceJudgmentBatch(
            evaluation_id=evaluation_id,
            policy=CorpusRelevanceJudgmentPolicy.NIA_CORPUS_RELATIVE_POOLED_V1,
            judgments=sorted(judgments, key=lambda item: item.review_key),
        )

    def _validate_blind_coverage(
        self,
        batches: dict[str, NiaCaseCorpusRelevanceJudgmentBatch],
        blind_path: Path,
    ) -> None:
        blind_by_id = {
            item.evaluation_id: item
            for item in CandidatePoolArtifactLoader().load_blind(blind_path)
        }
        if set(batches) != set(blind_by_id):
            raise RuntimeError(
                "복원 대상과 블라인드 후보의 evaluation_id 집합이 다릅니다: "
                f"judgments_only={sorted(set(batches) - set(blind_by_id))}, "
                f"blind_only={sorted(set(blind_by_id) - set(batches))}"
            )
        for evaluation_id, batch in batches.items():
            expected_keys = {
                candidate.review_key
                for candidate in blind_by_id[evaluation_id].candidates
            }
            actual_keys = {judgment.review_key for judgment in batch.judgments}
            if actual_keys != expected_keys:
                raise RuntimeError(
                    "복원 판정과 블라인드 후보의 review_key가 다릅니다: "
                    f"evaluation_id={evaluation_id}, "
                    f"judgments_only={sorted(actual_keys - expected_keys)}, "
                    f"blind_only={sorted(expected_keys - actual_keys)}"
                )

    def _anchor_filename(self, evaluation_id: str) -> str:
        suffix = evaluation_id
        for prefix in CorpusRelativeEvaluationIdPrefix:
            if evaluation_id.startswith(prefix.value):
                suffix = evaluation_id.removeprefix(prefix.value)
                break
        if suffix == evaluation_id:
            raise RuntimeError(f"지원하지 않는 evaluation_id입니다: {evaluation_id}")
        return f"{self.JUDGMENT_FILE_PREFIX}{suffix}{self.JUDGMENT_FILE_SUFFIX}"

    def _write_rerank_batches(
        self,
        path: Path,
        batches: dict[str, NiaCaseCorpusRelevanceJudgmentBatch],
    ) -> bool:
        expected = [batch for _, batch in sorted(batches.items())]
        if path.exists() and path.read_text(encoding="utf-8").strip():
            existing = [
                NiaCaseCorpusRelevanceJudgmentBatch.model_validate_json(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if existing != expected:
                raise RuntimeError(
                    "기존 reranker 보완 판정과 최종 골든의 판정이 다릅니다. "
                    f"자동 복원을 중단합니다: {path}"
                )
            return False
        CandidatePoolJsonlWriter().write(path, expected)
        return True


class NiaCaseCorpusRelativeRecoveryVerifier:
    """복원된 원본만으로 기존 산출물이 재현되는지 쓰기 없이 확인한다."""

    def verify(self) -> NiaCaseCorpusRelativeVerificationResult:
        paths = NiaCaseCorpusRelativeEvaluationCli
        query_loader = NiaCaseSemanticEvaluationQueryLoader()
        queries = query_loader.load(paths.QUERY_PATH).items
        manifests = self._load_models(
            paths.MANIFEST_PATH,
            CorpusRelativeAnchorManifestItem,
        )
        query_ids = {item.evaluation_id for item in queries}
        pool_loader = CandidatePoolArtifactLoader()
        internal_items = [
            item
            for item in pool_loader.load_internal(paths.INTERNAL_POOL_PATH)
            if item.evaluation_id in query_ids
        ]
        probes = [
            item
            for item in self._load_models(
                paths.RERANK_PROBE_PATH,
                NiaCaseSemanticRerankProbeItem,
            )
            if item.evaluation_id in query_ids
        ]

        judgment_loader = NiaCaseCorpusRelativeJudgmentArtifactLoader()
        rebuilt_golden = NiaCaseCorpusRelativeGoldenBuilder().build(
            queries=queries,
            manifests=manifests,
            internal_items=internal_items,
            anchor_batches=judgment_loader.load_anchor_batches(
                paths.ANCHOR_JUDGMENT_DIR
            ),
            rerank_batches=judgment_loader.load_rerank_batches(
                paths.RERANK_JUDGMENT_PATH
            ),
        )
        frozen_golden = self._load_models(
            paths.GOLDEN_OUTPUT_PATH,
            NiaCaseCorpusRelativeGoldenCase,
        )
        if rebuilt_golden != frozen_golden:
            raise RuntimeError("복원 판정으로 재구축한 골든셋이 기존 골든셋과 다릅니다.")

        rebuilt_report = NiaCaseCorpusRelativeGoldenEvaluator().evaluate(
            queries=queries,
            golden_cases=rebuilt_golden,
            internal_items=internal_items,
            probes=probes,
        )
        frozen_evaluations = self._load_models(
            paths.EVALUATION_OUTPUT_PATH,
            NiaCaseCorpusRelativeQueryEvaluation,
        )
        if rebuilt_report.queries != frozen_evaluations:
            raise RuntimeError("복원 판정으로 재계산한 평가 결과가 기존 결과와 다릅니다.")

        rendered_report = NiaCaseCorpusRelativeMarkdownReporter().render(rebuilt_report)
        frozen_report = paths.REPORT_OUTPUT_PATH.read_text(encoding="utf-8")
        # 기존 보고서의 5~6절은 평가 후 수동 분석이므로 자동 생성 구간만 동일성을 확인한다.
        if not frozen_report.startswith(rendered_report):
            raise RuntimeError(
                "복원 판정으로 재생성한 보고서 구간이 기존 보고서와 다릅니다."
            )
        return NiaCaseCorpusRelativeVerificationResult(
            golden_matches=True,
            evaluation_matches=True,
            report_matches=True,
        )

    def _load_models(
        self,
        path: Path,
        model_type: type[RecoveryModel],
    ) -> list[RecoveryModel]:
        return [
            model_type.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class NiaCaseCorpusRelativeRecoveryCli:
    ANCHOR_BLIND_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_anchor_blind_v1.jsonl"
    )
    RERANK_BLIND_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_rerank_unjudged_blind_v1.jsonl"
    )

    @classmethod
    def main(cls) -> None:
        paths = NiaCaseCorpusRelativeEvaluationCli
        recovery = NiaCaseCorpusRelativeJudgmentRecovery().recover(
            golden_path=paths.GOLDEN_OUTPUT_PATH,
            anchor_blind_path=cls.ANCHOR_BLIND_PATH,
            rerank_blind_path=cls.RERANK_BLIND_PATH,
            judgment_directory=paths.ANCHOR_JUDGMENT_DIR,
            rerank_judgment_path=paths.RERANK_JUDGMENT_PATH,
        )
        verification = NiaCaseCorpusRelativeRecoveryVerifier().verify()
        print(
            "판정 원본 복원 완료: "
            f"anchor={recovery.anchor_judgment_count}, "
            f"rerank={recovery.rerank_judgment_count}, "
            f"restored_anchor_files={recovery.restored_anchor_file_count}, "
            f"preserved_anchor_files={recovery.preserved_anchor_file_count}, "
            f"rerank_file_restored={recovery.restored_rerank_file}, "
            f"reproducible={verification.golden_matches and verification.evaluation_matches and verification.report_matches}"
        )


if __name__ == "__main__":
    NiaCaseCorpusRelativeRecoveryCli.main()
