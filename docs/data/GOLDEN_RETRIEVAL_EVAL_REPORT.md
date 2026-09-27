# RAG 검색(Retrieval) 성능평가 보고서 — 50개 정밀 골든셋

> 이 평가는 OpenAI API 호출 없이 로컬 임베더(BGE-M3)와 로컬 재랭커(bge-reranker-v2-m3),
> 그리고 실제 PostgreSQL DB(`skincare_reference_20260923_v5_2`)를 대상으로 100% 로컬 환경에서 수행되었습니다.

## 1. 전체 지표 요약 (Overall Metrics)

- **평가 케이스 수**: 50건
- **Hit@1**: 26.0%
- **Hit@3**: 46.0%
- **Hit@5**: 54.0%
- **Recall@3**: 26.2%
- **Recall@5**: 41.5%
- **Recall@10**: 52.8%
- **Precision@3**: 26.0%
- **Precision@5**: 25.2%
- **MRR (Mean Reciprocal Rank)**: 0.3754

## 2. 카테고리별 지표 (Category Breakdown)

| 카테고리 | 케이스 수 | Hit@1 | Hit@3 | Hit@5 | Recall@3 | Recall@5 | Recall@10 | Precision@5 | MRR |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **efficacy** | 12건 | 33.3% | 75.0% | 83.3% | 37.5% | 70.8% | 88.9% | 38.3% | 0.5466 |
| **precaution** | 10건 | 0.0% | 10.0% | 30.0% | 5.0% | 20.0% | 30.0% | 8.0% | 0.0900 |
| **regulatory** | 8건 | 12.5% | 25.0% | 25.0% | 16.7% | 25.0% | 28.1% | 12.5% | 0.1845 |
| **comparison** | 8건 | 37.5% | 50.0% | 62.5% | 28.1% | 37.5% | 50.0% | 22.5% | 0.5003 |
| **alias** | 6건 | 50.0% | 83.3% | 83.3% | 41.7% | 54.2% | 75.0% | 40.0% | 0.6389 |
| **zero_evidence** | 6건 | 33.3% | 33.3% | 33.3% | 33.3% | 33.3% | 33.3% | 33.3% | 0.3333 |

## 3. 케이스별 상세 결과 (Case Details)

