# 백엔드 (FastAPI · 업무 로직)

## Agent 통합

- `agent_configuration.py`: `config.yaml`의 OpenAI·로컬 모델·검색 설정을 Agent Pydantic
  설정으로 변환한다. 구형 `rag_chunk` 경로는 1,536차원을, 2-Layer Claim/Evidence 경로는
  BGE-M3 1,024차원과 active `annotation_version`을 각각 검증한다.
- `rag_search_backend.py`: repository의 pgvector/BM25 결과를 현재 Agent 검색 DTO로 변환한다.
- `rag_ingestion_service.py`: DB 트랜잭션을 유지하면서 설정에서 선택한 비동기 임베딩 파이프라인을
  호출한다.

구형 `RagQueryService`와 동기식 `OpenAiEmbedder`는 사용하지 않는다. 현재 운영 임베더는
비동기 `OpenAiTextEmbedder`이며 사용자 질의의 최종 진입점은 Agent의
`ChatService.handle_turn`이다. 히스토리·상품·성분·루틴·체크포인터 운영 구현은 `ChatAgentAssembler`
(`backend/services/agent_assembly.py`)가 `backend/main.py` lifespan에서 연결한다(2026-09-22, #62).
조립 위치·실패 정책·실행 제한의 근거는 [Backend → Agent 호출 계약](../contracts/backend-to-agent.md)
2절 "운영 조립 구현 현황"을 따른다.

## 2-Layer RAG 최신 dump 읽기 연동 (2026-09-17)

> 상태: **dump 복원·계약·읽기 전용 smoke 검증 완료**
>
> 기준 dump: `data/skincare_latest_2026-09-17.dump`

2026-09-17에 기존 `app` DB를 덮어쓰지 않고 Docker PostgreSQL의 `skincare_latest` DB로
복원했으며 `pg_restore --exit-on-error`가 정상 완료됐다. 구현 입력·출력과 저장값 매핑은
[`backend-to-agent.md`](../contracts/backend-to-agent.md)의 9절에 누적한다.

### 왜 Backend 수정이 필요한가

이번 Backend 수정은 Backend의 기존 API나 업무 로직을 크게 바꾸기 위한 것이 아니다. 최신
dump에 저장된 Claim/Evidence를 기존 Agent 포트 계약으로 변환해 주입하기 위한 연결 작업이다.

- Agent는 LangGraph 흐름, Claim별 Evidence 판정, 추천 근거 등급과 응답 조립을 담당한다.
- Backend는 DB 세션, SQLAlchemy 조회, 트랜잭션과 ORM/DB 행의 Agent DTO 변환을 담당한다.
- 따라서 `claim_chunk`, `evidence_chunk`를 직접 읽는 구현을 `agent/`에 넣지 않는다.
- Backend는 조회 결과만 `ClaimSearchResult`, `HybridSearchResult` 등 Agent 소유 Pydantic DTO로
  변환하고, Claim 지원 여부나 상품 추천 여부를 결정하지 않는다.

즉 수정 원인은 **Agent 기능 자체의 재구현**이 아니라, **최신 dump와 Agent 계약 사이에 실제
DB 어댑터가 아직 없기 때문**이다.

### 확인된 dump 계약

별도 검증 DB 복원과 읽기 전용 SQL smoke test에서 다음을 확인했다.

| 항목 | 확인 결과 |
| --- | --- |
| Claim | `claim_document` 1건, `claim_chunk` 5건, 성분 연결 5건 |
| Evidence | `evidence_document` 3건, `evidence_chunk` 3건, 성분 연결 3건 |
| 임베딩 | Claim/Evidence 모두 `BAAI/bge-m3`, 1,024차원 |
| Product | 2,262건, 전성분 token 84,390건 |
| 확정 상품 매핑 | `match_acceptance=confirmed` 78,280건 |
| 연결 시나리오 | 나이아신아마이드 Claim 1건 → Evidence 3건 → confirmed 상품 994건 |
| Claim-only 시나리오 | Evidence 없이 confirmed 상품으로 연결되는 Claim 성분 존재 |
| 벡터 연산 | pgvector cosine distance 조회 정상 |

`claim_chunk.decision`의 DB 설명은 `ingestible_*`를 운영 검색 대상으로 정의하고,
`claim_document.production_ready`는 런타임 필수 필터로 강제하지 않는다고 명시한다. 따라서 현재
5개 Claim은 검색 후보이며 `production_ready=false`여도 검색에서 제외하지 않는다. Agent로
전달하는 최소 `ClaimHit`에는 이 저장 전용 필드를 복제하지 않는다.

기존 이 문서의 `rag_chunk` 1,536차원 설명은 구형 단일 RAG 경로에 대한 것이다. 최신 2-Layer
경로는 별도 `claim_chunk`, `evidence_chunk`의 BGE-M3 1,024차원 벡터를 사용한다. 두 경로를
하나의 검색기로 섞지 않는다.

### 구현 범위

마이그레이션과 ORM 모델 동기화 전에도, 복원된 dump를 기준으로 읽기 전용 통합 smoke를 만들 수
있다. 이 경우 변경 범위는 다음으로 제한한다.

| 계층 | 구현 파일 | 책임 |
| --- | --- | --- |
| `backend/repositories/` | `claim_search_repository.py` | `ingestible_*` Claim, 성분 연결, vector 조회 |
| `backend/repositories/` | `evidence_search_repository.py` | 성분별 Evidence vector/text 조회와 Citation 메타데이터 보존 |
| `backend/repositories/` | `agent_ingredient_repository.py` | 표준명·정규화명·구명칭 정확 일치 조회 |
| `backend/repositories/` | `agent_product_repository.py` | `confirmed` 성분 연결만 사용한 상품 조회·중복 제거 |
| `backend/services/` | `two_layer_rag_adapters.py` | DB 결과를 기존 Agent 포트 DTO로 변환 |
| `tests/agent/` | `two_layer_rag_dump_smoke.py` | 실제 BGE-M3 기반 결정적 dump smoke 실행기 |
| `tests/db/` | `test_two_layer_rag_dump.py` | Claim → 미검수 Evidence → Claim-only Product 통합 회귀 검증 |

SQL은 Repository에만 두며, Agent가 `AsyncSession`, SQLAlchemy 모델 또는 Backend 구현을 import하지
않게 한다. 공개 Agent 포트와 LangGraph 흐름은 최대한 변경하지 않는다.

### 이번 최소 범위에서 하지 않는 것

- FastAPI 채팅 API 신규 구현
- 인증·세션·운영 체크포인터 연결
- 기존 Backend API와 서비스 전반 리팩터링
- dump 스키마 변경 또는 데이터 재적재
- `migrations/`, `models/` 변경
- 기존 `rag_chunk` 삭제
- Claim/Evidence의 자동 재임베딩

이 범위는 dump를 이미 복원한 DB를 읽는 통합 검증용이다. 저장소만으로 새 DB를 재현하거나 이후
스키마 변경을 적용하려면 별도로 모델·ERD·migration 계보를 동기화해야 한다.

### 확정 정책과 후속 항목

1. **Evidence 검수 상태**
   - 현재 PubMed 3건의 `evidence_document.document_status`가 `NULL`이다.
   - `UNREVIEWED`로 변환하며 Citation과 `SUPPORTED` 근거로 승격하지 않는다.
   - 연결 Claim은 `INSUFFICIENT`가 되지만 `CLAIM_ONLY` 상품 후보로 유지한다.
   - 검증 완료 자료로 사용할 의도라면 Data 파트에서 저장값 또는 명시적인 매핑 규칙을 제공해야 한다.
2. **Alembic revision**
   - dump의 revision은 `3165318c750d`, 현재 코드 head는 `d4c2a7e91b30`이다.
   - 현재 저장소는 `3165318c750d`를 알지 못하므로 dump 복원 후 `alembic upgrade`를 실행하지 않는다.
   - migration 동기화는 현재 읽기 전용 smoke와 분리한다.
3. **BGE-M3 설정**
   - dump 검색에는 `agent.embedding.provider: local`, `BAAI/bge-m3`를 사용해야 한다.
   - 기존 OpenAI 1,536차원 임계값 `0.45`를 BGE-M3 기준으로 확정하지 않는다.
4. **계약 문서**
   - `docs/contracts/backend-to-agent.md` 9절에 BGE-M3 2-Layer 조회 입력·출력·실패 상태를
     반영했다.

### 실제 BGE-M3 smoke 결과

다음 명령은 외부 LLM을 호출하지 않고 실제 `BAAI/bge-m3`로 Claim/Evidence 질의를 임베딩한 뒤
복원 DB와 Agent 판정 규칙을 연결한다.

```bash
uv run python -m tests.agent.two_layer_rag_dump_smoke
```

2026-09-17 실행 결과:

| 확인 항목 | 결과 |
| --- | ---: |
| 검색된 Claim | 5건 |
| 나이아신아마이드 Evidence | 3건 |
| `UNREVIEWED` Evidence | 3건 |
| `CLAIM_ONLY` 성분 | 5개 |
| confirmed 상품이 있는 Claim-only 성분 | 3개 |
| 중복 제거 후 상품 sample | 10개 |

따라서 `production_ready=false`는 Claim 검색을 막지 않는다. Evidence 검증을 통과하지 못해도
해당 성분은 `CLAIM_ONLY`로 남고, confirmed 상품 연결이 있으면 최종 상품 후보에 포함된다.

### 최소 완료 조건

- 기존 `app` DB를 덮어쓰지 않고 최신 dump를 별도 DB에 복원할 수 있다.
- 실제 Claim 검색 결과가 `ClaimSearchResult` 계약을 통과한다.
- 성분별 Evidence 검색 결과가 실제 Evidence ID와 Citation 메타데이터를 보존한다.
- 개별 Evidence를 복합 Claim 근거로 승격하지 않는다.
- Evidence가 없는 Claim 성분도 `CLAIM_ONLY` 상품 후보로 이어진다.
- Product 조회는 `confirmed` 매핑만 사용한다.
- Agent는 DB와 Backend를 직접 import하지 않는다.
- 읽기 전용 DB 통합 smoke와 기존 Agent 회귀 테스트가 모두 통과한다.

## NIA Case Document DB 적재 (2026-09-20)

Data exporter가 만든 JSONL과 manifest를 먼저 전체 검증한 뒤, 변경된 사례만
`BAAI/bge-m3` 1,024차원 벡터로 만들어 `nia_case_document`에 batch upsert한다.
Repository는 commit하지 않고 Service가 batch별 transaction을 확정하므로 중간 실패 후 재실행할 수 있다.

사용자가 실행할 순서:

```powershell
uv run alembic upgrade head
uv run python -m backend.services.nia_case_ingestion_service
```

기본 입력은 다음 두 파일이다.

- `data/processed/nia_case_documents_10s_30s.jsonl`
- `data/processed/nia_case_documents_10s_30s.manifest.json`

실행 전 `config.yaml`의 `agent.embedding.provider`는 `local`, `model`은 `BAAI/bge-m3`여야 한다.
같은 `(case_id, text_version, embedding_model)`의 `content_hash`가 같으면 재임베딩하지 않는다.
이 단계는 Case 검색 저장소만 만들며 Claim annotation이나 LangGraph 연결은 실행하지 않는다.

## 관련 문서

- [Agent ↔ Backend 성분 식별 정규화 계획](../agent/RAG_YK/2026-09-22_INGREDIENT_ALIAS_RESOLUTION_PLAN.md)
- [Backend → Agent 호출 계약](../contracts/backend-to-agent.md)
- [DB 기반 Product Taxonomy 연동 상태](../agent/RAG_YK/2026-09-21_1832_DB_PRODUCT_TAXONOMY_INTEGRATION_STATUS.md)
- [Data → Backend NIA Case 적재 계약](../contracts/data-to-backend.md)
- [Backend → Data 채팅 히스토리 테이블 생성 요청](../contracts/backend-to-data.md)
- [Agent 통합 검토](../agent/AGENT_INTEGRATION_REVIEW.md)
- [2-Layer RAG Agent 통합 작업계획 및 작업 일지](../agent/TWO_LAYER_RAG_FOLLOWUP_PLAN.md)
- [Claim → Evidence RAG 인터페이스 계약](../contracts/claim-evidence-rag-interface.md)
- [front → backend 계약](../contracts/front-to-backend.md): 홈 화면(`GET /home`, 초안),
  AI 채팅(미정), 회원가입 확장(성별·연령대·약관동의 — 확정 및 구현 완료.
  `models/user.py`, `backend/schemas/auth.py`)

## Evidence RAG `document_status` 매핑 보류 (2026-09-17)

`TwoLayerEvidenceSearchBackend`는 DB의 `evidence_document.document_status`를 Agent의
`EvidenceReviewStatus`로 바꾸는 경계다. 따라서 저장 상태 매핑이 Backend 어댑터에 있는 구조는
유지한다. 다만 현재 `_VERIFIED_STATUS = "verified"`는 확정된 저장 계약이 아니다.

실제 `skincare_latest` DB의 `ck_evidence_document_document_status`가 허용하는 값은 다음과 같다.

```text
final, amended_final, tentative, draft, rereview, unknown, NULL
```

`verified`는 허용값이 아니므로 현재 어댑터의 조건은 실제 DB에서 참이 될 수 없다. 이 코드는
2026-09-17 읽기 전용 smoke 구현 당시 `document_status=NULL → UNREVIEWED` 동작을 보수적으로
보장하기 위해 둔 임시 매핑이다. 당시 세 PubMed 행이 모두 `NULL`이어서 검수 완료 상태의 양방향
계약은 검증하지 못했다.

Evidence RAG 저장·검수 흐름을 구현하기 전까지는 다음 기준을 따른다.

- 현행 `NULL → UNREVIEWED` 동작을 유지한다.
- `peer_reviewed_study`를 사람 검수 완료 상태로 대신 사용하지 않는다.
- `final` 또는 `amended_final`을 임의로 `VERIFIED`에 연결하지 않는다.
- DB CHECK 제약조건을 우회해 `verified` 값을 직접 저장하지 않는다.

후속 구현에서는 Data 파트와 `final`/`amended_final`의 의미를 먼저 합의한다. 사람 검수 완료 의미가
맞으면 허용 상태 집합을 Enum으로 정의해 Backend 어댑터에서 `VERIFIED`로 변환한다. 문서 생명주기
상태일 뿐이라면 `review_status` 같은 별도 컬럼이 필요하며, 이 경우 ERD 문서 확인 후 모델과
마이그레이션을 작성한다. 어느 경우든 `docs/contracts/backend-to-agent.md`의 현재 `verified` 예시는
실제 저장 계약에 맞게 먼저 수정하고 통합 테스트를 추가한다.

## NIA Claim 적재 연결 (2026-09-21)

> 상태: **코드와 계약은 보존하되, 현재 P3 기본 경로에서는 실행 보류**

Data가 생성한 `nia_claim_documents_production.jsonl`과 manifest를 검증하고, 검색 가능한
`ingestible_structured`/`ingestible_free_text` statement만 BGE-M3 1,024차원으로 임베딩해
기존 Claim 테이블에 동기화한다.

2026-09-21 합의에 따라 피부 고민형 P3는 Case Top-3에서 Agent가 런타임 Claim을 추출한다.
따라서 아래 명령은 현재 P3 준비·실행 절차에 포함하지 않는다. offline Claim index를 후속
최적화로 다시 채택할 때 사용할 수 있도록 구현은 삭제하지 않는다.

```powershell
uv run python -m backend.services.claim_ingestion_service
```

- `claim_document`: annotation record 단위 provenance
- `claim_chunk`: 검색 가능한 statement만 저장
- `claim_chunk_ingredient`: matched 및 unresolved 성분 연결 보존
- batch commit/rollback은 Service, SQL은 Repository가 담당
- 기존 Claim 모델을 사용하므로 새 migration은 없다.

입력 계약과 실패 규칙은 [data-to-backend.md](../contracts/data-to-backend.md)의
`NIA Claim production 산출물 적재 계약` 절을 따른다.

## NIA Case 런타임 검색 연결 (2026-09-21 10:20 KST)

피부 고민형 Agent 기본 경로를 위해 기존 `nia_case_document`를 읽는
`BackendNiaCaseRetriever`를 연결했다. 새 모델·마이그레이션은 없다.

- Repository가 `text_version`과 `embedding_model`을 정확히 일치시켜 cosine 후보를 조회한다.
- BGE-M3 1,024차원이 아니면 DB 조회 전에 `UNSUPPORTED`로 반환한다.
- training/validation 3,581건 전체를 검색 대상으로 사용하고 `dataset_split`은 provenance로만
  Agent에 반환한다.
- NIA `evidence_sources`는 공식 Citation으로 오인되지 않도록 Agent Case DTO에서 제외한다.
- Backend는 Case Claim을 생성·검증하지 않으며, 이 책임은 Agent에 있다.
- Case 기본 경로에서는 offline Claim `annotation_version`이 없어도 운영 설정을 조립할 수 있다.

읽기 전용 실제 DB 통합 테스트에서 후보 20건, 중복 Case ID 0건, 본문·버전 DTO 변환을 확인했다.

## DB 기반 Product Taxonomy Agent 연동 (2026-09-21 18:34 KST)

> 상태: **DB 조회·변환 및 2-Layer CLI 주입 완료 / Backend API 운영 조립은 추가 연결 필요**

Backend는 `product` 테이블의 실제 `service_category`와 `product_type_normalized`를 집계해
Agent 소유 `ProductTaxonomy`로 변환한다.

```text
AgentProductReadRepository.list_taxonomy()
→ TwoLayerProductTaxonomyProvider.load()
→ ProductTaxonomy
```

현재 일반 2-Layer CLI와 Trace CLI는 시작 시 Provider를 호출하고 그 결과를 Agent에 명시적으로
주입한다. 따라서 두 CLI에서 실행되는 질문 해석과 상품 필터는 `FixtureProductTaxonomy`가 아니라
DB의 최신 분류값을 사용한다.

상품 검색에서 카테고리가 지정되면 `TwoLayerProductRepository`가 `ProductCategory.code`를
`AgentProductReadRepository`에 전달한다. 저장소는 `product.service_category` 일치 조건을
정렬과 `LIMIT`보다 먼저 SQL에 적용하므로, 앞선 다른 카테고리 상품 때문에 요청한 카테고리의
후보가 누락되지 않는다. 카테고리가 없으면 기존처럼 확정 성분 연결만으로 조회한다.

실행 배너에서는 다음 항목으로 확인할 수 있다.

```text
상품 taxonomy: product-taxonomy/db-v1:<digest>
```

`DevelopmentAgentFactory`의 fixture 기본값은 DB 없이 실행하는 단위 테스트와 개발 fallback을 위해
유지한다. CLI는 `product_taxonomy`를 직접 넘기므로 이 fallback을 사용하지 않는다.

실제 Backend API 운영 경로까지 완료하려면 애플리케이션 시작 또는 Agent 의존성 조립 시 다음
연결을 추가해야 한다.

```text
DB session factory
→ TwoLayerProductTaxonomyProvider.load()
→ ProductionAgentDependencies.product_taxonomy
→ ProductionAgentFactory.create()
```

Provider·DTO 계약을 새로 복제하지 않고 기존 구현을 재사용한다. Backend 운영 진입점이 확정되기
전까지는 CLI 연동 완료와 API 연동 완료를 구분해서 표시한다. 전체 구현 위치와 확인 기준은
[DB 기반 Product Taxonomy 연동 상태](../agent/RAG_YK/2026-09-21_1832_DB_PRODUCT_TAXONOMY_INTEGRATION_STATUS.md),
호출 계약은 [Backend → Agent 호출 계약](../contracts/backend-to-agent.md) 11절을 따른다.
