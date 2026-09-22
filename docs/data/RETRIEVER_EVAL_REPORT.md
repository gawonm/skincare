# Retriever Evaluation Report

## 범위와 방법

canonical `skincare_reference_2026-09-22_v5.dump`(SHA-256
`48d8ef1411d6a2f066b4b554aed2003ef379723934daffe07cc1770e1755b3e5`)를 별도
read-only 평가 DB(`evidence_retriever_eval`)에 복원해 **production Evidence
retriever 코드를 한 줄도 고치지 않고 그대로 호출**했다. 평가가 끝난 뒤 이
임시 DB는 drop했다.

### 실제로 호출한 production 코드

- `agent/rag/retrieval/hybrid_retriever.py::HybridEvidenceRetriever` (벡터+BM25
  RRF 융합, source lane 1차/폴백, reranker 적용까지 전부 실제 경로)
- `backend/services/two_layer_rag_adapters.py::TwoLayerEvidenceSearchBackend`
  (production Evidence 검색 backend - `rag_chunk`를 쓰는 구형
  `SqlAlchemyHybridSearchBackend`이 아니라, 지금 실제로 `evidence_document`/
  `evidence_chunk`를 조회하는 쪽)
- `backend/repositories/evidence_search_repository.py::EvidenceSearchRepository`
  (벡터/텍스트 SQL 자체)
- `agent/rag/embedding/local_embedder.py`(BGE-M3, `TextEmbedderFactory` 경유),
  `agent/rag/retrieval/local_reranker.py::LocalBgeRerankerV2M3` +
  `cross_encoder.py::LocalBgeCrossEncoderScorer`(bge-reranker-v2-m3) - 둘 다
  로컬 캐시된 모델로 실행, production과 동일 조합
- `agent/rag/retrieval/ingredient_alias_mapper.py::CommonIngredientAliasMapper`
  (BHA/AHA 등 모호 성분군 판정)

DB는 읽기 전용 연결만 썼고(`SELECT`만), Agent/Backend/Model 코드는 전혀 수정하지
않았다. 코드: `data/scripts/retriever_eval.py` +
`data/scripts/retriever_eval_schemas.py`(둘 다 새 파일, production 코드
import만 한다). 단위 테스트: `tests/unit/test_retriever_eval.py`(채점 로직만,
DB/모델 미사용).

### 평가에서 직접 고른 값 (production 기본값 아님)

`config.yaml`에 `agent.retrieval` 블록이 없어 `free_text_min_vector_similarity`가
설정돼 있지 않다(`core/config.py`의 기본값은 `None`이고, 값을 안 주면
`tests/agent/interactive_two_layer_rag_cli.py`도 동일하게 `RuntimeError`를
던진다 - 이 프로젝트에 정해진 production 값 자체가 없다는 뜻). 이 평가에서는
`0.3`(BGE-M3 코사인 유사도 완만한 컷오프)을 직접 골라 썼다. `rrf_k=60`,
`rerank_candidate_limit=30`은 `core/config.py`의 실제 기본값을 그대로 썼다.

### 케이스 설계

target_ids는 실제 성분명(예: "Niacinamide")을 `ingredient_master`에서
읽기 전용으로 조회해 확정했다(성분명 -> ingredient_id 해석 자체는 이번 평가의
대상이 아니라, 검색 자체를 평가하기 위한 입력 준비 단계다). "bare BHA
ambiguity" 케이스만 예외로, `CommonIngredientAliasMapper`(production 코드)를
직접 호출해 모호 판정 여부를 확인했다. 질의 문장은 실제 서비스가 한국어
UI라는 점을 반영해 한국어로 작성했다 - `QuestionIntentClassifier`(source
lane을 결정하는 production 코드)가 한국어 키워드만 인식하기 때문에, 영어
케이스 라벨을 그대로 영어 질의로 보내면 precaution/regulation lane이 전혀
트리거되지 않아 그 자체가 왜곡된 평가가 된다.

## 결과 요약

| case_id | verdict | failure classification |
| --- | --- | --- |
| niacinamide_efficacy | PASS | - |
| niacinamide_barrier_sebum | PASS | - |
| retinol_efficacy | PASS | - |
| retinol_precaution | PASS | - |
| salicylic_acid_efficacy | PASS | - |
| salicylic_acid_precaution | PASS | - |
| ascorbic_acid | **FAIL** | AGENT-RETRIEVAL |
| sodium_ascorbyl_phosphate | PASS | - |
| capryloyl_salicylic_acid | PASS | - |
| tranexamic_acid | PASS | - |
| adenosine_safety | PASS | - |
| hyaluronic_acid_family | PASS | - |
| centella_madecassoside | PASS | - |
| bare_bha_ambiguity | PASS | - |
| zero_evidence_ingredient | PASS | - |
| mfds_regulatory_query | PASS | - |

