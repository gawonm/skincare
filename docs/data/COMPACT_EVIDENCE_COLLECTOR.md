# Compact Evidence Collector (PubMed / CIR)

Evidence RAG 를 대규모 literature corpus 로 넓히는 게 아니라, **서비스 핵심 성분(Tier A)만 최소
충분 근거로** 수집하기 위한 collector 다. Tier A 는 하드코딩하지 않고 입력으로 받는다.
저장 계약은 `EvidenceDocument`/`EvidenceChunk`(BGE-M3 1024차원)를 그대로 쓴다
([EVIDENCE_STORAGE_ERD.md](EVIDENCE_STORAGE_ERD.md), [EXTERNAL_EVIDENCE_INGESTION_CONTRACT.md](EXTERNAL_EVIDENCE_INGESTION_CONTRACT.md)).

## 하는 일 / 안 하는 일

- 하는 일: 성분 목록 → PubMed 선별 / CIR report 선별 → `EvidenceBundle`(document draft + chunk
  draft) JSONL.
- 안 하는 일: DB 쓰기, 임베딩, Tier A 선정, IngredientMaster 전체 검색, PMC full-text, LLM 판정,
  스키마 변경. 임베딩·적재는 draft 를 읽는 이후 단계의 몫이다(현재 MFDS 로더는
  `EvidenceChunkStagingRecord` 를 읽으므로 draft 를 읽는 어댑터가 필요하다).

## 입력

`--ingredients-file`: `CollectionIngredient` JSON 배열.

```json
[{"ingredient_id": "<uuid>", "standard_name_en": "Niacinamide",
  "standard_name_ko": "나이아신아마이드", "aliases": ["Nicotinamide"]}]
```

## 실행

```bash
uv run python -m data.scripts.compact_evidence_collector --source pubmed \
  --ingredients-file tier_a.json --max-ingredients 1 --dry-run
```

| 옵션 | 의미 |
| --- | --- |
| `--source pubmed\|cir` | source 별로 분리 실행 |
| `--max-ingredients N` | 입력 앞에서 N개 성분만 처리 |
| `--max-papers-per-ingredient N` | PubMed 성분당 편수. 기본 3, **1~3 초과 시 오류**(성분 전체 기준, quota 아님: 0편 허용) |
| `--dry-run` | 파일을 쓰지 않는다. PubMed 는 읽기 요청(ESearch/EFetch)은 나간다 |
| `--cir-reports-file` | `--source cir` 입력: `CirReportCandidate` JSON 배열(PDF 경로 포함) |

기본 출력은 `data/processed/compact_evidence_bundles.jsonl`(bundle),
`data/manual_review/compact_evidence_pubmed_candidates.jsonl`(사람 검토용 후보).
출력 파일이 곧 진행 상태다 — 재실행하면 이미 있는 PMID/attachment 는 다시 저장하지 않고 성분
연결만 합치며, 이미 수집된 성분의 PubMed 검색은 건너뛴다(예산을 늘려 다시 받으려면 출력 파일에서
해당 성분의 bundle 을 지운다).

검수된 복합 제형은 일반 collector 출력에 자동 포함하지 않는다. 복수 표준 성분 ID를 확정한
`data/manual_review/pubmed_association_reviews.json`만
`data.scripts.pubmed_association_bundle`로 별도 bundle을 만들며, 현재 반영 내역은
[PUBMED_ASSOCIATION_EVIDENCE_REPORT.md](PUBMED_ASSOCIATION_EVIDENCE_REPORT.md)에 기록한다.

## PubMed

- 공식 E-utilities 만 사용, 요청 간격 0.4초, 실패는 3회 재시도 후 예외.
- 질의: ① 임상 근거(RCT/clinical trial/SR/meta-analysis) + 피부/국소 범위 → 예산을 못 채우면
  ② humans[MeSH] + 피부/국소 범위. 질의당 최대 15건만 가져온다. 한글 별칭은 질의에서 제외.
