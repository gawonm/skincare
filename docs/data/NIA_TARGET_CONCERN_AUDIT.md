# NIA `target_concern` 감사

> - generated_at: 2026-09-30
> - commit / branch: `ea915de` (origin/main) / `docs/data-runtime-quality-audits-v2`
> - DB: `skincare_reference_20260923_v5_2` (로컬 Docker, SELECT 전용) — Alembic `cdff29b164d8`
> - DB 이름과 핸드오프 기준 dump(`skincare_reference_2026-09-23_v5_2.dump`) 이름이 대응하지만, dump 자체와의 바이트 일치는 확인하지 않아 SHA256은 적지 않는다.
> - 핵심 행 수: `nia_case_document` 3,581 (training 3,177 / validation 404)
> - 수치 원본: `nia_target_concern_distribution.csv` (로컬 생성물, git 미추적)

## 결론

- `target_concern`은 **사람이 채운 자유 텍스트가 아니라 데이터셋의 대분류 8개**다. `case_id` 두 번째 토큰
  (`POR`, `WHT` 등)과 1:1로 대응하고, NULL·빈 값·`metadata.target_concern`과의 불일치가 모두 0건이다.
- Agent의 `NiaCaseConcernCategory` enum 8개 값이 DB label 8개와 **문자열까지 전부 일치**한다
  ([case_candidate_selector.py:15](../../agent/rag/retrieval/case_candidate_selector.py)). 정확 일치 매칭이 성립한다.
- 분포가 매우 치우쳐 있다. 모공·미백·여드름이 96.7%이고 민감성 4건, 피부처짐 2건뿐이다.

## 분포

| target_concern | case_id 접두어 | 전체 | training | validation | 비율 |
| --- | --- | ---: | ---: | ---: | ---: |
| 모공 | POR | 1,532 | 1,353 | 179 | 42.78% |
| 미백(색소침착/기미/칙칙함) | WHT | 1,244 | 1,098 | 146 | 34.74% |
| 여드름/뾰루지 | ACN | 686 | 621 | 65 | 19.16% |
| 붉어짐(홍조) | RED | 50 | 46 | 4 | 1.40% |
| 과각질/악건성 | DRY | 38 | 32 | 6 | 1.06% |
| 주름 | WRK | 25 | 23 | 2 | 0.70% |
| 민감성(트러블/자극감) | SEN | 4 | 3 | 1 | 0.11% |
| 피부처짐/탄력저하 | SAG | 2 | 1 | 1 | 0.06% |
| **합계** | | **3,581** | 3,177 | 404 | 100% |

## 무결성 점검

| 점검 | 결과 |
| --- | --- |
| `target_concern` NULL / 빈 문자열 | 0 / 0 |
| `target_concern` ≠ `metadata->>'target_concern'` | 0 |
| 고유 label 수 | 8 |
| `case_id` 중복 | 0 (고유 3,581) |
| `skin_concerns`(text[])에 target이 없는 행 | **3** |

`skin_concerns`에 target이 없는 3건은 다음과 같다. label이 틀렸다는 증거는 아니고, 두 필드가 서로 다른 정보를 담는다는 뜻이다.

| case_id | target_concern | skin_concerns |
| --- | --- | --- |
| COT_DRY_F_U30_08960 | 과각질/악건성 | 붉어짐(홍조) |
| COT_WHT_F_U30_01804 | 미백(색소침착/기미/칙칙함) | 주름 |
| COT_WHT_M_O30_06111 | 미백(색소침착/기미/칙칙함) | 모공 |

`skin_concerns` 길이는 1개(3,279건)와 2개(302건 = 모공 282 + 여드름 11 + 주름 9) 두 가지뿐이다.

## 해석과 한계

- Agent selector는 `target_concern` 정확 일치와 `skin_concerns` 별칭 부분 일치를 **합집합**으로 쓰고 hard filter로
  쓰지 않는다. 위 3건은 이 구조에서 문제가 되지 않는다.
- 민감성 4건·피부처짐 2건은 검색·평가 표본으로 너무 작다. 이 범주의 질의 품질은 NIA Case만으로 검증할 수 없다.
- `target_concern`은 사용자의 실제 진단이 아니라 설문 대분류다. 표시 문구에 그대로 노출하지 않는다.

## FOLLOW-UP (이번 배치에서는 수정하지 않음)

- `agent/adapters.py:591`의 `target_concern="피지"`는 8개 label에 없는 값이다. demo 어댑터로 보이나 확인이 필요하다.
