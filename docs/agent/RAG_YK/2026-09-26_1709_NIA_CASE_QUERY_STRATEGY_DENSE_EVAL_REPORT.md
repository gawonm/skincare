# NIA Case 단일 질의 구성 Dense Top-40 비교

## 실험 목적과 통제 조건

- `concern_summary`: 핵심·보조 고민명만 남긴 축약 하한선
- `profile_summary`: 나이·성별·계절·피부 타입·고민과 `피부 관련 성분 및 주의사항`을 결합한 기존 형식의 요약 질의
- `context_preserved`: 나이·피부 타입·계절·부위·증상·요청 방향을 포함한 평가용 사용자 원문
- 공통 조건: `BAAI/bge-m3`, 동일 DB, 동일 24개 질의, 동일 골든셋 v4, 질의당 Top-40
- 이 단계에서는 metadata selector와 reranker를 적용하지 않았다.

## 집계 결과

| 구분 | 전략 | Success@20 | Recall@20 | Success@40 | Recall@40 | MRR@40 | nDCG@40 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `all` | `concern_summary` | 0.292 | 0.133 | 0.292 | 0.198 | 0.110 | 0.120 |
| `all` | `profile_summary` | 0.375 | 0.170 | 0.417 | 0.221 | 0.172 | 0.150 |
| `all` | `context_preserved` | 0.833 | 0.481 | 0.833 | 0.481 | 0.841 | 0.557 |
| `core` | `concern_summary` | 0.111 | 0.029 | 0.111 | 0.029 | 0.034 | 0.021 |
| `core` | `profile_summary` | 0.222 | 0.059 | 0.278 | 0.069 | 0.056 | 0.043 |
| `core` | `context_preserved` | 0.833 | 0.490 | 0.833 | 0.490 | 0.824 | 0.555 |
| `rare_stress` | `concern_summary` | 0.833 | 0.483 | 0.833 | 0.773 | 0.365 | 0.455 |
| `rare_stress` | `profile_summary` | 0.833 | 0.550 | 0.833 | 0.740 | 0.570 | 0.516 |
| `rare_stress` | `context_preserved` | 0.833 | 0.450 | 0.833 | 0.450 | 0.900 | 0.562 |

## 질의별 대조

- 프로필 요약 질의 우세: 3건
- 문맥 보존 질의 우세: 17건
- 동률: 4건

우세 판정은 먼저 Top-40 관련 anchor 회수 개수를 비교하고, 개수가 같으면 첫 관련 anchor의 순위가 높은 전략을 선택했다.

| evaluation_id | 판정 | 프로필 요약 회수 | 문맥 회수 | 프로필 요약 첫 순위 | 문맥 첫 순위 | Top-40 교집합 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `evaluation_core_acne_01` | `context_preserved_wins` | 0 | 3 | - | 1 | 0 |
| `evaluation_core_acne_03` | `tie` | 0 | 0 | - | - | 7 |
| `evaluation_core_acne_04` | `context_preserved_wins` | 1 | 1 | 3 | 1 | 14 |
| `evaluation_core_acne_05` | `context_preserved_wins` | 0 | 3 | - | 1 | 10 |
| `evaluation_core_acne_08` | `context_preserved_wins` | 0 | 3 | - | 1 | 4 |
| `evaluation_core_composite_01` | `context_preserved_wins` | 0 | 3 | - | 1 | 0 |
| `evaluation_core_composite_02` | `context_preserved_wins` | 0 | 3 | - | 1 | 2 |
| `evaluation_core_composite_06` | `context_preserved_wins` | 1 | 3 | 4 | 1 | 3 |
| `evaluation_core_pigment_01` | `tie` | 0 | 0 | - | - | 0 |
| `evaluation_core_pigment_02` | `context_preserved_wins` | 1 | 3 | 36 | 1 | 9 |
| `evaluation_core_pigment_04` | `context_preserved_wins` | 0 | 1 | - | 2 | 6 |
| `evaluation_core_pigment_05` | `context_preserved_wins` | 0 | 1 | - | 2 | 1 |
| `evaluation_core_pigment_08` | `context_preserved_wins` | 0 | 2 | - | 1 | 6 |
| `evaluation_core_pores_01` | `context_preserved_wins` | 0 | 3 | - | 1 | 0 |
| `evaluation_core_pores_02` | `context_preserved_wins` | 2 | 3 | 6 | 1 | 13 |
| `evaluation_core_pores_03` | `context_preserved_wins` | 1 | 3 | 6 | 1 | 3 |
| `evaluation_core_pores_05` | `context_preserved_wins` | 0 | 3 | - | 1 | 0 |
| `evaluation_core_pores_08` | `tie` | 0 | 0 | - | - | 0 |
| `evaluation_rare_dry_02` | `profile_summary_wins` | 6 | 3 | 1 | 1 | 21 |
| `evaluation_rare_dry_03` | `profile_summary_wins` | 4 | 1 | 4 | 2 | 8 |
| `evaluation_rare_redness_02` | `context_preserved_wins` | 3 | 3 | 2 | 1 | 25 |
| `evaluation_rare_sagging_01` | `tie` | 0 | 0 | - | - | 5 |
| `evaluation_rare_sensitive_01` | `profile_summary_wins` | 3 | 2 | 1 | 1 | 1 |
| `evaluation_rare_wrinkles_02` | `context_preserved_wins` | 3 | 3 | 10 | 1 | 13 |

## 해석 제한

- Recall은 전체 3,581건의 완전 recall이 아니라 골든셋 v4의 초기 관련 anchor에 대한 회수율이다.
- 골든셋에 없는 새 관련 Case가 한 전략에서만 검색될 수 있으므로, 이 결과는 고정 anchor 회수 비교로 해석한다.
- 다음 metadata·reranker 실험에서는 각 전략의 신규 Top-3를 블라인드 판정한 뒤 모든 전략을 같은 확장 qrels로 다시 채점해야 한다.

## 결론

- 기본 검색 질의는 `context_preserved`를 유지한다. 전체 Recall@40이 프로필 요약 0.221에서 0.481로 높고, MRR@40도 0.172에서 0.841로 높다.
- 희소 스트레스셋에서는 프로필 요약형의 Recall@40이 0.740으로 문맥 보존형 0.450보다 높지만, 첫 관련 문서 순위는 문맥 보존형이 더 좋다.
- 고민명 축약 하한선의 전체 Recall@40은 0.198, 희소 Recall@40은 0.773이다.
- 프로필 요약 질의를 기본값이나 전체 대체안으로 사용하지 않는다. 희소 고민 보완은 다음 metadata 적용 방식 비교에서 검증한다.
