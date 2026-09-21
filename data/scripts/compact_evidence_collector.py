"""compact Evidence collector 진입점. 입력으로 받은 성분만, 상한 안에서, source 별로 수집한다.

Tier A 는 하드코딩하지 않는다 - `--ingredients-file`(JSON 배열)로 넘긴 성분만 처리한다.
DB 에 쓰지 않고 임베딩도 하지 않는다. 결과는 `EvidenceBundle` JSONL(draft)로만 남기며, 임베딩·
적재는 이후 단계가 이 파일을 읽어 수행한다.

- `--source pubmed`: 성분당 최대 `--max-papers-per-ingredient`(기본·상한 4)편만 선별한다.
  `--dry-run` 이어도 ESearch/EFetch 읽기 요청은 나가지만 파일은 쓰지 않는다.
- `--source cir`: 네트워크를 쓰지 않는다. 이미 발견한 report 목록(`--cir-reports-file`, PDF 경로
  포함)에서 성분별 최신 final/amended report 만 골라 PDF 텍스트를 chunk 로 나눈다.
  report 발견과 PDF 확보 자동화는 이 스크립트 범위 밖이다(docs/data/COMPACT_EVIDENCE_COLLECTOR.md).

재실행 안전성: 출력 JSONL 이 곧 진행 상태다. 이미 결과가 있는 PMID/attachment 는 다시 저장하지
않고(성분 연결만 합친다), 이미 수집된 성분의 PubMed 검색은 건너뛴다.

사용법:
    uv run python -m data.scripts.compact_evidence_collector --source pubmed \
        --ingredients-file tier_a.json --max-ingredients 1 --dry-run
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, TypeAdapter

from data.scripts.cir_evidence_builder import CirEvidenceBuilder
from data.scripts.cir_report_selector import CirReportSelector
from data.scripts.evidence_collector_schemas import (
    CirReportCandidate,
    CollectionIngredient,
    EvidenceBundle,
    EvidenceCollectionSource,
    PubmedAssessment,
)
from data.scripts.pubmed_client import PubmedClient, PubmedSource
from data.scripts.pubmed_evidence_collector import PubmedEvidenceCollector
from data.scripts.pubmed_evidence_mapper import PubmedEvidenceMapper
from data.scripts.pubmed_selection_policy import (
    DEFAULT_MAX_PAPERS_PER_INGREDIENT,
    PubmedSelectionPolicy,
)
from models.evidence_document import EvidenceDocumentSourceType

_DEFAULT_OUTPUT_PATH = Path("data/processed/compact_evidence_bundles.jsonl")
_DEFAULT_CANDIDATES_PATH = Path("data/manual_review/compact_evidence_pubmed_candidates.jsonl")
_JSON_INDENT = 2


class CompactCollectionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: EvidenceCollectionSource
    dry_run: bool
    ingredients_requested: int
    ingredients_skipped_already_collected: int
    documents_selected: int
    documents_new: int
    chunks_in_output: int
    review_candidates: int
    network_requests: int
    warnings: list[str]


class CompactEvidenceCollectorRunner:
    def __init__(
        self,
        *,
        output_path: Path = _DEFAULT_OUTPUT_PATH,
        candidates_path: Path = _DEFAULT_CANDIDATES_PATH,
        dry_run: bool,
        pubmed_source: PubmedSource | None = None,
        max_papers_per_ingredient: int = DEFAULT_MAX_PAPERS_PER_INGREDIENT,
        now: datetime | None = None,
    ) -> None:
        self._output_path = output_path
        self._candidates_path = candidates_path
        self._dry_run = dry_run
        self._pubmed_source = pubmed_source
        self._policy = PubmedSelectionPolicy(max_papers_per_ingredient)
        self._pubmed_mapper = PubmedEvidenceMapper()
        self._cir_builder = CirEvidenceBuilder()
        self._cir_selector = CirReportSelector()
        self._retrieved_at = now or datetime.now(UTC)

    # ------------------------------------------------------------------ pubmed

    def run_pubmed(self, ingredients: list[CollectionIngredient]) -> CompactCollectionSummary:
        source = self._pubmed_source or PubmedClient()
        collector = PubmedEvidenceCollector(source, self._policy)
        bundles = self._read_bundles()
        candidates = self._read_candidates()

        already_collected = {
            ingredient_id
            for bundle in bundles.values()
            if bundle.document.source_type is EvidenceDocumentSourceType.PUBMED_ABSTRACT
            for ingredient_id in bundle.document.ingredient_ids
        }
        skipped = 0
        selected_count = 0
        new_documents = 0
        for ingredient in ingredients:
            if ingredient.ingredient_id in already_collected:
                skipped += 1
                continue
            result = collector.collect(ingredient)
            names = self._policy.search_names(ingredient)
            for assessment in result.selected:
                selected_count += 1
                bundle = self._pubmed_mapper.to_bundle(
                    assessment,
                    ingredient_ids=[ingredient.ingredient_id],
                    raw_ingredient_names=names,
                    retrieved_at=self._retrieved_at,
                )
                new_documents += self._merge_bundle(bundles, bundle)
            for assessment in result.candidates:
                candidates[(assessment.ingredient_id, assessment.record.pmid)] = assessment
            self._write(bundles, candidates)

        return CompactCollectionSummary(
            source=EvidenceCollectionSource.PUBMED,
            dry_run=self._dry_run,
            ingredients_requested=len(ingredients),
            ingredients_skipped_already_collected=skipped,
            documents_selected=selected_count,
            documents_new=new_documents,
            chunks_in_output=sum(len(b.chunks) for b in bundles.values()),
            review_candidates=len(candidates),
            network_requests=getattr(source, "request_count", 0),
            warnings=[],
        )

    # --------------------------------------------------------------------- cir

    def run_cir(
        self, ingredients: list[CollectionIngredient], reports: list[CirReportCandidate]
    ) -> CompactCollectionSummary:
        bundles = self._read_bundles()
        selected = self._cir_selector.select(reports, [i.ingredient_id for i in ingredients])
        warnings: list[str] = []
        new_documents = 0
        for report in selected:
            if report.pdf_path is None:
                warnings.append(f"{report.attachment_id}: PDF 경로가 없어 건너뜀")
                continue
            page_texts = self._cir_builder.extract_page_texts(report.pdf_path)
            bundle, chunking = self._cir_builder.build_bundle(
                report, page_texts, retrieved_at=self._retrieved_at
            )
            warnings.extend(f"{report.attachment_id}: {w.value}" for w in chunking.warnings)
            new_documents += self._merge_bundle(bundles, bundle)
        self._write(bundles, None)

        return CompactCollectionSummary(
            source=EvidenceCollectionSource.CIR,
            dry_run=self._dry_run,
            ingredients_requested=len(ingredients),
            ingredients_skipped_already_collected=0,
            documents_selected=len(selected),
            documents_new=new_documents,
            chunks_in_output=sum(len(b.chunks) for b in bundles.values()),
            review_candidates=0,
            network_requests=0,
            warnings=warnings,
        )

    # ------------------------------------------------------------------ storage

    def _merge_bundle(self, bundles: dict[str, EvidenceBundle], new: EvidenceBundle) -> int:
        """같은 source_id 가 이미 있으면 새로 저장하지 않고 성분 연결만 합친다. 새 document 면 1."""
        source_id = new.document.source_id
        existing = bundles.get(source_id)
        if existing is None:
            bundles[source_id] = new
            return 1
        ingredient_ids = list(
            dict.fromkeys([*existing.document.ingredient_ids, *new.document.ingredient_ids])
        )
        raw_names = list(
            dict.fromkeys(
                [*existing.document.raw_ingredient_names, *new.document.raw_ingredient_names]
            )
        )
        bundles[source_id] = EvidenceBundle(
            document=existing.document.model_copy(
                update={"ingredient_ids": ingredient_ids, "raw_ingredient_names": raw_names}
            ),
            chunks=[
                c.model_copy(update={"ingredient_ids": ingredient_ids}) for c in existing.chunks
            ],
        )
        return 0

    def _read_bundles(self) -> dict[str, EvidenceBundle]:
        bundles: dict[str, EvidenceBundle] = {}
        for line in self._read_lines(self._output_path):
            bundle = EvidenceBundle.model_validate_json(line)
            bundles[bundle.document.source_id] = bundle
        return bundles

    def _read_candidates(self) -> dict[tuple[UUID, str], PubmedAssessment]:
        candidates: dict[tuple[UUID, str], PubmedAssessment] = {}
        for line in self._read_lines(self._candidates_path):
            assessment = PubmedAssessment.model_validate_json(line)
            candidates[(assessment.ingredient_id, assessment.record.pmid)] = assessment
        return candidates

    def _read_lines(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _write(
        self,
        bundles: dict[str, EvidenceBundle],
        candidates: dict[tuple[UUID, str], PubmedAssessment] | None,
    ) -> None:
        if self._dry_run:
            return
        self._write_jsonl(self._output_path, [b.model_dump_json() for b in bundles.values()])
        if candidates is not None:
            self._write_jsonl(
                self._candidates_path, [a.model_dump_json() for a in candidates.values()]
            )

    def _write_jsonl(self, path: Path, lines: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # 쓰는 도중 중단돼도 기존 결과가 깨지지 않도록 임시 파일에 쓰고 교체한다
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
        temp_path.replace(path)


def _load_json_list[T: BaseModel](path: Path, model: type[T], *, label: str) -> list[T]:
    if not path.exists():
        raise RuntimeError(f"{label} 파일이 없습니다: {path}")
    try:
        return TypeAdapter(list[model]).validate_json(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise RuntimeError(f"{label} 파일 형식이 올바르지 않습니다({path}): {e}") from e


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--source",
        type=EvidenceCollectionSource,
        choices=list(EvidenceCollectionSource),
        required=True,
    )
    parser.add_argument(
        "--ingredients-file", type=Path, required=True, help="CollectionIngredient JSON 배열"
    )
    parser.add_argument("--max-ingredients", type=int, default=None)
    parser.add_argument(
        "--max-papers-per-ingredient", type=int, default=DEFAULT_MAX_PAPERS_PER_INGREDIENT
    )
    parser.add_argument(
        "--cir-reports-file",
        type=Path,
        default=None,
        help="CirReportCandidate JSON 배열(--source cir)",
    )
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT_PATH)
    parser.add_argument("--candidates-output", type=Path, default=_DEFAULT_CANDIDATES_PATH)
    parser.add_argument(
        "--dry-run", action="store_true", help="파일을 쓰지 않는다(PubMed 읽기 요청은 나간다)"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    # 해외 성분·저널명이 cp949 콘솔에서 print 를 죽이지 않도록(docs/data/README.md 사례)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    args = _parse_args(argv)

    ingredients = _load_json_list(args.ingredients_file, CollectionIngredient, label="성분 입력")
    if args.max_ingredients is not None:
        ingredients = ingredients[: args.max_ingredients]

    runner = CompactEvidenceCollectorRunner(
        output_path=args.output,
        candidates_path=args.candidates_output,
        dry_run=args.dry_run,
        max_papers_per_ingredient=args.max_papers_per_ingredient,
    )
    if args.source is EvidenceCollectionSource.PUBMED:
        summary = runner.run_pubmed(ingredients)
    else:
        if args.cir_reports_file is None:
            raise RuntimeError("--source cir 는 --cir-reports-file 이 필요합니다")
        reports = _load_json_list(
            args.cir_reports_file, CirReportCandidate, label="CIR report 목록"
        )
        summary = runner.run_cir(ingredients, reports)
    print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=_JSON_INDENT))


if __name__ == "__main__":
    main()
