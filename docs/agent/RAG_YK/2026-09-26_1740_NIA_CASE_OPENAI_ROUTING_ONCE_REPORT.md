# NIA Case OpenAI 운영 Intent 1회 평가

> **범위 주의:** 이 문서는 OpenAI의 원시 Intent·route 제안 결과다. 실제 운영에서는 이후
> `RagRoutePolicy`가 route를 결정적으로 다시 검증한다. 최종 운영 경로 평가는
> `2026-09-26_1755_NIA_CASE_ROUTE_UPDATE_REPORT.md`를 기준으로 본다.

## 실행 조건

- 실행 ID: `openai_routing_once_20260926_1740_v1`
- 모델: `gpt-4o-mini`
- 질의: 24건
- 애플리케이션 API 호출: 24회
- 운영 설정 재시도: 1회
- 이번 평가 재시도: 0회
- 입력: 동결된 NIA Case 코퍼스 상대 평가 질의 24건
- 범위: OpenAI Intent/RAG route 해석과 운영 IntentQueryPlanner의 case_query 생성

## 결과

- Case query 생성: 22/24 (91.7%)
- 원문과 완전 일치: 22/24 (91.7%)
- 수정된 Case query: 0건
- Case query 누락: 2건

### RAG route 분포

| route | 질의 수 |
| --- | ---: |
| `evidence_only` | 2 |
| `claim_then_evidence` | 22 |
| `none` | 0 |

### Intent 분포

| intent | 질의 수 |
| --- | ---: |
| `product_discovery` | 19 |
| `routine_planning` | 2 |
| `evidence_qa` | 3 |

## 질의별 판정

