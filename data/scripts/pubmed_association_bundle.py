"""검수된 PubMed 복합 제형을 복수 표준 성분에 연결한 Evidence bundle로 만든다."""

import argparse
import json
import sys
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from data.scripts.evidence_collector_schemas import (
    CollectionIngredient,
    EvidenceBundle,
    PubmedSelectionDisposition,
    PubmedSelectionReason,
)
from data.scripts.pubmed_client import PubmedClient, PubmedSource
from data.scripts.pubmed_evidence_mapper import PubmedEvidenceMapper
from data.scripts.pubmed_selection_policy import PubmedSelectionPolicy
from models.evidence_document import EvidenceFormulationType

_DEFAULT_REVIEWS_PATH = Path("data/manual_review/pubmed_association_reviews.json")
_DEFAULT_OUTPUT_PATH = Path(
    "data/outputs/evidence_coverage/pubmed_association_bundle.jsonl"
)
_JSON_INDENT = 2


class AssociationReviewStatus(StrEnum):
    APPROVED = "approved"


class AssociationIngredient(BaseModel):
    model_config = ConfigDict(frozen=True)

    ingredient_id: UUID
    standard_name_en: str = Field(min_length=1)
    standard_name_ko: str | None = Field(default=None, min_length=1)
    aliases: list[str] = Field(default_factory=list)

    def collection_ingredient(self) -> CollectionIngredient:
        return CollectionIngredient(
            ingredient_id=self.ingredient_id,
            standard_name_en=self.standard_name_en,
            standard_name_ko=self.standard_name_ko,
            aliases=self.aliases,
        )


class PubmedAssociationReview(BaseModel):
    model_config = ConfigDict(frozen=True)

    pmid: str = Field(min_length=1)
    status: AssociationReviewStatus
    ingredients: list[AssociationIngredient] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_unique_ingredients(self) -> Self:
        ids = [ingredient.ingredient_id for ingredient in self.ingredients]
        if len(ids) != len(set(ids)):
            raise ValueError(f"PMID {self.pmid}의 association 성분 ID가 중복되었습니다.")
        return self


class PubmedAssociationBuildResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    bundles: list[EvidenceBundle]


class PubmedAssociationBuildSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    dry_run: bool
    reviews: int
    documents: int
    chunks: int
    ingredient_links: int
    output_path: str


class PubmedAssociationBundleBuilder:
    """공식 레코드와 자동 분류를 재검증한 뒤 검수된 복수 ID를 그대로 연결한다."""

    def __init__(self, source: PubmedSource | None = None) -> None:
        self._source = source or PubmedClient()
        self._policy = PubmedSelectionPolicy()
        self._mapper = PubmedEvidenceMapper()

    def build(
        self,
        reviews: list[PubmedAssociationReview],
        *,
        retrieved_at: datetime,
    ) -> PubmedAssociationBuildResult:
        pmids = list(dict.fromkeys(review.pmid for review in reviews))
        records = {record.pmid: record for record in self._source.fetch(pmids)}
        missing = [pmid for pmid in pmids if pmid not in records]
        if missing:
            raise RuntimeError("PubMed에서 검수 대상 PMID를 찾지 못했습니다: " + ", ".join(missing))

        bundles: list[EvidenceBundle] = []
        for review in reviews:
            if review.status is not AssociationReviewStatus.APPROVED:
                raise ValueError(f"승인되지 않은 association review입니다: PMID {review.pmid}")
            record = records[review.pmid]
            assessment = self._policy.assess_record(
                review.ingredients[0].collection_ingredient(),
                record,
            )
            if (
                assessment.formulation_type
                is not EvidenceFormulationType.COMBINATION_FORMULATION
                or assessment.disposition is not PubmedSelectionDisposition.CANDIDATE
                or assessment.reason
                is not PubmedSelectionReason.COMBINATION_REQUIRES_ASSOCIATION_MAPPING
            ):
                raise ValueError(
                    "검수 입력이 association 후보 분류와 일치하지 않습니다: "
                    f"PMID {review.pmid}, disposition={assessment.disposition.value}, "
                    f"reason={assessment.reason}, formulation={assessment.formulation_type.value}"
                )
            self._validate_mentions(review, record.title, record.abstract or "", record.mesh_terms)
            bundles.append(
                self._mapper.to_bundle(
                    assessment,
                    ingredient_ids=[ingredient.ingredient_id for ingredient in review.ingredients],
                    raw_ingredient_names=list(
                        dict.fromkeys(
                            name
                            for ingredient in review.ingredients
                            for name in [ingredient.standard_name_en, *ingredient.aliases]
                        )
                    ),
                    retrieved_at=retrieved_at,
                )
            )
        return PubmedAssociationBuildResult(bundles=bundles)

    def _validate_mentions(
        self,
        review: PubmedAssociationReview,
        title: str,
        abstract: str,
        mesh_terms: list[str],
    ) -> None:
        normalized_source = self._normalized(" ".join([title, abstract, *mesh_terms]))
        missing: list[str] = []
        for ingredient in review.ingredients:
            names = [ingredient.standard_name_en, *ingredient.aliases]
            if not any(self._normalized(name) in normalized_source for name in names):
                missing.append(ingredient.standard_name_en)
        if missing:
            raise ValueError(
                f"PMID {review.pmid} 원문에서 association 성분을 확인하지 못했습니다: "
                + ", ".join(missing)
            )

    def _normalized(self, value: str) -> str:
        return "".join(character.casefold() for character in value if character.isalnum())


class PubmedAssociationBundleCli:
    def run(self) -> None:
        arguments = self._arguments()
        reviews = self._read_reviews(arguments.reviews)
        result = PubmedAssociationBundleBuilder().build(
            reviews,
            retrieved_at=datetime.now(UTC),
        )
        if not arguments.dry_run:
            self._write(result, arguments.output)
        summary = PubmedAssociationBuildSummary(
            dry_run=arguments.dry_run,
            reviews=len(reviews),
            documents=len(result.bundles),
            chunks=sum(len(bundle.chunks) for bundle in result.bundles),
            ingredient_links=sum(
                len(chunk.ingredient_ids)
                for bundle in result.bundles
                for chunk in bundle.chunks
            ),
            output_path=str(arguments.output),
        )
        print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=_JSON_INDENT))

    def _read_reviews(self, path: Path) -> list[PubmedAssociationReview]:
        if not path.exists():
            raise RuntimeError(f"association review 파일이 없습니다: {path}")
        try:
            return TypeAdapter(list[PubmedAssociationReview]).validate_json(
                path.read_text(encoding="utf-8")
            )
        except ValueError as error:
            raise RuntimeError(f"association review 형식이 올바르지 않습니다: {error}") from error

    def _write(self, result: PubmedAssociationBuildResult, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(bundle.model_dump_json() + "\n" for bundle in result.bundles),
            encoding="utf-8",
        )

    def _arguments(self) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--reviews", type=Path, default=_DEFAULT_REVIEWS_PATH)
        parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT_PATH)
        parser.add_argument("--dry-run", action="store_true")
        return parser.parse_args()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    PubmedAssociationBundleCli().run()
