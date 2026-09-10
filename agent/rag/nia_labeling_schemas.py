"""NIA 의미 라벨링(관계·조건 단위 주석) 고정 스키마.

`docs/NIA_SEMANTIC_LABELING_SPEC.md` 3~5절의 설계 초안을 Pydantic discriminated union으로
구현한다. 이 모듈은 "무엇이 맞는 라벨인가"를 판단하지 않는다 - 사람(또는 규칙/모델)이 내린
라벨링 결정이 정해진 형식·참조·불변조건을 지키는지만 강제한다. 스키마 통과가 의미 정확성이나
과학적 근거 검증을 뜻하지 않는다.

`agent/rag/nia_qa_loader.py`가 만드는 `RagDocument`는 question/answer/CoT 단계를 그대로
청크로 쪼갤 뿐 주체-관계-대상-조건을 구조화하지 않는다. 이 모듈은 그 구조화 결과를 담는
별도 계층이며, 아직 로더·DB와 연결되지 않은 스키마 정의 단계다.
"""

from enum import StrEnum
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NiaDatasetSplit(StrEnum):
    """NIA 원본의 Training/Validation 구분. 검색 인덱스와 평가 자료를 섞지 않기 위해 보존한다."""

    TRAINING = "training"
    VALIDATION = "validation"


class NiaStatementType(StrEnum):
    """스펙 3절의 라벨 초안 7종. 허용 라벨에 맞지 않는 서술은 이 타입으로 강제 분류하지 않고
    원문을 보존한 채 검토 큐로 넘긴다(이 스키마 밖에서 처리)."""

    CASE_OBSERVATION = "case_observation"
    CAUSE_CLAIM = "cause_claim"
    INGREDIENT_EFFECT_CLAIM = "ingredient_effect_claim"
    PRECAUTION = "precaution"
    USAGE_INSTRUCTION = "usage_instruction"
    COMBINATION_CLAIM = "combination_claim"
    CONTEXTUAL_FACTOR = "contextual_factor"