- 선별(LLM 없음, title/abstract/publication type/MeSH 만, `pubmed_evidence_rules.py`): SELECTED 는 **이 성분의 국소 피부
  직접 근거**만이다. 다음을 모두 통과해야 하고, 통과하지 못하면 이유를 붙인 candidate(또는 버림)로 남는다. 성분당 대표 1~3편, 적합한
  논문이 없으면 0편이다.
  1. abstract 있음, erratum·editorial·letter·case report 등 제외
  2. **피부 관련성**: 제목/MeSH 에 피부 맥락이 있거나 초록에 서로 다른 피부 용어 2개 이상. 통과 못 하면 **버림**
     (`skin` 이 세포 출처로만 스치는 cystinosis 논문 등)
  3. **연구 설계**: human_clinical / review 만. mixed(임상+실험실)는 제형 개발 논문이 섞이므로 기본 candidate(`mixed_design_review`), 예외 규칙 없음. 임상 설계 단서(무작위·placebo·split-face 등)와 사람 대상 단서가
     함께 있어야 human 이고 "Humans" MeSH 단독은 human 이 아니다. in_vitro / ex_vivo / animal / unclear 는 candidate
     (`non_clinical_study_design`). DB enum 에 ex_vivo 가 없어 저장 시 in_vitro 로 접는다(마이그레이션 없음)
  4. **투여 경로**: topical 만. oral·injection 은 candidate(`route_not_topical`), 판별 불가는 topical 로 간주하지 않고
     candidate(`route_unclear`). 제목 단서가 우선, `oral cavity` 등은 경구 투여로 보지 않는다
  5. **직접성**: 제목에서 `outperforms/versus/compared with/than <성분>` 처럼 비교 대조로만 등장하면 candidate(`comparator_only`).
     제목에 성분이 없으면 candidate(`ingredient_not_in_title`)
  6. **claim topic**: abstract 가 지지하는 topic 만 연결(제목만으로는 안 됨). topic 이 비면 임의로 만들지 않고 자동 selected 도 하지 않는다
     (candidate `no_claim_topic`). `cytotoxicity`·일반 `safety` 단어는 precaution 이 아니다
  점수는 성분 언급, RCT·SR, 근거 topic 수가 올리고 복합 제형이 내린다. 동점은 최신 → PMID 순.
  **등급 우선 정렬**: 단일 성분 직접(`direct_single_topical_human`) → 리뷰 순으로 뽑는다. 복합 제형은
  현재 성분 하나에 자동 귀속하지 않고 `combination_requires_association_mapping` candidate로 보내 복수 표준 ID를 검수한다.
  상위 N편(≤3)만 SELECTED, 나머지는 `over_budget` candidate(성분당 최대 10). route/study_design/ingredient_role/skin_relevance/
  evidence_grade 는 candidate JSONL 에만 남고 DB 컬럼은 없다.
- **alias 계약**: `CollectionIngredient.aliases` 는 exact-equivalent 표기(철자·구 INCI 명칭)만 담는다. universe export 는
  IngredientMaster 의 구 영문명만 넣고, family expansion 용어·파생형·계열명(BHA/AHA 등)은 넣지 않는다. family 용어 결과를 원형 성분에
  귀속하지 않기 위해서다. 모호한 계열 용어의 일반화 처리는 Agent 쪽 정책이며 여기서 성분별로 하드코딩하지 않는다.
- 복합 제형: 제목에서 성분명에 붙은 `and/with/plus/+/,`, `chitin-glucan` 같은 하이픈 결합명 또는
  combination/combined를 감지해 `formulation_type=combination_formulation`으로 표시한다. 자동 SELECTED로
  만들지 않고, 모든 정확한 성분 ID를 검수해 association으로 연결하기 전까지 candidate로 보존한다.
- Chunk: 1 PMID = document 1건, abstract 원문 전체 = chunk 1건(`section="abstract"`,
  `chunk_index=0`, `chunk_id="PMID:{pmid}:abstract:0"`). authors 는 저장 컬럼이 없어 draft 에 넣지
  않는다(`PubmedRecord` 에만 있음).

## CIR

- 선택(`CirReportSelector`): FINAL / AMENDED_FINAL("Published Report")만 후보, 성분별 최신 1건.
  re-review("Not Opened")·draft·tentative·알 수 없는 라벨은 제외. group review 는 report 1건에
  요청된 성분 여러 개를 연결한다. `is_amended` 는 status 라벨만으로 구분되지 않아 입력이 채운다.
