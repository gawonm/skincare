"""소비자 성분 표현을 확정 동의어와 모호한 성분군으로 구분한다."""

import re
import unicodedata
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict, Field, model_validator

from agent.rag.schemas import (
    IngredientResolveRequest,
    IngredientResolveResult,
    LookupStatus,
    RagModel,
)


class IngredientAliasKind(StrEnum):
    EXACT_EQUIVALENT = "exact_equivalent"
    AMBIGUOUS_FAMILY = "ambiguous_family"


class IngredientAliasEntry(RagModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    consumer_term: str = Field(min_length=1)
    kind: IngredientAliasKind = IngredientAliasKind.EXACT_EQUIVALENT
    standard_name_ko: str | None = Field(default=None, min_length=1)
    candidate_standard_names_ko: list[str] = Field(default_factory=list)
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_target_shape(self) -> Self:
        if self.kind is IngredientAliasKind.EXACT_EQUIVALENT:
            if self.standard_name_ko is None or self.candidate_standard_names_ko:
                raise ValueError("확정 동의어에는 표준 성분명 하나만 필요합니다.")
            return self
        if self.standard_name_ko is not None or len(self.candidate_standard_names_ko) < 2:
            raise ValueError("모호한 성분군에는 서로 다른 표준 성분 후보가 2개 이상 필요합니다.")
        if len(self.candidate_standard_names_ko) != len(
            set(self.candidate_standard_names_ko)
        ):
            raise ValueError("모호한 성분군의 표준 성분 후보가 중복되었습니다.")
        return self


class IngredientMentionDetectionRequest(RagModel):
    text: str = Field(min_length=1)


class IngredientMentionDetectionResult(RagModel):
    mentions: list[str] = Field(default_factory=list)


class CommonIngredientAliasMapper:
    """확정 가능한 동의어만 단일 ID 조회로 보내고 성분군은 모호 상태로 보존한다."""

    def __init__(self, entries: list[IngredientAliasEntry] | None = None) -> None:
        self._entries: dict[str, IngredientAliasEntry] = {}
        for entry in self._defaults() if entries is None else entries:
            key = self._normalize(entry.consumer_term)
            if not key:
                raise ValueError("성분 별칭은 공백일 수 없습니다.")
            if key in self._entries and self._entries[key] != entry:
                raise ValueError(f"같은 성분 별칭에 서로 다른 해석이 지정되었습니다: {key}")
            self._entries[key] = entry.model_copy(deep=True)

    def map_request(self, request: IngredientResolveRequest) -> IngredientResolveRequest:
        entry = self._entry(request)
        if entry is None or entry.kind is IngredientAliasKind.AMBIGUOUS_FAMILY:
            return request.model_copy(deep=True)
        if entry.standard_name_ko is None:
            raise RuntimeError("확정 동의어에 표준 성분명이 없습니다.")
        return request.model_copy(update={"name": entry.standard_name_ko})

    def is_ambiguous_family(self, request: IngredientResolveRequest) -> bool:
        entry = self._entry(request)
        return entry is not None and entry.kind is IngredientAliasKind.AMBIGUOUS_FAMILY

    def family_candidates(self, request: IngredientResolveRequest) -> list[str]:
        entry = self._entry(request)
        if entry is None or entry.kind is not IngredientAliasKind.AMBIGUOUS_FAMILY:
            return []
        return list(entry.candidate_standard_names_ko)

    def detect_mentions(
        self, request: IngredientMentionDetectionRequest
    ) -> IngredientMentionDetectionResult:
        normalized_text = self._normalize(request.text)
        matched_keys: list[str] = []
        mentions: list[str] = []
        for key, entry in sorted(
            self._entries.items(), key=lambda item: len(item[0]), reverse=True
        ):
            if key not in normalized_text or any(key in matched for matched in matched_keys):
                continue
            if self._is_derivative_reference(normalized_text, key):
                continue
            if self._has_embedded_latin_match(normalized_text, key):
                continue
            matched_keys.append(key)
            mention = (
                entry.standard_name_ko
                if entry.kind is IngredientAliasKind.EXACT_EQUIVALENT
                else entry.consumer_term
            )
            if mention is not None and mention not in mentions:
                mentions.append(mention)
        return IngredientMentionDetectionResult(mentions=mentions)

    def validate_result(
        self, request: IngredientResolveRequest, result: IngredientResolveResult
    ) -> IngredientResolveResult:
        if result.status is not LookupStatus.SUCCESS or result.ingredient is None:
            return result
        ingredient = result.ingredient
        names = [ingredient.canonical_name, *ingredient.aliases]
        if self._normalize(request.name) not in {self._normalize(name) for name in names}:
            # 별칭 대상의 부분 일치가 유도체 전체 매칭으로 번지는 것을 막는다.
            return IngredientResolveResult(status=LookupStatus.NO_RESULTS)
        return result

    def _entry(self, request: IngredientResolveRequest) -> IngredientAliasEntry | None:
        normalized_key = self._normalize(request.name)
        direct = self._entries.get(normalized_key)
        if direct is not None:
            return direct

        # "A (B)" 형태의 복합 표기는 괄호 안팎 중 확정 동의어가 하나만 유효할 때 그 표준 성분으로 연결한다.
        return self._resolve_parenthesized(request.name)

    def _resolve_parenthesized(self, name: str) -> IngredientAliasEntry | None:
        match = re.match(r"^([^(]+)\s*\(([^)]+)\)$", name.strip())
        if not match:
            return None
        outer_term = match.group(1).strip()
        inner_term = match.group(2).strip()

        outer_entry = self._entries.get(self._normalize(outer_term))
        inner_entry = self._entries.get(self._normalize(inner_term))

        # 괄호 안팎 중 한쪽만 확정 동의어인 경우(예: 'BHA (Salicylic Acid)' -> 살리실릭애씨드) 확정 성분을 우선 채택한다.
        outer_exact = outer_entry if outer_entry and outer_entry.kind is IngredientAliasKind.EXACT_EQUIVALENT else None
        inner_exact = inner_entry if inner_entry and inner_entry.kind is IngredientAliasKind.EXACT_EQUIVALENT else None

        if outer_exact and inner_exact:
            if outer_exact.standard_name_ko == inner_exact.standard_name_ko:
                return outer_exact
            # 안팎이 서로 다른 확정 성분을 가리키면 모호하므로 자동 치환하지 않는다.
            return None
        if inner_exact:
            return inner_exact
        if outer_exact:
            return outer_exact
        return None

    def _normalize(self, name: str) -> str:
        # 공백과 대소문자만 정규화하고 괄호 내용은 별칭 의미의 일부로 보존한다.
        return "".join(unicodedata.normalize("NFKC", name).casefold().split())

    def _is_derivative_reference(self, normalized_text: str, key: str) -> bool:
        # 계열·유도체 질문을 대표 성분 하나로 축소하면 다른 물질의 근거를 붙일 수 있다.
        return any(
            marker in normalized_text
            for marker in (f"{key}유도체", f"{key}derivative", f"{key}계열")
        )

    def _has_embedded_latin_match(self, normalized_text: str, key: str) -> bool:
        if not key.isascii():
            return False
        start = normalized_text.find(key)
        while start >= 0:
            previous = normalized_text[start - 1] if start > 0 else ""
            end = start + len(key)
            following = normalized_text[end] if end < len(normalized_text) else ""
            if not (
                previous and previous.isascii() and previous.isalnum()
            ) and not (following and following.isascii() and following.isalnum()):
                return False
            start = normalized_text.find(key, start + 1)
        return True

    def _defaults(self) -> list[IngredientAliasEntry]:
        exact_entries = [
            *[
                IngredientAliasEntry(
                    consumer_term=term,
                    standard_name_ko="아스코빅애씨드",
                    description="비타민 C를 순수 아스코빅애씨드로 명시한 확정 동의어",
                )
                for term in (
                    "비타민C",
                    "vitamin c",
                    "ascorbic acid",
                    "l-ascorbic acid",
                    "아스코르빈산",
                )
            ],
            *[
                IngredientAliasEntry(
                    consumer_term=term,
                    standard_name_ko="살리실릭애씨드",
                    description="살리실산 표기를 화장품 표준 성분명으로 연결하는 확정 동의어",
                )
                for term in (
                    "살리실산",
                    "살리실산 (BHA)",
                    "BHA (살리실산)",
                    "살리실릭 애씨드",
                    "salicylic acid",
                    "bha (salicylic acid)",
                    "salicylic acid (bha)",
                )
            ],
            *[
                IngredientAliasEntry(
                    consumer_term=term,
                    standard_name_ko="나이아신아마이드",
                    description="피지 조절 및 미백에 범용으로 쓰이는 나이아신아마이드 확정 동의어",
                )
                for term in (
                    "나이아신아마이드",
                    "niacinamide",
                    "nicotinamide",
                )
            ],
            *[
                IngredientAliasEntry(
                    consumer_term=term,
                    standard_name_ko="판테놀",
                    description="장벽 보습에 쓰이는 판테놀의 영문 확정 동의어",
                )
                for term in (
                    "판테놀",
                    "panthenol",
                    "d-panthenol",
                )
            ],
            *[
                IngredientAliasEntry(
                    consumer_term=term,
                    standard_name_ko="병풀추출물",
                    description="진정에 널리 쓰이는 센텔라 아시아티카 표기의 병풀추출물 확정 동의어",
                )
                for term in (
                    "병풀추출물",
                    "centella asiatica extract",
                    "centella asiatica",
                )
            ],
            *[
                IngredientAliasEntry(
                    consumer_term=term,
                    standard_name_ko="글라이콜릭애씨드",
                    description="각질 제거 및 피지 케어에 쓰이는 글라이콜릭애씨드 확정 동의어",
                )
                for term in (
                    "글라이콜릭애씨드",
                    "glycolic acid",
                    "글리콜산",
                    "aha (glycolic acid)",
                    "glycolic acid (aha)",
                )
            ],
            *[
                IngredientAliasEntry(
                    consumer_term=term,
                    standard_name_ko="알로에베라잎즙가루",
                    description="소비자의 파우더 표기를 화장품 표준 국문 명칭인 가루로 연결하는 확정 동의어",
                )
                for term in (
                    "알로에 베라 잎즙 파우더",
                )
            ],
            *[
                IngredientAliasEntry(
                    consumer_term=term,
                    standard_name_ko="안디로바씨오일",
                    description="카라파 구아이아넨시스(Carapa Guianensis) 씨드 오일 표기를 표준 국문 명칭인 안디로바씨오일로 연결하는 확정 동의어",
                )
                for term in (
                    "카라파 구아이아넨시스 씨드 오일",
                    "카라파 구아이아넨시스 씨 오일",
                )
            ],
            *[
                IngredientAliasEntry(
                    consumer_term=term,
                    standard_name_ko="고추냉이뿌리추출물",
                    description="양고추냉이와 INCI 영문 표기를 확인된 표준 국문 명칭으로 연결하는 확정 동의어",
                )
                for term in (
                    "양고추냉이 뿌리 추출물",
                    "Cochlearia Armoracia Root Extract",
                )
            ],
        ]
        family_entries = [
            IngredientAliasEntry(
                consumer_term="BHA",
                kind=IngredientAliasKind.AMBIGUOUS_FAMILY,
                candidate_standard_names_ko=["살리실릭애씨드", "베타인살리실레이트"],
                description="BHA는 제품에 따라 서로 다른 베타하이드록시애씨드 계열 성분을 뜻할 수 있음",
            ),
            IngredientAliasEntry(
                consumer_term="AHA",
                kind=IngredientAliasKind.AMBIGUOUS_FAMILY,
                candidate_standard_names_ko=["글라이콜릭애씨드", "락틱애씨드"],
                description="AHA는 글라이콜릭애씨드, 락틱애씨드 등 다양한 알파하이드록시애씨드를 뜻할 수 있음",
            ),
            *[
                IngredientAliasEntry(
                    consumer_term=term,
                    kind=IngredientAliasKind.AMBIGUOUS_FAMILY,
                    candidate_standard_names_ko=["티트리잎오일", "티트리꽃/잎/줄기오일"],
                    description="일반적인 티트리 오일 표현만으로는 DB의 구체 성분을 하나로 확정할 수 없음",
                )
                for term in ("티트리 오일", "tea tree oil", "티트리", "tea tree")
            ],
        ]
        return [*exact_entries, *family_entries]
