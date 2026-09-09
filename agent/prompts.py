"""실제 LLM 어댑터가 사용할 목적별 프롬프트 템플릿."""

from enum import StrEnum
from typing import ClassVar

from pydantic import Field

from agent.schemas import AgentModel


class PromptPurpose(StrEnum):
    UNDERSTAND_REQUEST = "understand_request"
    PRODUCT_DISCOVERY = "product_discovery"
    ROUTINE_PLANNING = "routine_planning"
    EVIDENCE_QA = "evidence_qa"


class PromptRequest(AgentModel):
    purpose: PromptPurpose


class PromptTemplate(AgentModel):
    purpose: PromptPurpose
    system_message: str = Field(min_length=1)


class PromptCatalog:
    """프롬프트 선택을 문자열 분기 대신 Enum 계약으로 제공한다."""

    _TEMPLATES: ClassVar[dict[PromptPurpose, str]] = {
        PromptPurpose.UNDERSTAND_REQUEST: (
            "사용자 메시지와 같은 채팅방의 구조화 상태만 사용해 Intent, 조건, 참조, "
            "수정 요청을 추출하세요. 미상 값은 추측하지 말고 스키마에 맞게 반환하세요."
        ),
        PromptPurpose.PRODUCT_DISCOVERY: (
            "구조화된 제품 조회 결과에서 요청 조건을 만족하는 후보만 비교하세요. "
            "지원되지 않는 조건을 조용히 완화하지 마세요."
        ),
        PromptPurpose.ROUTINE_PLANNING: (
            "제품 사용 설명, 사용자 제약, 서비스 계획 정책의 출처를 구분하고 "
            "검증된 제약 안에서만 루틴 초안을 만드세요."
        ),
        PromptPurpose.EVIDENCE_QA: (
            "제공된 근거 구간만 사용하고 성분 형태, 제형, 농도, 사용 방식의 적용 범위와 "
            "검수 상태를 보존하세요. 자료 없음과 도구 실패를 구분하세요."
        ),
    }

    def get(self, request: PromptRequest) -> PromptTemplate:
        return PromptTemplate(
            purpose=request.purpose,
            system_message=self._TEMPLATES[request.purpose],
        )
