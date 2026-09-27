"""NIA Case 의미 검색 골든셋의 질의 기준표와 관련도 판정 스키마."""

from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Self

from pydantic import Field, HttpUrl, ValidationError, model_validator

from agent.rag.retrieval.case_candidate_selector import NiaCaseConcernCategory
from agent.rag.schemas import RagModel


class SemanticGoldenPhase(StrEnum):
    CALIBRATION = "calibration"
    EVALUATION = "evaluation"


class SemanticQueryType(StrEnum):
    SIMPLE = "simple"
    PROFILE_RICH = "profile_rich"
    COMPOSITE = "composite"
    CONFOUNDING = "confounding"


class RecommendationFunction(StrEnum):
    GENTLE_CLEANSING = "gentle_cleansing"
    BARRIER_SUPPORT = "barrier_support"
    HUMECTANCY = "humectancy"
    EMOLLIENCE = "emollience"
    OCCLUSION = "occlusion"
    COMEDONE_CONTROL = "comedone_control"
    SEBUM_BALANCE = "sebum_balance"
    ACNE_INFLAMMATION_CONTROL = "acne_inflammation_control"
    PIGMENT_REGULATION = "pigment_regulation"
    PHOTOPROTECTION = "photoprotection"
    VISIBLE_LIGHT_PROTECTION = "visible_light_protection"
    REDNESS_TRIGGER_CONTROL = "redness_trigger_control"
    COLLAGEN_SUPPORT = "collagen_support"
    FINE_LINE_PLUMPING = "fine_line_plumping"
    EXPECTATION_SETTING = "expectation_setting"


class IngredientGroupCode(StrEnum):
    BARRIER_LIPIDS = "barrier_lipids"
    HUMECTANTS = "humectants"
    EMOLLIENTS = "emollients"
    OCCLUSIVES = "occlusives"
    SALICYLIC_ACID = "salicylic_acid"
    TOPICAL_RETINOIDS = "topical_retinoids"
    BENZOYL_PEROXIDE = "benzoyl_peroxide"
    AZELAIC_ACID = "azelaic_acid"
    VITAMIN_C_ANTIOXIDANTS = "vitamin_c_antioxidants"
    TYROSINASE_INHIBITORS = "tyrosinase_inhibitors"
    BROAD_SPECTRUM_SUNSCREEN = "broad_spectrum_sunscreen"
    MINERAL_UV_FILTERS = "mineral_uv_filters"
    IRON_OXIDES = "iron_oxides"
    GENTLE_SOOTHING_SUPPORT = "gentle_soothing_support"
    NON_COMEDOGENIC_MOISTURIZERS = "non_comedogenic_moisturizers"


class RecommendationCautionCode(StrEnum):
    FRAGRANCE_IRRITATION = "fragrance_irritation"
    OVER_EXFOLIATION = "over_exfoliation"
    ACTIVE_OVERLOAD = "active_overload"
    RETINOID_IRRITATION = "retinoid_irritation"
    BENZOYL_PEROXIDE_DRYNESS = "benzoyl_peroxide_dryness"
    PATCH_TEST_AND_GRADUAL_USE = "patch_test_and_gradual_use"
    PROFESSIONAL_REVIEW = "professional_review"
    SUN_PROTECTION_REQUIRED = "sun_protection_required"
    REALISTIC_TOPICAL_LIMITS = "realistic_topical_limits"


class RecommendationConflictCode(StrEnum):
    WRONG_PRIMARY_CONCERN = "wrong_primary_concern"
    AGGRESSIVE_EXFOLIATION = "aggressive_exfoliation"
    EXFOLIATION_ON_IRRITATED_SKIN = "exfoliation_on_irritated_skin"
    DRYING_SEBUM_CONTROL = "drying_sebum_control"
    UNSAFE_ACTIVE_STACK = "unsafe_active_stack"
    MISSING_PHOTOPROTECTION = "missing_photoprotection"
    OVERPROMISED_LIFTING = "overpromised_lifting"
    IRRITATING_REDNESS_CARE = "irritating_redness_care"


