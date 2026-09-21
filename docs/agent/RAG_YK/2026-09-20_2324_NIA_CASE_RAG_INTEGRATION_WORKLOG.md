# NIA Case 기반 2-Layer RAG 통합 작업 합본

- 작성 일시: 2026-09-20 23:24 KST
- 최종 갱신: 2026-09-21 02:19 KST
- 작업 브랜치: `integration/nia-case-rag`
- 문서 역할: 2026-09-20까지의 결정, 구현, DB 상태와 다음 작업을 한곳에서 확인하는 운영 기준
- 현재 상태: P1·P2, 최신 `origin/main` 병합, 통합 DB 구성 및 실제 BGE-M3 smoke 완료

이 문서를 먼저 읽는다. 이전 설계·작업일지는 배경 확인이 필요할 때만 참고한다. 코드와 계약이
이 문서와 다르면 실제 코드, `docs/contracts/`, 최신 DB 검증 결과 순으로 확인한다.

## 1. 최종 목표와 확정 정책

피부 고민형 질문은 유사 NIA 사례를 먼저 찾은 뒤, Top-3 원문에서 런타임 LLM이 사용자 질문과
관련된 Claim을 exact quote로 추출한다. 규칙 검증과 표준 성분 ID 확정 후 공인 Evidence를
검증하고 confirmed 성분이 들어간 상품을 찾는다. 명시적인 성분 질문은 Case와 Claim 추출을
생략하고 Evidence로 바로 갈 수 있다.

```text
피부 고민형
  → NIA Case 후보 20건
  → BGE reranker Top-3
  → Top-3 원문의 런타임 Claim 추출
  → exact quote·성분명 규칙 검증
  → 표준 성분 ID
  → Evidence
  → Product
  → Claim-only / Evidence-supported를 구분한 답변

명시 성분형
  → Ingredient Resolution
  → Evidence
  → Product 또는 근거 답변
```

확정한 원칙은 다음과 같다.

- Case, 런타임 Claim, Evidence는 서로 다른 DTO와 LangGraph State로 유지한다.
- `nia_case_document`를 Claim이나 `rag_chunk`에 섞지 않는다.
- Case는 탐색 자료이며 Citation이나 공인 근거가 아니다.
- Evidence가 없거나 아직 검수되지 않아도 유효한 Claim과 연결 상품은
  `Claim 기반·공인 근거 미확인`으로 유지한다.
- 명시적 상반 근거, 검색 오류, 지원 불가는 단순 Evidence 부족과 구분한다.
- 복합 성분 Claim은 조합 전체를 직접 지원하는 Evidence가 있을 때만 `SUPPORTED`로 승격한다.
- 같은 상품은 `product_id`로 병합하고 Evidence-supported 연결을 우선한다.
- 경로, 필터, 검증, fallback, Citation 채택은 규칙 기반으로 처리한다.
- 런타임 LLM은 Top-3 원문에서 raw 성분명과 exact quote를 선택하며 ingredient ID·Evidence 상태를
  결정하지 않는다.
- Case ID, quote, 성분명, 단일/조합 형태 검증과 Ingredient Resolution은 규칙·저장소가 담당한다.
- NIA 전체 3,581건 offline Claim annotation은 P3 선행 조건에서 제외하고 후속 최적화로 보류한다.

## 2. 라우팅·성분 식별에서 유지할 기존 규칙

다음 정책은 이전 단발성 문서에서 이 문서로 이관했다.

- `피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?`처럼 피부 고민과 사용 대상 탐색이 함께 있는
  질문은 LLM이 `evidence_qa`로 분류해도 규칙으로 `product_discovery` 및
  `claim_then_evidence` 경로로 보정한다.
- 안전하게 확인된 완전 동의어만 alias로 사용한다. 계열명을 단일 성분으로 치환하지 않는다.
  예를 들어 `AHA → 글라이콜릭애씨드`처럼 여러 후보가 가능한 매핑은 금지한다.
- 자유 텍스트 Evidence fallback은 명시 성분이 있는 순수 Evidence 질문에서만 한 번 허용한다.
  상품 추천·루틴과 결합됐거나 성분이 모호하면 사용자 확인을 유지한다.
- 성분 ID는 반드시 저장소에서 확정하며 LLM이나 alias 사전이 임의 생성하지 않는다.

## 3. NIA 원본과 P1 산출물

원본 위치:

