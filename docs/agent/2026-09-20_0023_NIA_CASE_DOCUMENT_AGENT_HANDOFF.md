# NIA Case Document 이후 통합 RAG 구현 계획

- 작성 일시: 2026-09-20 00:23 KST
- 최종 갱신: 2026-09-20 01:48 KST
- 작업 브랜치: `integration/nia-case-rag`
- 목적: 최신 `main`의 NIA Data 산출 범위를 확인하고, Data → Backend → Agent 경계를 한 흐름으로 구현할 범위를 확정한다.
- 기준 문서:
  - [`docs/contracts/data-to-agent.md`](../contracts/data-to-agent.md)
  - 외부 전달본 `DB_REFERENCE_HANDOFF.md` (현재 저장소 `docs/data/`에는 미반영)
  - [`docs/contracts/claim-evidence-rag-interface.md`](../contracts/claim-evidence-rag-interface.md)

## 1. 결론

기존 2-Layer RAG의 `ClaimHit → Evidence → Product` 흐름은 유지한다. 새로 전달된
`NiaCaseDocument`는 사용자의 피부 고민과 유사한 사례 Top-3를 찾는 탐색 입력으로 사용하고,
현재 Claim 검색 앞에 사례 검색 단계를 추가하는 방향을 우선 검토한다.

```text
사용자 피부 고민
  → NIA 유사 사례 Top-3
  → 사례에 연결된 Claim·성분 후보
  → 공인 Evidence 검증
  → confirmed 성분 기반 상품 조회
  → Evidence 지원/Claim-only를 구분한 응답
```

명시적인 성분 질의는 기존과 같이 사례 검색을 생략하고 Evidence 검색으로 바로 이동한다.
Evidence가 없더라도 유효한 Claim에서 발견된 성분과 상품 후보는 제거하지 않고
`Claim 기반·공인 근거 미확인`으로 유지한다.

## 2. 최신 main에서 완료된 Data 범위

현재 `main`에는 다음 단계가 구현돼 있다.

```text
AI Hub Q-CoT-A ZIP/JSONL
  → NiaOriginalLoader
  → NiaOriginalAgeFilter(10~39세)
  → NiaCaseDocumentBuilder
  → NiaCaseDocument
```

완료된 범위는 다음과 같다.

- ZIP/JSONL 원본 로드
- 원본의 question, answer, CoT, meta, external, target_concern 보존
- `meta.age` 기준 만 10~39세 필터
- 질문·답변·CoT 전체를 하나의 `page_content`로 구성
- `embedding_text = page_content`인 `nia_case_text/v1` 문서 생성
- 검색 필터·출처·문맥 값을 `metadata`로 분리
- 관련 단위 테스트

따라서 Agent가 `question + answer + CoT → page_content` 또는
`meta/external/target_concern → metadata` 변환을 다시 구현하지 않는다. 이 형식은 Data가 소유한
`NiaCaseDocumentBuilder`의 책임이다.

아직 구현되지 않은 범위는 다음과 같다.

- BGE-M3 embedding
- vector/text index 적재
- 유사 사례 Top-3 retrieval
- reranker
- 사례와 Claim·표준 성분 ID의 연결
- Agent LangGraph 운영 연결

## 3. NiaOriginalRecord와 NiaCaseDocument의 차이

### 3.1 한 줄 정의

- `NiaOriginalRecord`: AI Hub 원본 한 줄을 손실 없이 읽기 위한 원본 보존 모델
- `NiaCaseDocument`: 원본 한 사례를 검색하기 좋게 조립한 RAG용 파생 문서

비유하면 `NiaOriginalRecord`는 원본 설문·상담 기록이고, `NiaCaseDocument`는 그 기록을 검색
인덱스에 넣기 위해 만든 검색 카드다.

### 3.2 구조 비교

| 구분 | `NiaOriginalRecord` | `NiaCaseDocument` |
| --- | --- | --- |
| 목적 | 원본 파싱·검증·보존 | 임베딩·사례 검색 입력 |
| 데이터 모양 | `info`, `meta`, `external`, `chain_of_thought`의 중첩 구조 | `page_content`, `embedding_text`, `metadata` 중심 구조 |
| 원문 처리 | 원본 필드와 타입을 그대로 유지 | 질문·답변·CoT에 라벨과 줄바꿈을 붙여 한 문자열로 결합 |
| 검색 본문 | 별도 검색 본문 없음 | `embedding_text` 사용 |
| 검색 필터 | 여러 원본 필드에 흩어져 있음 | `metadata`에 `age`, `skin_type`, `skin_concerns` 등으로 모음 |
| 저장소 의존성 | 없음 | 없음. 실제 pgvector 형태 변환은 저장소 어댑터 책임 |
| 관계 | 기준 원본 | 원본 1건에서 생성되는 파생 문서 1건 |

