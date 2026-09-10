# 에이전트 (RAG · 챗봇)

`agent/rag/`(문서 로딩·청킹·임베딩·검색·답변 생성)와 `agent/tools/`(에이전트가 호출하는 도구)를
다룬다. 폴더 구조와 import 방향은 [STRUCTURE.md](../../STRUCTURE.md), 코드 작성 규칙은
[CLAUDE.md](../../CLAUDE.md)를 따른다.

## 담당 범위

이 문서가 다루는 담당 범위는 다음까지다.

- 소스 문서(Evidence/IngredientKnowledgeFact/NIA Q&A) → `RagDocument` 변환 (`agent/rag/loaders/`)
- 의미단위 청킹 (`agent/rag/chunking/`)
- 임베딩 (`agent/rag/embedding/`)
- 하이브리드 검색·질문 축 분류 (`agent/rag/retrieval/`)
- 근거 검증·답변 생성 (`agent/rag/generation/`)
- 근거 없는 문장을 만들지 않는 것 — 이 파트의 가장 중요한 제약이다

다음은 담당 범위 밖이며, 이 문서와 이 파트의 작업 목록에 포함하지 않는다.

- 챗봇 UI, 추천 API, 제품 랭킹 엔진, 프론트엔드
- 사용자 발화 의도 분류기, 루틴/스케줄링 엔진
- DB 세션 생성 — `agent`는 세션을 직접 만들지 않고 파라미터로 받는다 ([STRUCTURE.md](../../STRUCTURE.md))
- `backend` import — `agent`는 FastAPI를 모른다

## 현재 구현 상태 (2026-09-10 기준)

