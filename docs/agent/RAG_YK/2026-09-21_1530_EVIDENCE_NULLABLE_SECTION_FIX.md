# 식약처(MFDS) Evidence 검색 `section=NULL` 처리 및 DTO 변환 보강

- 기록 일시: 2026-09-21 15:30 (KST)
- 작업 주체: **Antigravity**
- 대상 브랜치: `integration/nia-case-rag`
- 범위: `backend/repositories/`, `backend/services/`, `tests/db/`, 관련 문서
- Agent 포트 변경: 없음 (기존 Agent Pydantic 계약 유지)

---

## 1. 변경 배경

`2026-09-21_1459_AGENT_ALIAS_AND_ATOMIC_CLAIM_UPDATE.md`에서 언급되었던 E2E 실행 시의 도구 실패 2건에 대해, 사용자가 `--verbose` 플래그로 CLI를 실행하여 구체적인 에러 원인을 포착했다.

```text
uv run python -m tests.agent.interactive_two_layer_rag_cli "피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?" --verbose
```

실행 로그에서 살리실산(BHA) 대상 Evidence 검색 2건([검색 1], [검색 3])이 다음 에러로 중단되었다.

```text
Evidence 검색 또는 DTO 변환에 실패했습니다: 1 validation error for EvidenceSearchRow
section
  Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
```

이로 인해 살리실산 관련 Claim들이 `tool_failure`로 처리되어 공인 근거 확인이 차단되고 최종 보류 사유로 누적되었다.

---

## 2. 원인 분석

1. **DB 스키마와 데이터 특성**:
   - `evidence_chunk.section` 컬럼은 논문(PubMed) 청크의 경우 `'abstract'` 등의 값이 채워지지만, **식약처(MFDS) 규제 청크는 `section`이 `NULL`**로 적재되어 있다 (`models/evidence_chunk.py` 및 `docs/data/EVIDENCE_STORAGE_ERD.md` 명세: `section: Mapped[str | None]`).
2. **Repository DTO의 Nullable 불일치**:
   - `backend/repositories/evidence_search_repository.py`의 `EvidenceSearchRow` 모델에 `section: str = Field(min_length=1)`로 선언되어 있어, `None`이 반환되는 식약처 규제 근거 청크를 읽어들일 때 Pydantic 유효성 검증 예외가 발생했다.
   - 나이아신아마이드는 PubMed 논문 청크(`section='abstract'`)가 연결되어 통과했으나, 살리실산은 식약처 규제 청크(`section=None`)만 연결되어 있어 조회 즉시 실패했다.
3. **어댑터 변환 및 매핑 결함**:
   - `backend/services/two_layer_rag_adapters.py`에서 `field_id=row.section`을 전달하여, Agent의 `RagChunkDraft.field_id`(필수 문자열) 검증에서도 연쇄 실패할 소지가 있었다.
   - `locator=f"{row.section}:{row.chunk_index}"` 서식 또한 `section`이 없을 때 `"None:0"`으로 잘못 조합되었다.
   - 식약처 데이터의 `claim_topics`인 `concentration_regulation`과 `usage_instruction`이 `EvidenceTopicIntentMapper`에 누락되어 질문 축으로 매핑되지 못했다.

---

## 3. Antigravity 작업 상세

### 3.1 `backend/repositories/evidence_search_repository.py`
- `EvidenceSearchRow.section` 타입을 `str = Field(min_length=1)`에서 `str | None = None`으로 수정하여 DB의 `NULL` 값을 안전하게 수용하도록 했다.

### 3.2 `backend/services/two_layer_rag_adapters.py`
- **`RagChunkDraft.field_id` Fallback**:
  - `field_id=row.section or "content"`로 지정하여 `section`이 `None`인 식약처 청크도 Agent의 필수 문자열 제약을 온전히 충족하도록 보장했다.
- **`EvidenceRecord.locator` 서식 분기**:
  - `locator = f"{row.section}:{row.chunk_index}" if row.section else f"chunk:{row.chunk_index}"`로 수정하여 `section`이 없을 때 명확한 청크 식별자를 조합하도록 했다.
- **`EvidenceTopicIntentMapper` 주제 매핑 추가**:
  - `concentration_regulation` → `QuestionIntent.REGULATION`
  - `usage_instruction` → `QuestionIntent.USAGE_FREQUENCY`

### 3.3 `tests/db/test_two_layer_rag_dump.py`
- 살리실산(`5c3fa47f-b797-452c-bc86-04a872aa3f71`)의 식약처 근거(section=NULL)를 검색하고, `EvidenceSearchRow` 및 `RetrievedChunk` 변환과 `locator` 생성이 정상 동작하는지 검증하는 `test_mfds_evidence_search_with_nullable_section_succeeds` 통합 테스트를 추가했다.

---

## 4. 검증 결과

1. **DB 통합 테스트**:
   ```bash
   uv run pytest tests/db/test_two_layer_rag_dump.py -m integration
   # 4 passed in 1.04s
   ```
2. **전체 단위 테스트**:
   ```bash
   uv run pytest tests/unit
   # 278 passed in 3.57s
   ```
3. **에이전트 회귀 테스트**:
   ```bash
   uv run pytest tests/agent
   # 170 passed in 8.90s
   ```
4. **린트 검사**:
   ```bash
   uv run ruff check backend/repositories/evidence_search_repository.py backend/services/two_layer_rag_adapters.py tests/db/test_two_layer_rag_dump.py
   # All checks passed!
   ```

---

## 5. 변경 파일 목록

- `backend/repositories/evidence_search_repository.py`: `EvidenceSearchRow.section` nullable 처리
- `backend/services/two_layer_rag_adapters.py`: `field_id` fallback, `locator` 서식, 식약처 토픽 매핑 보강
- `tests/db/test_two_layer_rag_dump.py`: 식약처 section=NULL 검색 회귀 테스트 추가
- `docs/agent/RAG_YK/2026-09-21_1530_EVIDENCE_NULLABLE_SECTION_FIX.md`: 본 작업 기록 문서 신규 작성