예를 들어 원본이 다음과 같은 논리 구조라면,

```text
info.question
info.answer
meta.age
meta.skin_concerns
chain_of_thought[]
external[]
```

RAG 문서는 다음처럼 바뀐다.

```text
page_content:
  [질문]
  ...

  [답변]
  ...

  [추론]
  1. ...

embedding_text:
  page_content와 동일(v1)

metadata:
  case_id, age, skin_type, skin_concerns, target_concern,
  source_survey_id, external, evidence_sources 등
```

`NiaCaseDocument`는 원본을 대체하는 저장 모델이 아니다. 검색에 필요한 알려진 필드를 선택해
재배치한 파생 결과이므로, 원본의 향후 추가 필드까지 완전히 역변환할 수 있다고 가정하지 않는다.

## 4. 권장 책임 분리

### Data

- `NiaOriginalRecord` 로드와 원본 검증
- 연령 필터
- `NiaCaseDocument` 생성
- 오프라인 Claim·성분 annotation의 소유 여부 확정
- 재현 가능한 산출 명령과 결과 manifest 제공

### Backend

- `NiaCaseDocument`를 저장 가능한 형태로 변환
- DB 쓰기·읽기와 vector/text 검색 Repository
- Agent가 소유한 검색 DTO로 결과 매핑
- `ProductionAgentFactory`에 실제 검색 구현 주입

### Agent

- 사례 검색 요청·결과 DTO와 Port
- 피부 고민형 질의의 사례 검색 라우팅
- Top-3 후보 선택·중복 제거·실패 정책
- 사례 → Claim → Evidence → Product 상태 전이
- Claim-only 유지와 응답 신뢰도 표현
- Fixture 및 통합 계약 테스트

Agent는 `data.scripts`의 Pydantic 모델을 직접 import하지 않는다. Backend가 Data 산출물을 읽어
Agent 소유 DTO로 변환한다. 또한 Agent는 Data가 이미 만든 `page_content`와 `metadata`를 다시
조립하지 않는다.

## 5. Agent에서 구현할 작업

### 5.1 계약·DTO

- `CaseSearchRequest`
- `CaseSearchHit`
- `CaseSearchResult`
- `CaseRetriever`

검색 결과에는 최소 `case_id`, `page_content`, `text_version`, 피부 고민 metadata, 검색 점수와
provenance가 필요하다. `evidence_sources`는 검증되지 않은 원문 metadata로만 보존하고 공식
Evidence/Citation으로 승격하지 않는다.

### 5.2 LangGraph

- 피부 고민형 경로 앞에 `search_cases` 노드 추가
- 유사 사례 Top-3를 State에서 Claim/Evidence와 분리해 저장
- 명시적 성분 질의는 사례 검색 생략
- 사례 검색 실패, 결과 없음, Claim 없음, Evidence 없음 상태를 구분
- 기존 Claim-only 상품 유지 정책 보존

### 5.3 검색 정책

- 임베딩 모델: `BAAI/bge-m3`
- 차원: 1,024
- 기본 후보 수: Top-3
- 초기에는 임의 유사도 임계값을 확정하지 않고 점수 분포와 평가 결과를 수집
- reranker는 검색 기반선 검증 후 별도 단계로 연결

### 5.4 테스트

1. 피부 고민 → 사례 Top-3 → Claim → Evidence → 상품
2. Evidence가 없는 Claim도 상품 유지
3. 사례는 있으나 표준 성분 연결이 없는 경우
4. 같은 상품이 여러 성분에서 나온 경우 중복 제거
5. 명시적 성분 질의의 사례 검색 생략
6. NIA `evidence_sources`가 Citation으로 노출되지 않는지 확인
7. 지식 없음과 상품 없음 구분
8. Case/Claim/Evidence 각 검색 실패 상태 구분

## 6. Data 단계에서 구현할 사항

1. 3,581건 `NiaCaseDocument`를 생성하는 실행 명령 또는 CLI
2. 산출 JSONL과 manifest에 건수, split, SHA-256, `case_id` 유일성 검증 결과 기록
3. 테스트 가능한 소규모 `NiaCaseDocument` fixture
4. `case_id`와 `claim_document.source_record_id`를 같은 원본 레코드 ID로 유지
5. `evidence_sources`를 검증되지 않은 provenance로만 보존

가장 중요한 확인 사항은 **Case → Claim·Ingredient 연결을 누가 생성하는가**다. 현재 Data에는
production annotation과 성분 매칭 코드가 이미 있으므로, 런타임 Agent가 같은 추출을 다시 하는
것보다 기존 오프라인 annotation 경로를 재사용하고 Agent가 결과를 조회하는 방식을 적용한다.