- Chunk(`CirSectionChunker`): 전체 대문자 단독 줄을 heading 으로 감지, 3쪽 이상 반복되는 줄은
  러닝 헤더로 제거, `REFERENCES` 이후는 제외. **임베딩 대상은 heading 에 `CLINICAL`,
  `SAFETY ASSESSMENT`, `DISCUSSION`, `CONCLUSION` 이 들어간 section 뿐**이다. 조각은 절대 page
  경계를 넘지 않고, 3,000자를 넘는 조각만 문장 끝에서 나눈다. heading 을 하나도 못 찾거나 대상
  section 이 없으면 chunk 를 만들지 않고 경고한다(전체 페이지를 임베딩하지 않는다).
- 원문 전체는 로컬 PDF 로 보존되고 draft 에는 대상 section 원문 span 과 provenance(page, section,
  chunk_index, content_hash, parser_version, 제목, URL)만 담긴다.

### 텍스트 추출

`CirPdfTextExtractor`(pdfplumber): `x_tolerance=1`(기본 3 은 공백을 잃음), 가운데 선을 걸치는 단어가
2% 이하인 페이지는 좌·우 컬럼을 따로 뽑아 이어 붙인다(기본 추출은 컬럼을 같은 줄로 섞어
`REFERENCES` heading 이 줄 끝에 붙고 참고문헌이 CONCLUSION 으로 섞였다 — Niacinamide 실측).

### Niacinamide 실측(2026-09-21, 브라우저 1회 수동 확보 + collector)

- status 페이지(`cir-ingredient-status-report?id=2a9f266a-…`)에서 `a[href*='view-attachment']` 1개
  (`Published Report`, attachment `39cd1a17-…`) 발견.
- viewer 페이지의 `iframe/embed/object` src 가 `blob:` URL 이고 그 안에서 `fetch(blob)` →
  base64 로 PDF 205,539 bytes(`%PDF-1.4`) 확보. 두 페이지 로드 사이 10초 간격.
- `--source cir` 결과: document 1건(`cir_attachment:39cd1a17-…`, status `final`) + chunk 12건 —
  `CLINICAL ASSESSMENT OF SAFETY` 20~24쪽 10건, `DISCUSSION` 28쪽 1건, `CONCLUSION` 28쪽 1건.
  참고문헌·러닝헤더·INTRODUCTION 등은 제외됐다.

### 아직 저장소 코드가 아닌 것 (blocker)

1. **report 발견/PDF 확보 자동화**: 위 절차는 scratchpad 스크립트로만 검증했고 collector 코드에는
   없다. Playwright 로 구현하려면 Crawl-delay 10초 준수와 `blob:` 추출을 클래스로 만들어야 한다.
   지금은 사람이 받은 PDF 를 `pdf_path` 로 넘긴다. status 페이지 행에서는 라벨(`Published Report`)만
   얻었고 발행일·저널·DOI 는 얻지 못했다 — 이 값들은 PDF 첫 페이지 인용 문자열 파싱이 필요해
   현재는 `CirReportCandidate` 입력값이다(smoke 에서는 `CIR_PDF_INGESTION_FEASIBILITY.md` 에 기록된
   값 — 2005년, International Journal of Toxicology, DOI — 을 그대로 채웠다).
2. 검색 경로(`/search/`)는 robots.txt 가 막으므로 성분 → status 페이지 UUID 매핑은 입력으로 받아야 한다.

## 알려진 한계

- PubMed 성분 매칭은 이름 경계 일치라 `Nicotinamide Riboside` 같은 **다른 화합물**이 alias
  `Nicotinamide` 로 잡힐 수 있다(실측). 국소 맥락 점수가 후순위로 밀지만 제거하지는 않는다 —
  성분명 정확 매칭이 필요하면 `ingredient_master` 기준 검증을 붙여야 한다.
- 연구 유형·복합 제형은 title/MeSH/publication type 규칙 추정이다. 놓치면 UNKNOWN/단일로 남는다.
- CIR heading·컬럼 규칙은 2005년 Niacinamide 1건으로만 검증됐다. 오래된/amended 보고서 템플릿은
  미검증(스캔본이면 텍스트 레이어가 없을 수 있다). 여러 페이지에 3번 이상 반복되는 진짜
  heading 은 러닝 헤더로 오인될 수 있다.
