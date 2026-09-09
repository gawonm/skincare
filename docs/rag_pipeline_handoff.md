# RAG 파이프라인 인수인계 문서

작성 기준: 2026-09-10 (한국시간), 이 세션에서 직접 코드를 작성·실행·검증한 내용만 담는다.
대상 저장소: `/Users/moon/projects/skincare-rag-pipeline` (워크트리, 브랜치 `feature/rag-pipeline`, 미푸시)

> 이 문서는 [docs/SKINCARE_DATA_RAG_HANDOFF.md](SKINCARE_DATA_RAG_HANDOFF.md)(다른 세션이 작성)가
> "남은 작업"으로 정리한 항목들을 이 세션에서 이어받아 처리한 뒤의 **현재 상태**를 기록한다.
> 두 문서가 겹치는 부분(상품/올리브영 파트, 기술 스택 표 등)은 그 문서를 참고하고, 여기서는
> RAG 성분 근거 파트에 집중한다.

## 1. 한 줄 요약

**서비스 최상위 기준은 사용자가 준 플로우차트다.** 이 파트가 만든 건 그 플로우차트의
"①성분 확인" 분기가 실제로 동작하는 데 필요한 것 — 성분 근거를 모으고(RAG 적재), 질문을
받으면 근거를 찾아 검증하고(RAG 조회), 근거가 없으면 없다고 정직하게 답하는 파이프라인이다.
챗봇 UI·추천 API·루틴 엔진은 이 파트 담당이 아니다.

## 2. 상태를 읽는 법