```text
C:\Users\Admin\Documents\03.스킨케어 성분-효능 추천 데이터
```

처리 흐름:

```text
AI Hub Q-CoT-A ZIP/JSONL
  → NiaOriginalLoader
  → NiaOriginalAgeFilter(10 <= age <= 39)
  → NiaCaseDocumentBuilder
  → NiaCase exporter
  → JSONL + manifest
```

`NiaOriginalRecord`는 원본 보존 모델이고 `NiaCaseDocument`는 검색용 파생 문서다.
`NiaCaseDocument` 한 건은 질문, 답변, 전체 CoT를 하나의 `page_content`와
`embedding_text`로 보존한다. `text_version`은 `nia_case_text/v1`이다.

실제 검증 결과:

| 항목 | 결과 |
| --- | ---: |
| 원본 ZIP | 15개 |
| 전체 레코드 | 9,000건 |
| 10~39세 Case | 3,581건 |
| Training / Validation | 3,177 / 404건 |
| 중복 `case_id` | 0건 |
| 빈 검색 본문 | 0건 |
| JSONL SHA-256 | `189b72b4a71b8becd05edfc3d123d1d2a4e03a8174408c03c1187ea50cfc9173` |

산출물:

- `data/processed/nia_case_documents_10s_30s.jsonl`
- `data/processed/nia_case_documents_10s_30s.manifest.json`

P1 구현은 `data/scripts/nia_case_rag/`에 있으며 Loader/Filter/Builder를 중복 구현하지 않는다.

## 4. P2 저장·임베딩 구현 결과

확정한 저장 구조:

- 전용 테이블: `nia_case_document`
- 사례 1건당 벡터 1개
- 모델: `BAAI/bge-m3`
- 차원: 1,024
- 운영 검색 split: `training`
- `validation` 404건은 검색 품질 평가용으로 보존
- 자연키: `(case_id, text_version, embedding_model)`
- 인덱스: cosine HNSW

구현 위치:

- 모델: `models/nia_case_document.py`
- migration: `migrations/versions/a7d3c91e5f42_add_nia_case_document.py`
- Repository: `backend/repositories/nia_case_document_repository.py`
- 적재 Service/CLI: `backend/services/nia_case_ingestion_service.py`
- 입력·결과 DTO: `backend/services/nia_case_ingestion_schemas.py`

적재기는 JSONL·manifest의 SHA-256, 전체/split/archive별 건수, 중복 ID와 `text_version`을 DB 변경
전에 검증한다. 같은 `content_hash`는 재임베딩하지 않으며 batch 실패 시 해당 batch를 rollback한다.

기존 `skincare_latest`에서 생성한 뒤 최종 통합 DB로 이전한 결과:

| 항목 | 결과 |
| --- | ---: |
| 전체 | 3,581건 |
| Training | 3,177건 |
| Validation | 404건 |
| 고유 `case_id` | 3,581개 |
| 임베딩 | BGE-M3, 1,024차원 |

Windows에서는 PyPI CPU Torch 대신 CUDA 12.6 wheel을 사용하도록 `pyproject.toml`과 `uv.lock`을
갱신했다. 실제 RTX 4070 Laptop GPU와 BGE-M3 `cuda:0` 실행을 확인했다.

## 5. 2026-09-20 최종 DB 기준본

프로젝트 로컬 파일:

- `data/skincare_reference_2026-09-20_v2.dump`
- `data/skincare_reference_2026-09-20_v2.dump.sha256`
- SHA-256: `5ecd670ee1e85553008abb5d7c43da0700a3149089eeb4c061948361271a5d54`

두 파일은 `.gitignore` 대상이다. 별도 빈 DB 복원과 직접 SQL 검증을 통과했다.

| 항목 | v2 기준본 |
| --- | ---: |
| Alembic | `2063ce3feae3` |
| Product | 2,262건 |
| ProductIngredient | 84,390건 |
| confirmed 연결 | 78,280건 / 상품 2,180개 |
| IngredientMaster | 21,974건 |
| IngredientKnowledgeFact | 2,411건 |
| EvidenceDocument | 14건 |
| EvidenceChunk | 8,291건(MFDS 8,288 + PubMed 3) |
| EvidenceChunkIngredient | 8,291건 |
| Evidence embedding | BGE-M3 1,024차원, NULL 0건 |
| Claim | document 1건 / chunk 5건 smoke |
| `rag_chunk` | 0건 |
| NIA Case | 미포함 |

