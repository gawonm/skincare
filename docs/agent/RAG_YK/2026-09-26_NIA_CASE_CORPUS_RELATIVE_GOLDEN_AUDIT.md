# NIA Case 코퍼스 상대 골든셋 v2 복원 및 블라인드 감사

## 감사 범위

- 최종 골든셋에서 유실된 판정 원본 200건을 역복원했다.
- 기존에 남아 있던 18건은 복원 예상값과 완전히 일치할 때만 보존했다.
- 골든셋, 평가 JSON, 자동 생성 보고서 구간이 복원 원본으로 재현되는지 확인했다.
- 기존 등급·case_id·검색 순위를 제외하고 질의별 1건을 해시로 선택해 24건을 다시 판정했다.

## 일치도 결과

- 정확 등급 일치율: `0.625`
- ±1 등급 이내 일치율: `0.958`
- 관련/비관련 이진 일치율(2점 이상): `0.875`
- Quadratic weighted kappa: `0.759`

| 등급 | 동결 골든 | 감사 재판정 |
| ---: | ---: | ---: |
| 0 | 2 | 3 |
| 1 | 5 | 3 |
| 2 | 7 | 6 |
| 3 | 10 | 12 |

## 불일치 사례

| evaluation_id | review_key | 동결 | 감사 |
| --- | --- | ---: | ---: |
| `evaluation_core_acne_03` | `2b47ee4498703775` | 2 | 1 |
| `evaluation_core_acne_04` | `9082c2bbc5033d5e` | 1 | 0 |
| `evaluation_core_acne_08` | `bf89dfec5463d84e` | 2 | 3 |
| `evaluation_core_composite_01` | `b0841885b0bb3157` | 2 | 3 |
| `evaluation_core_composite_02` | `0f8cf6832cb98573` | 3 | 2 |
| `evaluation_core_pigment_04` | `37a5962dfce920c2` | 1 | 0 |
| `evaluation_core_pigment_05` | `7ded0d83d8903ced` | 1 | 2 |
| `evaluation_core_pigment_08` | `e8c33590a51f1534` | 0 | 2 |
| `evaluation_rare_dry_02` | `2283888acd61489c` | 2 | 3 |

## 해석 한계

이번 감사 재판정도 동일 세션의 모델이 수행했으므로 독립된 두 번째 평가자의 검증은 아니다. 따라서 이 결과는 판정 규칙의 내부 일관성 점검으로 해석하고, 최종 신뢰성 주장은 사람 또는 독립 세션의 추가 표본 판정으로 보강해야 한다.

## 후속 조정 결과

불일치 9건을 규칙에 따라 재검토하여 4건은 동결 판정을 유지하고 5건은 감사 판정을 채택했다.
v2는 변경 이력으로 보존하고, 조정 결과는 `nia_case_corpus_relative_golden_v3.jsonl`로 분리했다.
전체 검색 지표는 유지됐으며 nDCG@3만 0.787에서 0.791로 변경됐다. 상세 근거는
`docs/agent/RAG_YK/2026-09-26_NIA_CASE_CORPUS_RELATIVE_GOLDEN_V3_ADJUDICATION_REPORT.md`에 있다.
