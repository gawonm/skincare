"""LLM structured output 전용 경량 스키마.

`nia_labeling_schemas.NiaLabelingDocument`와 두 가지가 다르다.
1. `source_spans`에 offset(start/end)이 없다 — LLM은 quote 텍스트만 반환하고,
   `NiaSourceSpanBuilder`가 원문에서 quote를 찾아 offset을 deterministic하게 계산한다.
2. 성분 언급에 `ingredient_id`가 없다 — LLM은 `raw_name`/`raw_name_ko`/
   `ambiguous_family` 여부만 판단하고, ingredient_id는 별도 deterministic 매칭
   단계(`nia_ingredient_matching_stage.py`)가 채운다.

`support_status`는 스키마에 아예 없다 — 항상 `unverified`로 고정하므로 LLM에 묻지 않는다
(사용자 규칙 5: 과학적 검증과 semantic annotation 분리).
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class LlmSourceQuote(BaseModel):
    json_path: str = Field(
        description="원문 내 위치. 예: $.chain_of_thought[1].content, $.external[0].details, $.info.question"
    )
    quote: str = Field(description="json_path가 가리키는 텍스트에 등장하는 원문 그대로의 부분 문자열")


class LlmIngredientMention(BaseModel):
    raw_name: str = Field(description="원문의 INCI 또는 성분 표현 그대로")
    raw_name_ko: str | None = None
    ambiguous_family: bool = Field(
        default=False,
        description=(
            "원문이 단일 INCI를 확정할 수 없는 계열명/병기/예시 나열이면 true "
            "(예: '대나무 추출물' 계열명, 'A나 B 같은' 예시 나열). 단일 INCI가 명확하면 false."
        ),
    )


class LlmCaseObservationStatement(BaseModel):
    statement_type: Literal["case_observation"] = "case_observation"
    subject: str = Field(description="사례가 보고하는 고민·상태 서술")
    quotes: list[LlmSourceQuote] = Field(min_length=1)
    note: str | None = None


class LlmCauseClaimStatement(BaseModel):
    statement_type: Literal["cause_claim"] = "cause_claim"
    subject: str
    relation: Literal["described_as_main_cause_of", "described_as_contributing_cause_of"]
    objects: list[str] = Field(min_length=1)
    scope_text: str | None = None
    quotes: list[LlmSourceQuote] = Field(min_length=1)
    note: str | None = None


class LlmIngredientEffectClaimStatement(BaseModel):
    statement_type: Literal["ingredient_effect_claim"] = "ingredient_effect_claim"
    subject: LlmIngredientMention
    object: str = Field(description="주장된 작용/효능")
    concentration_raw: str | None = Field(
        default=None, description="원문이 명시한 사용 농도만. 없으면 null"
    )
    quotes: list[LlmSourceQuote] = Field(min_length=1)
    note: str | None = None


class LlmPrecautionStatement(BaseModel):
    statement_type: Literal["precaution"] = "precaution"
    subject: str
    relation: Literal["avoid", "possible_irritation"] = "avoid"
    quotes: list[LlmSourceQuote] = Field(min_length=1)
    note: str | None = None


class LlmFrequency(BaseModel):
    min: int = Field(ge=0)
    max: int = Field(ge=0)
    period: Literal["day", "week", "month", "every_other_day"]


class LlmUsageInstructionStatement(BaseModel):
    statement_type: Literal["usage_instruction"] = "usage_instruction"
    action_id: str = Field(description="문서 내 고유 ID, 예: A001")
    action: str
    time_of_day: list[Literal["morning", "evening", "daytime", "night"]] = Field(default_factory=list)
    frequency: LlmFrequency | None = None
    quotes: list[LlmSourceQuote] = Field(min_length=1)
    note: str | None = None


class LlmCombinationClaimStatement(BaseModel):
    statement_type: Literal["combination_claim"] = "combination_claim"
    subjects: list[LlmIngredientMention] = Field(min_length=2)
    subject_plural_mode: Literal["each", "all", "joint", "uncertain"]
    object: str
    quotes: list[LlmSourceQuote] = Field(min_length=1)
    note: str | None = Field(
        default=None, description="subject_plural_mode=uncertain이면 반드시 근거를 적는다"
    )


class LlmContextualFactorStatement(BaseModel):
    statement_type: Literal["contextual_factor"] = "contextual_factor"
    factor_raw: str
    details_raw: str
    priority_raw: int
    causal_link_status: Literal["not_established", "established_in_text"]
    quotes: list[LlmSourceQuote] = Field(min_length=1)
    note: str | None = None


LlmStatement = Annotated[
    Union[
        LlmCaseObservationStatement,
        LlmCauseClaimStatement,
        LlmIngredientEffectClaimStatement,
        LlmPrecautionStatement,
        LlmUsageInstructionStatement,
        LlmCombinationClaimStatement,
        LlmContextualFactorStatement,
    ],
    Field(discriminator="statement_type"),
]


class LlmNiaLabelingOutput(BaseModel):
    """LLM이 record 하나 전체를 보고 반환하는 statement 목록. 7개 타입을 강제하지 않는다."""

    statements: list[LlmStatement] = Field(default_factory=list)