다만 로컬에는 production annotation 산출물이 없다. `data/scripts/nia_production_annotation_run.py`는
존재하지만 입력 `data/processed/nia_qa_10s_30s.jsonl`과 production 출력 JSONL이 모두 없고,
전체 실행은 OpenAI `gpt-4o-mini` 호출 비용이 발생한다. 따라서 Case 저장·검색 구현과 전체 Claim
annotation 실행을 분리하며, 비용이 발생하는 전체 annotation은 별도 승인 전에는 실행하지 않는다.

## 7. Backend 단계에서 구현할 사항

1. `NiaCaseDocument → Agent CaseSearchHit` mapper
2. NIA 사례 저장 위치와 인덱스 형태 결정
3. BGE-M3 벡터·`text_version`·metadata 저장
4. Top-3 vector/hybrid 조회 Repository
5. 지원할 metadata 필터 범위
6. `CaseRetriever` 구현체와 운영 의존성 주입
7. Case ID에 연결된 Claim 조회 지원

새 테이블은 `nia_case_document` 하나를 제안한다. 기존 `claim_document`와 물리 FK를 만들지 않고
`nia_case_document.case_id = claim_document.source_record_id` 규칙으로 연결한다. 동일 Case에 여러
`annotation_version`이 공존할 수 있어 FK 하나로 특정 Claim run을 고정하지 않기 위해서다.

ERD 초안은 `docs/erd/app.md`에 먼저 기록하고 사용자 확인 뒤에만 ORM과 migration을 작성한다.

## 8. 구현 기준

다음 정책을 구현 기준으로 확정할 필요가 있다.

> `NiaCaseDocument` Top-3 검색을 기존 Claim 검색 앞에 추가하고,
> 기존 `ClaimHit → Evidence → Product` 구조는 유지한다.

이 방향이면 기존 2-Layer 구현을 보존하면서 신규 사례 검색을 추가할 수 있고,
NIA 사례를 공인 Evidence로 오인하는 것도 방지할 수 있다.

추가 기준은 다음과 같다.

- Case 임베딩은 `BAAI/bge-m3`, 1,024차원으로 고정한다.
- 운영 검색에는 `training` split만 사용하고 `validation` split은 평가에 남긴다.
- Case 후보 검색과 최종 Top-3 선택을 분리한다. 1차 후보 검색 이후 BGE reranker를 적용한다.
- 임의의 similarity cutoff는 먼저 넣지 않고 평가 질의의 점수 분포를 확인한 뒤 결정한다.
- Case 검색이 실패하거나 결과가 없으면 오류 상태를 보존한 채 기존 Claim 검색 fallback을 허용한다.
- Case에 연결된 Claim의 Evidence가 없어도 Claim-only 상품 후보는 제거하지 않는다.

## 9. 실제 AI Hub 원본 점검 결과

점검 경로:

```text
C:\Users\Admin\Documents\03.스킨케어 성분-효능 추천 데이터
```

기존 `NiaOriginalLoader` → `NiaOriginalAgeFilter` → `NiaCaseDocumentBuilder`를 실제 원본에 적용한
읽기 전용 점검 결과는 다음과 같다.

| 항목 | 결과 |
| --- | ---: |
| ZIP | 15개 |
| JSONL 레코드 | 9,000건 |
| Training / Validation | 8,000 / 1,000건 |
| 고유 `case_id` | 9,000개 |
| 중복 `case_id` | 0개 |
| 10~39세 Case Document | 3,581건 |
| 빈 `page_content` / `embedding_text` | 0건 / 0건 |
| `text_version` | `nia_case_text/v1` |

따라서 원본 파서나 Case Document 변환기를 새로 만들 필요는 없다. 새로 필요한 코드는 3개 기존
클래스를 연결하는 exporter/manifest, DB 적재·검색, Agent 검색 포트와 LangGraph 연결이다.

## 10. 단계별 실행 계획

### P0. 계약·ERD 승인

상태: **완료 — 2026-09-20 사용자 확인**

- `data-to-agent.md`: Case export 구조와 원본/검색용 데이터의 경계
- `data-to-backend.md`: JSONL 적재, BGE-M3 임베딩, upsert와 실패 계약
- `backend-to-agent.md`: `CaseRetriever` 입력·출력과 상태 계약
- `docs/erd/app.md`: `nia_case_document` 제안 스키마

완료 조건은 사용자 ERD 확인이다. 승인 전에는 ORM·migration을 작성하지 않는다.

### P1. Data exporter

상태: **구현·실제 원본 검증 완료 — 2026-09-20**

- 기존 Loader/Filter/Builder를 순서대로 조립한다.
- JSONL과 manifest를 증분·결정적으로 생성한다.
- 원본 절대 경로는 저장하지 않고 archive/member/line provenance만 남긴다.
- 9,000건 입력, 3,581건 출력, split별 건수, 중복과 해시를 검증한다.

### P2. Case 저장·임베딩