`agent/rag/*`와 `models/rag_chunk.py`(pgvector+ParadeDB BM25 통합 인덱스)로 3개 소스를 하나의
임베딩 인덱스에 적재한다. 실제 적재 건수·소스별 신뢰도 티어는 [docs/data/data.md의 "RAG 적재
진행 상태"](../data/data.md#rag-적재-진행-상태)에 있다 — 같은 숫자를 이 문서에 중복해서 적지
않는다.

### 근거 검증 3단계 신뢰도 티어

`RagConfidenceTier`(`models/rag_chunk.py`)로 소스를 구분하고, `AnswerGenerator`
(`agent/rag/generation/answer_generator.py`)가 이 중 `OFFICIAL_REGULATORY`(MFDS)와
`STRUCTURED_KNOWLEDGE`(Knowledgedata) 두 티어만 "검증된 근거"로 인정한다.
`AI_GENERATED_REVIEWED`(NIA Q&A)만 있으면 `ONLY_AI_GENERATED_AVAILABLE`로 근거 부족 처리한다.
이건 버그가 아니라 코드 주석에 명시된 의도적 설계다 — NIA는 AI가 생성하고 전문가 패널이
검증한 데이터지, 공식 규제기관·사람이 구조화한 지식이 아니기 때문이다.

**단, 이 정책 때문에 NIA는 현재 "임베딩은 됐지만 검증 근거 생성에는 전혀 쓰이지 않는" 상태다.**
사용자가 지정한 이 프로젝트의 핵심 목표(NIA의 성분 지식과 피부·환경·사용 조건 상담 사례를
보존해 검색에 활용하는 것)와 이 현재 정책 사이에는 차이가 있다. 이 문서 하단
["다음에 필요한 것"](#다음에-필요한-것)에서 다룬다.

### 질문 축 분류의 구조적 한계

`QuestionIntentClassifier`(`agent/rag/retrieval/question_intent_classifier.py`)가 질문을
7개 축(효능/피부타입/농도/주의사항/규제/사용주기/조합)으로 분류하고,
`INTENT_TO_VERIFIABLE_CHUNK_FIELDS`가 각 축을 뒷받침할 수 있는 `RagChunkField`를 정의한다.
`USAGE_FREQUENCY`와 `COMBINATION` 두 축은 매핑이 **빈 집합**이다 — Evidence/
IngredientKnowledgeFact 어디에도 사용주기·조합 전용 필드가 없어서, 이 두 축을 묻는 질문은
구조화된 근거만으로는 항상 근거 부족으로 판정된다. NIA Q-CoT-A의 `NIA_COT_STEP` 청크에는
실제로 사용 시간·빈도·순서 서술이 들어 있지만, 위 신뢰도 티어 정책 때문에 애초에 검증 근거
후보에 들어가지 못해 이 갭을 메우지 못한다.

### NIA Q&A 로더의 현재 범위

`NiaQaLoader`(`agent/rag/loaders/nia_qa_loader.py`)는 `info.question`/`info.answer`/
`chain_of_thought[].content`만 청크로 만든다. `meta`(나이·성별·피부타입·피부고민·초기 피부상태)와
`external`(계절·스트레스 등 배경요인)은 파싱 모델(`NiaQaRecord`)에 아예 없어 로더를 거치면서
사라진다. `ingredient_id`는 코드 주석대로 "NIA Q&A는 상황 상담 사례라 한 성분에 매이지 않는다"는
의도적 선택으로 항상 `None`이다 — 다만 이 때문에 "성분 X + 피부타입 Y + 사용시간 Z" 같은 조건
조합 검색에서 NIA 근거를 걸러낼 방법이 지금은 없다(질문 축과 연결할 조건 필드 자체가 없다).

## NIA 원본 감사 결과 — agent 계층에 영향 있는 부분만

전체 감사(파싱 건수·분류표·출처 통계)는 [docs/data/data.md](../data/data.md)가 정본이다.
여기서는 `agent/rag/generation/answer_generator.py`와 `agent/rag/retrieval/*`의 판단에 직접
영향을 주는 사실만 요약한다.

- **evidence_sources 상당수가 placeholder다.** Training 8,000건 전수 조사 기준
  `PMID:12345678`이 2,961건(37%)에서 반복 등장하고, `DOI:10.xxxx/xxxxx` 2,780건,
  `DOI:10.1234/example` 164건이 확인됐다. `RagDocumentMetadata.citation_refs`에 이 값이
  그대로 들어가므로, NIA 청크를 앞으로 어떤 형태로든 근거로 노출하게 되면 이 citation을
  검증된 출처로 보여주면 안 된다. (기존 `docs/data/data.md`의 "evidence_sources(PMID/DOI
  실제 논문 인용)" 서술은 이 부분 정정이 필요해 아래에서 같이 고쳤다.)
- **아카이브명과 `info.target_concern`이 72%(5,772/8,000) 불일치한다.** `NiaQaRecord`가
  `info.target_concern`만 쓰고 있어 이 필드 자체는 영향받지 않지만, 향후 "피부고민별 필터"를
  agent 쪽에서 만들 때 아카이브 파일명을 신뢰하면 안 된다는 뜻이다.

## 이번 세션에 추가한 파일: `agent/rag/nia_labeling_schemas.py`

`docs/NIA_SEMANTIC_LABELING_SPEC.md`가 요구하는 "원문을 관계·조건 단위로 라벨링하고 고정
스키마로 재사용"을 위한 Pydantic discriminated union이다. **주의: 아직 `NiaQaLoader`·
`RagChunk`·DB 어디와도 연결되지 않은 독립 스키마 정의 단계다.** 현재 상태:

- 7개 statement 타입(`case_observation`/`cause_claim`/`ingredient_effect_claim`/
  `precaution`/`usage_instruction`/`combination_claim`/`contextual_factor`)을
  `NiaStatementType` discriminator로 구분.
- `NiaSourceSpan`이 원문 인용 오프셋(Unicode 코드포인트 기준 `[start, end)`)을 강제하고,
  `NiaLabelingSpanVerifier`가 승인된 라벨링을 다시 읽을 때 원문과 quote가 여전히 일치하는지
  재검증한다.
- `NiaIngredientSubject.matching_status`에 `unresolved_ambiguous_family` 상태를 따로 둬서
  "대나무 추출물" 같은 계열명을 단일 INCI로 임의 확정하지 않도록 강제한다.
- Training 파일럿 5건(33 statements)을 이 스키마 + span 재검증까지 통과시켜 검증함
  (`docs/NIA_SEMANTIC_LABELING_SPEC.md` 8절의 회귀 사례 일부를 실제 데이터로 재현).

## 다음에 필요한 것

아래는 구현하지 않고 남겨 둔 것이다. 임의로 정하지 않고 사용자 확인 후 진행한다.

- 라벨링 결과(`NiaLabelingDocument`)를 `NiaQaLoader`/`RagChunk`와 어떻게 연결할지. 지금은
  라벨링이 `NiaQaRecord`와 완전히 별개 경로다.
- NIA를 "검증된 근거"로 승격하지 않으면서도 "사례 검색"에는 쓰이게 하려면
  `AnswerGenerator`/`RetrievedChunk`에 신뢰도 티어와 별개인 사용 목적 구분(사례 vs 검증 근거)이
  필요한지, 아니면 지금처럼 완전히 배제할지.
- `QuestionIntentClassifier`의 `USAGE_FREQUENCY`/`COMBINATION` 빈 집합을 라벨링된
  `usage_instruction`/`combination_claim` statement로 채울지 여부.

## 관련 문서

- NIA 데이터 성격·라이선스·전체 적재 현황: [docs/data/data.md](../data/data.md)
- 의미 라벨링 설계 초안: [docs/NIA_SEMANTIC_LABELING_SPEC.md](../NIA_SEMANTIC_LABELING_SPEC.md)
- 폴더 구조와 import 방향: [STRUCTURE.md](../../STRUCTURE.md)
