"""조건 보존은 인용한 모든 자료를 대상으로 검사한다. 의미적 함의 검증은 별도다."""

from enum import StrEnum
from typing import ClassVar

from pydantic import Field

from agent.rag.schemas import EvidenceRecord, GeneratedEvidenceStatement, RagModel


class EvidenceConditionLabel(StrEnum):
    CONCENTRATION = "농도"
    FORMULATION = "제형"
    ROUTE = "사용 경로"
    USAGE = "사용법"
    DURATION = "기간"
    PH = "pH"
    JURISDICTION = "관할"
    RAW_CONDITION = "기타 조건"


class EvidenceConditionFact(RagModel):
    label: EvidenceConditionLabel
    value: str = Field(min_length=1)


class EvidenceConditionExtractor:
    _FIELD_LABELS: ClassVar[dict[str, EvidenceConditionLabel]] = {
        "concentration": EvidenceConditionLabel.CONCENTRATION,
        "formulation": EvidenceConditionLabel.FORMULATION,
        "route": EvidenceConditionLabel.ROUTE,
        "usage": EvidenceConditionLabel.USAGE,
        "duration": EvidenceConditionLabel.DURATION,
        "ph": EvidenceConditionLabel.PH,
        "jurisdiction": EvidenceConditionLabel.JURISDICTION,
    }

    def extract(self, evidence: EvidenceRecord) -> list[EvidenceConditionFact]:
        facts = [
            EvidenceConditionFact(label=self._FIELD_LABELS[field], value=value)
            for field, value in evidence.conditions.model_dump().items()
            if value
        ]
        if evidence.raw_conditions:
            facts.append(
                EvidenceConditionFact(
                    label=EvidenceConditionLabel.RAW_CONDITION,
                    value=evidence.raw_conditions,
                )
            )
        if evidence.jurisdiction:
            facts.append(
                EvidenceConditionFact(
                    label=EvidenceConditionLabel.JURISDICTION,
                    value=evidence.jurisdiction,
                )
            )
        unique: dict[str, EvidenceConditionFact] = {}
        for fact in facts:
            key = " ".join(fact.value.casefold().split())
            unique.setdefault(key, fact)
        return list(unique.values())


class EvidenceConditionPresenter:
    """원문 조건은 번역 추측 대신 짧은 구조화 표기로 사용자에게 함께 보여준다."""

    def __init__(self, extractor: EvidenceConditionExtractor | None = None) -> None:
        self._extractor = extractor or EvidenceConditionExtractor()

    def present(
        self,
        claim: GeneratedEvidenceStatement,
        sources: list[EvidenceRecord],
    ) -> GeneratedEvidenceStatement:
        sentence = claim.sentence.strip()
        normalized_sentence = " ".join(sentence.casefold().split())
        facts: dict[str, EvidenceConditionFact] = {}
        for source in sources:
            for fact in self._extractor.extract(source):
                key = " ".join(fact.value.casefold().split())
                if key not in normalized_sentence:
                    facts.setdefault(key, fact)
        if not facts:
            return claim.model_copy(deep=True)
        conditions = "; ".join(
            f"{fact.label.value}={fact.value}" for fact in facts.values()
        )
        return claim.model_copy(update={"sentence": f"{sentence} (적용 조건: {conditions})"})


class ConditionPreservationChecker:
    def __init__(self, extractor: EvidenceConditionExtractor | None = None) -> None:
        self._extractor = extractor or EvidenceConditionExtractor()

    def is_preserved(
        self,
        claim: GeneratedEvidenceStatement,
        evidence: EvidenceRecord,
    ) -> bool:
        sentence = " ".join(claim.sentence.casefold().split())
        # 제형·투여경로·자유문 조건은 동의어를 임의 해석하지 않고 보존된 경우만 채택한다.
        return all(
            " ".join(fact.value.casefold().split()) in sentence
            for fact in self._extractor.extract(evidence)
        )
