"""NIA Case 의미 기반 평가의 anchor 판정을 최종 골든셋으로 동결한다."""

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Self

from pydantic import Field, model_validator

from agent.rag.schemas import RagModel
from tests.agent.nia_case_semantic_candidate_pool import (
    CandidatePoolArtifactLoader,
    InternalCandidatePoolItem,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQuery,
    NiaCaseSemanticEvaluationQueryLoader,
    SemanticEvaluationCohort,
)
from tests.agent.nia_case_semantic_golden_schemas import (
    FinalRelevanceGrade,
    JudgmentReasonCode,
    NiaCaseSemanticJudgment,
    NiaCaseSemanticJudgmentBatch,
    NiaCaseSemanticQueryReference,
    NiaCaseSemanticReferenceLoader,
    RecommendationConflictCode,
    RecommendationUtilityScore,
    SituationFitScore,
)


class SemanticGoldenJudgmentPolicy(StrEnum):
    POOLED_ANCHOR = "pooled_anchor"


class NiaCaseSemanticGoldenProvenance(RagModel):
    golden_version: str = Field(min_length=1)
    corpus_document_count: int = Field(ge=1)
    corpus_text_version: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    judgment_policy: SemanticGoldenJudgmentPolicy
    generated_at_kst: str = Field(min_length=1)


class NiaCaseSemanticGradedQrel(RagModel):
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    case_id: str = Field(min_length=1)
    situation_fit: SituationFitScore
    recommendation_utility: RecommendationUtilityScore
    conflict_codes: list[RecommendationConflictCode] = Field(default_factory=list)
    reason_codes: list[JudgmentReasonCode] = Field(min_length=1)
    relevance_grade: FinalRelevanceGrade
    note: str = Field(min_length=1)