**16 cases / 15 pass / 1 fail**

## 지표

| 지표 | 값 | 비고 |
| --- | --- | --- |
| Ingredient Hit@3 | 14/14 (100%) | SINGLE 모드 케이스만(모호/zero-evidence 2건 제외) |
| Ingredient Hit@5 | 14/14 (100%) | 〃 |
| Ingredient Precision@5 | 평균 1.00 | 14건 전부 top-5가 전부 예상 성분 |
| Expected Source Hit@5 | 14/14 (100%) | ascorbic_acid도 source는 맞았음(claim_topic만 실패) |
| Claim Topic Hit@5 | 13/14 (92.9%) | ascorbic_acid 1건 실패 |
| Forbidden Ingredient Hit count | 0 | 공유 CIR 문서(Ascorbic Acid/Sodium Ascorbyl Phosphate, Salicylic Acid/Capryloyl Salicylic Acid, Hyaluronic Acid family) 전부 chunk 단위로 정확히 분리됨 |
| Citation Metadata Completeness | 15/16 케이스(93.75%) | `hyaluronic_acid_family`에서 CIR chunk 4건의 `url`이 canonical에 원래 비어 있음(아래 finding 참고) |
| Zero-evidence False Positive count | 0 | `zero_evidence_ingredient` 케이스가 정확히 빈 결과 반환 |

## 유일한 실패: `ascorbic_acid`

- 질의: "아스코빅애씨드(비타민C) 효능이 궁금해요", target_ids=[Ascorbic Acid].
- top-5가 전부 CIR 안전성 보고서의 `precaution` chunk 5건이었고, 같은 성분에
  실제로 존재하는 PubMed `efficacy` chunk 3건(`evidence_chunk_ingredient` 기준
  확인됨)은 하나도 top-5에 들지 못했다.
- **분류: AGENT-RETRIEVAL.** DB 확인 결과 해당 claim_topic의 evidence 자체는
  존재하므로(DATA 문제 아님) 랭킹/후보 다양성 쪽 문제로 판단했다 - CIR
  document 한 건이 chunk 19개(전부 precaution)를 갖고 있어, 같은 target_id
  안에서 벡터·재랭커 점수가 근소하게 앞선 CIR chunk들이 PubMed efficacy
  chunk를 top-5 밖으로 밀어낸 것으로 보인다. 근본 원인(재랭커 점수 산정,
  fusion 시 문서당 후보 수 제한 여부 등)은 이번 평가 범위 밖이라 코드를
  고치지 않았다 - 확인만 하고 넘긴다.

## 추가 finding(실패로 세지는 않았지만 기록)

- **Citation Metadata Completeness 미달**: `hyaluronic_acid_family` 케이스의
  top-5 중 CIR chunk 4건(`Safety Assessment of Hyaluronates as Used in
  Cosmetics`)이 `evidence_document.url`/`evidence_chunk.url` 둘 다 비어 있다.
  이 문서는 이번 세션 초반에 처리한 "기존 CIR 8개 reuse" 대상 중 하나로,
  canonical DB에 원래부터 url이 없던 상태였다(이번 write에서 건드리지 않은
  기존 canonical 데이터). **분류: DATA.** 검색 자체는 정확했고(성분/오류
  없음), 인용 메타데이터 한 필드가 비어 있을 뿐이다.

## 산출물

- `data/outputs/evidence_coverage/retriever_eval_results.csv` (16 케이스 ×
  top-5 chunk, case당 결과 없으면 1행만)
- `docs/data/RETRIEVER_EVAL_REPORT.md` (이 문서)

## 판정

`READY_FOR_E2E_EVAL: YES`

16개 케이스 중 15개가 통과했고, 유일한 실패(`ascorbic_acid`)와 하나의 finding
(`hyaluronic_acid_family` 인용 메타데이터)은 둘 다 즉시 코드 수정 없이 분류만
해서 남겼다(지시대로). 모호 성분군(BHA) 판정과 zero-evidence 성분 처리
모두 안전하게 동작해, 다음 단계(E2E 평가)로 넘어가는 데 걸리는 치명적
blocker는 없다.
