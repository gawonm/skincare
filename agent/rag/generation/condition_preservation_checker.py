"""조건 보존은 인용한 모든 자료를 대상으로 검사한다. 의미적 함의 검증은 별도다."""

import re

from agent.rag.schemas import EvidenceRecord, GeneratedClaim


class ConditionPreservationChecker:
    _PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%\s*(?:이하|미만|이상|초과)?")
    _JURISDICTIONS = ("한국", "대한민국", "미국", "EU", "유럽", "일본", "중국", "아세안")

    def is_preserved(self, claim: GeneratedClaim, evidence: EvidenceRecord) -> bool:
        sentence = " ".join(claim.sentence.casefold().split())
        required = [value for value in evidence.conditions.model_dump().values() if value]
        required.extend(
            value for value in (evidence.raw_conditions, evidence.jurisdiction) if value
        )
        required.extend(match.group(0) for match in self._PERCENT.finditer(evidence.text))
        required.extend(term for term in self._JURISDICTIONS if term in evidence.text)
        # 제형·투여경로·자유문 조건은 동의어를 임의 해석하지 않고 보존된 경우만 채택한다.
        return all(" ".join(value.casefold().split()) in sentence for value in required)
