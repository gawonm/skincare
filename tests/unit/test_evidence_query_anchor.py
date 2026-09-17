"""`EvidenceQueryAnchor` 직렬화·validation. LLM/embedding/DB 호출 없음."""

import pytest
from pydantic import ValidationError

from agent.rag.schemas import (
    EvidenceClaimTopic,
    EvidenceQueryAnchor,
    EvidenceQueryOrigin,
    IngredientMatchMode,
    IngredientScope,
)


def _base_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "anchor_id": "anchor-1",
        "request_id": "request-1",
        "origin": EvidenceQueryOrigin.DIRECT_QUERY,
        "origin_ref": None,
        "ingredient_scope": IngredientScope.SINGLE,
        "ingredient_refs": ["ingredient-a"],
        "ingredient_match_mode": None,
        "claim_topic": EvidenceClaimTopic.EFFICACY,
        "query_text": "나이아신아마이드 효능",
    }
    kwargs.update(overrides)
    return kwargs


# --- Valid ---------------------------------------------------------------


def test_valid_claim_hit_single_no_match_mode() -> None:
    anchor = EvidenceQueryAnchor(
        **_base_kwargs(
            origin=EvidenceQueryOrigin.CLAIM_HIT,
            origin_ref="COT_ACN_F_O30_00525-S005",
        )
    )
    assert anchor.origin is EvidenceQueryOrigin.CLAIM_HIT
    assert anchor.ingredient_match_mode is None


def test_valid_direct_query_single_no_match_mode() -> None:
    anchor = EvidenceQueryAnchor(**_base_kwargs())
    assert anchor.origin is EvidenceQueryOrigin.DIRECT_QUERY
    assert anchor.origin_ref is None


def test_valid_direct_query_multi_any() -> None:
    anchor = EvidenceQueryAnchor(
        **_base_kwargs(
            ingredient_scope=IngredientScope.MULTI,
            ingredient_refs=["ingredient-a", "ingredient-b"],
            ingredient_match_mode=IngredientMatchMode.ANY,
            claim_topic=EvidenceClaimTopic.COMBINATION,
        )
    )
    assert anchor.ingredient_match_mode is IngredientMatchMode.ANY


def test_valid_direct_query_multi_all() -> None:
    anchor = EvidenceQueryAnchor(
        **_base_kwargs(
            ingredient_scope=IngredientScope.MULTI,
            ingredient_refs=["ingredient-a", "ingredient-b"],
            ingredient_match_mode=IngredientMatchMode.ALL,
            claim_topic=EvidenceClaimTopic.COMBINATION,
        )
    )
    assert anchor.ingredient_match_mode is IngredientMatchMode.ALL


# --- Invalid ---------------------------------------------------------------


def test_empty_ingredient_refs_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceQueryAnchor(**_base_kwargs(ingredient_refs=[]))


def test_single_scope_with_two_ingredients_rejected() -> None:
    with pytest.raises(ValidationError, match="정확히 1개"):
        EvidenceQueryAnchor(**_base_kwargs(ingredient_refs=["ingredient-a", "ingredient-b"]))


@pytest.mark.parametrize("mode", [IngredientMatchMode.ANY, IngredientMatchMode.ALL])
def test_single_scope_with_match_mode_rejected(mode: IngredientMatchMode) -> None:
    with pytest.raises(ValidationError, match="반드시 None"):
        EvidenceQueryAnchor(**_base_kwargs(ingredient_match_mode=mode))


def test_multi_scope_with_one_ingredient_rejected() -> None:
    with pytest.raises(ValidationError, match="2개 이상"):
        EvidenceQueryAnchor(
            **_base_kwargs(
                ingredient_scope=IngredientScope.MULTI,
                ingredient_match_mode=IngredientMatchMode.ANY,
            )
        )


def test_multi_scope_without_match_mode_rejected() -> None:
    with pytest.raises(ValidationError, match="필수"):
        EvidenceQueryAnchor(
            **_base_kwargs(
                ingredient_scope=IngredientScope.MULTI,
                ingredient_refs=["ingredient-a", "ingredient-b"],
            )
        )


def test_duplicate_ingredient_refs_rejected() -> None:
    with pytest.raises(ValidationError, match="중복"):
        EvidenceQueryAnchor(
            **_base_kwargs(
                ingredient_scope=IngredientScope.MULTI,
                ingredient_refs=["ingredient-a", "ingredient-a"],
                ingredient_match_mode=IngredientMatchMode.ANY,
            )
        )


def test_claim_hit_without_origin_ref_rejected() -> None:
    with pytest.raises(ValidationError, match="필수"):
        EvidenceQueryAnchor(**_base_kwargs(origin=EvidenceQueryOrigin.CLAIM_HIT))


def test_direct_query_with_origin_ref_rejected() -> None:
    with pytest.raises(ValidationError, match="반드시 None"):
        EvidenceQueryAnchor(
            **_base_kwargs(
                origin=EvidenceQueryOrigin.DIRECT_QUERY,
                origin_ref="unexpected-claim-statement-id",
            )
        )


def test_blank_query_text_rejected() -> None:
    with pytest.raises(ValidationError, match="공백"):
        EvidenceQueryAnchor(**_base_kwargs(query_text="   "))


def test_claim_topic_as_list_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceQueryAnchor(
            **_base_kwargs(claim_topic=[EvidenceClaimTopic.EFFICACY, EvidenceClaimTopic.PRECAUTION])
        )


def test_limit_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceQueryAnchor(**_base_kwargs(limit=0))


# --- query_terms 결정적 정규화 ---------------------------------------------


def test_query_terms_dedup_strip_and_drop_blank() -> None:
    anchor = EvidenceQueryAnchor(
        **_base_kwargs(query_terms=[" niacinamide ", "niacinamide", "", "   ", "sebum control"])
    )
    assert anchor.query_terms == ["niacinamide", "sebum control"]


# --- Round-trip --------------------------------------------------------


def test_round_trip_model_dump_preserves_enums_and_ids() -> None:
    original = EvidenceQueryAnchor(
        **_base_kwargs(
            ingredient_scope=IngredientScope.MULTI,
            ingredient_refs=["ingredient-a", "ingredient-b"],
            ingredient_match_mode=IngredientMatchMode.ALL,
            claim_topic=EvidenceClaimTopic.COMBINATION,
        )
    )
    dumped = original.model_dump()
    restored = EvidenceQueryAnchor(**dumped)

    assert restored == original
    assert restored.origin is EvidenceQueryOrigin.DIRECT_QUERY
    assert restored.ingredient_scope is IngredientScope.MULTI
    assert restored.ingredient_match_mode is IngredientMatchMode.ALL
    assert restored.claim_topic is EvidenceClaimTopic.COMBINATION
    assert restored.ingredient_refs == ["ingredient-a", "ingredient-b"]


def test_anchor_has_no_embedding_citation_or_support_level_fields() -> None:
    field_names = set(EvidenceQueryAnchor.model_fields)
    for forbidden in ("embedding", "url", "doi", "pmid", "page", "section", "support_level"):
        assert forbidden not in field_names, f"{forbidden!r}은 EvidenceQueryAnchor에 있으면 안 된다"
