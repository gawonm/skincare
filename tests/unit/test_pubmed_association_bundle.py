"""검수된 복합 PubMed 자료가 단일 성분으로 축소되지 않는지 검증한다."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from data.scripts.evidence_collector_schemas import PubmedRecord
from data.scripts.pubmed_association_bundle import (
    AssociationIngredient,
    AssociationReviewStatus,
    PubmedAssociationBundleBuilder,
    PubmedAssociationReview,
)
from models.evidence_document import EvidenceFormulationType


class AssociationSource:
    def __init__(self, records: list[PubmedRecord]) -> None:
        self._records = {record.pmid: record for record in records}

    def fetch(self, pmids: list[str]) -> list[PubmedRecord]:
        return [self._records[pmid] for pmid in pmids if pmid in self._records]


class PubmedAssociationFixture:
    CHITIN_ID = UUID("c4399298-58ae-4df1-8f6b-eeaae7a98ce3")
    BETA_GLUCAN_ID = UUID("94c4bad8-5f3b-47c9-8044-543ec8f971a7")

    def record(self) -> PubmedRecord:
        return PubmedRecord(
            pmid="19099547",
            doi="10.1111/test",
            title="Chitin-glucan, a natural cell scaffold for skin moisturization.",
            abstract=(
                "A randomized double-blind placebo-controlled study evaluated topical "
                "chitin and beta-glucan formulations applied twice daily. Skin hydration "
                "improved and transepidermal water loss decreased."
            ),
            journal="Test journal",
            publication_date=date(2008, 12, 1),
            publication_types=["Randomized Controlled Trial"],
            mesh_terms=["Humans", "Skin", "Chitin", "beta-Glucans"],
            authors=["Tester A"],
        )

    def review(self, *, beta_aliases: list[str] | None = None) -> PubmedAssociationReview:
        return PubmedAssociationReview(
            pmid="19099547",
            status=AssociationReviewStatus.APPROVED,
            ingredients=[
                AssociationIngredient(
                    ingredient_id=self.CHITIN_ID,
                    standard_name_en="Chitin",
                ),
                AssociationIngredient(
                    ingredient_id=self.BETA_GLUCAN_ID,
                    standard_name_en="Beta-Glucan",
                    aliases=beta_aliases or ["beta-glucan"],
                ),
            ],
        )


class TestPubmedAssociationBundleBuilder:
    def test_복합_자료를_두_표준_성분에_연결한다(self) -> None:
        fixture = PubmedAssociationFixture()
        result = PubmedAssociationBundleBuilder(
            AssociationSource([fixture.record()])
        ).build([fixture.review()], retrieved_at=datetime(2026, 9, 23, tzinfo=UTC))

        assert len(result.bundles) == 1
        bundle = result.bundles[0]
        assert bundle.document.formulation_type is EvidenceFormulationType.COMBINATION_FORMULATION
        assert bundle.document.ingredient_ids == [fixture.CHITIN_ID, fixture.BETA_GLUCAN_ID]
        assert bundle.chunks[0].ingredient_ids == [fixture.CHITIN_ID, fixture.BETA_GLUCAN_ID]

    def test_원문에서_확인할_수_없는_성분_연결은_거부한다(self) -> None:
        fixture = PubmedAssociationFixture()
        review = fixture.review(beta_aliases=["unmentioned compound"])
        review = review.model_copy(
            update={
                "ingredients": [
                    review.ingredients[0],
                    review.ingredients[1].model_copy(
                        update={"standard_name_en": "Unmentioned Compound"}
                    ),
                ]
            }
        )

        with pytest.raises(ValueError, match="원문에서 association 성분"):
            PubmedAssociationBundleBuilder(AssociationSource([fixture.record()])).build(
                [review],
                retrieved_at=datetime(2026, 9, 23, tzinfo=UTC),
            )
