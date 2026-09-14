"""NIA record 원문 전체를 LLM에 넣어 statement 후보를 추출한다.

LLM은 quote 텍스트와 성분 raw_name만 반환한다 — offset 계산과 ingredient_id 확정은
각각 `NiaSourceSpanBuilder`, `nia_ingredient_matching_stage.py`가 deterministic하게
담당한다(사용자 규칙: LLM이 offset·ingredient_id를 직접 생성하지 않음).
"""

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from core.config import OpenAiConfig
from data.scripts.nia_llm_label_schemas import LlmNiaLabelingOutput

_SYSTEM_PROMPT = (
    "당신은 화장품 상담 CoT(chain_of_thought) 원문에서 의미 라벨을 추출하는 도구입니다. "
    "아래 record(JSON)에 실제로 적힌 내용만 구조화하세요. "
    "일반적인 화장품 지식이나 외부 정보를 추가하지 마세요. "
    "각 statement의 quotes는 record의 실제 문자열 '완전히 동일한' 부분 문자열이어야 합니다 "
    "(패러프레이즈·요약·띄어쓰기 변경 금지, 원문을 문자 단위로 그대로 복사하세요). "
    "json_path의 배열 인덱스는 반드시 그 내용이 실제로 위치한 인덱스를 쓰세요 — "
    "예를 들어 chain_of_thought[1]의 내용이 성분 설명이라면 원인 분석 문장을 "
    "chain_of_thought[1]에서 인용하면 안 됩니다. 각 quote를 만들기 전에 그 json_path가 "
    "가리키는 텍스트 안에 그 문자열이 실제로 있는지 스스로 확인하세요. "
    "7개 statement_type(case_observation, cause_claim, ingredient_effect_claim, precaution, "
    "usage_instruction, combination_claim, contextual_factor)을 모두 억지로 채우지 말고, "
    "원문에 실제로 존재하는 것만 추출하세요. "
    "성분 언급은 raw_name(원문 그대로의 INCI/성분 표현)만 반환하고 ingredient_id는 생성하지 마세요. "
    "원문이 여러 INCI를 병기하거나 예시로만 나열해 단일 성분을 확정할 수 없으면 "
    "ambiguous_family=true로 표시하세요. "
    "combination_claim은 두 성분이 같은 문단에 동시에 등장한다는 이유만으로 만들지 말고, "
    "원문이 실제로 공동 효과·병용을 서술할 때만 만드세요."
)


class NiaLlmLabeler:
    def __init__(self, config: OpenAiConfig) -> None:
        self._client = ChatOpenAI(
            api_key=config.api_key,
            model=config.chat_model.value,
            timeout=config.timeout_seconds,
            max_retries=config.max_retries,
        ).with_structured_output(LlmNiaLabelingOutput, method="function_calling")

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
