# 2-Layer RAG Agent 후속 보완 작업계획

## 1. 문서 목적과 기준

이 문서는 현재 구현 중인 2-Layer RAG Agent에서 아래 두 항목을 보완하기 위한 실행계획이다.

1. 복합 성분 Claim이 개별 성분 Evidence만으로 `SUPPORTED`가 되는 경로 차단
2. 여러 성분 검색에서 같은 상품이 반환될 때의 중복 제거 동작 검증

정책의 최상위 기준은
[`TWO_LAYER_RAG_REFACTOR_PLAN.md`](TWO_LAYER_RAG_REFACTOR_PLAN.md)이다. 이 문서는 기존 정책을
대체하지 않고, 해당 문서의 P4·P5를 완료하기 위한 후속 계획과 작업 이력을 누적한다.

현재 상태는 `VERIFIED`다. 사용자 승인 후 계획의 P1~P5 구현과 검증을 완료했다.

## 2. 작업 범위

### 포함

- `agent/claim_verification.py`의 복합 Claim 판정 규칙 보강
- 필요한 경우 기존 `agent/rag/claim_schemas.py` DTO의 최소 보완
- 상품 후보 병합·중복 제거의 현행 동작 확인
- `tests/agent/test_claim_verification.py`에 복합 Claim 회귀 테스트 추가
- `tests/agent/test_two_layer_rag.py`에 동일 상품 중복 제거 통합 테스트 추가
- Agent 대상 테스트와 정적 검사 실행
- 이 문서와 기준 계획 문서에 검증 결과·커밋을 누적 기록

### 제외

- `backend/`, `models/`, `migrations/`, `data/scripts/` 변경
- Claim/Evidence 저장 구조와 실제 SQLAlchemy 조회 구현
- 임베딩 모델 또는 벡터 차원 변경
- 상품-성분 매핑 생성·수정
- `match_acceptance=confirmed` 필터의 Backend 구현
- 프롬프트 전반 재작성과 작업 호출 예산 최적화

이번 작업은 Agent 파트 안에서 판정 규칙과 회귀 테스트만 다룬다. 다른 파트 계약 변경이 필요하다고
확인되면 구현하지 않고 별도 협의 항목으로 기록한다.

## 3. 현재 확인된 문제

### 3.1 복합 성분 Claim의 과도한 승격 가능성

현재 `ClaimEvidenceVerifier`는 대상 성분이 둘 이상일 때 조합 Evidence가 없어도 각 성분의
`per_target` 결과가 모두 검증 가능하면 Claim 전체를 `SUPPORTED`로 판정할 수 있다.

예를 들어 Claim이 다음과 같다고 가정한다.

> 나이아신아마이드와 레티놀을 함께 사용하면 피지 고민에 도움이 된다.

검색 결과가 아래와 같더라도 조합 Claim 자체가 검증된 것은 아니다.

- 나이아신아마이드 단독 효능 Evidence 있음
- 레티놀 단독 효능 Evidence 있음
- 두 성분을 함께 사용한 조합 Evidence 없음

개별 성분의 근거를 조합의 효과·안전성 근거로 확대하면 안 되므로 별도 Rule 방어가 필요하다.

### 3.2 동일 상품 중복 제거의 회귀 검증 부족

동일한 상품이 여러 추천 성분 검색에서 반복 반환될 수 있다. 현재 구현에는 `product_id` 기준 병합
로직이 있지만, 아래 충돌 상황을 고정하는 테스트가 부족하다.

- 같은 상품이 Evidence-supported 성분과 Claim-only 성분 양쪽에서 반환되는 경우
- 같은 상품이 여러 Claim-only 성분에서 반복 반환되는 경우
- 병합 과정에서 성분 ID, statement ID, Evidence ID가 유실되는 경우
- 중복 제거 뒤 근거 등급 정렬이 뒤바뀌는 경우

먼저 테스트로 기대 동작과 현행 동작을 비교한다. 테스트에서 결함이 확인된 경우에만 상품 병합 로직의
최소 수정을 제안하며, 예상과 다른 정책 선택이 필요하면 사용자에게 다시 확인받는다.