class SituationFitScore(IntEnum):
    NONE = 0
    PARTIAL = 1
    STRONG = 2


class RecommendationUtilityScore(IntEnum):
    NONE = 0
    PARTIAL = 1
    STRONG = 2


class FinalRelevanceGrade(IntEnum):
    NOT_RELEVANT = 0
    SUPPORTIVE = 1
    RELEVANT = 2
    HIGHLY_RELEVANT = 3


class JudgmentReasonCode(StrEnum):
    PRIMARY_CONCERN_MATCH = "primary_concern_match"
    SECONDARY_CONCERN_MATCH = "secondary_concern_match"
    SYMPTOM_MATCH = "symptom_match"
    CONTEXT_MATCH = "context_match"
    PROFILE_SUPPORT = "profile_support"
    REQUIRED_FUNCTION_MATCH = "required_function_match"
    PARTIAL_FUNCTION_COVERAGE = "partial_function_coverage"
    CAUTION_MATCH = "caution_match"
    INCIDENTAL_KEYWORD_ONLY = "incidental_keyword_only"
    DOMINANT_GOAL_CONFLICT = "dominant_goal_conflict"
    INSUFFICIENT_RECOMMENDATION = "insufficient_recommendation"
    DUPLICATE_EQUIVALENT = "duplicate_equivalent"


class IngredientGroupReference(RagModel):
    code: IngredientGroupCode
    examples: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class RecommendationCaution(RagModel):
    code: RecommendationCautionCode
    detail: str = Field(min_length=1)


class RecommendationConflict(RagModel):
    code: RecommendationConflictCode
    detail: str = Field(min_length=1)


class ClinicalReferenceSource(RagModel):
    title: str = Field(min_length=1)
    url: HttpUrl
    use_scope: str = Field(min_length=1)


class NiaCaseSemanticQueryReference(RagModel):
    evaluation_id: str = Field(pattern=r"^(calibration|evaluation)_[a-z0-9_]+$")
    phase: SemanticGoldenPhase
    query_type: SemanticQueryType
    query: str = Field(min_length=1)
    primary_concerns: list[NiaCaseConcernCategory] = Field(min_length=1)
    secondary_concerns: list[NiaCaseConcernCategory] = Field(default_factory=list)
    profile_context: list[str] = Field(default_factory=list)
    required_functions: list[RecommendationFunction] = Field(min_length=1)
    acceptable_ingredient_groups: list[IngredientGroupReference] = Field(min_length=1)
    cautions: list[RecommendationCaution] = Field(min_length=1)
    contradictions: list[RecommendationConflict] = Field(min_length=1)
    reference_sources: list[ClinicalReferenceSource] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_reference_card(self) -> Self:
        if set(self.primary_concerns) & set(self.secondary_concerns):
            raise ValueError("주 고민과 보조 고민은 중복될 수 없습니다.")
        self._raise_on_duplicate(self.required_functions, "필수 추천 기능")
        self._raise_on_duplicate(
            [group.code for group in self.acceptable_ingredient_groups],
            "허용 성분군",
        )
        self._raise_on_duplicate([caution.code for caution in self.cautions], "주의사항")
        self._raise_on_duplicate(
            [conflict.code for conflict in self.contradictions],
            "추천 충돌",
        )
        return self

    def _raise_on_duplicate(self, values: list[object], label: str) -> None:
        if len(values) != len(set(values)):
            raise ValueError(f"{label} 코드가 중복되었습니다: evaluation_id={self.evaluation_id}")


class NiaCaseSemanticReferenceSet(RagModel):
    items: list[NiaCaseSemanticQueryReference] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_items(self) -> Self:
        evaluation_ids = [item.evaluation_id for item in self.items]
        queries = [item.query.casefold().strip() for item in self.items]
        if len(evaluation_ids) != len(set(evaluation_ids)):
            raise ValueError("calibration evaluation_id가 중복되었습니다.")
        if len(queries) != len(set(queries)):
            raise ValueError("calibration 사용자 질의가 중복되었습니다.")
        return self


