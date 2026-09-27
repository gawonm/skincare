"""NIA Case 최종 동결 평가 질의의 구조를 정의한다."""

from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from pydantic import Field, model_validator

from agent.rag.retrieval.case_candidate_selector import NiaCaseConcernCategory
from agent.rag.schemas import RagModel
from tests.agent.nia_case_semantic_golden_schemas import (
    ClinicalReferenceSource,
    IngredientGroupReference,
    NiaCaseSemanticCalibrationLoader,
    NiaCaseSemanticQueryReference,
    NiaCaseSemanticReferenceSet,
    RecommendationCaution,
    RecommendationConflict,
    SemanticGoldenPhase,
    SemanticQueryType,
)


class SemanticEvaluationCohort(StrEnum):
    CORE = "core"
    RARE_STRESS = "rare_stress"


class NiaCaseSemanticEvaluationQuery(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    cohort: SemanticEvaluationCohort
    query_type: SemanticQueryType
    query: str = Field(min_length=1)
    primary_concerns: list[NiaCaseConcernCategory] = Field(min_length=1)
    secondary_concerns: list[NiaCaseConcernCategory] = Field(default_factory=list)
    calibration_template_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_query(self) -> "NiaCaseSemanticEvaluationQuery":
        if set(self.primary_concerns) & set(self.secondary_concerns):
            raise ValueError("주 고민과 보조 고민은 중복될 수 없습니다.")
        if len(self.calibration_template_ids) != len(
            set(self.calibration_template_ids)
        ):
            raise ValueError("calibration 기준 카드 ID가 중복되었습니다.")
        return self


class NiaCaseSemanticEvaluationQuerySet(RagModel):
    items: list[NiaCaseSemanticEvaluationQuery] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_queries(self) -> "NiaCaseSemanticEvaluationQuerySet":
        if len({item.evaluation_id for item in self.items}) != len(self.items):
            raise ValueError("최종 평가 evaluation_id가 중복되었습니다.")
        if len({item.query.casefold().strip() for item in self.items}) != len(self.items):
            raise ValueError("최종 평가 사용자 질의가 중복되었습니다.")
        return self


class NiaCaseSemanticEvaluationQueryLoader:
    def load(self, path: Path) -> NiaCaseSemanticEvaluationQuerySet:
        try:
            items = [
                NiaCaseSemanticEvaluationQuery.model_validate_json(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, ValueError) as error:
            raise RuntimeError(f"최종 평가 질의 파일을 읽지 못했습니다: {path}") from error
        return NiaCaseSemanticEvaluationQuerySet(items=items)


class NiaCaseSemanticEvaluationReferenceBuilder:
    def build(
        self,
        query_set: NiaCaseSemanticEvaluationQuerySet,
        calibration_references: list[NiaCaseSemanticQueryReference],
    ) -> NiaCaseSemanticReferenceSet:
        templates = {item.evaluation_id: item for item in calibration_references}
        return NiaCaseSemanticReferenceSet(
            items=[self._build_reference(item, templates) for item in query_set.items]
        )

    def _build_reference(
        self,
        query: NiaCaseSemanticEvaluationQuery,
        templates: dict[str, NiaCaseSemanticQueryReference],
    ) -> NiaCaseSemanticQueryReference:
        selected = [templates[item] for item in query.calibration_template_ids]
        return NiaCaseSemanticQueryReference(
            evaluation_id=query.evaluation_id,
            phase=SemanticGoldenPhase.EVALUATION,
            query_type=query.query_type,
            query=query.query,
            primary_concerns=query.primary_concerns,
            secondary_concerns=query.secondary_concerns,
            required_functions=list(
                dict.fromkeys(
                    function
                    for reference in selected
                    for function in reference.required_functions
                )
            ),
            acceptable_ingredient_groups=self._ingredient_groups(selected),
            cautions=self._cautions(selected),
            contradictions=self._conflicts(selected),
            reference_sources=self._sources(selected),
        )

    def _ingredient_groups(
        self, references: list[NiaCaseSemanticQueryReference]
    ) -> list[IngredientGroupReference]:
        unique = {
            item.code: item
            for reference in references
            for item in reference.acceptable_ingredient_groups
        }
        return list(unique.values())

    def _cautions(
        self, references: list[NiaCaseSemanticQueryReference]
    ) -> list[RecommendationCaution]:
        unique = {
            item.code: item for reference in references for item in reference.cautions
        }
        return list(unique.values())

    def _conflicts(
        self, references: list[NiaCaseSemanticQueryReference]
    ) -> list[RecommendationConflict]:
        unique = {
            item.code: item
            for reference in references
            for item in reference.contradictions
        }
        return list(unique.values())

    def _sources(
        self, references: list[NiaCaseSemanticQueryReference]
    ) -> list[ClinicalReferenceSource]:
        unique = {
            str(item.url): item
            for reference in references
            for item in reference.reference_sources
        }
        return list(unique.values())


class NiaCaseSemanticEvaluationReferenceWriter:
    def write(self, path: Path, reference_set: NiaCaseSemanticReferenceSet) -> None:
        try:
            with path.open("w", encoding="utf-8", newline="\n") as destination:
                for item in reference_set.items:
                    destination.write(item.model_dump_json())
                    destination.write("\n")
        except OSError as error:
            raise RuntimeError(f"최종 평가 기준 카드를 쓰지 못했습니다: {path}") from error


class NiaCaseSemanticEvaluationReferenceCli:
    QUERY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_queries_v1.jsonl"
    )
    CALIBRATION_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_v1.jsonl"
    )
    OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_references_v1.jsonl"
    )

    @classmethod
    def main(cls) -> None:
        query_set = NiaCaseSemanticEvaluationQueryLoader().load(cls.QUERY_PATH)
        calibration = NiaCaseSemanticCalibrationLoader().load(cls.CALIBRATION_PATH)
        references = NiaCaseSemanticEvaluationReferenceBuilder().build(
            query_set=query_set,
            calibration_references=calibration.items,
        )
        NiaCaseSemanticEvaluationReferenceWriter().write(cls.OUTPUT_PATH, references)
        print(f"evaluation references: {len(references.items)}")


if __name__ == "__main__":
    NiaCaseSemanticEvaluationReferenceCli.main()