## 4. 확정할 구현 규칙

### 4.1 복합 Claim 판정

복합 Claim은 다음 조건을 모두 만족할 때만 `SUPPORTED`로 판정한다.

1. 대상 `ingredient_ids`가 둘 이상이다.
2. 생성 결과에 `combination` 판정이 존재한다.
3. `combination.has_verifiable_evidence`가 참이다.
4. 인용한 모든 Evidence가 실제 검색 결과에 포함되어 있다.
5. 인용 Evidence의 `target_ids`가 복합 Claim의 전체 성분 ID를 포함한다.
6. 검증 가능한 요약 문장이 존재한다.

조합 결과가 없거나 위 조건 중 하나라도 실패하면 Claim 상태는 `INSUFFICIENT`로 유지한다. 이때
Evidence 부재를 효과 없음이나 상반 근거로 해석하지 않으며, 기준 정책에 따라 해당 성분들은
`CLAIM_ONLY` 상품 탐색 후보로 남길 수 있다.

개별 성분의 `per_target` Evidence는 복합 Claim의 `SUPPORTED` 판정이나 Citation으로 승격하지
않는다. 단일 성분 Claim의 기존 판정 규칙은 변경하지 않는다.

### 4.2 상품 중복 제거 기대 동작

동일한 `product_id`는 최종 `ProductCandidateSet`에 한 번만 포함한다.

- Evidence-supported 성분이 하나라도 연결되면 상품의 최종 근거 등급은
  `EVIDENCE_SUPPORTED`로 유지한다.
- Evidence-supported 성분 ID와 Claim-only 성분 ID는 각각 중복 없이 합친다.
- 관련 statement ID와 Evidence ID도 중복 없이 합친다.
- 최초 검색 순서를 불필요하게 뒤집지 않는다.
- 전체 결과에서는 Evidence-supported 상품을 Claim-only 상품보다 먼저 표시한다.
- Claim-only 연결이 함께 존재했다는 정보는 병합 후에도 보존한다.

이 항목은 우선 테스트로 현행 구현을 확인한다. 위 기대 동작과 구현이 일치하면 상품 로직은 수정하지
않고 테스트만 추가한다.

## 5. 구현 순서

### P1. 기준선 재검증

- 현재 변경 파일과 diff를 다시 확인한다.
- `uv run`으로 기존 Agent 테스트의 기준선을 확인한다.
- 실패가 있으면 이번 작업으로 발생한 실패와 기존 미완성 변경의 실패를 구분한다.

완료 조건:

- 수정 전 테스트 결과가 기록되어 있다.
- 실패가 있다면 테스트명과 원인이 작업 일지에 남아 있다.

### P2. 복합 Claim 회귀 테스트 작성

아래 사례를 우선 테스트로 고정한다.

1. 복합 조합 Evidence가 있고 전체 대상 ID가 일치하면 `SUPPORTED`
2. 조합 Evidence 없이 개별 성분 Evidence만 모두 있으면 `INSUFFICIENT`
3. 조합 Evidence가 검색 결과에 없는 출처를 인용하면 `INSUFFICIENT`
4. 조합 Evidence가 일부 성분만 대상으로 하면 `INSUFFICIENT`
5. 단일 성분 Claim의 기존 `SUPPORTED` 판정은 유지

완료 조건:

- 현재 결함을 재현하는 테스트가 수정 전 실패한다.
- 단일 성분 경로의 회귀가 없다.

### P3. 복합 Claim 판정 규칙 수정

- 복합 Claim에서는 `generated.combination`만 지원 판정 후보로 사용한다.
- 개별 성분 결과를 모두 모아 조합 근거로 승격하는 fallback을 제거한다.
- 검색 결과·대상 ID·요약 문장 검증은 기존 Rule 검증을 재사용한다.
- 새로운 라이브러리와 폴더는 추가하지 않는다.

완료 조건:

- P2 테스트가 모두 통과한다.
- 조합 근거가 없을 때 Citation이 생성되지 않는다.
- 조합 근거 부족 성분은 `CLAIM_ONLY` 후보로 이어질 수 있다.

### P4. 동일 상품 중복 제거 테스트