class NiaCaseSemanticCalibrationSet(NiaCaseSemanticReferenceSet):
    @model_validator(mode="after")
    def validate_calibration_phase(self) -> Self:
        if any(item.phase is not SemanticGoldenPhase.CALIBRATION for item in self.items):
            raise ValueError("calibration 기준표에는 calibration phase만 허용됩니다.")
        return self


class NiaCaseSemanticJudgment(RagModel):
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    situation_fit: SituationFitScore
    recommendation_utility: RecommendationUtilityScore
    conflict_codes: list[RecommendationConflictCode] = Field(default_factory=list)
    reason_codes: list[JudgmentReasonCode] = Field(min_length=1)
    relevance_grade: FinalRelevanceGrade
    note: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_relevance_grade(self) -> Self:
        expected = self.expected_relevance_grade()
        if self.relevance_grade is not expected:
            raise ValueError(
                "상황 적합성·추천 유용성·충돌에 따른 관련도 등급이 일치하지 않습니다: "
                f"review_key={self.review_key}, expected={expected.value}, "
                f"actual={self.relevance_grade.value}"
            )
        if len(self.conflict_codes) != len(set(self.conflict_codes)):
            raise ValueError("추천 충돌 코드가 중복되었습니다.")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("판정 이유 코드가 중복되었습니다.")
        return self

    def expected_relevance_grade(self) -> FinalRelevanceGrade:
        if self.conflict_codes or self.situation_fit is SituationFitScore.NONE:
            return FinalRelevanceGrade.NOT_RELEVANT
        if (
            self.situation_fit is SituationFitScore.STRONG
            and self.recommendation_utility is RecommendationUtilityScore.STRONG
        ):
            return FinalRelevanceGrade.HIGHLY_RELEVANT
        if (
            self.situation_fit is SituationFitScore.STRONG
            and self.recommendation_utility is RecommendationUtilityScore.PARTIAL
        ) or (
            self.situation_fit is SituationFitScore.PARTIAL
            and self.recommendation_utility is RecommendationUtilityScore.STRONG
        ):
            return FinalRelevanceGrade.RELEVANT
        if self.recommendation_utility is not RecommendationUtilityScore.NONE:
            return FinalRelevanceGrade.SUPPORTIVE
        if self.situation_fit is SituationFitScore.STRONG:
            return FinalRelevanceGrade.SUPPORTIVE
        return FinalRelevanceGrade.NOT_RELEVANT


class NiaCaseSemanticJudgmentBatch(RagModel):
    evaluation_id: str = Field(min_length=1)
    judgments: list[NiaCaseSemanticJudgment] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_review_keys(self) -> Self:
        review_keys = [judgment.review_key for judgment in self.judgments]
        if len(review_keys) != len(set(review_keys)):
            raise ValueError("판정 batch에 중복 review_key가 있습니다.")
        return self


class NiaCaseSemanticReferenceLoader:
    def load(self, path: Path) -> NiaCaseSemanticReferenceSet:
        items: list[NiaCaseSemanticQueryReference] = []
        try:
            with path.open("r", encoding="utf-8") as source:
                for line_number, line in enumerate(source, start=1):
                    if not line.strip():
                        continue
                    try:
                        items.append(NiaCaseSemanticQueryReference.model_validate_json(line))
                    except ValidationError as error:
                        raise RuntimeError(
                            "NIA Case 의미 검색 기준표가 잘못되었습니다: "
                            f"path={path}, line={line_number}, detail={error}"
                        ) from error
        except OSError as error:
            raise RuntimeError(f"NIA Case 의미 검색 기준표를 읽지 못했습니다: {path}") from error
        return NiaCaseSemanticReferenceSet(items=items)


class NiaCaseSemanticCalibrationLoader:
    def load(self, path: Path) -> NiaCaseSemanticCalibrationSet:
        references = NiaCaseSemanticReferenceLoader().load(path)
        return NiaCaseSemanticCalibrationSet(items=references.items)
