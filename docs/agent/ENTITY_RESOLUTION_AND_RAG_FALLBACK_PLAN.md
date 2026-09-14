# [작업 예정서] 성분 식별(Entity Resolution) 개선 및 RAG 자유 텍스트 폴백 구현

- **작성일**: 2026-09-13
- **담당 파트**: `agent` (에이전트 상태 그래프 및 RAG 검색 파이프라인)
- **관련 문서**: [docs/agent/README.md](README.md), [AGENTS.md](../../AGENTS.md)

---

## 0. 실제 반영 내용과 원안 대비 보완 (2026-09-13)

아래 1~6절은 최초 제안 기록이다. **실제 동작·범위는 이 절을 우선한다.**
제안서의 데이터 건수는 작성 당시 보고값이며 이번 코드 변경에서 DB를 재조회하지 않았다.

### 안전한 동의어와 통칭을 구분

- `CommonIngredientAliasMapper`를 `agent/rag/retrieval/ingredient_alias_mapper.py`에 분리했다.
  원문을 먼저 조회하고 `NO_RESULTS`일 때만 확인된 동의어로 한 번 더 조회한다.
  재조회도 기존 도구 호출 제한에 포함하며, 오류·미지원·모호한 후보는 별칭으로 덮어쓰지 않는다.
- 초기 목록은 `비타민C`, `vitamin c`, `ascorbic acid`, `아스코르빈산`의
  `아스코빅애씨드` 조회 표기로 제한했다. 공백·대소문자·전각 문자를 정규화하되
  전체 명칭이 일치할 때만 적용한다. 제품의 실제 유도체·함량을 확정하는 기능이 아니다.