아래 사례를 통합 테스트로 추가한다.

1. 동일 상품이 Evidence-supported 성분과 Claim-only 성분에서 각각 반환됨
2. 동일 상품이 둘 이상의 Claim-only 성분에서 반복 반환됨
3. 병합 후 상품은 한 건이고 관련 ID 목록은 유실 없이 합쳐짐
4. Evidence-supported 상품의 우선순위와 Citation은 유지됨

완료 조건:

- 현행 동작이 기대 규칙과 일치하는지 확인된다.
- 일치하면 테스트만 남기고 상품 병합 코드는 수정하지 않는다.
- 불일치하면 실제 결과와 수정 제안을 기록한 뒤, 정책 판단이 필요한 경우 사용자 확인 후 수정한다.

### P5. 전체 검증과 문서 누적

실행 예정 명령:

```powershell
uv run pytest tests/agent/test_claim_verification.py tests/agent/test_two_layer_rag.py -q
uv run pytest tests/agent -q
uv run ruff check agent tests/agent
git diff --check
```

완료 조건:

- 대상 테스트, Agent 전체 테스트, Ruff가 통과한다.
- 테스트 개수와 결과를 이 문서의 작업 일지에 기록한다.
- 기준 문서의 단계 상태와 작업 일지를 실제 결과에 맞게 갱신한다.

## 6. 예상 수정 파일

| 파일 | 예정 변경 |
| --- | --- |
| `agent/claim_verification.py` | 복합 Claim을 개별 Evidence로 승격하는 fallback 차단 |
| `agent/rag/claim_schemas.py` | 판정에 필요한 정보가 부족할 때만 최소 보완 |
| `tests/agent/test_claim_verification.py` | 복합 Claim 판정 회귀 테스트 |
| `tests/agent/test_two_layer_rag.py` | 동일 상품 병합·중복 제거 통합 테스트 |
| `docs/agent/TWO_LAYER_RAG_REFACTOR_PLAN.md` | 단계 상태와 누적 작업 일지 갱신 |
| `docs/agent/TWO_LAYER_RAG_FOLLOWUP_PLAN.md` | 이번 작업의 실행 결과와 결정 누적 |

`agent/rag/claim_schemas.py`는 현재 DTO로 충분하면 수정하지 않는다. 상품 중복 제거 구현 파일도
테스트에서 실제 결함이 확인될 때만 수정 대상으로 추가한다.

## 7. 커밋 계획

구현 승인 후 아래처럼 되돌릴 수 있는 단위로 나눈다.

1. `test(agent): 복합 Claim Evidence 판정 회귀 테스트`
2. `fix(agent): 개별 근거의 복합 Claim 승격 차단`
3. `test(agent): 추천 상품 중복 제거와 근거 병합 검증`
4. `docs(agent): 2-Layer RAG 후속 보완 작업 일지 갱신`

테스트가 현재 미완성 코드와 함께 움직여 분리가 불가능한 경우에는 실제 diff를 확인한 뒤 커밋 경계를
조정하며, 기능 수정과 문서 변경은 가능한 한 분리한다.

## 8. 보류 항목

다음 항목은 중요하지만 이번 승인 대상에는 포함하지 않는다.

- Claim 수와 성분 수가 많을 때 `DEFAULT_MAX_TOOL_CALLS`를 초과하는 문제
- Evidence 검색을 Claim별로 호출할지 성분별로 묶을지에 대한 배치 정책
- `TaskPlanBuilder`의 사용자 Intent와 내부 실행 작업 완전 분리
- 실제 Backend 어댑터의 `match_acceptance=confirmed` 강제 여부
- BGE-M3 운영 데이터와 smoke fixture의 1,536차원 임베딩 간 통합 전략

각 항목은 Agent 단독 판단으로 다른 파트 계약을 바꾸지 않고 별도 계획과 합의로 진행한다.

## 9. 작업 일지

### LOG-F01 — 2026-09-17 — 후속 보완 계획 작성