상태: **구현·실제 DB 적재 검증 완료 — 2026-09-20**

- `nia_case_document` ORM과 Alembic migration을 추가한다.
- Backend service가 export JSONL을 검증하고 BGE-M3 1,024차원으로 임베딩한다.
- Repository가 `(case_id, text_version, embedding_model)` 자연키로 안전하게 upsert한다.
- 재실행 시 내용 해시가 같은 행은 불필요하게 다시 임베딩하지 않는다.

### P3. Case 검색과 Agent 연결

- Agent에 Case 전용 DTO와 `CaseRetriever`를 추가한다.
- Backend adapter가 `training` split, `text_version`, `embedding_model`을 정확히 필터링한다.
- 피부 고민형 경로에 Case 검색과 rerank 노드를 추가하고 명시 성분 경로는 건너뛴다.
- Top-3 Case ID로 같은 `source_record_id`의 Claim만 조회한 뒤 기존 Evidence/Product 흐름을 재사용한다.

### P4. Claim coverage 분리 검증

- 현재 DB의 Claim은 smoke 수준이므로 3,581 Case 전체와 연결되지 않는다는 사실을 테스트로 드러낸다.
- Case 검색 자체와 Case → Claim coverage를 별도 지표로 기록한다.
- production annotation 전체 실행은 API 비용과 예상 처리 시간을 확인받은 뒤 별도 작업으로 수행한다.

### P5. 통합 평가

- 피부 고민형, 명시 성분형, Case 없음, Claim 없음, Evidence 없음, 상품 중복을 각각 검증한다.
- `evidence_sources`가 Citation으로 승격되지 않는지 확인한다.
- Case Recall/Top-3 적합도와 Claim coverage를 분리해 보고한다.

## 11. P1 구현 결과와 사용자 실행 방법

추가 파일:

- `data/scripts/nia_case_rag/export_schemas.py`
- `data/scripts/nia_case_rag/exporter.py`
- `tests/unit/test_nia_case_exporter.py`

기존 Loader/Filter/Builder는 수정하지 않고 조립했다. exporter는 Training/Validation의
`02.라벨링데이터` 아래 `TL_*.zip`/`VL_*.zip`만 찾으며, Case JSONL에는 원본 절대 경로를 넣지
않고 archive명, ZIP member명, 물리적 줄 번호만 저장한다.

사용자 실행 명령:

```powershell
uv run python -m data.scripts.nia_case_rag.exporter `
  --input-root "C:\Users\Admin\Documents\03.스킨케어 성분-효능 추천 데이터"
```

기본 출력:

```text
data/processed/nia_case_documents_10s_30s.jsonl
data/processed/nia_case_documents_10s_30s.manifest.json
```

기존 출력이 있으면 덮어쓰지 않고 실패한다. 의도적인 재생성에만 `--overwrite`를 사용한다.

실제 원본 검증 결과:

| 검증 항목 | 결과 |
| --- | ---: |
| 입력 ZIP / 레코드 | 15개 / 9,000건 |
| 출력 Case | 3,581건 |
| Training / Validation | 3,177 / 404건 |
| 중복 Case ID | 0건 |
| 절대 입력 경로 노출 | 없음 |
| 동일 입력 재실행 SHA-256 | 일치 |
| SHA-256 | `189b72b4a71b8becd05edfc3d123d1d2a4e03a8174408c03c1187ea50cfc9173` |

검증 명령 결과는 exporter 관련 테스트를 포함해 29개 통과, Ruff 통과다. 실제 smoke 산출물은
검증 후 `tmp/`에서 삭제했으며 사용자가 위 명령을 실행하면 기본 `data/processed/` 경로에 새로
생성된다.

## 12. P2 구현 결과와 사용자 실행 방법

P1 파일은 실행 흐름이 한곳에 보이도록 `data/scripts/nia_case_rag/` 하위 패키지로 이동했다.
P2에서는 승인된 ERD대로 `nia_case_document` 모델과 Alembic migration을 추가하고,
Backend Repository/Service가 JSONL 검증 → 변경 판정 → BGE-M3 임베딩 → batch upsert를 수행한다.

```powershell
# 1. 테이블 생성
uv run alembic upgrade head

# 2. 기본 data/processed 산출물 임베딩·적재
uv run python -m backend.services.nia_case_ingestion_service
```

적재기는 manifest의 SHA-256, 전체/split/archive 건수, `text_version`, 중복 `case_id`를 DB 변경 전에
검증한다. 임베딩 결과가 `BAAI/bge-m3`가 아니거나 1,024차원이 아니면 저장하지 않는다. 같은
`content_hash`는 재임베딩하지 않으며, 오류가 난 batch만 rollback한다.

이 구현은 Case 저장까지다. Case 검색을 LangGraph 앞단에 연결하는 P3와 전체 3,581건 Claim
annotation은 포함하지 않는다.
