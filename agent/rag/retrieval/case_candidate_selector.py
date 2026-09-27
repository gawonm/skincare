"""NIA Case 벡터 후보를 저장된 고민 메타데이터로 좁힌다."""

from enum import StrEnum
from typing import ClassVar

from pydantic import Field

from agent.rag.case_schemas import (
    DEFAULT_CASE_RERANK_CANDIDATE_LIMIT,
    CaseSearchHit,
)
from agent.rag.schemas import RagModel


class NiaCaseConcernCategory(StrEnum):
    HYPERKERATOSIS_DRYNESS = "과각질/악건성"
    PORES = "모공"
    PIGMENTATION = "미백(색소침착/기미/칙칙함)"
    SENSITIVITY = "민감성(트러블/자극감)"
    REDNESS = "붉어짐(홍조)"
    ACNE = "여드름/뾰루지"
    WRINKLES = "주름"
    SAGGING = "피부처짐/탄력저하"


class NiaCaseSkinType(StrEnum):
    DRY = "건성"
    OILY = "지성"
    COMBINATION = "복합성"
    NORMAL = "중성"


class CaseCandidateSelectionRequest(RagModel):
    query: str = Field(min_length=1)
    skin_concerns: list[str] = Field(default_factory=list)
    candidates: list[CaseSearchHit] = Field(min_length=1)
    limit: int = Field(default=DEFAULT_CASE_RERANK_CANDIDATE_LIMIT, ge=3)


class CaseCandidateSelectionResult(RagModel):
    detected_categories: list[NiaCaseConcernCategory] = Field(default_factory=list)
    detected_skin_types: list[NiaCaseSkinType] = Field(default_factory=list)
    candidates: list[CaseSearchHit] = Field(min_length=1)
    direct_match_count: int = Field(ge=0)


class CaseMetadataCandidateSelector:
    """메타데이터 일치 후보를 앞세우되 Dense 후보를 제거하지 않는다."""
    _ALIASES: ClassVar[dict[NiaCaseConcernCategory, tuple[str, ...]]] = {
        NiaCaseConcernCategory.HYPERKERATOSIS_DRYNESS: (
            "과각질",
            "악건성",
            "건조",
            "당김",
            "수분 부족",
        ),
        NiaCaseConcernCategory.PORES: ("모공",),
        NiaCaseConcernCategory.PIGMENTATION: (
            "미백",
            "색소침착",
            "기미",
            "칙칙",
        ),
        NiaCaseConcernCategory.SENSITIVITY: (
            "민감",
            "자극",
            "트러블",
        ),
        NiaCaseConcernCategory.REDNESS: ("붉어짐", "붉은", "홍조"),
        NiaCaseConcernCategory.ACNE: ("여드름", "뾰루지", "좁쌀", "트러블"),
        NiaCaseConcernCategory.WRINKLES: ("주름",),
        NiaCaseConcernCategory.SAGGING: ("피부처짐", "처짐", "탄력저하", "탄력 저하"),
    }
    _SKIN_TYPE_ALIASES: ClassVar[dict[NiaCaseSkinType, tuple[str, ...]]] = {
        NiaCaseSkinType.DRY: ("건성", "악건성", "건조", "당김", "수분 부족", "속건조"),
        NiaCaseSkinType.OILY: ("지성", "유분"),
        NiaCaseSkinType.COMBINATION: ("복합성", "수부지"),
        NiaCaseSkinType.NORMAL: ("중성",),
    }

    def select(
        self,
        request: CaseCandidateSelectionRequest,
    ) -> CaseCandidateSelectionResult:
        search_texts = [request.query, *request.skin_concerns]
        categories = self._categories_in(search_texts)
        skin_types = self._skin_types_in(search_texts)
        if not categories:
            return CaseCandidateSelectionResult(
                detected_skin_types=skin_types,
                candidates=request.candidates[: request.limit],
                direct_match_count=0,
            )

        category_values = set(categories)
        skin_type_values = {skin_type.value for skin_type in skin_types}
        direct_ids = {
            candidate.case_id
            for candidate in request.candidates
            if self._candidate_categories(candidate) & category_values
        }
        # 메타데이터는 완전한 정답 라벨이 아니므로 hard filter로 사용하지 않는다.
        # 직접 고민 일치와 피부 타입 일치를 앞세우되, 나머지는 기존 벡터 순서로 모두 보존한다.
        selected = sorted(
            request.candidates,
            key=lambda candidate: (
                candidate.case_id not in direct_ids,
                candidate.metadata.skin_type not in skin_type_values
                if skin_type_values
                else False,
                -candidate.vector_similarity,
                candidate.case_id,
            ),
        )[: request.limit]
        return CaseCandidateSelectionResult(
            detected_categories=categories,
            detected_skin_types=skin_types,
            candidates=selected,
            direct_match_count=len(direct_ids),
        )

    def _candidate_categories(
        self,
        candidate: CaseSearchHit,
    ) -> set[NiaCaseConcernCategory]:
        exact_target = self._exact_category(candidate.metadata.target_concern)
        categories = set(self._categories_in(candidate.metadata.skin_concerns))
        if exact_target is not None:
            categories.add(exact_target)
        return categories

    def _categories_in(self, texts: list[str]) -> list[NiaCaseConcernCategory]:
        normalized = [text.casefold() for text in texts]
        return [
            category
            for category, aliases in self._ALIASES.items()
            if any(alias.casefold() in text for alias in aliases for text in normalized)
        ]

    def _skin_types_in(self, texts: list[str]) -> list[NiaCaseSkinType]:
        normalized = [text.casefold() for text in texts]
        return [
            skin_type
            for skin_type, aliases in self._SKIN_TYPE_ALIASES.items()
            if any(alias.casefold() in text for alias in aliases for text in normalized)
        ]

    def _exact_category(self, value: str) -> NiaCaseConcernCategory | None:
        normalized = value.casefold().strip()
        return next(
            (
                category
                for category in NiaCaseConcernCategory
                if category.value.casefold() == normalized
            ),
            None,
        )
