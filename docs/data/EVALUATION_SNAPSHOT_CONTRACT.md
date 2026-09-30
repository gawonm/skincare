# 평가 Snapshot 계약 (T5)

> - generated_at: 2026-09-30 / 코드 기준 commit `ea915de`
> - DB: `skincare_reference_20260923_v5_2` (SELECT 전용) — Alembic `cdff29b164d8`
> - Data manifest: `evaluation_baseline_manifest.json` (로컬 생성물, git 미추적. 값은 아래 §3 표와 같다)
> - 이 문서는 **제안**이다. Agent 쪽 fixture는 만들지 않았고 Agent/Backend 파일도 수정하지 않았다.

## 0. 먼저 알아야 할 한계

- **Q01~Q05 raw 로그(`data/outputs/e2e_trace/Q0*.log`)는 이 저장소·이 맥 어디에도 없다.** gitignore 대상이라
  실행한 PC에만 있다. 이 문서의 Q 가용성(§6)은 로그가 아니라 Notion WBS 3.3.2 페이지의 질의별 요약 기록을
  근거로 했다. 따라서 §6은 **하한선**이다. raw 로그를 받으면 PARTIAL/NOT_AVAILABLE 일부가 AVAILABLE로 바뀔 수 있다.
- Q01~Q05가 실행된 DB의 이름과 commit은 저장소에 기록돼 있지 않다. 이 manifest의 DB는 같은 dump 계열의 기준 DB이고,
  이전 측정 기준값(3,581 / 2,262 / 84,390 / 128 / 8,487)과 행 수가 일치한다. 내용 동일성은 검증하지 못했다.
- 새 E2E 실행과 LLM 호출은 하지 않았다.

## 1. 목적

Agent/Backend가 Case 정합 정책, Evidence 표현, 상품 후보 관련성, 루틴 품질 검증을 바꾸기 전후로 **같은 데이터
상태·같은 Q01~Q05 baseline**을 놓고 비교할 수 있게, 무엇을 누가 고정할지 정한다.

## 2. 소유 구분

| 구분 | 소유 | 보존 대상 |
| --- | --- | --- |
| A. Data state manifest | Data/RAG | 데이터 상태 식별 (DB, Alembic, 행 수, 모델·버전 메타데이터, 원천 데이터셋 식별자) |
| B. 시나리오 fixture | Agent | Agent 파이프라인이 만든 중간·최종 결과 |

경계 원칙: Data는 "어떤 데이터에서 나온 baseline인가"만 책임진다. 파이프라인 결과(Case, Claim, 루틴)는 Agent가 보존한다.
fixture 형식의 확정은 Agent 파트 결정이며, 공용 계약이 필요하면 `docs/contracts/`에서 합의한다(규칙 16).

## 3. A. Data State Manifest

파일: `evaluation_baseline_manifest.json`(git 미추적, 로컬 보관). 아래 표가 그 내용이다. 현재 값은 DB SELECT로 확인했다.

| 필드 | 현재 값 | 비고 |
| --- | --- | --- |
| `manifest_version` | `"1"` | 필드 추가는 minor, 의미 변경은 major(§7) |
| `data_state_id` | `skincare-ref-v5_2__alembic-cdff29b164d8__manifest-1` | §5 |
| `db_name` | `skincare_reference_20260923_v5_2` | |
| `alembic_revision` | `cdff29b164d8` | dump 원본 revision은 `9f4c2a7d8e61` (Notion 기록) |
| `row_counts.nia_case_document` | 3,581 | |
| `row_counts.product` | 2,262 | |
| `row_counts.product_ingredient_snapshot` / `product_ingredient` | 2,216 / 84,390 | |
| `row_counts.ingredient_master` | 21,974 | 성분 해석 사전 |
| `row_counts.evidence_document` / `evidence_chunk` | 128 / 8,487 | |
| `corpus_versions.nia_case_document.text_version` | `nia_case_text/v1` | 3,581건 전부 |
| 임베딩 | `BAAI/bge-m3`, 1024차원 | Case 3,581 / Evidence 8,487 전부 벡터 있음 |
| 벡터 인덱스 | HNSW (근사 검색) | §4 판단에 영향 |
| `runtime_models_reported.reranker_model` | `BAAI/bge-reranker-v2-m3` | 출처 Notion. 실행 당시 config는 미기록 |
| `dump.sha256` | `null` | 복원 DB와 dump 동일성 미검증이라 기록하지 않음 |
| `baseline_run.executed_db_name` / `executed_git_commit` | `null` | 저장소에 기록 없음 |
| `chat_model` | `null` | 실행 당시 값 미기록 |