- 상태: `AWAITING_APPROVAL`
- 기준 문서: `TWO_LAYER_RAG_REFACTOR_PLAN.md`
- 작성 내용:
  - 복합 Claim은 조합 자체의 검증 가능한 Evidence가 있을 때만 `SUPPORTED`로 판정하도록 계획했다.
  - 개별 성분 Evidence는 복합 Claim의 지원 근거나 Citation으로 승격하지 않도록 했다.
  - 동일 상품 중복 제거는 먼저 테스트로 현행 동작을 확인하고, 실제 결함이 있을 때만 구현을 수정하도록
    범위를 제한했다.
  - Agent 파트 밖의 저장소·DB·Backend 계약은 이번 작업에서 제외했다.
- 코드 변경: 없음
- 다음 단계: 사용자 계획 확인 후 P1 기준선 재검증 시작

### LOG-F02 — 2026-09-17 — 후속 보완 구현 및 검증 완료

- 상태: `VERIFIED`
- 완료 단계: P1, P2, P3, P4, P5
- 구현 결과:
  - 복합 Claim에서 개별 성분 Evidence를 모아 `SUPPORTED`로 승격하던 fallback을 제거했다.
  - 조합 결과 부재는 `missing_combination_evidence`, 검색하지 않은 출처나 불완전한 대상 인용은
    `citation_validation_failed`로 구분했다.
  - 조합 근거 부족 Claim은 `INSUFFICIENT`로 유지되며 `CLAIM_ONLY` 상품 후보가 될 수 있다.
  - 동일 상품 중복 제거는 현행 `product_id` 병합 로직이 계획의 기대 동작과 일치해 구현을
    변경하지 않고 회귀 테스트만 추가했다.
  - 후보 번호를 참조하는 상품 요청이 불필요한 Claim RAG로 진입하지 않도록 Product 경로 조건을
    보완했다.
- 검증 결과:
  - 복합 Claim 판정 테스트: 10개 통과
  - 2-Layer RAG 통합 테스트: 10개 통과
  - Agent 전체 테스트: 116개 통과
  - 프로젝트 전체 테스트: 186개 통과
  - Ruff: 통과
  - `git diff --check`: 통과
- 보류 항목:
  - 도구 호출 예산과 Evidence 배치 정책
  - Backend의 `match_acceptance=confirmed` 강제 검증
  - 운영 BGE-M3 인덱스와 실제 DB 어댑터 통합 테스트

### LOG-F03 — 2026-09-17 — 최신 dump 기반 실제 LangGraph 실행 확인

- 상태: `VERIFIED`
- 실행 진입점: `tests/agent/interactive_two_layer_rag_cli.py`
- 실행 명령:

  ```powershell
  uv run python -m tests.agent.interactive_two_layer_rag_cli "피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?"
  ```

- 실제 연결:
  - Intent·답변 모델: OpenAI `gpt-4o-mini`
  - Claim·Evidence 임베딩: `BAAI/bge-m3` 1,024차원
  - Evidence 리랭커: `BAAI/bge-reranker-v2-m3`
  - Claim·Evidence·성분·상품: `skincare_latest` DB
- 실행 결과:
  - LangGraph가 질의를 `product_discovery`로 판정하고 `partial` 상태로 완료했다.
  - Claim 5건을 발굴하고 성분별 Evidence 검색을 5회 수행했다.
  - 나이아신아마이드 Evidence 3건을 검색했지만 모두 `unreviewed`라 Claim을 공인 근거 지원으로
    승격하지 않았다.
  - Evidence가 없거나 검수되지 않은 Claim도 제거하지 않고 `CLAIM_ONLY`로 유지했다.
  - Claim 기반 상품 후보 13건을 최종 응답에 표시했으며, 상품이 없는 성분 2건은 보류 사유로
    명시했다.
- 실행 환경 보완:
  - 기존 CLI의 이모지가 Windows `cp949` 출력에서 실패하므로 새 CLI 진입점에서만 UTF-8로
    출력 스트림을 설정했다.
  - 기존 `tests/agent/interactive_rag_cli.py`와 `config.yaml`은 변경하지 않았다.
- 검증 결과:
  - Agent 전체 테스트: 116개 통과
  - Ruff: 통과
  - Pyrefly: 오류 없음
  - `git diff --check`: 통과