- 이 이름 관계는 [NIH ODS 비타민 C 자료](https://ods.od.nih.gov/factsheets/VitaminC-HealthProfessional/)를
  참고했다. 실제 ID는 반드시 저장소에서 얻고, 재조회 결과의 정규명·별칭도 요청과 대조한다.
  저장소의 부분 일치로 다른 유도체가 반환되면 확정 ID로 승격하지 않는다.
- 원안의 `AHA → 글라이콜릭애씨드` 같은 계열→단일 성분 치환은 반영하지 않았다.
  [FDA 자료](https://www.fda.gov/cosmetics/cosmetic-ingredients/alpha-hydroxy-acids)도
  AHA에 글리콜산·젖산 등 여러 성분을 포함한다. 시카·비타민 B군 등 나머지 목록도
  검증된 동의어 계약 없이 기본 사전에 추가하지 않는다. 미식별 근거 질문은 아래 폴백으로 처리한다.

### 폴백은 한 번의 전체 질문 검색

- `agent/evidence_query_policy.py`의 `EvidenceQueryPolicy`가 폴백 허용과 검색 범위를 결정한다.
  정책은 DB·모델을 호출하거나 그래프 상태를 직접 변경하지 않는다.
- **명시적 성분 언급이 있는 순수 `EVIDENCE_QA`**에서 미식별/모호한 이름이 남으면 허용한다.
  제품 추천·루틴·저장 등 다른 Intent가 함께 있으면 기존 확인 질문을 유지한다.
  대상 없는 지시어 질문이나 유효하지 않은 후보 참조도 계속 확인을 요구한다.
- 일부 성분만 식별되어도 질문 원문과 사용자 조건을 유지한 채 `target_ids=[]`,
  `combination_target_ids=[]`로 검색한다. 식별된 ID만 필터로 남겨 미식별 대상의 문헌이
  후보에서 빠지는 문제를 방지한다. 별도의 추가 검색·병합 파이프라인은 만들지 않았다.
- 폴백 응답은 `PARTIAL`이며 미확정 이름과 한계를 표시한다. 검색 결과가 모든 질문 대상을
  다룬다고 보장하지 않는다. 기존 유사도 임계값·리랭커·검수·조건·인용 검사는 유지한다.
  병용 대상이 미확정이면 기존 생성기의 병용 근거 보류 정책을 그대로 따른다.
- 성분/대상 조회 오류는 무결과로 바꾸거나 자유 검색으로 덮지 않는다.
  검색 자체의 `NO_RESULTS`, `UNSUPPORTED`, `ERROR`도 기존 경로대로 구분한다.
- 미식별 대상이 섞인 요청에서는 식별된 일부 ID만 후속 대화의 확정 대상으로 저장하지 않는다.
  다음 "그 성분"이 어느 대상인지 불분명하면 확인 질문을 한다.

### 변경 경계와 검증

- 제품 코드: `agent/nodes.py`와 위 두 신규 모듈만 변경했다.
- 회귀 검사: `tests/agent/test_entity_resolution_fallback.py`.
  동의어 조회, 일부/전체 미식별, 모호한 후보, 혼합 Intent, 호출 제한, 조회 장애,
  다중 턴 참조, 미검수 자료, 병용 보류와 검색 상태를 DB/API 없이 검사한다.
- CLI는 기존 `ChatService` 경로를 사용하므로 **CLI 별도의 매퍼 연결은 추가하지 않았다.**
  Backend·DB 스키마·공용 설정·의존성과 공개 요청/응답 DTO는 변경하지 않았다.
- 실제 모델 품질·DB 검색 품질과 비용을 수반하는 실측은 단위 테스트 통과와 구분한다.

```sh
.venv/bin/python -m pytest tests/agent tests/unit -q -p no:cacheprovider
```

---

## 1. 개요 및 배경

스킨케어 에이전트 CLI 및 대화 테스트 환경에서 사용자가 다음과 같은 일반적인 질문을 입력했을 때, 정상적인 근거 검색이나 답변 생성이 진행되지 못하고 즉시 대화가 차단되는 현상이 발생했습니다.

> **사용자 입력**: `"나이아신아마이드와 비타민C의 효능"`<br>
> **에이전트 응답**: `"성분명을 하나의 후보로 식별하지 못했습니다. 정확한 표시 명칭을 알려주세요."` (`ChatStatus.NEEDS_INPUT`)

본 작업 예정서는 해당 현상의 근본 원인을 분석하고, 사용자가 선택한 **방안 C(방안 A: RAG 자유 텍스트 검색 폴백 + 방안 B: 일상 성분 통칭 사전 매핑 결합)**를 시스템에 안정적으로 적용하기 위한 상세 설계와 실행 계획을 정의합니다.

---

## 2. 현상 및 근본 원인 분석

### 2.1 실행 흐름 및 차단 지점

```mermaid
flowchart TD
    A["사용자 입력: '나이아신아마이드와 비타민C의 효능'"] --> B["understand_request<br/>(LLM 의도 파싱)"]
    B -->|intents: EVIDENCE_QA<br/>ingredient_mentions: ['나이아신아마이드', '비타민C']| C["resolve_entities<br/>(성분 식별 노드)"]

    C -->|나이아신아마이드| D["DB 성분 검색 성공<br/>(ingredient_ids에 추가)"]
    C -->|비타민C| E["DB 성분 검색 실패 (NO_RESULTS)<br/>unresolved_names.append('비타민C')"]

    D --> F["assess_information<br/>(정보 평가 노드)"]
    E --> F

    F -->|❌ unresolved_names 존재 확인| G["clarification_question 생성<br/>'성분명을 하나의 후보로 식별하지 못했습니다...'"]
    G --> H["after_information 라우터<br/>-> ASK_USER 분기"]
    H --> I["ask_user 노드<br/>ChatStatus.NEEDS_INPUT 반환 및 강제 종료"]

    style G fill:#ffcccc,stroke:#ff0000,stroke-width:2px
    style I fill:#ffcccc,stroke:#ff0000,stroke-width:2px

    subgraph "정상 도달해야 할 RAG 파이프라인 (완전 차단됨)"
        J["process_task (_process_evidence)"]
        K["SqlAlchemyHybridSearchBackend<br/>(ParadeDB BM25 + pgvector 코사인 검색)"]
        L["AnswerGenerator (답변 생성)"]
    end
```

### 2.2 근본 원인 상세

1. **화장품 표준 전성분명(KCIA/식약처)과 소비자 일상 명칭의 괴리**
   - 현재 `ingredient_master` 테이블은 대한화장품협회(KCIA)의 표준 전성분 명칭을 기준으로 적재되어 있습니다.
   - 소비자는 일상적으로 `"비타민C"`라고 부르지만, 표준 성분명은 `"아스코빅애씨드"`(Ascorbic Acid)입니다.
   - 마찬가지로 `"비타민B3"`는 `"나이아신아마이드"`, `"시카"`는 `"병풀추출물"`, `"비타민B5"`는 `"판테놀"`이 표준명입니다.
   - LLM 의도 해석기는 사용자의 원문 질문에서 자연어 그대로 `["나이아신아마이드", "비타민C"]`를 추출하므로, DB의 표준명 일치 검색(`standard_name_ko`, `standard_name_en`, `normalized_name_ko`)에서 `비타민C`는 완전히 누락되어 `NO_RESULTS`가 됩니다.

2. **`assess_information`의 일률적 하드 블로킹 (Hard-Blocking)**
   - `agent/nodes.py` 383~386행:
     ```python
     elif state.resolved_entities.unresolved_names:
         question = "성분명을 하나의 후보로 식별하지 못했습니다. 정확한 표시 명칭을 알려주세요."
         target_field = "ingredient_name"
         reason = "모호한 후보들을 서로 다른 확정 성분으로 취급하면 안 됩니다."
     ```
   - 이 규칙은 제품 추천(`PRODUCT_DISCOVERY`)이나 루틴 생성(`ROUTINE_PLANNING`) 시 잘못된 성분으로 제품을 오인 추천하거나 피부 자극을 유발하는 사고를 방지하기 위해 엄격하게 설계된 것입니다.
   - 하지만 논문/문헌 근거 질의(`EVIDENCE_QA`)에서는 성분 ID가 DB에 정확히 일치하지 않더라도 본문 텍스트 매칭을 통해 유의미한 지식을 탐색할 수 있습니다. 특히 복수 성분 질의에서 하나라도 미식별되면 전체 조회가 불가능해지는 치명적인 사용성 저하를 유발합니다.

3. **6.5만 건 RAG 하이브리드 검색 엔진의 역량 미활용**
   - 현재 DB에는 65,196건의 `rag_chunk`와 8,288건의 `evidence`가 적재되어 있으며, ParadeDB BM25 색인과 pgvector(1536차원) 코사인 인덱스가 정상 작동하고 있습니다.
   - `SqlAlchemyHybridSearchBackend`와 `RagChunkRepository`는 `target_ids`가 비어있을 경우 전체 문헌 청크를 대상으로 BM25 키워드 및 시맨틱 벡터 검색을 수행하도록 구현되어 있습니다.
   - 문헌 본문에는 `"비타민 C"`, `"ascorbic acid"`, `"시카"`, `"여드름"` 등의 일상 단어가 대량으로 포함되어 있으나, 그래프 앞단의 엄격한 차단으로 인해 쿼리가 전달조차 되지 못했습니다.

---

## 3. 해결 방안: 방안 C (방안 A + 방안 B 결합) 상세 설계

소비자 일상 언어를 포용하면서도 시스템의 신뢰성과 피부 안전성을 훼손하지 않도록 **2중 안전망(Defense-in-Depth)** 구조로 설계합니다.

```
[사용자 입력]
     │
     ▼
[1차 안전망: 방안 B] 일상 성분 통칭 사전 (IngredientAliasMapper)
     │  - "비타민C" -> "아스코빅애씨드" 자동 정규화
     │  - "시카" -> "병풀추출물" 자동 정규화
     │  - 정확한 ingredient_id 조회 성공률 극대화
     ▼
[성분 식별 결과 평가]
     ├─ 모든 성분 식별 성공 ───────────► 정상 RAG 파이프라인 (target_ids 필터링)
     └─ 미식별 성분 잔여 (신조어/오타 등)
            │
            ▼
[2차 안전망: 방안 A] 의도 기반 조건부 게이트 완화 & RAG 폴백
     ├─ PRODUCT_DISCOVERY / ROUTINE_PLANNING ─► 엄격 차단 유지 (안전성 확보)
     └─ EVIDENCE_QA ──────────────────────────► RAG 자유 텍스트 하이브리드 검색 수행
                                                 (식별된 ID + 원문 BM25/벡터 검색)
```

### 3.1 [파트 1 / 방안 B] 일상 성분 통칭(Alias) 매핑 계층 구현

#### 1) 설계 원칙
- **AGENTS.md 규칙 1, 2 준수**: 전역 딕셔너리가 아닌 Pydantic 모델과 클래스로 캡슐화합니다.
- **불필요한 DB 변경 없음**: DB 테이블 스키마나 마이그레이션 없이, `agent` 내부 또는 어댑터 레벨에서 안전하게 구동됩니다.

#### 2) 모델 및 클래스 설계
`agent/rag/retrieval/ingredient_alias_mapper.py` (신규 파일):

```python
from pydantic import BaseModel, ConfigDict, Field

class IngredientAliasEntry(BaseModel):
    """소비자 일상 표기와 공식 표준 성분명 간의 매핑 단위."""
    model_config = ConfigDict(frozen=True)

    consumer_term: str = Field(..., description="소비자가 입력하는 일상 명칭 (소문자/공백 정규화)")
    standard_name_ko: str = Field(..., description="KCIA 표준 국문명")
    description: str = Field(..., description="매핑 근거 및 비고")

class CommonIngredientAliasMapper:
    """화장품 도메인 필수 통칭 사전을 관리하고 표준명으로 변환한다."""

    def __init__(self, custom_entries: list[IngredientAliasEntry] | None = None) -> None:
        # 기본 사전 탑재 (확장 가능)
        ...

    def map_term(self, term: str) -> str:
        """소비자 표기를 표준 국문명으로 변환하며, 사전에 없으면 원본을 반환한다."""
        ...
```

#### 3) 초기 탑재 주요 화장품 통칭 목록
- **비타민 계열**:
  - `비타민C`, `비타민 C`, `vitamin c` ➔ `아스코빅애씨드`
  - `비타민B3`, `비타민 B3`, `vitamin b3` ➔ `나이아신아마이드`
  - `비타민B5`, `비타민 B5`, `프로비타민B5` ➔ `판테놀`
  - `비타민A`, `비타민 A` ➔ `레티놀`
  - `비타민E`, `비타민 E` ➔ `토코페롤`
- **진정/재생 계열**:
  - `시카`, `cica`, `병풀` ➔ `병풀추출물`
  - `티트리`, `tea tree` ➔ `티트리잎오일`
  - `어성초` ➔ `약모밀추출물`
- **각질/보습 계열**:
  - `살리실산`, `BHA`, `바하` ➔ `살리실릭애씨드`
  - `글리콜산`, `AHA`, `아하` ➔ `글라이콜릭애씨드`
  - `히알루론산`, `히알루론` ➔ `소듐하이알루로네이트`
- **탄력 계열**:
  - `EGF` ➔ `에스에이치-올리고펩타이드-1`

### 3.2 [파트 2 / 방안 A] RAG 자유 텍스트 폴백 및 조건부 게이트 완화

#### 1) `assess_information` 노드의 의도별 조건 분기 개선
`agent/nodes.py`의 `assess_information` 메서드에서 `unresolved_names`가 존재할 때의 차단 조건을 세분화합니다:

```python
# AS-IS (무조건 차단)
elif state.resolved_entities.unresolved_names:
    question = "성분명을 하나의 후보로 식별하지 못했습니다. 정확한 표시 명칭을 알려주세요."
    target_field = "ingredient_name"
    reason = "모호한 후보들을 서로 다른 확정 성분으로 취급하면 안 됩니다."

# TO-BE (의도 기반 선별 차단 및 RAG 통과)
elif state.resolved_entities.unresolved_names:
    # 상품 검색이나 루틴 생성은 제품 성분의 정확성이 필수적이므로 차단 유지
    requires_exact_ingredients = any(
        intent in parsed.intents
        for intent in (Intent.PRODUCT_DISCOVERY, Intent.ROUTINE_PLANNING)
    )
    if requires_exact_ingredients:
        question = "성분명을 하나의 후보로 식별하지 못했습니다. 정확한 표시 명칭을 알려주세요."
        target_field = "ingredient_name"
        reason = "상품 추천 및 루틴 생성 시 모호한 성분을 확정할 수 없습니다."
    elif Intent.EVIDENCE_QA in parsed.intents:
        # 지식/근거 질의인 경우, 미식별 성분이 있더라도 RAG 본문 하이브리드 검색으로 폴백 진행
        # 사용자에게 불필요한 차단 질문을 하지 않고 통과시킴
        pass
```

#### 2) `_process_evidence` 검색 파라미터 처리 유연화
`agent/nodes.py`의 `_process_evidence`:
- `target_ids`:
  - 식별된 성분이 1개 이상이면 해당 성분의 `ingredient_id` 목록 전달.
  - 모든 성분이 미식별되었거나 복합 질문인 경우 빈 리스트(`[]`) 허용.
- `SqlAlchemyHybridSearchBackend`는 `target_ids`가 비어있으면 코퍼스 전체(65,196개 청크)를 대상으로 BM25 + 벡터 검색을 자연어 `parsed.query`로 수행하여 고품질 근거 문헌을 확보합니다.

---

## 4. 변경 대상 파일 및 범위

AGENTS.md 규칙 10, 11, 15에 따라 `agent` 파트의 소유 경로만 수정하며, DB 스키마나 백엔드 공용 코드를 침범하지 않습니다.

| 구분 | 파일 경로 | 변경 내용 요약 |
| --- | --- | --- |
| **[NEW]** | `agent/rag/retrieval/ingredient_alias_mapper.py` | 일상 성분 통칭(Alias) Pydantic 모델 및 변환 매퍼 클래스 구현 |
| **[MODIFY]** | `agent/nodes.py` | 1) `resolve_entities`: 성분명 조회 전 `IngredientAliasMapper` 적용<br/>2) `assess_information`: `EVIDENCE_QA` 시 `unresolved_names` 하드 블로킹 해제 |
| **[MODIFY]** | `tests/agent/interactive_rag_cli.py` | `DbIngredientRepository`에 통칭 매퍼 연결 및 실환경 테스트 편의성 향상 |
| **[NEW]** | `tests/unit/test_ingredient_alias_and_fallback.py` | 통칭 매핑 및 RAG 폴백 상태 전이에 대한 단위 테스트 (API 호출 없음) |

