# LLM Routine Rule 생성·결정적 검증 구현

- 작성 시각: 2026-09-21 14:04 KST
- 대상 브랜치: `integration/nia-case-rag`
- 범위: `agent/`, `tests/agent/`, Agent 문서
- DB·마이그레이션 변경: 없음

## 1. 결정

루틴 전체를 고정 규칙으로 생성하지 않는다. LLM은 제공된 출처에서 Rule 후보를 추출하고 그
Rule 안에서 일정 초안을 만든다. 코드는 Rule 출처와 최종 일정의 기계적 제약을 검증한다.

```text
제품 directions + 관련 Evidence
→ LLM Rule 후보 생성
→ exact quote·제품 ID·출처 범위·검수 상태 검증
→ LLM RoutineDraft 생성
→ 제품 ID·요일·순서·중복·횟수·강제 Rule 검증
→ RoutinePlan 확정 또는 partial
```

LLM이 `routine_id`, `version`, Evidence 검수 상태를 결정하지 않는다.

## 2. Rule 신뢰도 정책

- 제품 공식 사용법에서 exact quote로 추출한 Rule: `REQUIRED`
- 검수 완료 Evidence에서 exact quote로 추출한 Rule: `REQUIRED`
- 미검수 Evidence에서 추출한 Rule: `WARNING`
- 출처가 없거나 quote가 원문과 다르거나 적용 제품 범위를 벗어난 Rule: 폐기 후 경고
- 출처에 숫자가 없으면 주당 사용 횟수를 생성하지 않음

지원 Rule 유형:

- 허용 시간대
- 주당 최대 사용 횟수
- 같은 시간대 사용 회피
- 제품 사용 순서
- 일반 경고

## 3. 결정적 검증 범위

- 입력에 없는 제품 ID 차단
- 선택 제품 누락 차단
- 제외 요일 배치 차단
- 같은 제품·요일·시간대 중복 차단
- 시간대별 order가 1부터 중복 없이 이어지는지 확인
- 요청한 주당 횟수 초과 차단
- `REQUIRED` Rule 위반 차단
- `WARNING` Rule과 무효 Rule 사유는 unresolved로 노출하고 응답을 `partial`로 표시

의학적 안전성을 코드가 임의로 판정하지 않는다. 관련 Evidence가 미검수이면 강제 Rule로
승격하지 않는다.

## 4. 구현 파일

- `agent/rag/schemas.py`: Rule·출처·Draft·검증 DTO
- `agent/ports.py`: Rule Generator와 Draft Generator 포트
- `agent/rag/routine_planner.py`: LLM 생성기, 출처 Builder, 결정적 Validator, Planner
- `agent/prompts.py`: Rule 추출과 RoutineDraft 프롬프트
- `agent/nodes.py`: 현재 사용자 요청과 Evidence를 Planner에 전달하고 경고 노출
- `agent/factory.py`: 운영 기본 LLM Planner 조립, 개발 Planner 주입 지원
- `tests/agent/interactive_two_layer_rag_cli.py`: 실제 CLI에서 LLM Planner 사용
- `tests/agent/test_llm_routine_planner.py`: 결정적 방어 테스트

## 5. 검증 결과

```text
새 Rule·Draft·Validator 핵심 테스트: 4 passed
기존 루틴 진입·생성·수정 회귀: 3 passed, 14 deselected
운영 Factory 기본 LLM Planner 조립: 1 passed, 11 deselected
Ruff: passed
```

요청 범위를 넓히지 않기 위해 전체 테스트는 실행하지 않았다. 실제 OpenAI 루틴 E2E도 아직
실행하지 않았다. 실제 실행 시 사용자 요청, 선택 제품 directions, 관련 Evidence 본문이 설정된
외부 모델로 전송된다.

## 6. `미검수 3건` DB 확인

실제 E2E CLI는 설정 DB 이름을 그대로 사용하지 않고 `skincare_latest` DB로 강제 연결한다.
해당 DB에서 나이아신아마이드에 연결된 Evidence는 정확히 다음 PubMed 3건이다.

1. `PMID:10971324:abstract:0` — 피부 장벽 지질 관련
2. `PMID:16766489:abstract:0` — 2% 나이아신아마이드와 피지 관련
3. `PMID:21822427:abstract:0` — 4% 나이아신아마이드와 기미 관련

세 건 모두 `evidence_level=peer_reviewed_study`이지만 `document_status=NULL`이다. 현재 Backend
어댑터는 `document_status == "verified"`일 때만 `VERIFIED`로 변환하므로 세 건 모두
`UNREVIEWED`가 된다.

따라서 `Evidence: 검색 3건 (검수완료 0, 미검수 3)`은 Evidence RAG가 실패했다는 뜻이 아니다.
벡터·텍스트 검색과 리랭킹으로 세 건을 찾았지만 Citation 및 확정 근거로 승격할 검수 상태가
없다는 뜻이다.

## 7. 후속 확인

- 실제 OpenAI Rule 생성과 RoutineDraft 생성 E2E
- 첫 Draft가 결정적 검증에 실패했을 때 검증 사유를 이용한 1회 재생성
- 실제 Product `directions` 채움 수준 확인
- `document_status`와 Agent `VERIFIED` 상태의 최종 Evidence 계약 합의
