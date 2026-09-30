# Evidence `document_status` 계약 정합

> - generated_at: 2026-09-30
> - commit / branch: `ea915de` (origin/main) / `docs/data-runtime-quality-audits-v2`
> - DB: `skincare_reference_20260923_v5_2` (로컬 Docker, SELECT 전용) — Alembic `cdff29b164d8`
> - DB 이름과 핸드오프 기준 dump(`skincare_reference_2026-09-23_v5_2.dump`) 이름이 대응하지만, dump 자체와의 바이트 일치는 확인하지 않아 SHA256은 적지 않는다.
> - 핵심 행 수: `evidence_document` 128 (MFDS 11 / CIR 15 / PubMed 102), `evidence_chunk` 8,487
> - 수치 원본: `evidence_status_distribution.csv` (로컬 생성물, git 미추적)

## 기준 계약

[backend-to-agent.md §13.1](../contracts/backend-to-agent.md) (2026-09-22 사용자 확인)이 현행 계약이다.

- `document_status`는 **문서 생명주기 메타데이터**이고, 답변 가능 여부를 정하는 검수 상태가 아니다.
- Agent는 `document_status`에서 파생한 검수 상태로 답변을 막거나 경고하지 않는다.
- 스키마·마이그레이션은 바꾸지 않는다. 별도 `review_status` 컬럼은 만들지 않는다.

## 실제 데이터

| source_type | document_status | evidence_level | 문서 | chunk | 성분 연결 없는 chunk |
| --- | --- | --- | ---: | ---: | ---: |
| cir | final | expert_reviewed | 12 | 82 | 1 |
| cir | amended_final | expert_reviewed | 2 | 13 | 2 |
| cir | rereview | expert_reviewed | 1 | 2 | 0 |
| mfds | NULL | official_regulatory | 11 | 8,288 | 0 |
| pubmed_abstract | NULL | peer_reviewed_study | 102 | 102 | 0 |
| **합계** | | | **128** | **8,487** | **3** |

- CHECK 제약 허용값: `final, amended_final, tentative, draft, rereview, unknown, NULL`. `verified`는 없다.
- MFDS·PubMed 113문서는 전부 NULL이다. 생명주기 값은 CIR에만 있다. 따라서 NULL은 "미검수"가 아니라
  "해당 출처는 생명주기 개념이 없음"으로 읽는 것이 §13.1과 일치한다.
- 성분 연결이 없는 chunk 3건은 모두 CIR이다.

## External ownership follow-up — 옛 문서와 §13.1의 의미 차이

아래 문서는 Data 파트 소유가 아니므로 이번 Data 브랜치에서 수정하지 않았다. 각 담당 파트가 정정할지 판단한다.

| 문서 (소유) | 현재 내용 | §13.1과의 차이 |
| --- | --- | --- |
| [docs/agent/README.md](../agent/README.md) "Evidence RAG 검수 상태 계약 보류" (Agent) | 계약 미확정으로 서술, Data와 합의 필요, PubMed 3건 기준 | §13.1은 2026-09-22 확정. `document_status`는 생명주기 메타데이터이며 답변 차단 기준이 아니다. 별도 `review_status` 컬럼도 만들지 않는다 |
| [docs/backend/README.md](../backend/README.md) "확정 정책과 후속 항목" 1항, "`document_status` 매핑 보류" (Backend) | `NULL → UNREVIEWED` 유지, `final`/`amended_final` 의미를 Data와 합의해야 한다고 서술 | 위와 같음. 합의 대상이 아니라 확정된 계약이다 |
| [PROJECT_OVERVIEW_FOR_PRESENTATION.md](../PROJECT_OVERVIEW_FOR_PRESENTATION.md) 190행, 248행 (공용) | `UNREVIEWED` Evidence를 Citation·`SUPPORTED`로 승격하지 않는 정책, "`VERIFIED` 매핑 계약 확정"을 남은 과제로 표기 | §13.1과 다르다 |
| [backend-to-agent.md](../contracts/backend-to-agent.md) §9.1 (공용 계약) | "저장값만 신뢰, NULL을 검증 완료로 승격하지 않는다" | §13.1 참조가 없어 §13.1과 충돌해 읽힐 수 있다. 계약 변경은 양쪽 합의가 필요하다 |

## 정정하지 않은 역사 문서 (기록용)

작성 당시 상황을 남기는 문서라 수정 대상이 아니다. 읽을 때 §13.1이 우선한다.

- [2026-09-23_AGENT_CLAIM_ROUTINE_EVIDENCE_HANDOFF.md](../coordination/2026-09-23_AGENT_CLAIM_ROUTINE_EVIDENCE_HANDOFF.md)
- [TWO_LAYER_RAG_FOLLOWUP_PLAN.md](../agent/TWO_LAYER_RAG_FOLLOWUP_PLAN.md)
- [AGENT_INTEGRATION_REVIEW.md](../agent/AGENT_INTEGRATION_REVIEW.md)
- [agent.md](../agent.md)

## External ownership follow-up — runtime 코드 잔여물

코드는 §13.1과 아직 어긋난다. 별도 Agent/Backend 작업이 필요하며 이 브랜치에서는 수정하지 않았다.

- Backend: `backend/services/two_layer_rag_adapters.py:303,415-418`의 `_VERIFIED_STATUS = "verified"` 매핑은
  DB 제약상 성립할 수 없다. 결과적으로 모든 Evidence가 `UNREVIEWED`가 된다.
- Agent: `agent/claim_verification.py:167`, `agent/rag/routine_planner.py:320`은 `review_status is VERIFIED`를 게이트로 쓴다.
- Agent: `agent/nodes.py:879,959`, `agent/rag/schemas.py:769`, `agent/rag_response.py:426`에 "미검수" 문구가 남아 있다.
