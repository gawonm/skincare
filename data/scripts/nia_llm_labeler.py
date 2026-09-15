"""NIA record 원문 전체를 LLM에 넣어 statement 후보를 추출한다.

LLM은 quote 텍스트와 성분 raw_name만 반환한다 — offset 계산과 ingredient_id 확정은
각각 `NiaSourceSpanBuilder`, `nia_ingredient_matching_stage.py`가 deterministic하게
담당한다(사용자 규칙: LLM이 offset·ingredient_id를 직접 생성하지 않음).
"""

import json

from langchain_core.messages import HumanMessage, SystemMessage

from core.config import LlmChatSettings, OpenAiConfig
from data.scripts.nia_chat_model_client import NiaChatModelClientFactory
from data.scripts.nia_llm_label_schemas import LlmNiaLabelingOutput

_SYSTEM_PROMPT = (
    "당신은 화장품 상담 CoT(chain_of_thought) 원문에서 의미 라벨을 추출하는 도구입니다. "
    "아래 record(JSON)에 실제로 적힌 내용만 구조화하세요. "
    "일반적인 화장품 지식이나 외부 정보를 추가하지 마세요. "
    "각 statement의 quote는 그 주장의 근거가 되는 원문 문장(들)을 최대한 그대로 옮기세요 — "
    "정확한 글자 단위 일치는 코드가 별도로 원문에서 복원하니, 당신은 '어느 json_path의 "
    "어느 문장이 이 주장의 근거인가'를 정확히 고르는 데 집중하세요(약간의 표현 차이는 "
    "괜찮지만, 실제로 그 문장이 말하는 내용과 다른 것을 인용하면 안 됩니다). "
    "json_path의 배열 인덱스는 반드시 그 내용이 실제로 위치한 인덱스를 쓰세요 — "
    "예를 들어 chain_of_thought[1]의 내용이 성분 설명이라면 원인 분석 문장을 "
    "chain_of_thought[1]에서 인용하면 안 됩니다. "
    "7개 statement_type(case_observation, cause_claim, ingredient_effect_claim, precaution, "
    "usage_instruction, combination_claim, contextual_factor)을 모두 억지로 채우지 말고, "
    "원문에 실제로 존재하는 것만 추출하세요. "
    "성분 언급은 raw_name(원문 그대로의 INCI/성분 표현)만 반환하고 ingredient_id는 생성하지 마세요. "
    "원문이 여러 INCI를 병기하거나 예시로만 나열해 단일 성분을 확정할 수 없으면 "
    "ambiguous_family=true로 표시하세요. "
    "combination_claim은 두 성분이 같은 문단에 동시에 등장한다는 이유만으로 만들지 말고, "
    "원문이 실제로 공동 효과·병용을 서술할 때만 만드세요. "
    "한 문장/문단에 여러 성분이 함께 언급될 때는 다음 기준으로 구분하세요: "
    "(A) 각 성분에 독립적인 효과가 따로 서술돼 있으면(예: 'A는 진정에, B는 보습에 도움') "
    "성분마다 별개의 ingredient_effect_claim을 만드세요(하나로 합치지 마세요). "
    "(B) 두 성분을 같이 쓸 때의 공동 효과가 명시돼 있으면(예: 'A와 B를 함께 쓰면 ~') "
    "combination_claim을 만드세요. "
    "(C) 여러 성분이 단순 나열만 되고 각각에 어떤 효과가 귀속되는지 원문만으로 불명확하면, "
    "억지로 나누거나 합치지 말고 statement 자체를 만들지 마세요(추측 금지)."
)


class NiaLlmLabeler:
    """provider(openai/ollama/local)에 무관하게 동작한다 — `ChatModelConfig` 조립은
    `NiaChatModelClientFactory`가 담당하고, 이 클래스는 구조화 출력 스키마만 안다."""

    def __init__(self, chat_settings: LlmChatSettings, openai_config: OpenAiConfig | None) -> None:
        base_client = NiaChatModelClientFactory().create(chat_settings, openai_config)
        self._client = base_client.with_structured_output(
            LlmNiaLabelingOutput, method="function_calling"
        )
        self.provider = chat_settings.provider.value
        self.model = (
            openai_config.chat_model.value
            if chat_settings.provider.value == "openai" and openai_config is not None
            else chat_settings.local.model
        )
        self.base_url = (
            None if chat_settings.provider.value == "openai" else chat_settings.local.base_url
        )

    async def label(self, record: dict) -> LlmNiaLabelingOutput:
        record_json = json.dumps(record, ensure_ascii=False, indent=2)
        result = await self._client.ainvoke(
            [
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=f"record:\n{record_json}"),
            ]
        )
        if not isinstance(result, LlmNiaLabelingOutput):
            raise TypeError("LLM이 LlmNiaLabelingOutput 형식의 응답을 반환하지 않았습니다.")
        return result
