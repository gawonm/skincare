"""NIA Case 코퍼스 상대 골든셋의 소규모 블라인드 감사 표본을 만든다."""

import hashlib
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from pydantic import Field, FiniteFloat

from agent.rag.schemas import RagModel
from tests.agent.evaluate_nia_case_corpus_relative_golden import (
    NiaCaseCorpusRelativeGoldenCase,
)
from tests.agent.nia_case_corpus_relevance_schemas import (
    CorpusRelevanceGrade,
    NiaCaseCorpusRelevanceJudgmentBatch,
)
from tests.agent.nia_case_semantic_candidate_pool import (
    BlindCandidatePoolItem,
    CandidatePoolArtifactLoader,
    CandidatePoolJsonlWriter,
)


class CorpusRelativeAuditSamplingPolicy(StrEnum):
    ONE_PER_QUERY_HASH_V1 = "one_per_query_hash_v1"


class NiaCaseCorpusRelativeAuditManifestEntry(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    policy: CorpusRelativeAuditSamplingPolicy


class NiaCaseCorpusRelativeAuditBuildResult(RagModel):
    manifests: list[NiaCaseCorpusRelativeAuditManifestEntry] = Field(min_length=1)
    blind_items: list[BlindCandidatePoolItem] = Field(min_length=1)


class NiaCaseCorpusRelativeAuditGradeCount(RagModel):
    grade: CorpusRelevanceGrade
    count: int = Field(ge=0)


class NiaCaseCorpusRelativeAuditDisagreement(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    frozen_grade: CorpusRelevanceGrade
    audit_grade: CorpusRelevanceGrade


class NiaCaseCorpusRelativeAuditReport(RagModel):
    sample_count: int = Field(ge=1)
    exact_grade_agreement: FiniteFloat = Field(ge=0.0, le=1.0)
    within_one_grade_agreement: FiniteFloat = Field(ge=0.0, le=1.0)
    binary_relevance_agreement: FiniteFloat = Field(ge=0.0, le=1.0)
    quadratic_weighted_kappa: FiniteFloat = Field(ge=-1.0, le=1.0)
    frozen_grade_counts: list[NiaCaseCorpusRelativeAuditGradeCount]
    audit_grade_counts: list[NiaCaseCorpusRelativeAuditGradeCount]
    disagreements: list[NiaCaseCorpusRelativeAuditDisagreement]


class NiaCaseCorpusRelativeAuditSampler:
    """기존 등급과 무관한 해시로 질의별 후보 한 건을 선택한다."""

    SAMPLE_COUNT_PER_QUERY: ClassVar[int] = 1

    def sample(
        self,
        items: list[BlindCandidatePoolItem],
    ) -> NiaCaseCorpusRelativeAuditBuildResult:
        manifests: list[NiaCaseCorpusRelativeAuditManifestEntry] = []
        blind_items: list[BlindCandidatePoolItem] = []
        for item in sorted(items, key=lambda candidate: candidate.evaluation_id):
            candidates = sorted(item.candidates, key=lambda candidate: candidate.review_key)
            digest = hashlib.sha256(item.evaluation_id.encode("utf-8")).digest()
            index = int.from_bytes(digest[:8], byteorder="big") % len(candidates)
            selected = candidates[index]
            manifests.append(
                NiaCaseCorpusRelativeAuditManifestEntry(
                    evaluation_id=item.evaluation_id,
                    review_key=selected.review_key,
                    policy=CorpusRelativeAuditSamplingPolicy.ONE_PER_QUERY_HASH_V1,
                )
            )
            blind_items.append(
                BlindCandidatePoolItem(
                    evaluation_id=item.evaluation_id,
                    query=item.query,
                    candidate_count=self.SAMPLE_COUNT_PER_QUERY,
                    candidates=[selected],
                )
            )
        return NiaCaseCorpusRelativeAuditBuildResult(
            manifests=manifests,
            blind_items=blind_items,
        )


class NiaCaseCorpusRelativeAuditEvaluator:
    """블라인드 재판정과 동결 qrel의 일치도를 계산한다."""

    def evaluate(
        self,
        blind_items: list[BlindCandidatePoolItem],
        audit_batches: list[NiaCaseCorpusRelevanceJudgmentBatch],
        golden_cases: list[NiaCaseCorpusRelativeGoldenCase],
    ) -> NiaCaseCorpusRelativeAuditReport:
        sampled_keys = {
            item.evaluation_id: item.candidates[0].review_key for item in blind_items
        }
        audit_by_id = {item.evaluation_id: item for item in audit_batches}
        golden_by_id = {item.evaluation_id.value: item for item in golden_cases}
        if set(sampled_keys) != set(audit_by_id):
            raise RuntimeError("감사 표본과 재판정 배치의 evaluation_id가 다릅니다.")

        frozen_grades: list[CorpusRelevanceGrade] = []
        audit_grades: list[CorpusRelevanceGrade] = []
        disagreements: list[NiaCaseCorpusRelativeAuditDisagreement] = []
        for evaluation_id, review_key in sorted(sampled_keys.items()):
            batch = audit_by_id[evaluation_id]
            if len(batch.judgments) != 1 or batch.judgments[0].review_key != review_key:
                raise RuntimeError(
                    "감사 재판정이 블라인드 표본 한 건을 정확히 덮지 않습니다: "
                    f"{evaluation_id}"
                )
            frozen_qrel = next(
                qrel
                for qrel in golden_by_id[evaluation_id].graded_qrels
                if qrel.review_key == review_key
            )
            frozen_grade = frozen_qrel.relevance_grade
            audit_grade = batch.judgments[0].relevance_grade
            frozen_grades.append(frozen_grade)
            audit_grades.append(audit_grade)
            if frozen_grade is not audit_grade:
                disagreements.append(
                    NiaCaseCorpusRelativeAuditDisagreement(
                        evaluation_id=evaluation_id,
                        review_key=review_key,
                        frozen_grade=frozen_grade,
                        audit_grade=audit_grade,
                    )
                )

        sample_count = len(frozen_grades)
        return NiaCaseCorpusRelativeAuditReport(
            sample_count=sample_count,
            exact_grade_agreement=sum(
                frozen is audit
                for frozen, audit in zip(frozen_grades, audit_grades, strict=True)
            )
            / sample_count,
            within_one_grade_agreement=sum(
                abs(int(frozen) - int(audit)) <= 1
                for frozen, audit in zip(frozen_grades, audit_grades, strict=True)
            )
            / sample_count,
            binary_relevance_agreement=sum(
                (frozen >= CorpusRelevanceGrade.RELEVANT)
                == (audit >= CorpusRelevanceGrade.RELEVANT)
                for frozen, audit in zip(frozen_grades, audit_grades, strict=True)
            )
            / sample_count,
            quadratic_weighted_kappa=self._quadratic_weighted_kappa(
                frozen_grades,
                audit_grades,
            ),
            frozen_grade_counts=self._grade_counts(frozen_grades),
            audit_grade_counts=self._grade_counts(audit_grades),
            disagreements=disagreements,
        )

    def _grade_counts(
        self,
        grades: list[CorpusRelevanceGrade],
    ) -> list[NiaCaseCorpusRelativeAuditGradeCount]:
        return [
            NiaCaseCorpusRelativeAuditGradeCount(
                grade=grade,
                count=grades.count(grade),
            )
            for grade in CorpusRelevanceGrade
        ]

    def _quadratic_weighted_kappa(
        self,
        frozen_grades: list[CorpusRelevanceGrade],
        audit_grades: list[CorpusRelevanceGrade],
    ) -> float:
        grade_values = [int(grade) for grade in CorpusRelevanceGrade]
        maximum_distance_squared = float(max(grade_values) ** 2)
        sample_count = len(frozen_grades)
        observed_disagreement = sum(
            ((int(frozen) - int(audit)) ** 2) / maximum_distance_squared
            for frozen, audit in zip(frozen_grades, audit_grades, strict=True)
        ) / sample_count
        frozen_counts = {grade: frozen_grades.count(grade) for grade in CorpusRelevanceGrade}
        audit_counts = {grade: audit_grades.count(grade) for grade in CorpusRelevanceGrade}
        expected_disagreement = sum(
            (((int(frozen) - int(audit)) ** 2) / maximum_distance_squared)
            * (frozen_counts[frozen] / sample_count)
            * (audit_counts[audit] / sample_count)
            for frozen in CorpusRelevanceGrade
            for audit in CorpusRelevanceGrade
        )
        if expected_disagreement == 0.0:
            return 1.0 if observed_disagreement == 0.0 else 0.0
        return 1.0 - (observed_disagreement / expected_disagreement)


class NiaCaseCorpusRelativeAuditMarkdownReporter:
    def render(self, report: NiaCaseCorpusRelativeAuditReport) -> str:
        frozen_counts = {item.grade: item.count for item in report.frozen_grade_counts}
        audit_counts = {item.grade: item.count for item in report.audit_grade_counts}
        lines = [
            "# NIA Case 코퍼스 상대 골든셋 v2 복원 및 블라인드 감사",
            "",
            "## 감사 범위",
            "",
            "- 최종 골든셋에서 유실된 판정 원본 200건을 역복원했다.",
            "- 기존에 남아 있던 18건은 복원 예상값과 완전히 일치할 때만 보존했다.",
            "- 골든셋, 평가 JSON, 자동 생성 보고서 구간이 복원 원본으로 재현되는지 확인했다.",
            "- 기존 등급·case_id·검색 순위를 제외하고 질의별 1건을 해시로 선택해 24건을 다시 판정했다.",
            "",
            "## 일치도 결과",
            "",
            f"- 정확 등급 일치율: `{report.exact_grade_agreement:.3f}`",
            f"- ±1 등급 이내 일치율: `{report.within_one_grade_agreement:.3f}`",
            f"- 관련/비관련 이진 일치율(2점 이상): `{report.binary_relevance_agreement:.3f}`",
            f"- Quadratic weighted kappa: `{report.quadratic_weighted_kappa:.3f}`",
            "",
            "| 등급 | 동결 골든 | 감사 재판정 |",
            "| ---: | ---: | ---: |",
        ]
        for grade in CorpusRelevanceGrade:
            lines.append(
                f"| {int(grade)} | {frozen_counts[grade]} | {audit_counts[grade]} |"
            )
        lines.extend(
            [
                "",
                "## 불일치 사례",
                "",
                "| evaluation_id | review_key | 동결 | 감사 |",
                "| --- | --- | ---: | ---: |",
            ]
        )
        for item in report.disagreements:
            lines.append(
                f"| `{item.evaluation_id}` | `{item.review_key}` | "
                f"{int(item.frozen_grade)} | {int(item.audit_grade)} |"
            )
        if not report.disagreements:
            lines.append("| - | - | - | - |")
        lines.extend(
            [
                "",
                "## 해석 한계",
                "",
                (
                    "이번 감사 재판정도 동일 세션의 모델이 수행했으므로 독립된 두 번째 평가자의 검증은 아니다. "
                    "따라서 이 결과는 판정 규칙의 내부 일관성 점검으로 해석하고, 최종 신뢰성 주장은 사람 또는 "
                    "독립 세션의 추가 표본 판정으로 보강해야 한다."
                ),
                "",
            ]
        )
        return "\n".join(lines)


class NiaCaseCorpusRelativeAuditCli:
    SOURCE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_anchor_blind_v1.jsonl"
    )
    MANIFEST_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_audit_manifest_v1.jsonl"
    )
    BLIND_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_audit_blind_v1.jsonl"
    )
    JUDGMENT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_audit_judgments_v1.jsonl"
    )
    GOLDEN_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_corpus_relative_golden_v2.jsonl"
    )
    REPORT_OUTPUT_PATH: ClassVar[Path] = Path(
        "docs/agent/RAG_YK/2026-09-26_NIA_CASE_CORPUS_RELATIVE_GOLDEN_AUDIT.md"
    )

    @classmethod
    def main(cls) -> None:
        source = CandidatePoolArtifactLoader().load_blind(cls.SOURCE_PATH)
        result = NiaCaseCorpusRelativeAuditSampler().sample(source)
        writer = CandidatePoolJsonlWriter()
        writer.write(cls.MANIFEST_OUTPUT_PATH, list(result.manifests))
        writer.write(cls.BLIND_OUTPUT_PATH, list(result.blind_items))
        print(
            "블라인드 감사 표본 생성 완료: "
            f"queries={len(result.blind_items)}, "
            f"candidates={sum(item.candidate_count for item in result.blind_items)}"
        )
        if not cls.JUDGMENT_PATH.exists():
            return
        judgments = [
            NiaCaseCorpusRelevanceJudgmentBatch.model_validate_json(line)
            for line in cls.JUDGMENT_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        golden_cases = [
            NiaCaseCorpusRelativeGoldenCase.model_validate_json(line)
            for line in cls.GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        report = NiaCaseCorpusRelativeAuditEvaluator().evaluate(
            blind_items=result.blind_items,
            audit_batches=judgments,
            golden_cases=golden_cases,
        )
        cls.REPORT_OUTPUT_PATH.write_text(
            NiaCaseCorpusRelativeAuditMarkdownReporter().render(report),
            encoding="utf-8",
        )
        print(
            "블라인드 감사 평가 완료: "
            f"exact={report.exact_grade_agreement:.3f}, "
            f"within_one={report.within_one_grade_agreement:.3f}, "
            f"binary={report.binary_relevance_agreement:.3f}, "
            f"weighted_kappa={report.quadratic_weighted_kappa:.3f}"
        )


if __name__ == "__main__":
    NiaCaseCorpusRelativeAuditCli.main()