---

## 5. AGENTS.md 규칙 준수 점검표

- [x] **규칙 1 (클래스 기반)**: `CommonIngredientAliasMapper` 클래스 정의
- [x] **규칙 2 (Pydantic / Enum 기반)**: `IngredientAliasEntry` 모델 정의 및 타입 힌트 준수
- [x] **규칙 3 (불확실한 내용 확인)**: 작업 전 상세 예정서를 작성하여 사용자 승인 후 착수
- [x] **규칙 4 (한국어 주석 및 "왜" 기술)**: 왜 EVIDENCE_QA는 완화하고 PRODUCT_DISCOVERY는 유지하는지 주석 명기
- [x] **규칙 5 (수정 후 3줄 요약)**: 파일 수정 후 작업 내역 보고
- [x] **규칙 6 (새 라이브러리 추가 없음)**: 기존 의존성(Pydantic, SQLAlchemy 등)만 사용
- [x] **규칙 8 (요청한 것만 수행)**: 성분 식별 및 RAG 폴백 범위를 벗어난 리팩터링 금지
- [x] **규칙 10, 11 (폴더 구조 및 import 방향)**: `agent` 내부 및 `tests/`만 수정, 역방향 import 없음
- [x] **규칙 15 (자기 파트만 구현)**: `agent` 파트 범위 엄격 준수