| evaluation_id | route | intents | case query 관계 | 생성 질의 |
| --- | --- | --- | --- | --- |
| `evaluation_core_pores_01` | `claim_then_evidence` | `product_discovery` | `exact` | 코에 블랙헤드가 반복되고 모공이 막혀 보여요. 자극을 줄이면서 관리하고 싶습니다. |
| `evaluation_core_pores_02` | `claim_then_evidence` | `product_discovery` | `exact` | 27살 지성 피부이고 여름마다 코와 이마의 피지와 모공이 심해집니다. 피부를 과하게 말리지 않는 관리가 필요해요. |
| `evaluation_core_pores_03` | `claim_then_evidence` | `product_discovery` | `exact` | 35살 건성 피부인데 볼 모공이 세로로 늘어져 보이고 세안 후 당김도 있습니다. |
| `evaluation_core_pores_05` | `claim_then_evidence` | `product_discovery` | `exact` | T존은 번들거리지만 볼은 건조한데 얼굴 전체에 같은 모공 제품을 써도 되는지 걱정됩니다. |
| `evaluation_core_pores_08` | `claim_then_evidence` | `evidence_qa` | `exact` | 모공 때문에 각질 제거를 자주 했더니 볼이 화끈거립니다. 모공 관리와 장벽 회복 중 무엇을 우선해야 할까요? |
| `evaluation_core_pigment_01` | `claim_then_evidence` | `product_discovery` | `exact` | 여드름이 나았는데 볼에 갈색 자국이 오래 남아 있습니다. |
| `evaluation_core_pigment_02` | `claim_then_evidence` | `product_discovery` | `exact` | 36살 여성이고 야외 활동 후 양쪽 볼 기미가 짙어졌습니다. 자극이 적은 색소 관리가 필요해요. |
| `evaluation_core_pigment_04` | `claim_then_evidence` | `product_discovery` | `exact` | 미백 제품을 여러 개 겹쳐 쓴 뒤 따갑고 붉어졌는데 색소는 더 진해진 것 같아요. |
| `evaluation_core_pigment_05` | `claim_then_evidence` | `product_discovery` | `exact` | 29살 복합성 피부이고 턱 여드름 자국과 새 뾰루지가 함께 있습니다. 둘을 악화시키지 않는 관리가 필요해요. |
| `evaluation_core_pigment_08` | `claim_then_evidence` | `product_discovery` | `exact` | 기미에 좋다는 필링을 자주 했더니 건조하고 따가워졌습니다. 색소와 장벽을 같이 회복하고 싶어요. |
| `evaluation_core_acne_01` | `claim_then_evidence` | `product_discovery` | `exact` | 이마에 좁쌀처럼 막힌 여드름이 계속 생깁니다. |
| `evaluation_core_acne_03` | `claim_then_evidence` | `product_discovery` | `exact` | 16살이고 이마와 코에 화이트헤드가 많아요. 처음 쓰기 쉬운 순한 성분을 알고 싶습니다. |
| `evaluation_core_acne_04` | `evidence_only` | `evidence_qa` | `missing` | - |
| `evaluation_core_acne_05` | `claim_then_evidence` | `product_discovery` | `exact` | 33살 복합성 피부이고 생리 전마다 턱에 단단한 여드름이 생기며 세안 후에는 건조합니다. |
| `evaluation_core_acne_08` | `claim_then_evidence` | `routine_planning` | `exact` | 30살 남성이고 면도하는 턱선에 여드름과 따가움이 반복됩니다. 자극을 줄이는 루틴이 필요합니다. |
| `evaluation_core_composite_01` | `claim_then_evidence` | `routine_planning` | `exact` | T존 모공과 피지는 심한데 볼은 붉고 건조합니다. 두 부위를 한 루틴에서 관리하고 싶어요. |
| `evaluation_core_composite_02` | `claim_then_evidence` | `product_discovery` | `exact` | 턱 여드름과 갈색 자국, 볼의 따가움이 함께 있어 활성 성분을 어떻게 나눠 써야 할지 모르겠습니다. |
| `evaluation_core_composite_06` | `claim_then_evidence` | `product_discovery` | `exact` | 피부가 번들거리면서도 세안 후 따갑고, 모공과 붉은 여드름이 같이 보입니다. |
| `evaluation_rare_dry_02` | `claim_then_evidence` | `product_discovery` | `exact` | 24살 건성 피부이고 입 주변이 갈라지고 화장품을 바르면 따갑습니다. 장벽을 회복하고 싶어요. |
| `evaluation_rare_dry_03` | `claim_then_evidence` | `product_discovery` | `exact` | 각질을 없애려고 필링을 했더니 더 건조하고 아파졌습니다. 각질 제거보다 보습을 먼저 해야 하나요? |
| `evaluation_rare_redness_02` | `claim_then_evidence` | `product_discovery` | `exact` | 32살 복합성 피부이고 세안이나 온도 변화 후 양 볼 홍조와 따가움이 오래갑니다. |
| `evaluation_rare_wrinkles_02` | `claim_then_evidence` | `product_discovery` | `exact` | 잔주름 관리를 위해 레티놀을 시작하고 싶지만 피부가 쉽게 건조하고 따가워집니다. |
| `evaluation_rare_sensitive_01` | `claim_then_evidence` | `product_discovery` | `exact` | 새 화장품만 쓰면 볼이 따갑고 붉어집니다. 성분을 늘리기 전에 피부를 안정시키고 싶어요. |
| `evaluation_rare_sagging_01` | `evidence_only` | `evidence_qa` | `missing` | - |

## 해석 기준

- `exact`이면 OpenAI가 route와 Intent를 정하더라도 실제 Case 임베딩 질의는 원문과 같습니다.
- `modified`이면 해당 질의는 생성된 Case 질의로 BGE-M3 검색을 다시 평가해야 합니다.
- `missing`이면 OpenAI 라우팅 단계에서 Case RAG에 진입하지 못한 실패로 봅니다.
- 이 실행은 OpenAI가 검색 정답을 생성하는 평가가 아니라, 운영 라우팅이 동결 질의를 NIA Case 검색으로 넘기는지 확인하는 평가입니다.