이 문서의 모든 수치·통과 여부는 **이 세션에서 실제로 명령을 실행해서 나온 결과**다("~라고
들었다"가 아니다). 표시 방식:

- ✅ **실행 확인**: 이 세션에서 실제로 돌려서 결과를 봤다.
- 📝 **코드 완료, 미실행**: 코드는 있지만 이 세션에서 끝까지 실행해보지 않았다(주로 비용·시간 때문).
- ⛔ **미착수**: 코드 자체가 없다.

## 3. 오늘 세션에서 한 일 (시간 순)

1. RAG 파이프라인 1차 구현 — 로더/청킹/임베딩/검색/생성 전 부품, `rag_chunk` 테이블, 적재 서비스
2. NIA AI Hub dataset 71886 조사 — `docs/data.md`의 "리뷰데이터라 제외" 서술이 틀렸음을 발견해 정정,
   라이선스(비영리 R&D 한정) 확인
3. 전체 데이터 적재: Evidence 8,288행/14,480청크, Knowledgedata 2,411행/5,714청크, NIA 9,000레코드/45,002청크 ✅
4. 재적재 안전성 요구 반영 — 재적재해도 안전한지, 관련성 판정이 정확한지 지적받고 보강:
   - `RagChunkRepository.sync_documents()`: upsert + 무변경 스킵 + 삭제된 필드 정리, 실제 재실행으로
     버그 발견(임베딩 벡터는 재호출마다 미세하게 달라짐 → "무변경" 판정에서 제외) → 수정 ✅
   - BM25 검색: 질문에 괄호/물음표가 있으면 pg_search 파서가 깨지는 실전 버그 발견 → sanitizer 추가 ✅
   - `IngredientMentionResolver`: 성분 언급 추출, "나이아신아마이드" 안의 "나이아신" 오탐 버그
     발견 → span 기반 dedup으로 수정 ✅
   - `QuestionIntentClassifier` + `AnswerGenerator`의 질문축 필터링, 문장 단위 인용 검증(구조화
     출력 + ID유효성·조건보존 2단계 검사) 구현 ✅
   - MFDS Evidence 원자적 교체(`replace_mfds_evidence_and_reindex`) 구현 — 임베딩까지 전부
     준비한 뒤에만 DB 삭제+삽입을 한 트랜잭션으로 확정
5. **외부 코드 리뷰(다른 세션/도구)로 4개 실버그 추가 발견 → 전부 수정+재검증** ✅
   - 조건보존 검사가 "하나라도 겹치면 통과"였음(교집합) → "전부 보존해야 통과"(부분집합)로 수정
   - 유효/무효 인용번호가 섞이면 무효만 조용히 제거하던 것 → 하나라도 무효면 문장 전체 폐기로 수정
   - 문장별 인용 매핑이 내부에서만 쓰이고 최종 응답엔 안 남던 것 → `IngredientVerificationResult.claims` 필드 추가
   - COMBINATION 의도가 허용 필드 빈 집합이라 관련성 필터에서 전멸하던 것 → 필터에서 COMBINATION 제외, 조합 판정은 전용 단계로 분리
6. `RagQueryService` 조립 — 성분 언급 해소 → 의도 분류 → (성분별/조합별) 검색 → 답변 생성을
   하나의 호출로 연결. 개별 성분 판정과 조합 판정을 분리해서 반환(성분 A+B 근거를 합쳐
   "같이 써도 된다"로 오인하지 않게) ✅
7. MFDS 교체 실패 복원 테스트 — 가짜 임베더로 두 실패 지점(임베딩 준비 실패 / DB 쓰기 중 실패)을
   실제 MFDS API 호출 없이 검증 ✅

## 4. 지금 이 순간의 검증 상태

### 4.1 데이터 (✅ 이 세션에서 직접 SQL로 재확인, 2026-09-10)

```
uv run alembic current  →  0ff194fd5f2f (head)
```

| 소스 | 소스 행 수 | 문서 수 | 청크 수 |
| --- | ---: | ---: | ---: |
| `evidence` (MFDS) | 8,288 | 8,288 | 14,480 |
| `ingredient_knowledge_fact` (Knowledgedata=NIA 지식성분데이터) | 2,411 | 2,411 | 5,714 |
| NIA Q&A (jsonl 실제 파싱, 파일 개수 아님) | 9,000 (파싱성공 9,000/실패 0/ID중복 0) | 9,000 | 45,002 |
| `ingredient_master` (KCIA) | 21,974 | — | — |
| **합계** | | | **65,196** |

### 4.2 코드 품질 (✅ 이 세션에서 실행)

```
uv run ruff check .     → 전체 0 에러
uv run pyrefly check .  → 전체 0 에러
```

### 4.3 테스트 (✅ 이 세션에서 실행, 전부 통과)

```
uv run pytest                # 기본 실행 - integration 제외
tests/db/test_mfds_replace_rollback.py .. (2)
tests/db/test_rag_chunk_repository_sync.py ....... (7)
tests/unit/test_condition_preservation_checker.py ..... (5)
tests/unit/test_field_chunker.py .. (2)
tests/unit/test_hybrid_retriever.py ... (3)
tests/unit/test_ingredient_mention_resolver.py .... (4)
tests/unit/test_question_intent_classifier.py ..... (5)
= 28 passed =

uv run pytest -m integration  # 실제 OpenAI 호출 포함
tests/integration/test_rag_query_flow.py .... (4)
tests/integration/test_rag_query_service.py ... (3)
= 7 passed =
```

DB 테스트는 SAVEPOINT 격리(`tests/conftest.py`)라 로컬 개발 DB(위 65,196청크)를 건드리지 않는다
— 매 테스트 후 롤백되는 걸 실제로 확인했다(대량 삭제·삽입을 하는 MFDS 롤백 테스트 전후로
`rag_chunk` 총건수가 정확히 65,196으로 그대로였다).

### 4.4 실제 질문으로 확인한 동작 (✅ 라이브 실행)

| 질문 | 결과 | 의미 |
| --- | --- | --- |
| "p-하이드록시벤조익애씨드(파라벤류) 국내 배합 한도?" | 근거O, MFDS 출처, 조건(0.14%/0.8%, 어린이 예외) 보존 | 정상 케이스 |
| "1,2-Hexanediol 하루 몇 번 써야 하나요?" | 근거X, `NOT_RELEVANT_TO_QUESTION` | 성분은 맞는데 축(사용주기)이 구조화 데이터에 아예 없음 - 정확한 거부 |
| "레티놀이랑 나이아신아마이드 같이 써도 되나요?" | 개별 성분 둘 다 근거O, **조합은 근거X**(`MISSING_COMBINATION_EVIDENCE`) | 개별 근거를 조합 근거로 오인하지 않음 |
| "오늘 날씨 어때요?" | 근거X | 무관 질문 정상 거부 |

## 5. 아직 안 끝난 것 (정직하게)

| 항목 | 상태 |
|---|---|
| 조건보존 검사 | 정규식 기반 휴리스틱(%, 국가명). "이하/이상/제외" 같은 정성적 조건, 나이·용도 조건은 못 잡음 |
| 자유 텍스트(성분 미특정) 질문의 관련성 | intents가 비면 티어 판정만 함 - "오늘 날씨"가 우연히 `ONLY_AI_GENERATED_AVAILABLE`로 걸린 것도 운이 좋았을 뿐, 임계값 기반 관련성 판정은 없음 |
| 전체 동기화(문서 자체가 사라진 경우) | `sync_documents`는 "문서 안의 필드가 줄어든" 경우는 처리하지만, "문서(예: 특정 Evidence row)가 소스에서 통째로 사라졌는데 그 사실을 fetched_refs로 어떻게 알려줄지"는 호출부(rag_ingestion_service)가 아직 소스 테이블 전체와 diff하는 로직을 안 짜뒀음 - 지금은 Evidence는 MFDS 전량교체로, Knowledgedata/NIA는 매번 전체 재조회라 실질적 문제는 없지만 명시적으로 짜진 않음 |
| CIR 2단계(개별 성분 스크래핑) | 미착수. 포털만 있고 벌크 API 없어서 이용약관 확인 먼저 필요 |
| 커버리지 문서(`docs/rag_coverage_mvp.md`) | 글라이콜릭애씨드 권장농도 셀 수치 직접 파싱 확인 안 함 |
| 상품(올리브영) 데이터 | 이 세션 범위 밖 - [docs/oliveyoung_global_pipeline_handoff.md](oliveyoung_global_pipeline_handoff.md) 참고 |
| API/HTTP 엔드포인트 | 없음. `RagQueryService`는 파이썬 클래스로만 존재, `backend/api/`는 비어 있음 |

## 6. 다음 담당자가 알아야 할 설계 결정과 이유

- **성분이 특정되면 그 성분으로만 검색을 좁힌다.** 다른 성분 근거를 끌어와 대충 답하지 않는다.
  질문에서 성분을 못 찾으면(모호하거나 등록 안 된 표기) `AMBIGUOUS_INGREDIENT`로 명확화를 요구한다.
- **NIA(AI 생성+전문가검증)는 절대 "검증된 근거"가 아니다.** 개별 성분이든 조합 관계든 어디서나
  일관되게 이 규칙을 적용한다 - MFDS/Knowledgedata가 없으면 NIA가 아무리 많아도 근거부족이다.
- **조합 질문은 개별 성분 근거 두 개를 합쳐서 답하지 않는다.** "조합 자체를 다루는 근거"가
  따로 있어야 하고, 지금 데이터 모델엔 그런 전용 필드가 없어서(`Evidence.topic`에 조합 카테고리
  없음) 대부분의 조합 질문은 구조적으로 근거부족이 나온다 - 이건 버그가 아니라 데이터가 그렇다.
- **재적재는 "새로 만든 것만 넣기"가 아니라 "교체"다.** 원본에서 사라진 필드는 청크도 지워야
  하고, 변경 없는 건 손대면 안 되고(`updated_at` 헛갈림), 실패하면 통째로 롤백돼야 한다. 이
  세 가지를 한꺼번에 처음부터 설계 안 하면 나중에 "재적재했더니 검색결과가 이상해졌다"가 생긴다.

## 7. 다음에 할 일 (우선순위)

1. 자유 텍스트 질문 관련성 판정 — 지금은 사실상 무방비. 평가셋으로 임계값/판정 기준을 정하고,
   임계값 정하는 세트와 최종 검증 세트를 분리해야 한다(같은 세트로 정하고 검증하면 의미 없음).
2. 전체 동기화 경계를 명시적으로 짜기 — "이 소스에서 이 문서가 완전히 사라졌다"를 판단하는
   경로를 rag_ingestion_service에 만들기(지금은 Evidence만 전량교체라 우회하고 있음).
3. 조건보존 검사 고도화 — 정규식 토큰 매칭 말고 더 일반적인 조건 누락 탐지.
4. CIR 2단계, 글라이콜릭애씨드 커버리지 셀 확인.
5. `backend/api/`에 실제 엔드포인트를 만들어 `RagQueryService`를 HTTP로 노출(다른 파트가
   챗봇에서 호출할 수 있게) - 이건 이 파트 범위인지 다른 파트 범위인지 먼저 확인 필요.

## 8. 실행 방법 요약

```bash
# 환경 준비 (최초 1회)
uv sync --dev
cp config.yaml.sample config.yaml   # openai.api_key, mfds.service_key 채우기
docker compose up -d
uv run alembic upgrade head

# 전체 재적재 (이미 적재돼 있으면 sync_documents가 안전하게 갱신만 함)
uv run python -m backend.services.rag_ingestion_service --nia-qa-zip "data/nia_qa/*.zip"

# MFDS만 원자적으로 교체 (전량 재수집, 시간 걸림)
uv run python -m backend.services.rag_ingestion_service --mfds-replace

# 검사
uv run pytest              # 기본 (OpenAI 호출 없음)
uv run pytest -m integration  # 실제 API 호출 포함
uv run ruff check . && uv run pyrefly check .
```

질문에 답하는 방법(코드 예시, HTTP API 아직 없음):

```python
from backend.services.rag_query_service import RagQueryService
# session, embedder, generator를 만든 뒤
service = await RagQueryService.create(session, embedder, generator)
result = await service.answer("나이아신아마이드 효능이 뭐예요?")
# result.per_ingredient / result.combination / result.free_text
```