---

## 6. 검증 계획 (API 호출 비용 절감 방안)

사용자의 "실제 코드는 API를 호출하기 때문에 무분별하게 테스트하기 어렵다"는 요청을 최우선으로 고려합니다.

### 6.1 1단계: 단위 테스트 (API 비용 0원, Mock/Fixture 검증)
- `tests/unit/test_ingredient_alias_and_fallback.py` 작성
- Fake/Mock LLM 및 InMemory Repository를 주입하여 아래 시나리오 검증:
  1. `"비타민C"` 입력 시 `아스코빅애씨드`로 정상 치환되어 `ingredient_id` 매핑 성공 여부
  2. 사전에 없는 미지의 성분(예: `"미지의추출물"`) 입력 시:
     - `Intent.EVIDENCE_QA`: 질문 차단 없이 RAG 검색 노드(`process_task`)로 정상 전이되는지 확인
     - `Intent.PRODUCT_DISCOVERY`: 기존처럼 안전하게 `ASK_USER`로 질문 차단되는지 확인
  3. 실행 명령어:
     ```sh
     .venv/bin/pytest tests/unit/test_ingredient_alias_and_fallback.py -v
     ```

### 6.2 2단계: DB 하이브리드 검색 단위 검증 (LLM 호출 없음)
- DB의 6.5만 개 청크를 대상으로 `target_ids=[]` 전달 시 ParadeDB BM25 검색이 정상 작동하는지 단독 SQL 리포지토리 테스트로 확인.

### 6.3 3단계: 대화형 CLI 실측 검증 (최종 1회)
- `tests/agent/interactive_rag_cli.py`를 실행하여 사용자가 겪었던 질문 1회 실측:
  - 입력: `"나이아신아마이드와 비타민C의 효능"`
  - 기대 결과: 차단 없이 정상적으로 두 성분의 효능 및 배합 관련 근거 문헌 검색 및 답변 출력 확인.
