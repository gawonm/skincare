# Evidence `document_status` 계약 정합

> - generated_at: 2026-09-30
> - commit / branch: `ea915de` (origin/main) / `docs/data-runtime-quality-audits-v2`
> - DB: `skincare_reference_20260923_v5_2` (로컬 Docker, SELECT 전용) — Alembic `cdff29b164d8`
> - DB 이름과 핸드오프 기준 dump(`skincare_reference_2026-09-23_v5_2.dump`) 이름이 대응하지만, dump 자체와의 바이트 일치는 확인하지 않아 SHA256은 적지 않는다.
> - 핵심 행 수: `evidence_document` 128 (MFDS 11 / CIR 15 / PubMed 102), `evidence_chunk` 8,487
> - 수치 원본: [evidence_status_distribution.csv](evidence_status_distribution.csv)

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

## 옛 문서와 충돌하는 문장 (이번 배치에서 정정)

| 문서 | 옛 내용 | 조치 |
| --- | --- | --- |
| [docs/agent/README.md](../agent/README.md) "Evidence RAG 검수 상태 계약 보류" | 계약 미확정, Data와 합의 필요, PubMed 3건 등 | §13.1 확정으로 정정 |
| [docs/backend/README.md](../backend/README.md) "확정 정책과 후속 항목" 1항, "`document_status` 매핑 보류" | `NULL → UNREVIEWED` 유지 | §13.1 확정으로 정정 |
| [PROJECT_OVERVIEW_FOR_PRESENTATION.md](../PROJECT_OVERVIEW_FOR_PRESENTATION.md) | `UNREVIEWED` Evidence 보수 정책 | §13.1 기준으로 정정 |
| [backend-to-agent.md](../contracts/backend-to-agent.md) §9.1 | "저장값만 신뢰, NULL을 검증 완료로 승격하지 않는다" | §13.1 참조 한 줄 추가 |

## 정정하지 않은 역사 문서 (기록용)

작성 당시 상황을 남기는 문서라 수정하지 않는다. 읽을 때 §13.1이 우선한다.

- [2026-09-23_AGENT_CLAIM_ROUTINE_EVIDENCE_HANDOFF.md](../coordination/2026-09-23_AGENT_CLAIM_ROUTINE_EVIDENCE_HANDOFF.md)
- [TWO_LAYER_RAG_FOLLOWUP_PLAN.md](../agent/TWO_LAYER_RAG_FOLLOWUP_PLAN.md)
- [AGENT_INTEGRATION_REVIEW.md](../agent/AGENT_INTEGRATION_REVIEW.md)
- [agent.md](../agent.md)

## FOLLOW-UP — runtime 코드 잔여물 (수정하지 않음)

문서만 정정하고 코드는 §13.1과 아직 어긋난다. 별도 agent/backend 작업이 필요하다.

- `backend/services/two_layer_rag_adapters.py:303,415-418`: `_VERIFIED_STATUS = "verified"` 매핑은 DB 제약상 성립할 수 없다.
  결과적으로 모든 Evidence가 `UNREVIEWED`가 된다.
- `agent/claim_verification.py:167`, `agent/rag/routine_planner.py:320`은 `review_status is VERIFIED`를 게이트로 쓴다.
- `agent/nodes.py:879,959`, `agent/rag/schemas.py:769`, `agent/rag_response.py:426`에 "미검수" 문구가 남아 있다.
