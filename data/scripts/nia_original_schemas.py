"""AI Hub 배포 원본 Q-CoT-A JSONL 한 줄을 그대로 담는 스키마.

이 모듈은 원본을 손실 없이 옮기는 것까지만 책임진다. page_content 생성, metadata 평탄화,
연령 필터, 값 정규화는 여기서 하지 않는다(별도 단계).

- `extra="allow"`: 원본에 이 스키마가 모르는 필드가 있어도 버리지 않고 `model_extra` 에 남긴다.
- `strict=True`: `"52"` 같은 문자열이 조용히 int 로 바뀌는 것을 막는다. 타입이 원본과 다르면
  변환하지 않고 검증 실패로 드러낸다.
- 원본 데이터 모델과 출처(`NiaRecordSource`)는 분리한다. 출처 정보가 원본 필드처럼 보이면
  round-trip 비교가 깨지고, 원본에 없는 값을 있는 것처럼 오해하게 된다.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class _NiaOriginalModel(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, frozen=True)


class NiaInfo(_NiaOriginalModel):
    id: str
    source_survey_id: str
    target_concern: str
    question: str
    answer: str
    evidence_sources: list[str]


class NiaMeta(_NiaOriginalModel):
    gender: str
    age: int
    initial_skin_condition: str
    skin_type: str
    skin_concerns: list[str]
    image_filename: str


class NiaExternalFactor(_NiaOriginalModel):
    priority: int
    factor: str
    details: str


class NiaChainOfThoughtStep(_NiaOriginalModel):
    step: int
    title: str
    content: str


class NiaOriginalRecord(_NiaOriginalModel):
    info: NiaInfo
    meta: NiaMeta
    external: list[NiaExternalFactor]
    chain_of_thought: list[NiaChainOfThoughtStep]


class NiaRecordSource(BaseModel):
    """레코드가 어느 입력의 몇 번째 줄에서 왔는지. 오류 위치 추적과 재현에 쓴다."""

    model_config = ConfigDict(frozen=True)

    input_path: Path
    # 직접 JSONL 입력이면 zip 내부 멤버가 없다
    member_name: str | None = None
    line_number: int


class NiaOriginalEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    record: NiaOriginalRecord
    source: NiaRecordSource