기존 `skincare_latest`는 NIA 3,581건이 있지만 Evidence는 PubMed 3건뿐이고, 새 v2는 Evidence
8,291건이 있지만 NIA가 없다. 두 기준을 합치기 위해 v2를 새 DB에 복원하고 기존 NIA 행을 벡터와
함께 이전했다. 기존 DB는 삭제하거나 덮어쓰지 않았다.

## 6. Migration 통합 상태

현재 계보:

```text
3165318c750d
├─ 2063ce3feae3  # main Chat schema
└─ a7d3c91e5f42  # NIA Case schema
```

NIA migration의 부모를 main migration으로 사후 변경하지 않는다. 기존 로컬 DB에는 NIA head가
이미 적용돼 있어 부모를 바꾸면 Chat migration까지 적용된 것으로 잘못 해석할 수 있기 때문이다.
두 revision을 부모로 갖는 schema 변경 없는 merge revision `9f4c2a7d8e61`을 추가했다.

최신 `origin/main` 병합에서 발생한 다음 두 충돌은 양쪽 의도를 보존해 해결했다.

- `docs/erd/app.md`: main의 Evidence/Chat/Product taxonomy/v2 상태와 NIA Case 설계를 모두 보존
- `tests/unit/test_claim_storage_schema.py`: 특정 head 고정은 제거하고 NIA·Chat 양쪽이 최종
  merge head의 조상인지 검사

충돌 해결 후 목표:

```text
2063ce3feae3 ─┐
              ├─ 9f4c2a7d8e61  # 최종 단일 head
a7d3c91e5f42 ─┘
```

병합 커밋은 `4f85032`이며 `alembic heads` 결과는 `9f4c2a7d8e61 (head)` 한 건이다.
관련 Claim/NIA/Chat 계보와 MFDS embedding/Product taxonomy 단위 테스트 58개 및 Ruff 검사를
통과했다.

## 7. 새 통합 DB 구성 결과

통합 DB 이름은 `skincare_integrated_20260920`이다. 기존 `skincare_latest`는 덮어쓰거나 삭제하지
않았다.

1. Git 충돌을 양쪽 내용 보존 방식으로 해결한다.
2. Alembic merge revision을 추가하고 `alembic heads`가 1개인지 확인한다.
3. v2 dump를 새 빈 DB에 복원한다.
4. `alembic upgrade head`로 NIA Case 테이블과 merge revision을 적용한다.
5. 기존 `skincare_latest.nia_case_document` 3,581건을 벡터 포함 그대로 새 DB에 복사한다.
6. Product, Evidence, NIA, Chat schema, migration head를 검증한다.
7. 검증을 통과한 뒤 로컬 `config.yaml`의 DB명만 새 DB로 전환한다.

실제 검증 결과:

| 검증 | 결과 |
| --- | ---: |
| Product | 2,262 |
| EvidenceChunk | 8,291 |
| Evidence embedding NULL | 0 |
| NIA Case | 3,581 |
| NIA Training / Validation | 3,177 / 404 |
| NIA embedding NULL / 중복 자연키 | 0 / 0 |
| Claim | document 1 / chunk 5 |
| Chat 테이블 | 3개 존재 |
| Alembic revision | `9f4c2a7d8e61` |

로컬 `config.yaml`도 이 DB를 가리키도록 전환했다. 설정 파일은 Git 추적 대상이 아니며, 공유
sample 설정의 기본 DB명은 변경하지 않았다.

## 8. Evidence 검색 수정과 검수 상태의 남은 문제

통합 DB smoke에서 성분 연결 3건이 존재하는데도 벡터 검색이 0건을 반환하는 문제가 발견됐다.
원인은 HNSW 근사 검색이 전체 8,291건에서 소수 후보를 먼저 고른 뒤 성분 필터를 적용해, 희소한
성분 Evidence가 후보에서 탈락하는 실행 계획이었다.

`EvidenceSearchRepository`는 다음처럼 수정했다.

- 성분 미지정 검색은 기존 HNSW 검색을 유지한다.
- 성분 지정 검색은 연결된 청크를 materialized 후보 집합으로 먼저 제한한다.
- 제한된 후보 안에서 cosine 거리를 정확히 정렬한다.
- vector와 text 검색 모두 성분 지정/미지정 SQL을 명시적으로 분리한다.

