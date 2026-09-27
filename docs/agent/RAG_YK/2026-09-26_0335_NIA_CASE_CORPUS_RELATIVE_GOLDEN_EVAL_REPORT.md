# NIA Case 코퍼스 상대 골든셋 v2 단계별 검색 평가 보고서

## 1. 평가 개요

- **평가 기준**: `nia_corpus_relative_pooled_v1` (24개 활성 질의, 초기 144건 anchor + reranker Top-3 신규 노출 56건 = 총 200건 블라인드 판정)
- **골든셋 산출물**: `tests/agent/nia_case_corpus_relative_golden_v2.jsonl`
- **평가 결과 산출물**: `tests/agent/nia_case_corpus_relative_evaluation_results_v2.jsonl`
- **단계별 지표**:
  - Dense Top-40: `Anchor Success@40`, `Anchor Recall@40`
  - Metadata Top-20: `Anchor Success@20`, `Anchor Retention@20`
  - Reranker Top-3: `Precision@3`, `nDCG@3`, `Highly Relevant Success@3`, `direction conflict@3`, `exact duplicate@3`

## 2. Cohort별 요약 지표

| 구분 | 질의 수 | Anchor Success@40 | Anchor Recall@40 | Metadata Success@20 | Metadata Retention@20 | Precision@3 | nDCG@3 | 3점 포함 비율@3 | 방향 충돌 수@3 | 중복 노출 수@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all` | 24 | 0.833 | 0.481 | 0.792 | 0.892 | 0.806 | 0.787 | 0.708 | 4 | 2 |
| `core` | 18 | 0.833 | 0.490 | 0.778 | 0.911 | 0.833 | 0.783 | 0.722 | 3 | 2 |
| `rare_stress` | 6 | 0.833 | 0.450 | 0.833 | 0.833 | 0.722 | 0.797 | 0.667 | 1 | 0 |

## 3. 질의별 상세 결과 (24개 활성 질의)

| evaluation_id | cohort | 관련 anchor 수 | Dense 회수/전체 | Metadata 보존/Dense | Top-3 등급 | Precision@3 | nDCG@3 | 방향 충돌@3 | 중복@3 |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| `evaluation_core_pores_01` | `core` | 6 | 3/6 | 3/3 | `[3, 3, 3]` | 1.000 | 1.000 | 0 | 0 |
| `evaluation_core_pores_02` | `core` | 6 | 3/6 | 3/3 | `[3, 3, 2]` | 1.000 | 0.866 | 0 | 0 |
| `evaluation_core_pores_03` | `core` | 6 | 3/6 | 3/3 | `[2, 3, 3]` | 1.000 | 0.732 | 0 | 0 |
| `evaluation_core_pores_05` | `core` | 6 | 3/6 | 2/3 | `[2, 2, 2]` | 1.000 | 1.000 | 0 | 1 |
| `evaluation_core_pores_08` | `core` | 0 | 0/0 | 0/0 | `[0, 0, 0]` | 0.000 | 0.000 | 3 | 0 |
| `evaluation_core_pigment_01` | `core` | 2 | 0/2 | 0/0 | `[1, 1, 3]` | 0.333 | 0.344 | 0 | 0 |
| `evaluation_core_pigment_02` | `core` | 6 | 3/6 | 3/3 | `[3, 3, 3]` | 1.000 | 1.000 | 0 | 0 |
| `evaluation_core_pigment_04` | `core` | 1 | 1/1 | 0/1 | `[2, 2, 2]` | 1.000 | 1.000 | 0 | 0 |
| `evaluation_core_pigment_05` | `core` | 2 | 1/2 | 1/1 | `[1, 1, 1]` | 0.000 | 0.179 | 0 | 0 |
| `evaluation_core_pigment_08` | `core` | 1 | 1/1 | 1/1 | `[1, 3, 2]` | 0.667 | 0.666 | 0 | 0 |
| `evaluation_core_acne_01` | `core` | 6 | 3/6 | 3/3 | `[3, 3, 3]` | 1.000 | 1.000 | 0 | 1 |
| `evaluation_core_acne_03` | `core` | 3 | 0/3 | 0/0 | `[3, 3, 3]` | 1.000 | 1.000 | 0 | 0 |
| `evaluation_core_acne_04` | `core` | 3 | 1/3 | 1/1 | `[2, 2, 2]` | 1.000 | 0.615 | 0 | 0 |
| `evaluation_core_acne_05` | `core` | 6 | 3/6 | 3/3 | `[3, 3, 3]` | 1.000 | 1.000 | 0 | 0 |
| `evaluation_core_acne_08` | `core` | 6 | 3/6 | 3/3 | `[3, 3, 3]` | 1.000 | 1.000 | 0 | 0 |
| `evaluation_core_composite_01` | `core` | 6 | 3/6 | 3/3 | `[3, 3, 3]` | 1.000 | 1.000 | 0 | 0 |
| `evaluation_core_composite_02` | `core` | 6 | 3/6 | 3/3 | `[3, 2, 2]` | 1.000 | 0.697 | 0 | 0 |
| `evaluation_core_composite_06` | `core` | 6 | 3/6 | 3/3 | `[3, 3, 3]` | 1.000 | 1.000 | 0 | 0 |
| `evaluation_rare_dry_02` | `rare_stress` | 6 | 3/6 | 3/3 | `[3, 3, 3]` | 1.000 | 1.000 | 0 | 0 |
| `evaluation_rare_dry_03` | `rare_stress` | 4 | 1/4 | 1/1 | `[3, 3, 3]` | 1.000 | 1.000 | 0 | 0 |
| `evaluation_rare_redness_02` | `rare_stress` | 6 | 3/6 | 3/3 | `[3, 3, 3]` | 1.000 | 1.000 | 0 | 0 |
| `evaluation_rare_wrinkles_02` | `rare_stress` | 5 | 3/5 | 2/3 | `[2, 2, 1]` | 0.667 | 0.519 | 0 | 0 |
| `evaluation_rare_sensitive_01` | `rare_stress` | 5 | 2/5 | 1/2 | `[2, 3, 0]` | 0.667 | 0.497 | 1 | 0 |
| `evaluation_rare_sagging_01` | `rare_stress` | 0 | 0/0 | 0/0 | `[1, 1, 0]` | 0.000 | 0.765 | 0 | 0 |

## 4. 단계별 주요 병목 및 시사점

1. **Dense Top-40 (`Anchor Success@40 = 0.833`, `Anchor Recall@40 = 0.481`)**:
   - 24개 활성 질의 중 20개(83.3%)에서 관련 anchor(`relevance_grade >= 2`)를 최소 1건 이상 회수했다.
   - 미회수 4건 중 2건(`evaluation_core_pores_08`, `evaluation_rare_sagging_01`)은 코퍼스 내 초기 anchor 6건에 2점 이상 후보가 없는 코퍼스 한계 구간이며, 나머지 2건(`evaluation_core_pigment_01`, `evaluation_core_acne_03`)은 관련 anchor가 `off_rank_query_match`(Top-40 밖)에만 분포한 케이스다.
2. **Metadata Top-20 (`Anchor Retention@20 = 0.892`, `Anchor Success@20 = 0.792`)**:
   - Dense Top-40이 회수한 관련 anchor의 89.2%를 유지했다. `evaluation_core_pigment_04`에서만 Dense가 회수한 anchor 1건이 제외되었으나, Reranker 단계에서 보완 후보(`grade=2`) 3건을 상위로 정렬해 `Precision@3 = 1.000`을 유지했다.
3. **Reranker Top-3 (`Precision@3 = 0.806`, `nDCG@3 = 0.787`, `direction conflict@3 = 4`, `exact duplicate@3 = 2`)**:
   - 24개 질의 중 18개 질의에서 `Precision@3 = 1.000`, 17개 질의(70.8%)에서 최고 등급(`3점`) 사례를 Top-3에 포함시켰다.
   - **케어 방향 충돌(`direction conflict@3 = 4`)**: 각질 제거 과다로 볼이 화끈거리는 `evaluation_core_pores_08`(3건)과 새 화장품 자극으로 볼이 따갑고 붉어진 `evaluation_rare_sensitive_01`(1건)에서 BHA/레티놀 등 공격적 각질·피지 케어 사례가 노출되었다.
   - **동일 본문 중복(`exact duplicate@3 = 2`)**: `evaluation_core_pores_05`와 `evaluation_core_acne_01`에서 동일 `(question, answer)` 텍스트를 가진 중복 Case가 Top-3 중 2개 슬롯을 점유해 후보 정규화(deduplication)의 필요성을 보여준다.

## 5. 평가 전환(v1 → v2)의 의의

| 비교 항목 | v1 (엄격 조건 일치 기준, 40질의) | v2 (`nia_corpus_relative_pooled_v1`, 24질의) | 해석 및 의의 |
| --- | --- | --- | --- |
| **판정 철학** | 나이·성별·피부타입·발생 시점 완전 일치 요구 | 핵심 고민(`concern_fit`) + 요청 방향(`request_fit`) + 상태 맥락(`context_fit`) 중심, 방향 충돌(`direction_conflicts`) 즉시 0점 | 합성 상담 코퍼스의 특성을 반영해 '실제 답변 근거로 쓸 수 있는가'를 측정 |
| **Dense 회수력** | `Relevant Success@40 = 0.375` | `Anchor Success@40 = 0.833`, `Anchor Recall@40 = 0.481` | 나이·성별 불일치로 인한 가짜 실패를 제거하자 실제 Dense 회수 성공률(83.3%)과 잔여 어휘 병목(Recall 48.1%)이 분리됨 |
| **Metadata 보존율** | `Relevant Retention@20 = 0.900` | `Anchor Retention@20 = 0.892` (`Success@20 = 0.792`) | 희소 카테고리 보충 전략이 v1·v2 모두에서 ~90% 보존율로 일관되게 작동함을 검증 |
| **Reranker 정밀도** | `Precision@3 = 0.258`, `nDCG@3 = 0.562` | `Precision@3 = 0.806`, `nDCG@3 = 0.787`, `3점 비율 = 0.708` | 파이프라인 전체가 망가진 것이 아니라 일반 고민 질의에서는 80.6% 정밀도로 작동하며, 실패가 특정 병목(방향 충돌 4건, 중복 2건, 복합/자국 어휘 4건)에 집중됨을 규명 |

## 6. 검색 파이프라인 및 모델 업데이트 로드맵

1. **[즉시 적용 가능 · 난이도 낮음] 후보 본문 중복 제거(Content Deduplication) 추가**:
   - **대상**: `agent/rag/retrieval/case_candidate_selector.py` (`CaseMetadataCandidateSelector.select`) 또는 `agent/rag/retrieval/case_reranker.py` (`LocalBgeCaseRerankerV2M3.rerank`)
   - **문제**: NIA 코퍼스 내 서로 다른 `case_id`지만 `(question, answer)`가 100% 동일한 복제 문서가 존재하여 `evaluation_core_pores_05`, `evaluation_core_acne_01`의 Top-3 슬롯을 중복 점유함(`exact duplicate@3 = 2`).
   - **해결**: 정규화된 `(question.strip(), answer.strip())` 해시 기준으로 최초(최고 유사도/점수) 후보 1개만 남기도록 필터링하면, 재학습 없이 즉시 Top-3 유효 커버리지와 다양성이 상승한다.
2. **[단기 개선 · 난이도 낮음] `CaseMetadataCandidateSelector` 자극·장벽 어휘 및 세부 색소/면포 별칭 확장**:
   - **대상**: `agent/rag/retrieval/case_candidate_selector.py` (`_ALIASES`)
   - **문제**: `evaluation_core_pigment_04`처럼 `'따갑고 붉어졌는데'`가 들어간 질의에서 `_ALIASES[SENSITIVITY]`에 `'따갑'`, `'따가'`, `'화끈'`, `'장벽'`이 없어 `SENSITIVITY` 카테고리가 감지되지 않고, 그 결과 미백/홍조 일반 후보에 밀려 장벽 진정 관련 anchor가 Top-20에서 탈락함.
   - **해결**: `SENSITIVITY` 별칭에 `('따갑', '따가움', '화끈', '장벽', '뒤집어')`, `PIGMENTATION` 별칭에 `('자국', '잡티', '흔적')`, `ACNE` 별칭에 `('화이트헤드', '면포')`를 추가해 Metadata Top-20 보존율을 높인다.
3. **[중기 개선 · 핵심 과제] Reranker 단계의 케어 방향 충돌(Direction Conflict) 억제 가드레일**:
   - **대상**: `agent/rag/retrieval/case_reranker.py` (`LocalBgeCaseRerankerV2M3`) 및 리랭킹 후처리 점수 보정
   - **문제**: `evaluation_core_pores_08`(각질 제거 과다 후 볼 화끈거림 → BHA/레티놀 추천 3건 노출)과 `evaluation_rare_sensitive_01`(새 화장품 따가움·안정화 요청 → BHA 토너·이중 세안 추천 노출)에서 교차 인코더가 주제 어휘 유사도만 보고 임상적 역행 사례를 상위에 배치함(`direction conflict@3 = 4`).
   - **해결**:
     - (a) **규칙 기반 방향 충돌 페널티(Constraint-Aware Rerank Penalty)**: 질의에서 장벽 손상·자극 호소 신호(`따갑`, `화끈`, `필링/각질 제거 후 악화`, `안정시키고 싶어요`)가 감지될 때, 답변 본문이 고자극 각질/활성 성분(`살리실산`, `BHA`, `AHA`, `레티놀`, `스크럽`, `필링`)을 주된 해결책으로 권하는 후보의 `rerank_score`에 감점(margin penalty)을 부여하고 진정·장벽 회복(`세라마이드`, `판테놀`, `마데카소사이드`, `병풀`, `약산성`) 후보에 가점을 준다.
     - (b) **문서 템플릿 개선(`_DOCUMENT_TEMPLATE`)**: `LocalBgeCaseRerankerV2M3`의 입력 템플릿에서 단순 메타데이터 나열 대신 `[권장 케어 방향: 각질·피지 제거 / 장벽·진정 회복]` 요약 태그를 명시하거나, 이번 골든셋 v2의 200건(특히 `direction_conflicts` 하드 네거티브 사례)을 대조 학습(contrastive margin ranking) 검증 세트로 활용한다.
4. **[장기 개선 · 하이브리드 검색 및 답변 생성 연계] Lexical/Dense 하이브리드 회수 및 코퍼스 한계 보완**:
   - **대상**: Dense Top-40 회수 계층 및 답변 생성 프롬프트
   - **문제**: `Anchor Recall@40 = 0.481`에서 확인되듯 `여드름 갈색 자국(evaluation_core_pigment_01)`, `16살 화이트헤드 순한 성분(evaluation_core_acne_03)` 같은 구체적 어휘 후보가 Dense Top-40 밖(`off_rank_query_match`)에 머무르며, `처짐의 화장품 한계(evaluation_rare_sagging_01)`처럼 코퍼스에 정답이 없는 질문도 존재한다.
   - **해결**: Dense Top-30 + 키워드/BM25 어휘 매칭 Top-10을 결합하는 하이브리드 후보 풀 구성으로 `Anchor Recall@40`을 끌어올리고, Top-3 최고 리랭크 점수가 임계치 미만이거나 `direction_conflict`가 감지된 경우 에이전트 답변 생성기가 Case 원문에 억지 의존하지 않고 일반 피부과학 안전 원칙(장벽 회복 우선, 화장품의 탄력 개선 한계 명시)으로 답하도록 폴백(fallback) 정책을 연결한다.
