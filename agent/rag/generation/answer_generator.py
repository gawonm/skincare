"""검색된 청크를 근거로 LLM이 `IngredientVerificationResult`를 만든다.

플로우차트 "①성분 확인"의 "확인할 근거가 있나요?" 판정이 이 클래스의 핵심 책임이다.
판정은 다음 순서로 좁혀간다 - 어느 하나라도 걸리면 그 시점에 근거 부족으로 반환하고,
같은 성분의 다른 축·다른 성분의 근거로 대체하지 않는다.

1. **신뢰도 티어**: OFFICIAL_REGULATORY(MFDS)/STRUCTURED_KNOWLEDGE(Knowledgedata)만 "검증 가능
   근거"로 친다. AI_GENERATED_REVIEWED(NIA Q&A)만 있으면 근거 부족.
2. **질문 축과의 관련성**: 성분이 맞아도 질문이 묻는 축(효능/피부타입/농도/주의사항/규제)과
   무관한 `chunk_field`면 근거로 안 친다(`QuestionIntentClassifier` 참고) - RRF 점수가
   높다고 관련 있다는 뜻은 아니다.
3. **조합 질문의 관계 근거**: "두 성분 같이 써도 되나요" 류 질문은 개별 성분 근거가 있어도
   조합 자체를 다루는 근거가 없으면 근거 부족. 여기서도 NIA는 검증된 근거로 안 친다.
4. **문장 단위 인용 검증**: LLM이 여러 문장(claim)으로 나눠 답하게 하고, 문장마다 (a) 인용한
   근거 번호가 실제 검색 결과에 있는지(ID 유효성), (b) 원문의 조건(농도/관할 등)이 문장에도
   보존됐는지(내용 지지, 역방향 검사)를 검증한다. 실패한 문장은 버리고, 살아남은 문장이
   하나도 없으면 근거 부족으로 반환한다 - 빈 답변을 True로 두지 않는다.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from agent.rag.generation.condition_preservation_checker import ConditionPreservationChecker
from agent.rag.generation.prompts import EVIDENCE_ITEM_TEMPLATE, SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from agent.rag.retrieval.question_intent_classifier import (
    INTENT_TO_VERIFIABLE_CHUNK_FIELDS,
    QuestionIntent,
)
from agent.rag.schemas import (
    AnsweredClaim,
    IngredientVerificationResult,
    RetrievedChunk,
    SourceCitation,
    UnverifiableReason,
)
from models.rag_chunk import RagConfidenceTier

# 이 두 티어만 "검증된 근거"로 친다. AI_GENERATED_REVIEWED는 답변 참고용일 수는 있어도
# 플로우차트의 "검증 결과" 판정 기준은 아니다.
_VERIFIABLE_TIERS = (RagConfidenceTier.OFFICIAL_REGULATORY, RagConfidenceTier.STRUCTURED_KNOWLEDGE)

# 조합 질문에서 "이 청크가 조합 자체를 다룬다"고 볼 수 있는 신호 키워드. 지금 데이터 모델에는
# Evidence.topic/IngredientKnowledgeFact 어디에도 "조합" 전용 필드가 없어서, 텍스트 안에
# 이 키워드가 있는지로 대신 가려낸다 - 부정확할 수 있지만, 아무 근거나 조합 근거로 인정하는
# 것보다는 훨씬 보수적이다(놓치는 쪽으로 치우친다).
_COMBINATION_KEYWORDS = ("병용", "동시 사용", "함께 사용", "배합금지", "혼합금지", "併用")


class _LlmClaim(BaseModel):
    sentence: str = Field(description="근거에 기반한 짧은 문장 하나")
    cited_indices: list[int] = Field(description="이 문장이 인용한 근거 번호 목록(1부터)")


class _LlmAnswer(BaseModel):
    claims: list[_LlmClaim]


class AnswerGenerator:
    """`RetrievedChunk` 목록으로 `IngredientVerificationResult`를 만든다."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = ChatOpenAI(api_key=api_key, model=model)
        self._structured_client = self._client.with_structured_output(_LlmAnswer)
        self._condition_checker = ConditionPreservationChecker()

    def generate(
        self,
        question: str,
        retrieved: list[RetrievedChunk],
        intents: tuple[QuestionIntent, ...] = (),
        is_combination_question: bool = False,
    ) -> IngredientVerificationResult:
        if not retrieved:
            return self._unverifiable(UnverifiableReason.NO_EVIDENCE_FOUND)

        verifiable = [chunk for chunk in retrieved if chunk.confidence_tier in _VERIFIABLE_TIERS]
        if not verifiable:
            return self._unverifiable(UnverifiableReason.ONLY_AI_GENERATED_AVAILABLE)

        relevant = self._filter_by_intent(verifiable, intents)
        if intents and not relevant:
            return self._unverifiable(UnverifiableReason.NOT_RELEVANT_TO_QUESTION)

        if is_combination_question:
            relevant = self._filter_combination_evidence(relevant)
            if not relevant:
                return self._unverifiable(UnverifiableReason.MISSING_COMBINATION_EVIDENCE)

        llm_claims = self._generate_claims(question, relevant)
        validated = self._validate_claims(llm_claims, relevant)
        if not validated:
            return self._unverifiable(UnverifiableReason.CITATION_VALIDATION_FAILED)

        answered_claims = tuple(
            AnsweredClaim(sentence=sentence, sources=tuple(self._deduplicated_citations(chunks)))
            for sentence, chunks in validated
        )
        all_cited_chunks = [chunk for _, chunks in validated for chunk in chunks]
        return IngredientVerificationResult(
            has_verifiable_evidence=True,
            answer=" ".join(claim.sentence for claim in answered_claims),
            claims=answered_claims,
            sources=tuple(self._deduplicated_citations(all_cited_chunks)),
        )

    def _unverifiable(self, reason: UnverifiableReason) -> IngredientVerificationResult:
        return IngredientVerificationResult(
            has_verifiable_evidence=False, unverifiable_reason=reason
        )

    def _filter_by_intent(
        self, chunks: list[RetrievedChunk], intents: tuple[QuestionIntent, ...]
    ) -> list[RetrievedChunk]:
        # COMBINATION은 이 축 필터에서 뺀다 - INTENT_TO_VERIFIABLE_CHUNK_FIELDS의 COMBINATION
        # 매핑이 빈 집합이라, 조합 질문이 COMBINATION 하나만 감지되면 여기서 전부 걸러져
        # _filter_combination_evidence를 타보지도 못하고 근거부족이 되는 버그가 있었다
        # (2026-09-10, 코드 리뷰로 발견). 조합 근거 판정은 이 메서드가 아니라 별도로
        # _filter_combination_evidence가 전담한다.
        axis_intents = tuple(
            intent for intent in intents if intent is not QuestionIntent.COMBINATION
        )
        if not axis_intents:
            # 질문 축을 못 정했으면(자유 텍스트 등) 티어 판정만으로 좁힌 결과를 그대로 쓴다 -
            # 관련성을 판단할 근거가 없어 보수적으로 필터링을 건너뛴다.
            return chunks
        allowed_fields = frozenset().union(
            *(INTENT_TO_VERIFIABLE_CHUNK_FIELDS[intent] for intent in axis_intents)
        )
        return [chunk for chunk in chunks if chunk.chunk_field in allowed_fields]

    def _filter_combination_evidence(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return [
            chunk
            for chunk in chunks
            if any(keyword in chunk.content for keyword in _COMBINATION_KEYWORDS)
        ]

    def _generate_claims(self, question: str, relevant: list[RetrievedChunk]) -> list[_LlmClaim]:
        evidence_block = "\n".join(
            EVIDENCE_ITEM_TEMPLATE.format(
                index=index, source_title=chunk.source_title, content=chunk.content
            )
            for index, chunk in enumerate(relevant, start=1)
        )
        response = self._structured_client.invoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(
                    content=USER_PROMPT_TEMPLATE.format(
                        question=question, evidence_block=evidence_block
                    )
                ),
            ]
        )
        assert isinstance(response, _LlmAnswer)  # with_structured_output 계약
        return response.claims

    def _validate_claims(
        self, claims: list[_LlmClaim], relevant: list[RetrievedChunk]
    ) -> list[tuple[str, list[RetrievedChunk]]]:
        validated: list[tuple[str, list[RetrievedChunk]]] = []
        for claim in claims:
            cited_chunks = self._resolve_valid_citations(claim.cited_indices, relevant)
            if cited_chunks is None:
                continue  # ID 유효성 검증 실패 - 존재하지 않는 근거 번호를 하나라도 인용함
            if not any(
                self._condition_checker.is_preserved(claim.sentence, chunk.content)
                for chunk in cited_chunks
            ):
                continue  # 내용 지지 검증 실패 - 원문 조건이 문장에서 빠짐(일반화)
            validated.append((claim.sentence, cited_chunks))
        return validated

    def _resolve_valid_citations(
        self, cited_indices: list[int], relevant: list[RetrievedChunk]
    ) -> list[RetrievedChunk] | None:
        # 1부터 시작하는 근거 번호만 유효하다. 인용 번호가 하나도 없거나, 유효/무효 번호가
        # 섞여 있으면(무효 번호만 조용히 걸러내고 넘어갔던 첫 버전은 LLM이 존재하지 않는
        # 근거를 지어낸 걸 숨기는 셈이었다 - 2026-09-10 코드 리뷰로 발견) 문장 전체를
        # 버린다. "일부만 맞는 인용"을 신뢰할 근거는 없다.
        if not cited_indices:
            return None
        if any(not (1 <= i <= len(relevant)) for i in cited_indices):
            return None
        return [relevant[i - 1] for i in cited_indices]

    def _deduplicated_citations(self, chunks: list[RetrievedChunk]) -> list[SourceCitation]:
        # 같은 성분이 여러 필드(효능/주의사항 등)에서 동시에 매칭되면 청크는 여러 개지만
        # 출처는 하나로 보여줘야 한다. source_title을 그 출처의 식별자로 쓴다.
        seen_titles: set[str] = set()
        citations: list[SourceCitation] = []
        for chunk in chunks:
            if chunk.source_title in seen_titles:
                continue
            seen_titles.add(chunk.source_title)
            citations.append(self._to_citation(chunk))
        return citations

    def _to_citation(self, chunk: RetrievedChunk) -> SourceCitation:
        return SourceCitation(
            source_title=chunk.source_title,
            source_url=chunk.source_url,
            citation_refs=chunk.citation_refs,
            confidence_tier=chunk.confidence_tier,
        )
