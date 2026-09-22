"""질문 목적별 Evidence 출처 우선순위를 결정한다."""

from agent.rag.retrieval.question_intent_classifier import QuestionIntentClassifier
from agent.rag.schemas import (
    EvidenceSearchRequest,
    EvidenceSourceLane,
    EvidenceSourcePlan,
    EvidenceSourceType,
    QuestionIntent,
)


class EvidenceSourcePolicy:
    """효능·안전·규제 질문이 서로 다른 공인 출처를 우선하도록 분리한다."""

    def __init__(self) -> None:
        self._classifier = QuestionIntentClassifier()

    def resolve(self, request: EvidenceSearchRequest) -> EvidenceSourcePlan:
        if request.source_plan is not None:
            return request.source_plan
        intents = self._classifier.classify(request)
        if QuestionIntent.REGULATION in intents:
            return EvidenceSourcePlan(
                lane=EvidenceSourceLane.REGULATION,
                primary_source_types=[EvidenceSourceType.MFDS],
                fallback_source_types=[EvidenceSourceType.CIR, EvidenceSourceType.PAPER],
            )
        if QuestionIntent.PRECAUTION in intents:
            return EvidenceSourcePlan(
                lane=EvidenceSourceLane.SAFETY,
                primary_source_types=[EvidenceSourceType.CIR, EvidenceSourceType.PAPER],
            )
        return EvidenceSourcePlan(
            lane=EvidenceSourceLane.EFFICACY,
            primary_source_types=[EvidenceSourceType.PAPER, EvidenceSourceType.CIR],
        )