수정 후 나이아신아마이드 Evidence 3건이 정상 조회된다.

새 Evidence 데이터와 임베딩 자체는 정상이다. 그러나 현재 Backend 어댑터는
`document_status == "verified"`만 `EvidenceReviewStatus.VERIFIED`로 변환한다.

- DB 스키마의 `document_status` 허용값에는 `verified`가 없다.
- MFDS/PubMed의 `document_status`는 실제로 `NULL`이다.
- 따라서 새 v2를 연결해도 현재 코드에서는 `검수완료 0건`으로 표시될 수 있다.

이는 dump 문제가 아니라 Backend→Agent 검수 정책 문제다. `evidence_level`을 검수 완료와 동일시하지
않으며, MFDS/PubMed/CIR별 승격 규칙을 계약으로 합의한 뒤 어댑터와 회귀 테스트를 함께 수정한다.
합의 전에는 Agent의 검수 게이트를 임의로 완화하지 않는다.

## 9. P3 구현 계획

> 이 절의 Case-scoped offline Claim 검색안은 2026-09-21 결정으로 대체됐다. 최신 계획은
> `2026-09-21_0219_RUNTIME_CASE_CLAIM_EXTRACTION_PLAN.md`, 최신 계약은
> `docs/contracts/backend-to-agent.md` 10절을 따른다. 아래 내용은 결정 이력으로만 보존한다.

### Agent

- `CaseSearchRequest`, `CaseSearchHit`, `CaseSearchResult`, `CaseBundle` 추가
- `CaseRetriever`, `CaseReranker` 포트 추가
- LangGraph에 `SEARCH_CASES`, `RERANK_CASES` 노드 추가
- 피부 고민형은 Case 경로, 명시 성분형은 기존 Evidence 직행 경로 유지
- NIA `metadata.evidence_sources`를 Citation DTO에 넣지 않음

### Backend

- `nia_case_document`의 training/validation 3,581건 전체에서 검색
- `nia_case_text/v1`, `BAAI/bge-m3`는 정확히 필터링하고 split은 provenance로 반환
- cosine 후보 20건 조회 후 BGE reranker Top-3 반환
- Claim 검색에 선택적 `source_record_ids` 필터 추가
- `nia_case_document.case_id = claim_document.source_record_id`로 논리 연결

### Fallback

- Case 오류/결과 없음: 오류 상태를 남기고 기존 제한 없는 Claim 검색
- Case는 있으나 연결 Claim 없음: 기존 Claim 검색 fallback
- Claim은 있으나 Evidence 없음/미검수: Claim-only 상품 유지
- Case 본문만 보고 런타임 LLM이 성분이나 Claim을 새로 만들지 않음

### 필수 테스트

1. 피부 고민 → Case Top-3 → 연결 Claim
2. 명시 성분 질의의 Case 생략
3. Training/Validation 전체 검색 및 split provenance 보존
4. Case 실패·결과 없음·연결 Claim 없음 fallback
5. Evidence가 없어도 Claim-only 상품 유지
6. NIA `evidence_sources` Citation 차단
7. 여러 성분에서 나온 동일 상품 중복 제거
8. 실제 통합 DB smoke

Claim은 현재 smoke 수준이므로 Case 검색 품질과 Case→Claim coverage를 분리해 보고한다. P3 완료를
3,581건 전체 상품 추천 완료로 표현하지 않는다.

## 10. 현재 체크포인트와 다음 순서

완료:

- [x] NIA 원본 구조 및 9,000건 확인
- [x] 10~39세 3,581건 export
- [x] `nia_case_document` ERD·모델·migration
- [x] BGE-M3 GPU 임베딩 및 3,581건 적재
- [x] v2 dump SHA·빈 DB 복원·행 수·무결성 검증
- [x] v2 dump를 프로젝트 `data/`에 배치하고 Git 제외 확인
- [x] P1/P2 변경을 기능 단위 로컬 커밋으로 보존
- [x] 최신 main 병합 시작 및 충돌 파일 확인
- [x] ERD·migration 테스트 충돌 해결
- [x] Alembic merge revision 작성
- [x] migration 관련 테스트 58개 및 Ruff 검사
- [x] 새 통합 DB 생성 및 v2 복원
- [x] NIA 3,581건 데이터 이전
- [x] 통합 DB 검증 후 로컬 `config.yaml` 전환
- [x] 성분 지정 Evidence HNSW 후필터 누락 수정
- [x] 실제 BGE-M3 2-Layer RAG smoke
- [x] Agent·단위 테스트 387개