## 4. 스냅샷 정책 (코드 확인 결과)

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| 요청 해석·intent (`LlmClient.understand`) | **SNAPSHOT_REQUIRED** | [agent/llm.py:22-33](../../agent/llm.py) `ChatOpenAI`에 temperature·seed 지정 없음 → 동일 입력에도 결과가 달라질 수 있다 |
| Case 관련 성분 선별 (LLM claim extraction) | **SNAPSHOT_REQUIRED** | [case_claim_extractor.py:24-116](../../agent/rag/case_claim_extractor.py) 같은 이유로 비결정적. 가설이 코드로 확인됨 |
| 최종 LLM 답변 문구 | NOT_NEEDED | 루틴 구조·상태 비교에는 불필요. 문구 대신 구조(슬롯, 상품, status)를 고정 |
| Dense 검색 결과 (Top-40, score) | RECOMPUTABLE | 로컬 BGE-M3 + 같은 코퍼스. 단 HNSW는 근사 검색이라 인덱스 재생성 시 순서가 달라질 수 있어 **Top-40 ID는 drift 확인용으로 함께 기록 권장** |
| rerank score / Top-3 | RECOMPUTABLE (결과 ID는 baseline 산출물로 SNAPSHOT_REQUIRED) | 로컬 cross-encoder라 같은 모델·입력이면 재계산 가능. 다만 baseline **결과** Top-3는 비교 기준이므로 고정 |
| 성분 해소 (`IngredientMentionResolver`) | RECOMPUTABLE | [ingredient_mention_resolver.py](../../agent/rag/retrieval/ingredient_mention_resolver.py)는 주입된 사전만 쓰는 순수 매칭. 입력이 LLM이 고른 이름이므로 그 이름이 고정되면 결정적. 결과 ID는 확인용으로 기록 |
| Evidence 검색 | RECOMPUTABLE | 같은 Evidence 코퍼스·모델이면 재계산. 결과 ID는 baseline 산출물로 기록 |
| Product 검색 | RECOMPUTABLE | 같은 product·매핑 상태이면 재계산. 결과 ID·카테고리·성분 ID 기록 |
| 정렬 동점(tie) 순서 | 미확인 | 상품·Evidence 정렬의 tie-break는 확인하지 않았다. Agent가 fixture 검증 시 확인 |

정리: **LLM이 관여하는 두 곳(요청 해석, 성분 선별)만 입력 측 SNAPSHOT_REQUIRED**이고, 나머지는 데이터 상태가 같으면
재계산 가능하다. 그래서 Data가 데이터 상태를 고정하고 Agent가 두 LLM 출력을 고정하면 baseline이 재현된다.

## 5. `data_state_id`

```
<manifest 종류>-<DB 계열>__alembic-<revision 12자리>__manifest-<버전>
현재: skincare-ref-v5_2__alembic-cdff29b164d8__manifest-1
```

- 사람이 읽으면 어떤 DB 계열(v5_2), 어떤 스키마(Alembic)인지 알 수 있다.
- 날짜를 넣지 않는다. 같은 상태를 다른 날 다시 측정해도 ID가 같아야 하기 때문이다. 상태가 바뀌면 §7 규칙으로 `v5_3`
  처럼 계열 이름이 바뀐다.
- dump 해시는 ID에 넣지 않았다. 동일성을 검증하지 못했다.

## 6. Q01~Q05 필드 가용성 (Notion 요약 기준, raw 로그 미확인)

표기: A=AVAILABLE, P=PARTIAL, N=NOT_AVAILABLE.

| 필드 | Q01 | Q02 | Q03 | Q04 | Q05 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| scenario_id, user_query | A | A | A | A | A | |
| intent | N | A `evidence_qa` | A `evidence_qa` | A `product_discovery` | A `routine_planning` | Q01은 미기재 |
| final status | A `partial` | A `completed` | A `completed` | A `completed` | A `partial` | |
| Top-3 Case ID | N | N/A (Case 미실행) | N/A | N/A | N | Q01·Q05 ID 미기재 |
| target_concern | N | N/A | N/A | N/A | P | Q05: "미백 2건 + 민감성 1건"으로만 기재, 순서·ID 없음 |
| rerank score | N | N/A | N/A | N/A | N | |
| Dense 상위 Case | N | N/A | N/A | N/A | P | Q05: "민감성 Case가 Top-40 상위에 존재"는 기재, ID·순위 없음 |
| 추출 claim/성분명 | P | N/A | N/A | N/A | P | Q05: ALOESIN, Hexapeptide-2 등 일부 이름만. Q01: 티트리(미해소), 살리실릭애씨드, 나이아신아마이드 |
| resolved ingredient ID | N | N | N | N | N | "정상 확정"이라는 서술만 있고 UUID 없음 |
| Evidence 결과 | P | P 5건 검색 | P 5건 검색, 3건 채택 | N/A | P 4개 성분 모두 no_results | Evidence ID·source_type 미기재. 전부 unreviewed(Q01·Q03) |
| RecommendationBasis | N | N | N | N | N | |
| Product ID / 개수 | P (PASS만) | N/A | N/A | P 5개 | P 20건 | ID 미기재. Q05는 exfoliating cleanser, retinol eye cream 노출이 서술됨 |
| Product category / 성분 ID | N | N/A | N/A | P 케어/세안/미분류 언급 | N | |
| 최종 루틴 | N/A | N/A | N/A | N/A | P 형식 생성됨, 품질 FAIL | 루틴 슬롯 내용 미기재 |

Q05 요구 항목별 결론

