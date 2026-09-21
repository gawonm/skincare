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
| `--max-papers-per-ingredient N` | PubMed 성분당 편수. 기본 4, **1~4 초과 시 오류**(성분 전체 기준) |
| `--dry-run` | 파일을 쓰지 않는다. PubMed 는 읽기 요청(ESearch/EFetch)은 나간다 |
| `--cir-reports-file` | `--source cir` 입력: `CirReportCandidate` JSON 배열(PDF 경로 포함) |

기본 출력은 `data/processed/compact_evidence_bundles.jsonl`(bundle),
`data/manual_review/compact_evidence_pubmed_candidates.jsonl`(사람 검토용 후보).
출력 파일이 곧 진행 상태다 — 재실행하면 이미 있는 PMID/attachment 는 다시 저장하지 않고 성분
연결만 합치며, 이미 수집된 성분의 PubMed 검색은 건너뛴다(예산을 늘려 다시 받으려면 출력 파일에서
해당 성분의 bundle 을 지운다).

## PubMed

- 공식 E-utilities 만 사용, 요청 간격 0.4초, 실패는 3회 재시도 후 예외.
- 질의: ① 임상 근거(RCT/clinical trial/SR/meta-analysis) + 피부/국소 범위 → 예산을 못 채우면
  ② humans[MeSH] + 피부/국소 범위. 질의당 최대 15건만 가져온다. 한글 별칭은 질의에서 제외.
- 선별(LLM 없음, title/abstract/publication type/MeSH 만): abstract 없음·erratum·editorial·
  letter·case report 등은 제외. 제목에 성분명이 없거나 연구 유형이 human/review/mixed 가 아니면
  자동 확정하지 않고 **candidate** 로 남긴다. 점수는 성분 직접 언급, RCT·SR, human, efficacy/
  precaution 키워드, 국소·화장품 맥락(경구 보충제 연구 후순위)이 올리고 복합 제형이 내린다.
  동점은 최신 → PMID 순. 상위 N편(≤4)만 SELECTED, 나머지는 `over_budget` candidate(성분당 최대 10).
- 복합 제형: 제목에서 성분명에 붙은 `and/with/plus/+/,` 또는 combination/combined 를 감지해
  `formulation_type=combination_formulation` 으로 표시하고 감점한다.
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