다음:

- [ ] Evidence 검수 상태 정책 합의·수정
- [ ] P3 Case 검색·런타임 Claim 추출·LangGraph 연결
- [ ] 런타임 방식 골든 셋·비용·지연 평가
- [ ] 필요할 때만 offline Claim annotation 재검토

최종 smoke 결과:

| 항목 | 결과 |
| --- | ---: |
| Claim | 5건 |
| 나이아신아마이드 Evidence | 3건 |
| `UNREVIEWED` Evidence | 3건 |
| Claim-only 성분 | 5개 |
| 상품 연결 Claim-only 성분 | 3개 |
| 중복 제거 상품 sample | 10개 |

검증 명령과 결과:

```powershell
uv run pytest tests/db/test_two_layer_rag_dump.py -m integration -q
# 2 passed

uv run pytest tests/unit tests/agent -q
# 387 passed

uv run python -m tests.agent.two_layer_rag_dump_smoke
# 실제 BAAI/bge-m3 및 skincare_integrated_20260920 사용, 정상 종료
```

## 11. 문서 확인 우선순위

1. 이 문서: 현재 작업 상태와 실행 순서
2. `docs/agent/README.md`: Agent 코드 진입점과 책임
3. `docs/contracts/backend-to-agent.md`: 실제 Agent 포트 계약
4. `docs/contracts/data-to-agent.md`: NIA 산출물 계약
5. `docs/contracts/data-to-backend.md`: NIA 적재 계약
6. `docs/agent/TWO_LAYER_RAG_FOLLOWUP_PLAN.md`: 완료된 2-Layer 구현 상세 이력
7. `docs/agent/AGENT_INTEGRATION_REVIEW.md`: 2026-09-11 기준의 역사적 연결 검토

## 12. 문서 정리 기록

다음 문서의 유효한 정책과 결과는 이 합본으로 이관하고 원본을 삭제했다.

- `docs/agent/2026-09-17_1751_INTENT_ROUTING_UPDATE.md`
- `docs/agent/2026-09-20_0023_NIA_CASE_DOCUMENT_AGENT_HANDOFF.md`
- `docs/agent/ENTITY_RESOLUTION_AND_RAG_FALLBACK_PLAN.md`
- `docs/agent/RAG_YK/ARCHITECTURE_REVIEW_AND_OPINION.md`

`TWO_LAYER_RAG_FOLLOWUP_PLAN.md`은 완료된 구현 이력 때문에 남겼고,
`AGENT_INTEGRATION_REVIEW.md`는 다른 파트 문서가 참조하므로 역사 문서로 보존했다. 초기 기획 문서는
삭제하지 않고 문서 상단에서 이 합본을 우선하도록 안내한다.

## 13. Case → Claim production 경로 구현 — 2026-09-21 01:30 KST

### 확인한 사실

- `skincare_reference_2026-09-20_v2.dump`의 Product/Evidence와 NIA Claim annotation은 서로
  다른 산출물이다.
- 과거 `1,497건`은 코드 주석에 남은 이전 실행 이력이며 현재 재사용 가능한 annotation JSONL이나
  DB 데이터가 아니다.
- 현재 production annotation 산출물 기준 완료 건수는 0건이다.
- 기존 통합 DB의 Claim document 1건/chunk 5건은 smoke fixture이며 전체 coverage가 아니다.

### 이번에 구현한 흐름

```text
AI Hub Q-CoT-A 원본
  → 10~39세 annotation corpus + provenance + manifest
  → Case Document 3,581건과 record ID 전수 대조
  → 안전한 offline LLM annotation
  → statement별 ingestion decision 재생성
  → Claim export JSONL + manifest
  → BGE-M3 1,024차원 임베딩
  → claim_document / claim_chunk / claim_chunk_ingredient 동기화
```

새 annotation corpus exporter의 실데이터 실행 결과:

| 항목 | 결과 |
| --- | ---: |
| 전체 원본 | 9,000건 |
| 10~39세 corpus | 3,581건 |
| Training / Validation | 3,177 / 404 |
| Case Document ID 누락 / 추가 | 0 / 0 |
| 기존 production annotation 완료 | 0건 |

`uv run python -m data.scripts.nia_production_annotation_run --dry-run`으로 위 상태를 검증했으며
OpenAI API는 호출하지 않았다.

