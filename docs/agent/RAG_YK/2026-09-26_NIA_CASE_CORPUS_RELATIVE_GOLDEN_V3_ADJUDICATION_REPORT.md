# NIA Case 코퍼스 상대 골든셋 v3 조정 보고서

## 결론

- v2 원본은 변경하지 않고 24건 블라인드 감사에서 불일치한 9건만 재검토했다.
- 4건은 v2 판정을 유지하고 5건은 감사 판정을 채택했다.
- 임베딩·검색·리랭킹을 다시 실행하지 않고 기존 고정 후보와 순위에 조정 qrel만 적용했다.

## 조정 내역

| evaluation_id | review_key | 결정 | 최종 등급 | 근거 |
| --- | --- | --- | ---: | --- |
| `evaluation_core_acne_03` | `2b47ee4498703775` | `accept_audit` | 1 | 화이트헤드는 인접 증상이지만 순한 입문 성분이라는 핵심 요청을 직접 충족하지 않아 2점 기준에는 부족하다. |
| `evaluation_core_acne_04` | `9082c2bbc5033d5e` | `accept_audit` | 0 | 현재 활성 제품 사용 후 자극을 호소하는데 BHA를 다시 권하므로 단순 누락이 아니라 요청 방향 충돌로 본다. |
| `evaluation_core_acne_08` | `bf89dfec5463d84e` | `keep_frozen` | 2 | 면도 자극은 다루지만 따가움을 줄이는 루틴보다 BHA 중심이라 요청 방향이 완전 일치하는 3점으로 올리지 않는다. |
| `evaluation_core_composite_01` | `b0841885b0bb3157` | `keep_frozen` | 2 | 복합성 맥락은 강하지만 볼 붉어짐과 부위별 적용 구분을 빠뜨려 복합 요청을 직접 해결하는 3점은 아니다. |
| `evaluation_core_composite_02` | `0f8cf6832cb98573` | `accept_audit` | 2 | 타겟 스팟 케어 언급만으로는 활성 성분을 나누어 쓰는 방법에 직접 답했다고 보기 어려워 2점으로 제한한다. |
| `evaluation_core_pigment_04` | `37a5962dfce920c2` | `accept_audit` | 0 | 활성 제품 중첩 후 자극이 발생한 질의에서 추가 미백 활성 성분을 주 해결책으로 제시해 현재 안정화 목표와 충돌한다. |
| `evaluation_core_pigment_05` | `7ded0d83d8903ced` | `keep_frozen` | 1 | 새 여드름에는 유용하지만 갈색 자국과 새 뾰루지를 함께 관리해야 하는 복합 목표 중 절반만 다뤄 인접 관련으로 유지한다. |
| `evaluation_core_pigment_08` | `e8c33590a51f1534` | `accept_audit` | 2 | 정기적 각질 관리가 부적절할 수 있으나 보습과 장벽 강화를 함께 제시하므로 답변 전체가 반대 방향인 0점보다 부분 관련 2점이 적합하다. |
| `evaluation_rare_dry_02` | `2283888acd61489c` | `keep_frozen` | 2 | 장벽 강화는 직접 맞지만 갈라지고 따가운 상태에 PHA를 병행해 전체 요청에 완전히 부합하는 3점으로 보기는 어렵다. |

## v2 → v3 지표 변화

| 구분 | 지표 | v2 | v3 | 변화 |
| --- | --- | ---: | ---: | ---: |
| `all` | Anchor Success@40 | 0.833 | 0.833 | +0.000 |
| `all` | Anchor Recall@40 | 0.481 | 0.481 | +0.000 |
| `all` | Metadata Success@20 | 0.792 | 0.792 | +0.000 |
| `all` | Metadata Retention@20 | 0.892 | 0.892 | +0.000 |
| `all` | Precision@3 | 0.806 | 0.806 | +0.000 |
| `all` | nDCG@3 | 0.787 | 0.791 | +0.004 |
| `core` | Anchor Success@40 | 0.833 | 0.833 | +0.000 |
| `core` | Anchor Recall@40 | 0.490 | 0.490 | +0.000 |
| `core` | Metadata Success@20 | 0.778 | 0.778 | +0.000 |
| `core` | Metadata Retention@20 | 0.911 | 0.911 | +0.000 |
| `core` | Precision@3 | 0.833 | 0.833 | +0.000 |
| `core` | nDCG@3 | 0.783 | 0.789 | +0.006 |
| `rare_stress` | Anchor Success@40 | 0.833 | 0.833 | +0.000 |
| `rare_stress` | Anchor Recall@40 | 0.450 | 0.450 | +0.000 |
| `rare_stress` | Metadata Success@20 | 0.833 | 0.833 | +0.000 |
| `rare_stress` | Metadata Retention@20 | 0.833 | 0.833 | +0.000 |
| `rare_stress` | Precision@3 | 0.722 | 0.722 | +0.000 |
| `rare_stress` | nDCG@3 | 0.797 | 0.797 | +0.000 |

## 평가 결과가 바뀐 질의

- `evaluation_core_pigment_08`
- `evaluation_core_acne_03`
- `evaluation_core_composite_02`

## 해석

v3는 복원 가능한 v2를 폐기한 새 골든셋이 아니라, 블라인드 감사 불일치만 명시적으로 조정한 후속 버전이다. 특히 방향 충돌과 복합 질의의 부분 대응 여부를 더 엄격히 구분한다.