class NiaCaseSemanticGoldenCase(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    cohort: SemanticEvaluationCohort
    query: str = Field(min_length=1)
    reference: NiaCaseSemanticQueryReference
    relevant_case_ids: list[str]
    highly_relevant_case_ids: list[str]
    corpus_ceiling_grade: FinalRelevanceGrade
    graded_qrels: list[NiaCaseSemanticGradedQrel] = Field(min_length=1)
    provenance: NiaCaseSemanticGoldenProvenance

    @model_validator(mode="after")
    def validate_derived_fields(self) -> Self:
        if self.reference.evaluation_id != self.evaluation_id:
            raise ValueError("질의와 추천 기준 카드의 evaluation_id가 다릅니다.")
        if self.reference.query != self.query:
            raise ValueError("질의와 추천 기준 카드의 query가 다릅니다.")
        if len({item.case_id for item in self.graded_qrels}) != len(self.graded_qrels):
            raise ValueError("동일 질의의 graded qrels에 중복 case_id가 있습니다.")

        expected_relevant = [
            item.case_id
            for item in self.graded_qrels
            if item.relevance_grade >= FinalRelevanceGrade.RELEVANT
        ]
        expected_highly_relevant = [
            item.case_id
            for item in self.graded_qrels
            if item.relevance_grade is FinalRelevanceGrade.HIGHLY_RELEVANT
        ]
        expected_ceiling = max(item.relevance_grade for item in self.graded_qrels)
        if self.relevant_case_ids != expected_relevant:
            raise ValueError("relevant_case_ids가 2~3점 qrels에서 파생되지 않았습니다.")
        if self.highly_relevant_case_ids != expected_highly_relevant:
            raise ValueError("highly_relevant_case_ids가 3점 qrels에서 파생되지 않았습니다.")
        if self.corpus_ceiling_grade is not expected_ceiling:
            raise ValueError("corpus_ceiling_grade가 anchor 최고 등급과 다릅니다.")
        return self


class NiaCaseSemanticGoldenSet(RagModel):
    items: list[NiaCaseSemanticGoldenCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_evaluation_ids(self) -> Self:
        evaluation_ids = [item.evaluation_id for item in self.items]
        if len(evaluation_ids) != len(set(evaluation_ids)):
            raise ValueError("최종 골든셋에 중복 evaluation_id가 있습니다.")
        return self


class NiaCaseSemanticJudgmentLoader:
    def load(self, paths: list[Path]) -> list[NiaCaseSemanticJudgmentBatch]:
        batches: list[NiaCaseSemanticJudgmentBatch] = []
        try:
            for path in paths:
                batches.extend(
                    NiaCaseSemanticJudgmentBatch.model_validate_json(line)
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
        except (OSError, ValueError) as error:
            raise RuntimeError("최종 평가 판정 파일을 읽지 못했습니다.") from error
        return batches


class NiaCaseSemanticGoldenBuilder:
    def build(
        self,
        queries: list[NiaCaseSemanticEvaluationQuery],
        references: list[NiaCaseSemanticQueryReference],
        internal_items: list[InternalCandidatePoolItem],
        judgments: list[NiaCaseSemanticJudgmentBatch],
        provenance: NiaCaseSemanticGoldenProvenance,
    ) -> NiaCaseSemanticGoldenSet:
        references_by_id = {item.evaluation_id: item for item in references}
        internal_by_id = {item.evaluation_id: item for item in internal_items}
        judgments_by_id = self._merge_judgments(judgments)
        expected_ids = {item.evaluation_id for item in queries}
        self._validate_id_set("추천 기준", expected_ids, set(references_by_id))
        self._validate_id_set("후보 풀", expected_ids, set(internal_by_id))
        self._validate_id_set("판정", expected_ids, set(judgments_by_id))

        items = [
            self._build_case(
                query=query,
                reference=references_by_id[query.evaluation_id],
                internal=internal_by_id[query.evaluation_id],
                batch=judgments_by_id[query.evaluation_id],
                provenance=provenance,
            )
            for query in queries
        ]
        return NiaCaseSemanticGoldenSet(items=items)

    def _merge_judgments(
        self,
        batches: list[NiaCaseSemanticJudgmentBatch],
    ) -> dict[str, NiaCaseSemanticJudgmentBatch]:
        grouped: dict[str, list[NiaCaseSemanticJudgment]] = {}
        for batch in batches:
            grouped.setdefault(batch.evaluation_id, []).extend(batch.judgments)
        merged: dict[str, NiaCaseSemanticJudgmentBatch] = {}
        for evaluation_id, items in grouped.items():
            review_keys = [item.review_key for item in items]
            if len(review_keys) != len(set(review_keys)):
                raise RuntimeError(
                    f"anchor와 reranker 보완 판정에 중복 review_key가 있습니다: {evaluation_id}"
                )
            merged[evaluation_id] = NiaCaseSemanticJudgmentBatch(
                evaluation_id=evaluation_id,
                judgments=items,
            )
        return merged

    def _build_case(
        self,
        query: NiaCaseSemanticEvaluationQuery,
        reference: NiaCaseSemanticQueryReference,
        internal: InternalCandidatePoolItem,
        batch: NiaCaseSemanticJudgmentBatch,
        provenance: NiaCaseSemanticGoldenProvenance,
    ) -> NiaCaseSemanticGoldenCase:
        case_ids_by_key = {
            candidate.review_key: candidate.case_id for candidate in internal.candidates
        }
        qrels = [self._build_qrel(item, case_ids_by_key) for item in batch.judgments]
        qrels.sort(key=lambda item: (-item.relevance_grade.value, item.case_id))
        return NiaCaseSemanticGoldenCase(
            evaluation_id=query.evaluation_id,
            cohort=query.cohort,
            query=query.query,
            reference=reference,
            relevant_case_ids=[
                item.case_id
                for item in qrels
                if item.relevance_grade >= FinalRelevanceGrade.RELEVANT
            ],
            highly_relevant_case_ids=[
                item.case_id
                for item in qrels
                if item.relevance_grade is FinalRelevanceGrade.HIGHLY_RELEVANT
            ],
            corpus_ceiling_grade=max(item.relevance_grade for item in qrels),
            graded_qrels=qrels,
            provenance=provenance,
        )

    def _build_qrel(
        self,
        judgment: NiaCaseSemanticJudgment,
        case_ids_by_key: dict[str, str],
    ) -> NiaCaseSemanticGradedQrel:
        try:
            case_id = case_ids_by_key[judgment.review_key]
        except KeyError as error:
            raise RuntimeError(
                f"판정 review_key가 내부 후보 풀에 없습니다: {judgment.review_key}"
            ) from error
        return NiaCaseSemanticGradedQrel(
            review_key=judgment.review_key,
            case_id=case_id,
            situation_fit=judgment.situation_fit,
            recommendation_utility=judgment.recommendation_utility,
            conflict_codes=judgment.conflict_codes,
            reason_codes=judgment.reason_codes,
            relevance_grade=judgment.relevance_grade,
            note=judgment.note,
        )

    def _validate_id_set(
        self,
        label: str,
        expected_ids: set[str],
        actual_ids: set[str],
    ) -> None:
        if actual_ids != expected_ids:
            missing = sorted(expected_ids - actual_ids)
            unexpected = sorted(actual_ids - expected_ids)
            raise RuntimeError(
                f"{label} evaluation_id 구성이 질의와 다릅니다: "
                f"missing={missing}, unexpected={unexpected}"
            )


class NiaCaseSemanticGoldenArtifact:
    def write(self, path: Path, golden_set: NiaCaseSemanticGoldenSet) -> None:
        try:
            with path.open("w", encoding="utf-8", newline="\n") as destination:
                for item in golden_set.items:
                    destination.write(item.model_dump_json())
                    destination.write("\n")
        except OSError as error:
            raise RuntimeError(f"최종 골든셋을 쓰지 못했습니다: {path}") from error

    def load(self, path: Path) -> NiaCaseSemanticGoldenSet:
        try:
            items = [
                NiaCaseSemanticGoldenCase.model_validate_json(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, ValueError) as error:
            raise RuntimeError(f"최종 골든셋을 읽지 못했습니다: {path}") from error
        return NiaCaseSemanticGoldenSet(items=items)


class NiaCaseSemanticGoldenCli:
    QUERY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_queries_v1.jsonl"
    )
    REFERENCE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_references_v1.jsonl"
    )
    INTERNAL_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_pool_v1.jsonl"
    )
    JUDGMENT_DIRECTORY: ClassVar[Path] = Path("tests/agent")
    JUDGMENT_PATTERNS: ClassVar[tuple[str, ...]] = (
        "nia_case_semantic_evaluation_anchor_judgments_*_v1.jsonl",
        "nia_case_semantic_evaluation_rerank_judgments_*_v1.jsonl",
    )
    OUTPUT_PATH: ClassVar[Path] = Path("tests/agent/nia_case_semantic_golden_v1.jsonl")
    GOLDEN_VERSION: ClassVar[str] = "nia_case_semantic_golden/v1"
    CORPUS_DOCUMENT_COUNT: ClassVar[int] = 3_581
    CORPUS_TEXT_VERSION: ClassVar[str] = "nia_case_text/v1"
    EMBEDDING_MODEL: ClassVar[str] = "BAAI/bge-m3"
    # Windows 실행 환경에 IANA tzdata가 없어도 동일한 KST 시각을 기록하기 위해 고정 오프셋을 쓴다.
    KST: ClassVar[timezone] = timezone(timedelta(hours=9), name="KST")

    @classmethod
    def main(cls) -> None:
        queries = NiaCaseSemanticEvaluationQueryLoader().load(cls.QUERY_PATH)
        references = NiaCaseSemanticReferenceLoader().load(cls.REFERENCE_PATH)
        internal = CandidatePoolArtifactLoader().load_internal(cls.INTERNAL_POOL_PATH)
        judgment_paths = sorted(
            path
            for pattern in cls.JUDGMENT_PATTERNS
            for path in cls.JUDGMENT_DIRECTORY.glob(pattern)
        )
        judgments = NiaCaseSemanticJudgmentLoader().load(judgment_paths)
        provenance = NiaCaseSemanticGoldenProvenance(
            golden_version=cls.GOLDEN_VERSION,
            corpus_document_count=cls.CORPUS_DOCUMENT_COUNT,
            corpus_text_version=cls.CORPUS_TEXT_VERSION,
            embedding_model=cls.EMBEDDING_MODEL,
            judgment_policy=SemanticGoldenJudgmentPolicy.POOLED_ANCHOR,
            generated_at_kst=datetime.now(cls.KST).isoformat(timespec="seconds"),
        )
        golden_set = NiaCaseSemanticGoldenBuilder().build(
            queries=queries.items,
            references=references.items,
            internal_items=internal,
            judgments=judgments,
            provenance=provenance,
        )
        NiaCaseSemanticGoldenArtifact().write(cls.OUTPUT_PATH, golden_set)
        print(
            f"semantic golden: queries={len(golden_set.items)}, "
            f"qrels={sum(len(item.graded_qrels) for item in golden_set.items)}, "
            f"relevant={sum(len(item.relevant_case_ids) for item in golden_set.items)}"
        )


if __name__ == "__main__":
    NiaCaseSemanticGoldenCli.main()