### 안전장치

- 기본 명령만으로는 3,581건 전체 LLM 호출이 시작되지 않는다.
- `--dry-run`: 입력·manifest·기존 결과만 검증한다.
- `--limit N`: 미완료 record 중 앞의 N건만 처리한다.
- `--record-id <ID>`: 지정 record만 처리한다. 반복 지정 가능하다.
- `--approve-full-run`: 제한 없는 전체 실행에 반드시 필요하다.
- 성공한 annotation은 건별 append·flush·fsync하며, 재실행은 JSONL에 없는 ID만 처리한다.
- corpus/provenance/Case Document SHA-256 또는 ID 집합이 바뀌면 LLM 호출 전에 중단한다.

### Claim export·DB 적재 정책

- 모든 statement와 `blocked`/`human_review`/`ingestible_*` decision은 export JSONL에 보존한다.
- DB의 검색 대상 `claim_chunk`에는 `ingestible_structured`와
  `ingestible_free_text`만 동기화한다.
- `blocked`와 `human_review`는 검색 청크에서 제외하지만 원본 annotation과 export에는 남는다.
- `claim_document`는 annotation record 단위로 저장하므로 eligible statement가 0개인 Case도
  annotation provenance를 유지할 수 있다.
- Claim content는 statement type별 규칙으로 결정적으로 조립하며 런타임 LLM으로 다시 만들지 않는다.
- 임베딩은 Evidence·Case와 동일한 `BAAI/bge-m3`, 1,024차원을 사용한다.
- 기존 Claim 테이블을 사용하므로 모델·migration 변경은 없다.

### 실행 순서

1. corpus 재검증이 필요할 때만 다음을 실행한다.

   ```powershell
   uv run python -m data.scripts.nia_case_rag.annotation_corpus_exporter `
     --input-root "C:\Users\Admin\Documents\03.스킨케어 성분-효능 추천 데이터" `
     --overwrite
   ```

2. 비용 없는 사전 점검:

   ```powershell
   uv run python -m data.scripts.nia_production_annotation_run --dry-run
   ```

3. 별도 승인 후 5건 smoke annotation:

   ```powershell
   uv run python -m data.scripts.nia_production_annotation_run --limit 5
   ```

4. 성공한 annotation을 Claim export로 변환:

   ```powershell
   uv run python -m data.scripts.nia_case_rag.claim_exporter
   ```

5. Claim을 BGE-M3로 임베딩하고 DB에 적재:

   ```powershell
   uv run python -m backend.services.claim_ingestion_service
   ```

6. 5건 결과와 비용·품질을 확인한 뒤에만 전체 annotation을 승인한다.

   ```powershell
   uv run python -m data.scripts.nia_production_annotation_run --approve-full-run
   ```

### 검증 결과와 다음 체크포인트

```powershell
uv run pytest tests/unit/test_nia_annotation_corpus_exporter.py `
  tests/unit/test_nia_production_annotation_run.py `
  tests/unit/test_nia_claim_exporter.py `
  tests/unit/test_claim_ingestion_service.py `
  tests/unit/test_nia_case_ingestion_service.py `
  tests/unit/test_claim_storage_schema.py -q
# 39 passed
```

- [x] 원본 corpus·provenance exporter
- [x] Case Document 3,581건 ID 전수 대조
- [x] annotation dry-run·limit·record-id·전체 승인 안전장치
- [x] annotation → Claim 결정적 변환기
- [x] Claim BGE-M3 적재 service/repository
- [x] 관련 단위 테스트 39개와 Ruff 검사
- [x] 전체 unit 274개 및 Agent 127개 회귀 테스트
- [ ] OpenAI 5건 smoke annotation — 비용 발생 전 별도 승인 필요
- [ ] 5건 Claim export·DB 적재·검색 smoke
- [ ] 전체 3,581건 annotation — 5건 결과 확인 후 별도 승인 필요
- [ ] P3 Case 검색 및 LangGraph 연결

## 14. P3 런타임 Claim 추출 방식으로 전환 — 2026-09-21 02:19 KST

### 결정

피부 고민형 P3의 기본 흐름을 Case-scoped Claim 벡터 검색에서 다음 구조로 변경한다.

```text
사용자 질문
  → NIA Case 벡터 검색
  → BGE reranker Top-3
  → 런타임 LLM exact-quote Claim 추출
  → 룰 기반 Claim 검증
  → Ingredient Resolution
  → Evidence/Product
