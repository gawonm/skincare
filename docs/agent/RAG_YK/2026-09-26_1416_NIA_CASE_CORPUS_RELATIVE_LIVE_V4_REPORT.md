# NIA Case 코퍼스 상대 골든셋 v4 Live 성능 평가

## 실행 정보

- 실행 ID: `live_20260926_1416_v1`
- 상태: `complete`
- 질의: 24건
- 코퍼스: 3,581건
- Dense 모델: `BAAI/bge-m3`
- Reranker 모델: `BAAI/bge-reranker-v2-m3`
- 전체 후보: 4,319건
- Top-3 결과: 72건
- 미판정 Top-3: 0건
- 평가 골든셋: `nia_case_corpus_relative_golden_v4.jsonl`, 220 qrels

Live Top-3에서 새로 발견된 20건을 기존과 같은 블라인드 판정 기준으로 보완한 뒤, 과거 캐시 기준선과 이번 Live 결과를 동일한 v4 qrels로 다시 채점했다.

## 기준선 대비 결과

| 구분 | 지표 | 과거 캐시 기준선 | Live | 변화 |
| --- | --- | ---: | ---: | ---: |
| `all` | Anchor Success@40 | 0.833 | 0.833 | +0.000 |
| `all` | Anchor Recall@40 | 0.481 | 0.481 | +0.000 |
| `all` | Metadata Success@20 | 0.792 | 0.792 | +0.000 |
| `all` | Metadata Retention@20 | 0.892 | 0.892 | +0.000 |
| `all` | Precision@3 | 0.806 | 0.778 | -0.028 |
| `all` | nDCG@3 | 0.779 | 0.743 | -0.036 |
| `core` | Anchor Success@40 | 0.833 | 0.833 | +0.000 |
| `core` | Anchor Recall@40 | 0.490 | 0.490 | +0.000 |
| `core` | Metadata Success@20 | 0.778 | 0.778 | +0.000 |
| `core` | Metadata Retention@20 | 0.911 | 0.911 | +0.000 |
| `core` | Precision@3 | 0.833 | 0.796 | -0.037 |
| `core` | nDCG@3 | 0.779 | 0.752 | -0.027 |
| `rare_stress` | Anchor Success@40 | 0.833 | 0.833 | +0.000 |
| `rare_stress` | Anchor Recall@40 | 0.450 | 0.450 | +0.000 |
| `rare_stress` | Metadata Success@20 | 0.833 | 0.833 | +0.000 |
| `rare_stress` | Metadata Retention@20 | 0.833 | 0.833 | +0.000 |
| `rare_stress` | Precision@3 | 0.722 | 0.722 | +0.000 |
| `rare_stress` | nDCG@3 | 0.780 | 0.716 | -0.064 |

## Top-3 변화

- 순서가 달라진 질의: 20/24
- 구성원이 달라진 질의: 16/24
- 구성원은 같고 순서만 달라진 질의: 4/24 (`evaluation_core_acne_03`, `evaluation_core_pigment_02`, `evaluation_core_pigment_05`, `evaluation_core_pores_03`)

구성원까지 달라진 질의는 다음과 같다.

- `evaluation_core_pores_01`
- `evaluation_core_pores_02`
- `evaluation_core_pores_08`
- `evaluation_core_pigment_01`
- `evaluation_core_pigment_04`
- `evaluation_core_pigment_08`
- `evaluation_core_acne_04`
- `evaluation_core_acne_08`
- `evaluation_core_composite_01`
- `evaluation_core_composite_02`
- `evaluation_core_composite_06`
- `evaluation_rare_dry_02`
- `evaluation_rare_dry_03`
- `evaluation_rare_wrinkles_02`
- `evaluation_rare_sensitive_01`
- `evaluation_rare_sagging_01`

## 실행 재현성 점검

- 과거 후보 풀과 이번 Live 후보 풀의 dense Top-40 순서 일치: **24/24 질의**
- 과거 후보 풀과 이번 Live 후보 풀의 dense Top-40 구성 일치: **24/24 질의**
- 동일 Live 후보 풀에 대한 리랭커 반복 실행 Top-3 순서 일치: **24/24 질의**
- 동일 Live 후보 풀에 대한 리랭커 반복 실행 Top-3 구성 일치: **24/24 질의**
- 반복 실행 Top-3 미판정 문서: **0건**

Dense 후보는 과거 기준선과 완전히 같고 현재 리랭커도 반복 실행에서 완전히 재현됐다. 따라서 이번 Top-3 차이는 실행 시점의 무작위 흔들림이 아니라 **과거 캐시 리랭커 출력과 현재 리랭커 출력 사이의 드리프트**로 한정할 수 있다. 다만 이 결과만으로 과거 대비 코드, 모델 파일, 라이브러리, 설정 중 어느 요소가 달라졌는지는 확정할 수 없다.

## 해석 주의

- Anchor Recall@40은 전체 3,581건에 대한 완전 recall이 아니라 판정된 초기 anchor에 대한 회수율이다.
- Precision@3과 nDCG@3는 이번 실행 Top-3 72건이 모두 판정된 상태에서 계산했다.
- 기존 v3의 nDCG@3 0.791과 v4 기준선 0.779는 qrels가 200건에서 220건으로 확장되면서 질의별 이상적 DCG가 바뀐 결과이므로 직접적인 모델 성능 하락으로 읽으면 안 된다.
- 다음 파이프라인 변경부터는 이번 Live 결과와 골든셋 v4를 새 기준선으로 사용한다.
