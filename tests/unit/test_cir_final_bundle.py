"""CIR final bundle의 exact-linkage와 snapshot blocker 회귀 검증."""

from pathlib import Path
from uuid import UUID

from data.scripts.cir_final_bundle import (
    ExactIngredientMatcher,
    IngredientSpec,
    LinkageType,
    PostgresCopySnapshotReader,
)


class TestExactIngredientMatcher:
    def test_parent_does_not_match_derivative(self) -> None:
        matcher = ExactIngredientMatcher()
        ingredient = IngredientSpec(
            name="Salicylic Acid",
            exact_terms=["Salicylic Acid"],
            excluded_terms=["Capryloyl Salicylic Acid"],
        )
        assert matcher.match("Capryloyl Salicylic Acid was reassessed.", ingredient) is None
        assert matcher.match("Salicylic Acid was reassessed.", ingredient) is not None
        assert matcher.match("Sodium salicylate was reassessed.", ingredient) is None

    def test_approved_exact_equivalent_is_preserved(self) -> None:
        matcher = ExactIngredientMatcher()
        ingredient = IngredientSpec(
            name="Ascorbic Acid", exact_terms=["L-Ascorbic Acid", "Ascorbic Acid"]
        )
        match = matcher.match("The report assessed L-Ascorbic Acid.", ingredient)
        assert match is not None and match.group(0) == "L-Ascorbic Acid"


class TestPostgresCopySnapshotReader:
    def test_reads_verified_id_without_guessing(self, tmp_path: Path) -> None:
        snapshot = tmp_path / "ingredient.sql"
        snapshot.write_text(
            "COPY public.ingredient_master (a,b,standard_name_en,d,e,f,g,h,id) FROM stdin;\n"
            "1\tko\tRetinol\t{}\t{}\tx\tx\tv\t8f45539c-d042-45f6-acb1-2a654e954a76\n"
            "\\.\n",
            encoding="utf-8",
        )
        result = PostgresCopySnapshotReader()._read_ingredient_ids(snapshot, ["Retinol"])
        assert result == {"Retinol": UUID("8f45539c-d042-45f6-acb1-2a654e954a76")}


def test_linkage_type_values_are_delivery_contract() -> None:
    assert LinkageType.NEW_DOCUMENT.value == "NEW_DOCUMENT"
    assert LinkageType.EXISTING_DOCUMENT_REUSE.value == "EXISTING_DOCUMENT_REUSE"