```

실제 Case 문서 길이는 평균 약 1,859자이며 중앙값 Top-3 합계가 약 5,547자여서, 선택된 세 사례를
구조화 추출 모델에 전달할 수 있는 규모임을 확인했다.

### LLM과 규칙의 경계

- LLM은 Top-3 원문에서 관련 성분 raw name과 exact quote만 선택한다.
- LLM은 ingredient ID, Evidence 상태, Citation, 상품 추천 가능 여부를 결정하지 않는다.
- 코드가 Case ID, quote 포함 여부, 성분명 포함 여부, 단일/조합 형태와 중복을 검증한다.
- 표준 성분 ID는 기존 Ingredient Repository가 조회한다.
- 검증·매칭된 성분만 Evidence/Product 단계로 넘긴다.
- Evidence 없음/미검수 상태에서도 기존 Claim-only 상품 정책은 유지한다.

### 기존 offline 경로

13절에서 구현한 annotation corpus, production runner, Claim export, BGE-M3 적재 코드는 삭제하지
않는다. 다만 현재 P3 완료 조건에서 5건/3,581건 production annotation을 실행하지 않으며,
production 완료 건수는 계속 0건이다. 런타임 방식의 비용·지연·재현성이 문제가 되면 후속 비교
평가에 재사용한다.

### 다음 구현 기준

- 최신 계획:
  `docs/agent/RAG_YK/2026-09-21_0219_RUNTIME_CASE_CLAIM_EXTRACTION_PLAN.md`
- 최신 경계 계약: `docs/contracts/backend-to-agent.md` 10절
- 기존 P3 Case-scoped Claim RAG 계획은 새 계획으로 교체했다.

## 15. P3 Case 기반 LangGraph 구현 결과 — 2026-09-21 10:20 KST

### 완료 흐름

```text
피부 고민 질의
  → BGE-M3 Case 검색 20건
  → 공유 BGE reranker Top-3
  → 런타임 LLM exact-quote Claim 추출
  → 룰 기반 Case ID·quote·성분명·중복 검증
  → Ingredient Resolution
  → Claim별 Evidence 검증
  → Evidence supported / Claim-only 성분 분류
  → confirmed 상품 검색·중복 병합
```

`RagRoute.CLAIM_THEN_EVIDENCE` 문자열은 기존 호출 호환 때문에 유지했다. 다만 운영 기본 그래프는
더 이상 `search_claims`로 가지 않고 `search_cases`에서 시작한다. offline `ClaimRetriever`는
명시적으로 주입한 비교 테스트에서만 과거 경로를 사용한다.

### 구현 파일

- Agent 계약: `agent/rag/case_schemas.py`, `agent/rag/case_claim_schemas.py`,
  `agent/rag/ports.py`
- Case 검색: `backend/repositories/nia_case_document_repository.py`,
  `backend/services/two_layer_rag_adapters.py`
- 런타임 추출·검증: `agent/rag/case_claim_extractor.py`,
  `agent/rag/case_claim_validator.py`
- Evidence anchor: `agent/rag/case_claim_anchor_adapter.py`
- LangGraph: `agent/rag_workflow.py`, `agent/graph.py`, `agent/schemas.py`,
  `agent/rag_response.py`
- 공유 reranker: `agent/rag/retrieval/cross_encoder.py`

### 확인 결과

- Evidence 검색 결과가 없어도 유효 Claim 성분은 `CLAIM_ONLY`로 남아 상품 후보에 포함된다.
- exact quote가 원문과 일치하지 않으면 Ingredient/Evidence/Product 호출 전에 제외된다.
- 일부만 매칭된 조합 Claim은 단일 성분 Evidence로 축소되지 않는다.
- 명시 성분 질의는 Case 경로를 호출하지 않는다.
- 실제 PostgreSQL에서 NIA Case 후보 20건 조회와 DTO 변환이 통과했다.
- 전체 기본 테스트 결과: `446 passed, 3 deselected`.

실제 OpenAI E2E는 Top-3 NIA 원문 외부 전송 승인이 없어 실행하지 않았다. 명시 승인 후
`tests.agent.interactive_two_layer_rag_cli`로 확인한다. 남은 품질 작업은 골든 셋, LLM 오류·reranker
fallback, ambiguous/unresolved 및 다중 Case provenance 회귀 테스트다.