| ID | 카테고리 | 질의 | Hit@3 | Hit@5 | Recall@5 | Precision@5 | MRR | 판정 |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `eff_niacinamide_sebum` | efficacy | 나이아신아마이드는 피지 분비 조절과 모공 개선에 효... | 1.0 | 1.0 | 0.50 | 0.20 | 0.500 | **PASS** |
| `eff_niacinamide_barrier` | efficacy | 나이아신아마이드가 손상된 피부 장벽 회복과 보습에 ... | 0.0 | 1.0 | 1.00 | 0.20 | 0.250 | **PASS** |
| `eff_salicylic_acid_acne` | efficacy | 살리실산이 여드름균 억제와 트러블 완화에 효과적인 ... | 1.0 | 1.0 | 1.00 | 0.60 | 1.000 | **PASS** |
| `eff_salicylic_acid_exfoliation` | efficacy | 살리실릭애씨드는 모공 속 피지와 각질 제거에 어떤 ... | 0.0 | 0.0 | 0.00 | 0.00 | 0.143 | **FAIL** |
| `eff_retinol_wrinkle` | efficacy | 레티놀은 잔주름 개선과 피부 탄력 증진에 왜 효과적... | 1.0 | 1.0 | 1.00 | 0.40 | 0.333 | **PASS** |
| `eff_ascorbic_acid_whitening` | efficacy | 순수 비타민C인 아스코빅애씨드는 기미 잡티 완화와 ... | 1.0 | 1.0 | 1.00 | 0.40 | 1.000 | **PASS** |
| `eff_panthenol_soothing` | efficacy | 판테놀 성분은 자극받은 민감 피부 진정과 보습에 어... | 1.0 | 1.0 | 0.50 | 0.40 | 0.333 | **PASS** |
| `eff_sodium_hyaluronate_moisture` | efficacy | 소듐하이알루로네이트는 피부 속건조와 수분 공급에 왜... | 1.0 | 1.0 | 1.00 | 0.80 | 1.000 | **PASS** |
| `eff_tranexamic_pigmentation` | efficacy | 트라넥사믹애씨드는 난치성 기미와 색소침착 개선에 효... | 1.0 | 1.0 | 1.00 | 0.60 | 1.000 | **PASS** |
| `eff_adenosine_antiaging` | efficacy | 아데노신이 피부 탄력과 안티에이징 주름 개선에 효과... | 1.0 | 1.0 | 1.00 | 0.60 | 0.500 | **PASS** |
| `eff_allantoin_skin_repair` | efficacy | 알란토인은 손상된 피부 장벽 회복과 자극 완화에 어... | 1.0 | 1.0 | 0.50 | 0.40 | 0.500 | **PASS** |
| `eff_zinc_pca_sebum` | efficacy | 징크피씨에이는 과도한 유분 피지 조절과 트러블 피부... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `prec_retinol_irritation` | precaution | 레티놀 처음 사용할 때 나타날 수 있는 각질 탈락이... | 0.0 | 1.0 | 1.00 | 0.20 | 0.200 | **PASS** |
| `prec_retinol_photosensitivity` | precaution | 레티놀을 낮에 바르면 햇빛에 피부가 민감해지나요 낮... | 0.0 | 1.0 | 0.50 | 0.20 | 0.200 | **PASS** |
| `prec_salicylic_acid_irritation` | precaution | 살리실산(BHA)을 너무 자주 쓰면 피부 장벽 손상... | 1.0 | 1.0 | 0.50 | 0.40 | 0.500 | **PASS** |
| `prec_ascorbic_acid_stinging` | precaution | 순수 비타민C 세럼을 바를 때 피부가 붉어지고 따가... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `prec_benzoic_acid_safety` | precaution | 화장품에 들어가는 벤조익애씨드(안식향산) 성분은 알... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `prec_phenoxyethanol_irritation` | precaution | 페녹시에탄올 방부제 성분은 민감성 피부에 자극이나 ... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `prec_toluene_toxicity` | precaution | 네일 화장품에 사용되는 톨루엔 성분의 흡입 독성과 ... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `prec_sulfur_dryness` | precaution | 유황 성분 화장품이나 연고를 여드름에 쓸 때 과도한... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `prec_alcohol_dryness` | precaution | 변성 알코올이나 에탄올이 다량 함유된 토너를 쓸 때... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `prec_p_aminophenol_allergy` | precaution | 염색약 성분인 p-아미노페놀은 두피 자극이나 접촉성... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `reg_salicylic_acid_limit` | regulatory | 국내 식약처 화장품 기준에서 살리실산의 최대 허용 ... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `reg_phenoxyethanol_limit` | regulatory | 화장품 보존제 페녹시에탄올의 식약처 고시 배합 한도... | 0.0 | 0.0 | 0.00 | 0.00 | 0.143 | **FAIL** |
| `reg_benzoic_acid_limit` | regulatory | 벤조익애씨드(안식향산) 및 그 나트륨염의 화장품 배... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `reg_retinol_functional` | regulatory | 식약처 주름개선 기능성화장품 고시에서 레티놀 기준 ... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `reg_zinc_pca_limit` | regulatory | 화장품 안전기준에서 징크피씨에이 및 아연 화합물의 ... | 1.0 | 1.0 | 1.00 | 0.60 | 0.333 | **PASS** |
| `reg_sulfur_limit` | regulatory | 식약처 고시에서 화장품에 사용 가능한 황(유황)의 ... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `reg_toluene_limit` | regulatory | 매니큐어 등 네일 제품에서 톨루엔의 식약처 배합 한... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `reg_tranexamic_acid_limit` | regulatory | 화장품 원료로서 트라넥사믹애씨드의 사용 기준과 국가... | 1.0 | 1.0 | 1.00 | 0.40 | 1.000 | **PASS** |
| `comp_retinol_bakuchiol` | comparison | 레티놀과 식물성 대체제인 바쿠치올의 효능과 피부 자... | 1.0 | 1.0 | 0.50 | 0.40 | 0.500 | **PASS** |
| `comp_niacinamide_salicylic` | comparison | 나이아신아마이드와 살리실산(BHA)을 함께 사용하면... | 0.0 | 0.0 | 0.00 | 0.00 | 0.111 | **FAIL** |
| `comp_ascorbic_niacinamide` | comparison | 순수 비타민C(아스코빅애씨드)와 나이아신아마이드를 ... | 0.0 | 0.0 | 0.00 | 0.00 | 0.050 | **FAIL** |
| `comp_salicylic_niacinamide_chloasma` | comparison | 기미(chloasma) 색소침착 치료에 초분자 살리... | 1.0 | 1.0 | 1.00 | 0.20 | 1.000 | **PASS** |
| `comp_centella_madecassoside` | comparison | 병풀추출물 원료와 병풀의 유효 활성 성분인 마데카소... | 1.0 | 1.0 | 1.00 | 0.80 | 1.000 | **PASS** |
| `comp_panthenol_ceramide` | comparison | 손상된 피부 장벽 회복을 위해 판테놀과 세라마이드엔... | 0.0 | 1.0 | 0.25 | 0.20 | 0.250 | **PASS** |
| `comp_tranexamic_niacinamide` | comparison | 트라넥사믹애씨드와 나이아신아마이드의 미백 및 색소침... | 1.0 | 1.0 | 0.25 | 0.20 | 1.000 | **PASS** |
| `comp_ascorbic_panthenol` | comparison | 산도가 높은 아스코빅애씨드(비타민C)의 따가운 자극... | 0.0 | 0.0 | 0.00 | 0.00 | 0.091 | **FAIL** |
| `alias_bha_acne` | alias | BHA 성분이 들어간 화장품이 블랙헤드와 좁쌀 여드... | 1.0 | 1.0 | 0.25 | 0.20 | 1.000 | **PASS** |
| `alias_aha_exfoliation` | alias | AHA 성분 토너나 필링젤의 각질 박리 및 피부결 ... | 1.0 | 1.0 | 0.50 | 0.40 | 1.000 | **PASS** |
| `alias_cica_soothing` | alias | 시카(CICA) 크림이 붉은기 완화와 피부 재생에 ... | 1.0 | 1.0 | 1.00 | 0.80 | 0.500 | **PASS** |
| `alias_vitamin_c_whitening` | alias | 비타민C 앰플을 바르면 기미 주근깨 미백에 얼마나 ... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `alias_panthenol_b5` | alias | 프로비타민 B5로 알려진 성분의 피부 장벽 재생 및... | 1.0 | 1.0 | 0.50 | 0.20 | 0.333 | **PASS** |
| `alias_hyaluronic_acid` | alias | 히알루론산 세럼이 피부 수분을 끌어당기는 원리와 보... | 1.0 | 1.0 | 1.00 | 0.80 | 1.000 | **PASS** |
| `zero_gamma_terpinene` | zero_evidence | 감마-터피넨 성분은 피부 장벽 개선에 대한 임상 논... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `zero_fake_chemical` | zero_evidence | 디메틸트리옥시펩타이드 성분의 안티에이징 주름 개선 ... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `zero_unrelated_query` | zero_evidence | 오늘 서울 날씨 기온이 몇 도인지 알려줄 수 있나요... | 1.0 | 1.0 | 1.00 | 1.00 | 1.000 | **PASS** |
| `zero_non_skincare_plant` | zero_evidence | 참나물 잎 추출물의 기미 주근깨 멜라닌 색소 억제 ... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
| `zero_unregistered_peptide` | zero_evidence | 옥타펩타이드-99 원료의 피부 침투 및 콜라겐 유도... | 1.0 | 1.0 | 1.00 | 1.00 | 1.000 | **PASS** |
| `zero_food_ingredient` | zero_evidence | 된장찌개 끓일 때 두부와 애호박을 언제 넣어야 맛있... | 0.0 | 0.0 | 0.00 | 0.00 | 0.000 | **FAIL** |