| 항목 | 상태 | 내용 |
| --- | --- | --- |
| Dense 상위 Case | PARTIAL | 존재는 확인, ID·순위·점수 없음 |
| rerank Top-3 | PARTIAL | 구성(미백 2 + 민감성 1)만 있고 ID·점수 없음 |
| target_concern | PARTIAL | 종류별 개수만 |
| resolved ingredient | PARTIAL | 대상 성분 4개, 이름 일부만. UUID 없음 |
| Evidence no_results | AVAILABLE | 4개 성분 모두 no_results |
| product candidates | PARTIAL | 20건 성공, ID 없음 |
| final routine | PARTIAL | 형식 생성 여부만, 내용 없음 |

결론: **Notion 요약만으로는 제안 fixture의 대부분(ID 계열, 점수)을 채울 수 없다.** 그 값은 raw 로그에 있을 수 있으나
(로그는 `--verbose` 트레이스 출력) 이 세션에서는 읽지 못했다. Agent가 fixture를 만들려면 어차피 새로 뽑아야 하는
값이 많다.

## 7. 버저닝 규칙

- `manifest_version`: 필드 추가·설명 변경은 minor, 필드 삭제·의미 변경은 major.
- `data_state_id`의 DB 계열 이름(`v5_2`)은 §8에서 REGENERATE_REQUIRED가 되는 변경이 생길 때만 올린다.
- baseline은 하나의 `data_state_id`에 묶는다. 다른 ID의 baseline과 비교 결과를 섞지 않는다.

## 8. Baseline 재생성 조건

| 변경 | 판정 | 이유 |
| --- | --- | --- |
| NIA corpus 변경 (행·`text_version`) | REGENERATE_REQUIRED | Case 후보 자체가 바뀜 |
| Evidence corpus 변경 | REGENERATE_REQUIRED | Evidence 결과가 바뀜 |
| Product / product_ingredient 변경 | REGENERATE_REQUIRED | 상품 후보·성분 연결이 바뀜 |
| ingredient_master 변경 | REGENERATE_REQUIRED | 성분 해소 결과가 바뀜 |
| embedding 모델 변경 | REGENERATE_REQUIRED | 모든 검색 순위가 바뀜 |
| embedding 재생성(같은 모델) | REGENERATE_REQUIRED (Top-40 ID가 같으면 REUSE_ALLOWED) | HNSW 근사 검색이라 순서가 미세하게 달라질 수 있음 |
| reranker 변경 | REGENERATE_REQUIRED | Top-3가 바뀜 |
| Claim extraction prompt/model 변경 | 성분 선별 fixture만 REGENERATE_REQUIRED, 데이터 baseline은 REUSE_ALLOWED | LLM 출력만 달라짐 |
| DB migration | 데이터 변경 없는 스키마 변경(컬럼 추가 등)은 REUSE_ALLOWED, `alembic_revision`은 manifest 갱신 | `9f4c2a7d8e61 → cdff29b164d8`(`product.view_count` 추가)처럼 결과에 영향 없는 것은 재사용 가능. 단 판단은 행·값 변경 여부로 한다 |
| Agent 코드(정책·validator) 변경 | REUSE_ALLOWED | 비교 대상이 바로 이것이라 baseline을 유지해야 함 |
| 코드 변경 없이 DB 값만 backfill(예: `service_category` NULL 154건) | REGENERATE_REQUIRED | 상품 역할 분류가 바뀜 |

## 9. Agent fixture 스키마 제안 (파일 생성 없음)

Agent가 만들 fixture에 필요한 필드만 제안한다. 위치·이름·타입은 Agent 소유 결정이다.

```python
class SnapshotSource(StrEnum):
    CAPTURED_LLM_OUTPUT = "captured_llm_output"   # 재실행 금지, 그대로 재생
    BASELINE_RESULT = "baseline_result"           # 비교 기준. 재계산 결과와 대조

class ScenarioFixture(BaseModel):
    data_state_id: str                       # Data manifest 와 연결
    scenario_id: str                         # Q01 ~ Q05
    user_query: str
    parsed_request: ...                      # SNAPSHOT_REQUIRED: intent 등 (captured_llm_output)
    dense_top40_case_ids: list[str]          # drift 확인용
    final_top3_cases: list[CaseRef]          # case_id, target_concern, rerank_score
    selected_ingredients: list[SelectedIngredient]   # raw_name, source_quote, case_id (captured_llm_output)
    resolved_ingredient_ids: list[str]
    evidence: list[EvidenceRef]              # evidence id, source_type, RecommendationBasis
    products: list[ProductRef]               # product_id, category, confirmed ingredient_ids
    routine: ...                             # 최종 루틴 구조
    final_status: str
```

## 10. 남은 일

1. raw 로그(`Q01.log`~`Q05.log`)를 받아 §6의 PARTIAL/NOT_AVAILABLE을 다시 판정한다. (사용자에게 로그 전달 필요)
2. Agent가 §4의 두 LLM 출력을 포함한 fixture를 만든다 (Agent 파트).
3. `baseline_run.executed_db_name`, `executed_git_commit`, 실행 당시 chat 모델을 Q01~Q05를 실행한 PC에서 확인해 manifest를
   채운다. 그 전에는 `null`로 둔다.