class NiaAnnotationStatus(StrEnum):
    """원문을 의미상 정확히 옮겼는가. 과학적 근거 검증과는 독립된 축이다."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class NiaSupportStatus(StrEnum):
    """인용이 해당 주장을 실제로 지지하는가. reference_status(식별자 상태)와 별개 축이다."""

    UNVERIFIED = "unverified"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"


class NiaReferenceStatus(StrEnum):
    """인용 식별자(DOI/PMID 등) 자체의 상태. 형식 검사 통과가 실제 문헌 존재를 뜻하지 않는다."""

    UNVERIFIED = "unverified"
    PLACEHOLDER_DETECTED = "placeholder_detected"
    RESOLVED = "resolved"
    UNAVAILABLE = "unavailable"


class NiaIngredientMatchingStatus(StrEnum):
    """성분 원문 표기 -> 표준 성분 사전 대조 상태. ID를 추측하지 않는다."""

    UNRESOLVED = "unresolved"
    # 원문이 "대나무 추출물" 같은 계열명으로 서술해 단일 INCI를 확정할 수 없는 경우.
    # 세부 후보들을 raw_name에 그대로 보존하고 이 상태로 표시한다(임의 확정 금지).
    UNRESOLVED_AMBIGUOUS_FAMILY = "unresolved_ambiguous_family"
    MATCHED = "matched"
    REJECTED = "rejected"


class NiaCausalLinkStatus(StrEnum):
    """external 배경요인과 본문 서술 사이의 인과 연결이 원문에 실제로 명시됐는지.

    external.priority가 높다고 자동으로 원인으로 승격하지 않기 위한 축이다.
    """

    NOT_ESTABLISHED = "not_established"
    ESTABLISHED_IN_TEXT = "established_in_text"


class NiaTimeOfDay(StrEnum):
    MORNING = "morning"
    EVENING = "evening"
    DAYTIME = "daytime"
    NIGHT = "night"


class NiaFrequencyPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class NiaSubjectPluralMode(StrEnum):
    """복수 주체(성분 등)가 언급됐을 때 그 관계가 개별/전체/공동/불명확 중 무엇인지.

    "A와 B로 X와 Y"를 네 개 독립 효능으로 임의 분배하지 않기 위한 필드다.
    """

    EACH = "each"
    ALL = "all"
    JOINT = "joint"
    UNCERTAIN = "uncertain"


class NiaCauseRelation(StrEnum):
    DESCRIBED_AS_MAIN_CAUSE_OF = "described_as_main_cause_of"
    DESCRIBED_AS_CONTRIBUTING_CAUSE_OF = "described_as_contributing_cause_of"


class NiaPrecautionRelation(StrEnum):
    AVOID = "avoid"
    POSSIBLE_IRRITATION = "possible_irritation"


class NiaSourceSpan(BaseModel):
    """주장/조건 하나가 원문의 어디서 나왔는지. 오프셋은 Unicode 코드포인트 기준 [start, end)."""

    model_config = ConfigDict(frozen=True)

    json_path: str
    quote: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_range_matches_quote_length(self) -> "NiaSourceSpan":
        if self.end <= self.start:
            raise ValueError(f"source_span 범위가 비정상: start={self.start} end={self.end}")
        if self.end - self.start != len(self.quote):
            raise ValueError(
                f"quote 길이와 [start,end) 범위가 불일치: quote_len={len(self.quote)} "
                f"range_len={self.end - self.start}"
            )
        return self


class NiaFrequency(BaseModel):
    model_config = ConfigDict(frozen=True)

    min: int = Field(ge=0)
    max: int = Field(ge=0)
    period: NiaFrequencyPeriod

    @model_validator(mode="after")
    def _check_min_le_max(self) -> "NiaFrequency":
        if self.min > self.max:
            raise ValueError(f"frequency.min({self.min}) > max({self.max})")
        return self


class NiaIngredientSubject(BaseModel):
    """성분 언급 하나. ingredient_id는 표준 사전 대조 전이면 반드시 None이다(추측 금지)."""

    model_config = ConfigDict(frozen=True)

    raw_name: str
    raw_name_ko: str | None = None
    ingredient_id: UUID | None = None
    matching_status: NiaIngredientMatchingStatus

    @model_validator(mode="after")
    def _check_id_requires_matched(self) -> "NiaIngredientSubject":
        if self.ingredient_id is not None and self.matching_status != NiaIngredientMatchingStatus.MATCHED:
            raise ValueError("ingredient_id가 있으면 matching_status는 matched여야 함")
        return self


class NiaCaseContext(BaseModel):
    """사례 프로필(meta). 주장의 적용 조건(statement별 조건)과는 별개다."""

    model_config = ConfigDict(frozen=True)

    age_raw: int | None
    age_text_raw: str | None
    gender_raw: str | None
    skin_type_raw: str | None
    skin_concerns_raw: tuple[str, ...]
    initial_skin_condition_raw: str | None


class NiaSourceMetadata(BaseModel):
    """원본 위치·버전. 아카이브명과 info.target_concern을 각각 보존하고 둘 중 하나로 합치지 않는다."""

    model_config = ConfigDict(frozen=True)

    record_id: str
    source_archive: str
    source_hash: str | None
    dataset_split: NiaDatasetSplit
    info_target_concern: str
    archive_name_target_concern_mismatch: bool


class NiaReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw: str
    reference_status: NiaReferenceStatus
    statement_links: tuple[str, ...] = Field(default=())


class NiaStatementBase(BaseModel):
    model_config = ConfigDict(frozen=True)

    statement_id: str
    source_spans: tuple[NiaSourceSpan, ...] = Field(min_length=1)
    annotation_status: NiaAnnotationStatus
    support_status: NiaSupportStatus
    note: str | None = None


class NiaCaseObservationStatement(NiaStatementBase):
    statement_type: Literal[NiaStatementType.CASE_OBSERVATION] = NiaStatementType.CASE_OBSERVATION
    subject: str  # 사례가 보고하는 고민·상태 서술. 진단으로 승격하지 않는다.


class NiaCauseClaimStatement(NiaStatementBase):
    statement_type: Literal[NiaStatementType.CAUSE_CLAIM] = NiaStatementType.CAUSE_CLAIM
    subject: str
    relation: NiaCauseRelation
    objects: tuple[str, ...] = Field(min_length=1)
    scope_text: str | None = None


class NiaIngredientEffectClaimStatement(NiaStatementBase):
    statement_type: Literal[NiaStatementType.INGREDIENT_EFFECT_CLAIM] = (
        NiaStatementType.INGREDIENT_EFFECT_CLAIM
    )
    subject: NiaIngredientSubject
    object: str  # 주장된 작용/효능. 제품 효능으로 일반화하지 않는다.


class NiaPrecautionStatement(NiaStatementBase):
    statement_type: Literal[NiaStatementType.PRECAUTION] = NiaStatementType.PRECAUTION
    subject: str
    relation: NiaPrecautionRelation = NiaPrecautionRelation.AVOID


class NiaUsageInstructionStatement(NiaStatementBase):
    statement_type: Literal[NiaStatementType.USAGE_INSTRUCTION] = NiaStatementType.USAGE_INSTRUCTION
    action_id: str
    action: str
    time_of_day: tuple[NiaTimeOfDay, ...] = Field(default=())
    frequency: NiaFrequency | None = None
    ingredient_ids: tuple[UUID, ...] = Field(default=())


class NiaCombinationClaimStatement(NiaStatementBase):
    statement_type: Literal[NiaStatementType.COMBINATION_CLAIM] = NiaStatementType.COMBINATION_CLAIM
    subjects: tuple[NiaIngredientSubject, ...] = Field(min_length=2)
    subject_plural_mode: NiaSubjectPluralMode
    object: str

    @model_validator(mode="after")
    def _check_explicit_combination(self) -> "NiaCombinationClaimStatement":
        # 단순 동시 언급은 병용 근거가 아니므로, uncertain 모드는 combination_claim으로
        # 승격하지 않고 반드시 검토 주석(note)을 요구한다.
        if self.subject_plural_mode == NiaSubjectPluralMode.UNCERTAIN and not self.note:
            raise ValueError("subject_plural_mode=uncertain인 combination_claim은 note로 근거를 남겨야 함")
        return self


class NiaContextualFactorStatement(NiaStatementBase):
    statement_type: Literal[NiaStatementType.CONTEXTUAL_FACTOR] = NiaStatementType.CONTEXTUAL_FACTOR
    factor_raw: str
    details_raw: str
    priority_raw: int
    causal_link_status: NiaCausalLinkStatus


NiaStatement = Annotated[
    Union[
        NiaCaseObservationStatement,
        NiaCauseClaimStatement,
        NiaIngredientEffectClaimStatement,
        NiaPrecautionStatement,
        NiaUsageInstructionStatement,
        NiaCombinationClaimStatement,
        NiaContextualFactorStatement,
    ],
    Field(discriminator="statement_type"),
]


class NiaLabelingDocument(BaseModel):
    """레코드 한 건에 대한 라벨링 결과 전체. 버전 고정 후 재적재 시 그대로 재사용한다."""

    model_config = ConfigDict(frozen=True)

    schema_version: str
    annotation_version: str
    is_example: bool
    is_partial_annotation: bool
    production_ready: bool
    annotator_count: int = Field(ge=1)
    source: NiaSourceMetadata
    case_context: NiaCaseContext
    statements: tuple[NiaStatement, ...]
    references: tuple[NiaReference, ...] = Field(default=())
    notes: tuple[str, ...] = Field(default=())

    @model_validator(mode="after")
    def _check_unique_statement_ids(self) -> "NiaLabelingDocument":
        ids = [s.statement_id for s in self.statements]
        duplicates = {sid for sid in ids if ids.count(sid) > 1}
        if duplicates:
            raise ValueError(f"statement_id 중복: {sorted(duplicates)}")
        return self


class NiaLabelingSpanVerifier:
    """승인된 라벨링 파일을 다시 읽을 때 source_span이 실제 원본과 여전히 일치하는지 재검증한다.

    스펙 5절: "고정 파서는 승인된 파일을 읽는 단계에서도 스키마·참조를 재검증한다.
    승인 후 원문이 바뀌면 해시 불일치를 보고하고 재검토한다."
    이 클래스는 그 중 source_span 부분만 담당한다(해시·성분ID·action_id 참조 검증은 별도 단계).
    """

    _SIMPLE_PATH_PREFIX = "$."

    def verify_document(self, document: NiaLabelingDocument, raw_record: dict) -> tuple[str, ...]:
        errors: list[str] = []
        for statement in document.statements:
            for span in statement.source_spans:
                error = self._verify_span(statement.statement_id, span, raw_record)
                if error is not None:
                    errors.append(error)
        return tuple(errors)

    def _verify_span(self, statement_id: str, span: NiaSourceSpan, raw_record: dict) -> str | None:
        try:
            text = self._resolve_path(raw_record, span.json_path)
        except (KeyError, IndexError, AssertionError) as exc:
            return f"{statement_id}: json_path 해석 실패 ({span.json_path}): {exc}"

        if not isinstance(text, str):
            return f"{statement_id}: json_path가 문자열이 아닌 값을 가리킴 ({span.json_path})"

        actual = text[span.start:span.end]
        if actual != span.quote:
            return (
                f"{statement_id}: quote 불일치 (path={span.json_path}, "
                f"expected={span.quote!r}, actual={actual!r})"
            )
        return None

    def _resolve_path(self, raw_record: dict, json_path: str):
        assert json_path.startswith(self._SIMPLE_PATH_PREFIX), f"지원하지 않는 json_path 형식: {json_path}"
        current = raw_record
        for part in json_path[len(self._SIMPLE_PATH_PREFIX):].split("."):
            if "[" in part:
                key, index_part = part[:-1].split("[")
                current = current[key][int(index_part)]
            else:
                current = current[part]
        return current
