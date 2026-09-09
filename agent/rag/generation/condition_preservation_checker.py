"""원문의 조건(농도%, 관할 국가 등)이 답변 문장에도 보존되는지 확인한다.

문장이 인용한 청크의 내용을 담고 있는지(정방향)만 보면 부족하다 - 원문이 "0.4% 이하에서"처럼
조건부로만 성립하는 주장인데, 답변 문장이 그 조건을 빼고 "이 성분은 안전하다"처럼 일반화하면
정방향 검사로는 못 잡는다. 그래서 원문에 있는 조건이 문장에도 남아 있는지(역방향)를 주 검사로
쓴다. 숫자·조건어의 단순 토큰 일치는 보조 신호일 뿐이고, "원문에 있던 조건이 문장에서 통째로
빠졌다"를 잡는 게 이 클래스의 목적이다.
"""

import re

_PERCENT_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*%")

# 사용 조건을 가르는 관할/국가 표기. MFDS Evidence의 jurisdiction 값과 정규 표현식으로
# 못 잡는 조건어(관할)를 텍스트에서 직접 찾기 위한 목록이라, 실제 데이터에 등장하는 표기를
# 그대로 나열한다(코드 등 약어가 아니라 사람이 읽는 표기).
_JURISDICTION_TERMS = (
    "한국",
    "대한민국",
    "미국",
    "EU",
    "유럽",
    "일본",
    "중국",
    "아세안",
    "캐나다",
    "호주",
)


class ConditionPreservationChecker:
    """원문의 조건 토큰이 문장에도 남아 있는지 확인한다."""

    def extract_conditions(self, text: str) -> set[str]:
        percents = {match.group(0).replace(" ", "") for match in _PERCENT_PATTERN.finditer(text)}
        jurisdictions = {term for term in _JURISDICTION_TERMS if term in text}
        return percents | jurisdictions

    def is_preserved(self, sentence: str, source_content: str) -> bool:
        """원문의 조건이 문장에 전부 남아 있어야 통과한다.

        하나라도 겹치면 통과(교집합이 비어있지 않으면 True)로 했던 첫 버전은 실제로
        틀렸다 - 원문에 "한국"과 "0.5% 이하"라는 조건이 둘 다 있는데 문장이 "한국"만
        남기고 농도 제한을 빼도 통과해버렸다(2026-09-10, 코드 리뷰로 발견). 원문의
        조건 중 하나라도 문장에서 빠지면 그 문장은 일반화된 것으로 보고 False다.
        """
        required = self.extract_conditions(source_content)
        if not required:
            # 원문 자체가 조건부 주장이 아니면(조건 토큰이 없으면) 이 검사는 통과시킨다.
            return True
        return required <= self.extract_conditions(sentence)
