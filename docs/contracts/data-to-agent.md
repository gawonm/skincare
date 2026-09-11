# data → agent: RAG 근거 데이터 전달

data 파트가 수집·정제한 성분 근거(MFDS 고시, Knowledgedata, NIA Q&A)를 agent 파트의 RAG
파이프라인(`agent/rag/loaders/`)이 읽어 쓰는 지점을 정리한다. 초안은 값을 넘기는 data 파트가
쓴다(CLAUDE.md 규칙 16). **agent/, agent/rag/의 구현 자체는 data 파트가 만들지 않는다** —
이 문서는 어디까지나 경계에서 주고받는 타입·경로만 다룬다.

## 0. 먼저 정리해야 할 충돌

`data/manual_review/nia_labeling_schemas.py`와 `agent/rag/nia_labeling_schemas.py`가 **내용이
완전히 동일한 채로 두 곳에 존재**한다(diff 결과 줄바꿈 문자만 다름, 로직 차이 없음).
`docs/agent/README.md`는 이 파일을 agent 파트가 이번 세션에 만든 것으로 기록하고 있다.

- 이 문서는 이 파일의 소유권을 정하지 않는다. `RAG-담당자-인수인계.md`가 지적한 "데이터 파트가
  agent 산출물을 임의로 만들었을 수 있다"는 문제와 정확히 같은 사례이므로, **에이전트
  담당자가 확인 후 하나만 남기고 나머지를 삭제**해야 한다(규칙 15). data 파트가 임의로 어느
  쪽을 지우지 않는다.

## 1. 현재 이미 동작 중인 경계 (참고용 — 이 문서가 새로 만드는 계약 아님)

`agent/rag/loaders/`의 `EvidenceLoader`, `KnowledgeFactLoader`, `NiaQaLoader`는 data 파트가
적재한 DB 테이블(`models/evidence.py`의 `Evidence`, `models/ingredient_knowledge.py`의
`IngredientKnowledgeFact`)을 세션으로 직접 조회해 `RagDocument`로 변환한다. CSV나 함수 호출이
아니라 **DB 테이블 자체가 현재의 data → agent 인터페이스**다. 이 방식은 이미 구현·검증
(`docs/data/rag_pipeline_handoff.md` 4.1절, 65,196청크 적재 확인)까지 끝난 상태라 이 문서에서
다시 정하지 않는다.

| 테이블 | 채우는 스크립트 | 소유 |
| --- | --- | --- |
| `evidence` | `data/scripts/import_mfds_restricted_ingredients.py` | data (모델 정의: `models/evidence.py`) |
| `ingredient_knowledge_fact` | `data/scripts/import_knowledgedata.py` | data (모델 정의: `models/ingredient_knowledge.py`) |
| NIA Q&A (jsonl, DB 테이블 아님) | `backend/services/rag_ingestion_service.py --nia-qa-zip` 실행 시 파일에서 직접 파싱 | 원본 파일은 data 관리, 파싱은 agent(`NiaQaLoader`) |

## 2. 아직 정해지지 않은 것 (인수인계 문서 6절 인계 요구 중 미해결분)

아래는 data 파트가 갖고 있지만 아직 agent와 연결이 합의되지 않은 항목이다. 임의로 형식을
정하지 않고 여기 적어 둔다(규칙 3, 16).

- **성분 매칭 확정/미해결 상태**: `data/manual_review/knowledgedata_ingredient_match_queue.csv`,
  `mfds_ingredient_match_queue.csv`에 있는 미해결 매칭이 RAG 검색·근거 검증에 어떻게 반영돼야
  하는지 — 지금은 agent 쪽이 이 큐를 전혀 참조하지 않는다.
- **NIA 의미 라벨링(`NiaLabelingDocument`) ↔ `RagChunk` 연결**: `docs/agent/README.md` "다음에
  필요한 것" 절이 이미 미정으로 남긴 것과 동일 항목. 0절의 파일 중복이 정리된 뒤에나 논의 가능.
- **제품 전성분(`product_ingredient`)과 RAG 근거의 연결 여부**: 현재 RAG는 성분 자체의 근거만
  다루고, 특정 제품의 전성분 목록과 엮는 기능은 없음. 필요 여부 자체가 미정.

## 3. 실패했을 때

해당 없음 — DB 조회 기반이라 별도의 실패 계약이 없다. 미해결 매칭 항목을 향후 연결하게 되면
그때 실패 처리(전체 중단 vs 건너뛰기)를 이 문서에 추가한다.

## 4. 절차

1. 에이전트 담당자가 0절의 중복 파일부터 정리.
2. 2절 항목 중 실제로 필요한 것부터 에이전트 담당자와 논의해 이 문서에 시그니처·타입을 추가.
3. 합의 전까지 data 파트는 `agent/`에 파일을 추가하지 않는다.
