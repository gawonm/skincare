# 살리실릭애씨드 Evidence 검색 이슈 보류 기록

- 기록 일시: 2026-09-21 14:37 (KST)
- 상태: **Evidence 영역 후속 작업으로 보류**
- 범위: Agent 실행 결과와 현재 DB 연결 상태 기록

## 1. 결정 사항

현재 Agent의 NIA Case 검색, 런타임 Claim 추출, 상품 추천 및 루틴 생성 흐름을 우선 진행한다.

살리실릭애씨드 질의에서 Evidence가 검색되지 않는 문제는 Evidence 저장소와 검수 정책을 확정한 뒤 별도 작업으로 처리한다. 이번 보류 과정에서는 Agent 코드, Backend 코드, DB 데이터를 변경하지 않는다.

## 2. 재현 질의와 결과

실행 명령:

```powershell
uv run python -m tests.agent.interactive_two_layer_rag_cli "살리실릭애씨드는 여드름 피부에 어떤 효과가 있고, 사용 시 주의할 점은 뭐야?"
```

확인된 결과:

- 실행 상태: `partial`
- 분류 의도: `evidence_qa`
- Evidence 검색 결과: 0건
- 최종 Citation: 0건
- compact 출력에서는 사용자 질문 전체가 Claim 이름처럼 표시되고 `Claim-only 유지`로 출력됨

## 3. DB에서 확인한 현재 상태

기준 DB: `skincare_latest`

- `IngredientMaster`에는 `살리실릭애씨드`가 존재함
  - `ingredient_id`: `5c3fa47f-b797-452c-bc86-04a872aa3f71`
- 해당 성분과 `evidence_chunk_ingredient`로 연결된 `evidence_chunk`는 0건임
- `IngredientKnowledgeFact`에는 해당 성분의 효능 및 주의사항 데이터가 1건 존재함
- 해당 Knowledge Fact의 규제 신뢰도는 `unverified`임

따라서 DB에 살리실릭애씨드 관련 정보가 전혀 없는 것이 아니라, 현재 Agent가 사용하는 신규 Evidence 검색 경로와 연결된 근거 청크가 없는 상태다.

## 4. 현재 진단

Evidence RAG 호출 자체는 수행됐다. 현재 검색 경로는 다음 저장 구조를 대상으로 한다.

```text
evidence_document
  → evidence_chunk
  → evidence_chunk_ingredient
```

반면 `IngredientKnowledgeFact`는 이 검색 경로에 포함되지 않는다. `rag_chunk`도 0건이므로 기존 범용 RAG 저장소를 통한 대체 검색도 발생하지 않는다.

또한 compact 출력의 `[Claim → Evidence]`와 `Claim-only 유지` 문구는 명시적 성분 질의인 `evidence_qa`에도 공통 표시 형식을 사용하기 때문에 오해를 만든다. 사용자 질문 전체가 표시된 것은 출력용 검색 요청 제목이며, 이것만으로 성분 추출 실패라고 단정할 수는 없다.

현재 compact 출력에는 `target_ids`가 나타나지 않으므로, 이 실행 결과만으로 `ingredient_mentions`에서 표준 성분 ID가 정상 추출됐는지는 확정하지 않는다. 다만 ID가 정상 추출됐더라도 연결된 Evidence 청크가 0건이면 현재와 같은 결과가 나온다.

## 5. 후속 작업 후보

Evidence 작업을 재개할 때 다음 항목을 순서대로 확인한다.

1. compact 출력에서 Claim 검색과 성분 직접 Evidence 검색을 구분한다.
2. 디버그 출력에 표준 성분명과 `target_ids`를 표시한다.
3. `IngredientKnowledgeFact`를 신규 Evidence 저장 구조로 적재할지 결정한다.
4. `unverified` Knowledge Fact를 최종 답변에 사용할 수 있는지 정책을 확정한다.
5. 살리실릭애씨드 질의를 verbose/E2E 모드로 재실행하여 성분 해석과 Evidence 요청 DTO를 확인한다.

## 6. 재개 조건

다음 두 사항이 합의되면 Evidence 연결 작업을 재개한다.

- Evidence 원천별 저장·검색 계약 확정
- `verified`와 `unverified` 자료의 답변 노출 및 Citation 정책 확정

`peer_reviewed` 등의 원천 유형만으로 자료를 임의로 `verified` 처리하지 않는다.

