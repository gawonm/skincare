# 백엔드 (FastAPI · 업무 로직)

## Agent 통합

- `agent_configuration.py`: `config.yaml`의 OpenAI·로컬 모델·검색 설정을 Agent Pydantic
  설정으로 변환하고 선택한 임베딩 출력 차원이 현재 DB의 1536차원과 같은지 검증한다. OpenAI
  검색 임계값을 생략하면 기존 검증값 `0.45`를 사용한다.
- `rag_search_backend.py`: repository의 pgvector/BM25 결과를 현재 Agent 검색 DTO로 변환한다.
- `rag_ingestion_service.py`: DB 트랜잭션을 유지하면서 설정에서 선택한 비동기 임베딩 파이프라인을
  호출한다.

구형 `RagQueryService`와 동기식 `OpenAiEmbedder`는 사용하지 않는다. 현재 운영 임베더는
비동기 `OpenAiTextEmbedder`이며 사용자 질의의 최종 진입점은 Agent의
`ChatService.handle_turn`이다. 히스토리·상품·성분·루틴·체크포인터 운영 구현은 아직 연결해야
한다.

## 2-Layer RAG 최신 dump 연동 검토 (2026-09-17)

> 상태: **구현 전 검토안**
>
> 기준 dump: `data/skincare_latest_2026-09-17.dump`

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

기존 이 문서의 `rag_chunk` 1,536차원 설명은 구형 단일 RAG 경로에 대한 것이다. 최신 2-Layer
경로는 별도 `claim_chunk`, `evidence_chunk`의 BGE-M3 1,024차원 벡터를 사용한다. 두 경로를
하나의 검색기로 섞지 않는다.

### 최소 구현 범위

마이그레이션과 ORM 모델 동기화 전에도, 복원된 dump를 기준으로 읽기 전용 통합 smoke를 만들 수
있다. 이 경우 변경 범위는 다음으로 제한한다.

| 계층 | 변경 후보 | 책임 |
| --- | --- | --- |
| `backend/repositories/` | Claim 전용 Repository | 허용 Claim, 성분 연결, vector/BM25 조회 |
| `backend/repositories/` | Evidence 전용 Repository | 성분별 Evidence, 문서·Citation 메타데이터 조회 |
| `backend/repositories/` | 기존 Product 조회 보완 | `match_acceptance=confirmed`만 상품 후보로 반환 |
| `backend/services/` | `ClaimRetriever` 어댑터 | DB 결과를 `ClaimSearchResult`로 변환 |
| `backend/services/` | `HybridSearchBackend` 어댑터 | DB 결과를 `HybridSearchResult`로 변환 |
| `backend/services/` | dump smoke 실행 조립 | 실제 어댑터를 Agent에 주입하고 한 요청 실행 |
| `tests/` | DB 통합 smoke | Claim → Evidence → Product 및 Citation 연결 검증 |

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

### 구현 전에 확정할 항목

1. **Evidence 검수 상태**
   - 현재 PubMed 3건의 `evidence_document.document_status`가 `NULL`이다.
   - 안전한 기본값은 `UNREVIEWED`이며, 이 경우 Citation과 `SUPPORTED` 근거로 승격하지 않는다.
   - 검증 완료 자료로 사용할 의도라면 Data 파트에서 저장값 또는 명시적인 매핑 규칙을 제공해야 한다.
2. **Alembic revision**
   - dump의 revision은 `3165318c750d`, 현재 코드 head는 `d4c2a7e91b30`이다.
   - 현재 저장소는 `3165318c750d`를 알지 못하므로 dump 복원 후 `alembic upgrade`를 실행하지 않는다.
   - migration 동기화는 현재 읽기 전용 smoke와 분리한다.
3. **BGE-M3 설정**
   - dump 검색에는 `agent.embedding.provider: local`, `BAAI/bge-m3`를 사용해야 한다.
   - 기존 OpenAI 1,536차원 임계값 `0.45`를 BGE-M3 기준으로 확정하지 않는다.
4. **계약 문서 갱신**
   - 현재 `docs/contracts/backend-to-agent.md`의 기본 운영 경로는 구형 1,536차원 설명을 포함한다.
   - 구현 전 BGE-M3 2-Layer 조회 입력·출력·실패 상태를 해당 계약에 먼저 반영하고 합의한다.

### 최소 완료 조건

- 기존 `app` DB를 덮어쓰지 않고 최신 dump를 별도 DB에 복원할 수 있다.
- 실제 Claim 검색 결과가 `ClaimSearchResult` 계약을 통과한다.
- 성분별 Evidence 검색 결과가 실제 Evidence ID와 Citation 메타데이터를 보존한다.
- 개별 Evidence를 복합 Claim 근거로 승격하지 않는다.
- Evidence가 없는 Claim 성분도 `CLAIM_ONLY` 상품 후보로 이어진다.
- Product 조회는 `confirmed` 매핑만 사용한다.
- Agent는 DB와 Backend를 직접 import하지 않는다.
- 읽기 전용 DB 통합 smoke와 기존 Agent 회귀 테스트가 모두 통과한다.

## 관련 문서

- [Backend → Agent 호출 계약](../contracts/backend-to-agent.md)
- [Agent 통합 검토](../agent/AGENT_INTEGRATION_REVIEW.md)
- [2-Layer RAG Agent 리팩터링 기준](../agent/TWO_LAYER_RAG_REFACTOR_PLAN.md)
- [2-Layer RAG main 대비 변경점](../agent/TWO_LAYER_RAG_MAIN_DIFF.md)
- [front → backend 계약](../contracts/front-to-backend.md): AI 채팅(미정), 회원가입 확장
  (성별·연령대·약관동의 — 확정 및 구현 완료. `models/user.py`, `backend/schemas/auth.py`)
