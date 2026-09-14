"""확인된 이름의 조회 표기만 보완하며 성분 ID나 유도체를 추정하지 않는다."""

import unicodedata

from pydantic import ConfigDict, Field

from agent.rag.schemas import (
    IngredientResolveRequest,
    IngredientResolveResult,
    LookupStatus,
    RagModel,
)


class IngredientAliasEntry(RagModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    consumer_term: str = Field(min_length=1)
    standard_name_ko: str = Field(min_length=1)
    description: str = Field(min_length=1)


class CommonIngredientAliasMapper:
    """원문 조회 실패 시에만 사용하는 작은 동의어 목록. 빈 목록으로 비활성화 가능."""

    def __init__(self, entries: list[IngredientAliasEntry] | None = None) -> None:
        self._entries: dict[str, IngredientAliasEntry] = {}
        for entry in self._defaults() if entries is None else entries:
            key = self._normalize(entry.consumer_term)
            if not key or not entry.standard_name_ko.strip():
                raise ValueError("성분 별칭과 표준명은 공백만으로 구성할 수 없습니다.")
            if (
                key in self._entries
                and self._entries[key].standard_name_ko != entry.standard_name_ko
            ):
                raise ValueError(f"같은 성분 별칭에 서로 다른 표준명이 지정되었습니다: {key}")
            self._entries[key] = entry.model_copy(deep=True)

    def map_request(self, request: IngredientResolveRequest) -> IngredientResolveRequest:
        entry = self._entries.get(self._normalize(request.name))
        if entry is None:
            return request.model_copy(deep=True)
        return request.model_copy(update={"name": entry.standard_name_ko})

    def validate_result(
        self, request: IngredientResolveRequest, result: IngredientResolveResult
    ) -> IngredientResolveResult:
        if result.status is not LookupStatus.SUCCESS or result.ingredient is None:
            return result
        ingredient = result.ingredient
        names = [ingredient.canonical_name, *ingredient.aliases]
        if self._normalize(request.name) not in {self._normalize(name) for name in names}:
            # 외부 저장소의 부분 일치가 염·유도체 한 건을 반환해도 동의어 식별 성공은 아니다.
            return IngredientResolveResult(status=LookupStatus.NO_RESULTS)
        return result

    def _normalize(self, name: str) -> str:
        # 부분 문자열을 치환하면 비타민 C 유도체까지 순수 성분으로 바뀔 수 있다.
        return "".join(unicodedata.normalize("NFKC", name).casefold().split())

    def _defaults(self) -> list[IngredientAliasEntry]:
        # NIH ODS의 vitamin C/ascorbic acid 동의어만 초기 제공한다.
        # https://ods.od.nih.gov/factsheets/VitaminC-HealthProfessional/
        # AHA·시카·비타민 B군 등 계열/통칭은 특정 단일 성분으로 확정하지 않는다.
        return [
            IngredientAliasEntry(
                consumer_term=term,
                standard_name_ko="아스코빅애씨드",
                description="비타민 C(ascorbic acid)의 표기. 제품의 유도체·함량은 확정하지 않음.",
            )
            for term in ("비타민C", "vitamin c", "ascorbic acid", "아스코르빈산")
        ]
