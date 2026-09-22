"""NIA Q-CoT-A(10~39세) 사례에서 `IngredientMaster` 성분 언급을 규칙 기반으로 세어
Evidence Tier A 성분 우선순위용 상담 relevance 통계를 만든다.

- LLM 을 쓰지 않는다. 성분 언급은 alias 사전 + 경계 검사로만 찾는다.
- 사례 입력은 canonical 경로(`NiaOriginalLoader → NiaOriginalAgeFilter → NiaCaseDocumentBuilder`)를
  그대로 쓴다. 이 모듈은 Tier A 를 고르지 않고 통계만 낸다.
- 집계 단위는 ingredient_id 다. 이름 문자열별로 따로 세지 않는다.

사용법:
    uv run python -m data.scripts.nia_ingredient_relevance --input-root <2.데이터(NIA) 경로>
"""

import argparse
import asyncio
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.config import settings
from core.database import Database
from data.scripts.ingredient_master_reader import IngredientMasterReader
from data.scripts.ingredient_schemas import IngredientCandidate
from data.scripts.nia_case_document_builder import NiaCaseDocumentBuilder
from data.scripts.nia_original_age_filter import NiaOriginalAgeFilter
from data.scripts.nia_original_loader import NiaOriginalLoader
from data.scripts.nia_original_schemas import NiaOriginalRecord

EXPECTED_FILTERED_CASE_COUNT = (
    3581  # 로컬 확보분 기준. 다르면 보고서에 경고만 남기고 중단하진 않는다
)
MIN_LATIN_ALIAS_LENGTH = 3
MIN_KOREAN_ALIAS_LENGTH = 2
TOP_N_OVERALL = 30
TOP_N_PER_CONCERN = 10
REJECTED_EXAMPLE_LIMIT = 30

_DEFAULT_OUTPUT_DIR = Path("data/processed")
_SUMMARY_FILENAME = "nia_ingredient_relevance_summary.csv"
_DETAIL_FILENAME = "nia_case_ingredient_mentions.csv"
_REPORT_FILENAME = "nia_ingredient_relevance_report.md"
_LABELING_DIRNAMES = ("Training", "Validation")
_LABELING_SUBDIR = "02.라벨링데이터"

_WHITESPACE = re.compile(r"\s+")
_HANGUL = re.compile(r"[가-힣]")
_WORD_CHAR = re.compile(r"[a-z0-9]")
_HANGUL_OR_WORD = re.compile(r"[가-힣a-z0-9]")
_BUCKET_PREFIX_LENGTH = 2


class NiaTextField(StrEnum):
    QUESTION = "question"
    ANSWER = "answer"
    COT = "cot"


class AliasRejectReason(StrEnum):
    TOO_SHORT = "too_short"
    GENERIC = "generic"
    NUMERIC_ONLY = "numeric_only"


# 다른 성분명의 일부로 흔히 등장하거나 일반어와 겹쳐 단독 alias 로는 오탐이 큰 단어. 소문자로 비교한다.
# "루틴"(Rutin)은 상담문에서 "스킨케어 routine" 의 한국어 표기로 쓰여 2천 건 넘게 오탐했고,
# "크림"(Cream)은 성분이 아니라 제형을 가리킨다. 영문 "rutin"/"cream" 은 그대로 매칭된다.
GENERIC_ALIASES = frozenset(
    {"acid", "alcohol", "water", "oil", "wax", "butter", "extract", "powder", "fragrance"}
    | {
        "산",
        "물",
        "오일",
        "알코올",
        "왁스",
        "버터",
        "추출물",
        "파우더",
        "향료",
        "정제수",
        "루틴",
        "크림",
    }
)


class NiaIngredientRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    ingredient_id: UUID
    standard_name_en: str | None
    standard_name_ko: str


class NiaMentionHit(BaseModel):
    """텍스트 안 alias 한 번의 등장. ingredient_id 가 None 이면 여러 성분에 걸린 ambiguous alias."""

    model_config = ConfigDict(frozen=True)

    alias: str
    ingredient_id: UUID | None


class NiaCaseInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    target_concern: str
    question: str
    answer: str
    cot: str


class NiaCaseIngredientMention(BaseModel):
    """case + ingredient 한 쌍. 같은 성분이 여러 번 나와도 한 행이다."""

    case_id: str
    target_concern: str
    ingredient_id: UUID
    found_in_question: bool
    found_in_answer: bool
    found_in_cot: bool
    mention_count: int
    matched_aliases: list[str]


class NiaIngredientSummary(BaseModel):
    ingredient_id: UUID
    standard_name_en: str | None
    standard_name_ko: str
    case_count: int
    mention_count: int
    question_case_count: int
    answer_case_count: int
    cot_case_count: int
    target_concern_distribution: dict[str, int]


class NiaRelevanceStats(BaseModel):
    total_records: int
    filtered_records: int
    cases_with_ingredient: int
    ambiguous_alias_hits: dict[str, int] = Field(default_factory=dict)


class NiaIngredientMentionExtractor:
    """alias 사전 기반 mention 탐지. 단순 `alias in text` 가 아니라 경계 검사와 최장 우선을 쓴다."""

    def __init__(self, ingredients: Iterable[IngredientCandidate]) -> None:
        alias_owners: dict[str, set[UUID]] = defaultdict(set)
        for ingredient in ingredients:
            for name in self._names_of(ingredient):
                alias = self._normalize_text(name)
                if alias:
                    alias_owners[alias].add(ingredient.ingredient_id)

        self.rejected_aliases: dict[str, AliasRejectReason] = {}
        self.ambiguous_aliases: dict[str, tuple[UUID, ...]] = {}
        # 앞 2글자로 후보를 좁혀 위치마다 전체 사전을 훑지 않는다
        self._buckets: dict[str, list[tuple[str, UUID | None]]] = defaultdict(list)
        for alias, owners in alias_owners.items():
            reason = self._reject_reason(alias)
            if reason:
                self.rejected_aliases[alias] = reason
                continue
            if len(owners) > 1:
                # 임의로 하나를 고르지 않고, 등장 시 ambiguous 로만 센다
                self.ambiguous_aliases[alias] = tuple(sorted(owners, key=str))
                owner = None
            else:
                (owner,) = owners
            self._buckets[alias[:_BUCKET_PREFIX_LENGTH]].append((alias, owner))
        for candidates in self._buckets.values():
            candidates.sort(key=lambda item: len(item[0]), reverse=True)

    def extract(self, text: str) -> list[NiaMentionHit]:
        """왼쪽부터 훑으며 각 위치에서 가장 긴 alias 를 잡고, 그 구간은 소비한다."""
        normalized = self._normalize_text(text)
        hits: list[NiaMentionHit] = []
        position = 0
        while position < len(normalized):
            matched = self._match_at(normalized, position)
            if matched is None:
                position += 1
                continue
            alias, owner = matched
            hits.append(NiaMentionHit(alias=alias, ingredient_id=owner))
            position += len(alias)
        return hits

    def _match_at(self, text: str, position: int) -> tuple[str, UUID | None] | None:
        for alias, owner in self._buckets.get(
            text[position : position + _BUCKET_PREFIX_LENGTH], ()
        ):
            end = position + len(alias)
            if text.startswith(alias, position) and self._has_boundary(text, position, end, alias):
                return alias, owner
        return None

    def _has_boundary(self, text: str, start: int, end: int, alias: str) -> bool:
        before = text[start - 1] if start > 0 else ""
        after = text[end] if end < len(text) else ""
        if _HANGUL.search(alias):
            # 한국어는 조사가 뒤에 붙으므로 오른쪽은 열어 두고, 왼쪽만 다른 단어의 일부인지 본다
            return not (before and _HANGUL_OR_WORD.match(before))
        return not (before and _WORD_CHAR.match(before)) and not (after and _WORD_CHAR.match(after))

    def _reject_reason(self, alias: str) -> AliasRejectReason | None:
        if alias in GENERIC_ALIASES:
            return AliasRejectReason.GENERIC
        if alias.replace(" ", "").isdigit():
            return AliasRejectReason.NUMERIC_ONLY
        min_length = MIN_KOREAN_ALIAS_LENGTH if _HANGUL.search(alias) else MIN_LATIN_ALIAS_LENGTH
        return AliasRejectReason.TOO_SHORT if len(alias) < min_length else None

    def _names_of(self, ingredient: IngredientCandidate) -> list[str]:
        names = [
            ingredient.standard_name_ko,
            ingredient.standard_name_en,
            ingredient.normalized_name_ko,
            ingredient.normalized_name_en,
            *ingredient.old_names_ko,
            *ingredient.old_names_en,
        ]
        return [name for name in names if name]

    def _normalize_text(self, text: str) -> str:
        return _WHITESPACE.sub(" ", text.lower()).strip()


class NiaIngredientRelevanceAggregator:
    """case 단위로 언급을 모아 detail 행과 ingredient 요약을 만든다."""

    def __init__(self, extractor: NiaIngredientMentionExtractor) -> None:
        self._extractor = extractor
        self.ambiguous_alias_hits: Counter[str] = Counter()

    def mentions_of_case(self, case: NiaCaseInput) -> list[NiaCaseIngredientMention]:
        fields = {
            NiaTextField.QUESTION: case.question,
            NiaTextField.ANSWER: case.answer,
            NiaTextField.COT: case.cot,
        }
        per_ingredient: dict[UUID, dict[NiaTextField, int]] = defaultdict(lambda: defaultdict(int))
        aliases: dict[UUID, set[str]] = defaultdict(set)
        for field, text in fields.items():
            for hit in self._extractor.extract(text):
                if hit.ingredient_id is None:
                    self.ambiguous_alias_hits[hit.alias] += 1
                    continue
                per_ingredient[hit.ingredient_id][field] += 1
                aliases[hit.ingredient_id].add(hit.alias)

        return [
            NiaCaseIngredientMention(
                case_id=case.case_id,
                target_concern=case.target_concern,
                ingredient_id=ingredient_id,
                found_in_question=NiaTextField.QUESTION in counts,
                found_in_answer=NiaTextField.ANSWER in counts,
                found_in_cot=NiaTextField.COT in counts,
                mention_count=sum(counts.values()),
                matched_aliases=sorted(aliases[ingredient_id]),
            )
            for ingredient_id, counts in per_ingredient.items()
        ]

    def summarize(
        self,
        mentions: list[NiaCaseIngredientMention],
        refs: dict[UUID, NiaIngredientRef],
    ) -> list[NiaIngredientSummary]:
        grouped: dict[UUID, list[NiaCaseIngredientMention]] = defaultdict(list)
        for mention in mentions:
            grouped[mention.ingredient_id].append(mention)

        summaries = []
        for ingredient_id, rows in grouped.items():
            ref = refs[ingredient_id]
            # (case, ingredient) 행이 이미 case 당 하나라 concern 도 case 기준으로 한 번만 센다
            concerns = Counter(row.target_concern for row in rows)
            summaries.append(
                NiaIngredientSummary(
                    ingredient_id=ingredient_id,
                    standard_name_en=ref.standard_name_en,
                    standard_name_ko=ref.standard_name_ko,
                    case_count=len(rows),
                    mention_count=sum(row.mention_count for row in rows),
                    question_case_count=sum(row.found_in_question for row in rows),
                    answer_case_count=sum(row.found_in_answer for row in rows),
                    cot_case_count=sum(row.found_in_cot for row in rows),
                    target_concern_distribution=dict(concerns.most_common()),
                )
            )
        summaries.sort(
            key=lambda s: (
                -s.case_count,
                -s.answer_case_count,
                -s.cot_case_count,
                s.standard_name_en or "",
            )
        )
        return summaries


class NiaIngredientRelevanceRunner:
    """canonical NIA 파이프라인으로 사례를 만들고 통계와 파일을 산출한다."""

    def __init__(
        self,
        ingredients: list[IngredientCandidate],
        loader: NiaOriginalLoader | None = None,
        age_filter: NiaOriginalAgeFilter | None = None,
        builder: NiaCaseDocumentBuilder | None = None,
    ) -> None:
        self._loader = loader or NiaOriginalLoader()
        self._age_filter = age_filter or NiaOriginalAgeFilter()
        self._builder = builder or NiaCaseDocumentBuilder()
        self._refs = {
            i.ingredient_id: NiaIngredientRef(
                ingredient_id=i.ingredient_id,
                standard_name_en=i.standard_name_en,
                standard_name_ko=i.standard_name_ko,
            )
            for i in ingredients
        }
        self._extractor = NiaIngredientMentionExtractor(ingredients)
        self._aggregator = NiaIngredientRelevanceAggregator(self._extractor)

    def run(
        self, input_paths: list[Path]
    ) -> tuple[list[NiaCaseIngredientMention], list[NiaIngredientSummary], NiaRelevanceStats]:
        entries = list(self._loader.iter_entries(input_paths))
        filtered = list(self._age_filter.filter(entries))
        mentions = self.mentions_of(filtered_records=[e.record for e in filtered])
        summaries = self._aggregator.summarize(mentions, self._refs)
        stats = NiaRelevanceStats(
            total_records=len(entries),
            filtered_records=len(filtered),
            cases_with_ingredient=len({m.case_id for m in mentions}),
            ambiguous_alias_hits=dict(self._aggregator.ambiguous_alias_hits.most_common()),
        )
        self.validate(summaries, stats)
        return mentions, summaries, stats

    def mentions_of(
        self, filtered_records: list[NiaOriginalRecord]
    ) -> list[NiaCaseIngredientMention]:
        mentions: list[NiaCaseIngredientMention] = []
        for record in filtered_records:
            # case_id/target_concern 은 builder 가 만든 canonical metadata 를 쓴다(원본 값 그대로)
            metadata = self._builder.build(record).metadata
            cot = "\n".join(f"{s.title}\n{s.content}" for s in record.chain_of_thought)
            case = NiaCaseInput(
                case_id=metadata.case_id,
                target_concern=metadata.target_concern,
                question=record.info.question,
                answer=record.info.answer,
                cot=cot,
            )
            mentions.extend(self._aggregator.mentions_of_case(case))
        return mentions

    def validate(self, summaries: list[NiaIngredientSummary], stats: NiaRelevanceStats) -> None:
        for s in summaries:
            if not (
                s.case_count <= stats.filtered_records
                and s.question_case_count <= s.case_count
                and s.answer_case_count <= s.case_count
                and s.cot_case_count <= s.case_count
            ):
                raise RuntimeError(f"집계 불변식 위반: {s.standard_name_en} ({s.ingredient_id})")

    def write_outputs(
        self,
        mentions: list[NiaCaseIngredientMention],
        summaries: list[NiaIngredientSummary],
        stats: NiaRelevanceStats,
        output_dir: Path,
    ) -> str:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_summary_csv(summaries, output_dir / _SUMMARY_FILENAME)
        self._write_detail_csv(mentions, output_dir / _DETAIL_FILENAME)
        report = self.build_report(summaries, stats)
        (output_dir / _REPORT_FILENAME).write_text(report, encoding="utf-8")
        return report

    def build_report(self, summaries: list[NiaIngredientSummary], stats: NiaRelevanceStats) -> str:
        def name(s: NiaIngredientSummary) -> str:
            return f"{s.standard_name_en or '-'} / {s.standard_name_ko}"

        lines = [
            "# NIA ingredient relevance coverage",
            "",
            f"- NIA records loaded: {stats.total_records}",
            f"- Age-filtered records: {stats.filtered_records}",
            f"- Cases with >=1 ingredient mention: {stats.cases_with_ingredient}",
            f"- Cases with no ingredient mention: {stats.filtered_records - stats.cases_with_ingredient}",
            f"- Unique matched ingredients: {len(summaries)}",
            (
                f"- Ambiguous aliases (in dictionary): {len(self._extractor.ambiguous_aliases)}"
                f" (텍스트에서 실제 등장한 것 {len(stats.ambiguous_alias_hits)}종, "
                f"{sum(stats.ambiguous_alias_hits.values())}회 — 집계 제외)"
            ),
            (
                f"- Rejected/general aliases: {len(self._extractor.rejected_aliases)}"
                f" {dict(Counter(r.value for r in self._extractor.rejected_aliases.values()))}"
            ),
            "",
        ]
        if stats.filtered_records != EXPECTED_FILTERED_CASE_COUNT:
            lines += [
                f"> 경고: age-filtered {stats.filtered_records}건이 기대값 {EXPECTED_FILTERED_CASE_COUNT}과 다릅니다.",
                "",
            ]
        lines += [
            "Validation: case_count/question/answer/cot_case_count <= filtered records — PASS",
            "",
            f"## Top {TOP_N_OVERALL} by case_count",
        ]
        by_case = summaries[:TOP_N_OVERALL]
        lines += [f"{i}. {name(s)} — {s.case_count}" for i, s in enumerate(by_case, 1)]
        lines += ["", f"## Top {TOP_N_OVERALL} by answer_case_count"]
        by_answer = sorted(
            summaries, key=lambda s: (-s.answer_case_count, -s.case_count, s.standard_name_en or "")
        )[:TOP_N_OVERALL]
        lines += [f"{i}. {name(s)} — {s.answer_case_count}" for i, s in enumerate(by_answer, 1)]

        lines += ["", f"## target_concern별 Top {TOP_N_PER_CONCERN}"]
        per_concern: dict[str, list[tuple[int, NiaIngredientSummary]]] = defaultdict(list)
        for s in summaries:
            for concern, count in s.target_concern_distribution.items():
                per_concern[concern].append((count, s))
        for concern in sorted(per_concern):
            ranked = sorted(
                per_concern[concern], key=lambda x: (-x[0], x[1].standard_name_en or "")
            )[:TOP_N_PER_CONCERN]
            lines += ["", f"### {concern}"]
            lines += [f"{i}. {name(s)} — {c}" for i, (c, s) in enumerate(ranked, 1)]

        lines += ["", "## Rejected alias examples"]
        lines += [
            f"- `{alias}` ({reason})"
            for alias, reason in list(self._extractor.rejected_aliases.items())[
                :REJECTED_EXAMPLE_LIMIT
            ]
        ]
        return "\n".join(lines) + "\n"

    def _write_summary_csv(self, summaries: list[NiaIngredientSummary], path: Path) -> None:
        columns = [
            "ingredient_id", "standard_name_en", "standard_name_ko", "case_count",
            "mention_count", "question_case_count", "answer_case_count", "cot_case_count",
            "target_concern_unique_count", "target_concern_distribution_json",
        ]  # fmt: skip
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(columns)
            for s in summaries:
                writer.writerow(
                    [
                        s.ingredient_id, s.standard_name_en or "", s.standard_name_ko, s.case_count,
                        s.mention_count, s.question_case_count, s.answer_case_count,
                        s.cot_case_count, len(s.target_concern_distribution),
                        json.dumps(s.target_concern_distribution, ensure_ascii=False),
                    ]
                )  # fmt: skip

    def _write_detail_csv(self, mentions: list[NiaCaseIngredientMention], path: Path) -> None:
        columns = [
            "case_id", "target_concern", "ingredient_id", "standard_name_en", "standard_name_ko",
            "found_in_question", "found_in_answer", "found_in_cot", "mention_count",
            "matched_aliases",
        ]  # fmt: skip
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(columns)
            for m in mentions:
                ref = self._refs[m.ingredient_id]
                writer.writerow(
                    [
                        m.case_id, m.target_concern, m.ingredient_id, ref.standard_name_en or "",
                        ref.standard_name_ko, m.found_in_question, m.found_in_answer,
                        m.found_in_cot, m.mention_count, "|".join(m.matched_aliases),
                    ]
                )  # fmt: skip


async def _load_candidates() -> list[IngredientCandidate]:
    database = Database(settings.database)
    try:
        async with database.session_factory() as session:
            rows = await IngredientMasterReader(session).list_all()
    finally:
        await database.dispose()
    return [
        IngredientCandidate(
            ingredient_id=row.id,
            standard_name_ko=row.standard_name_ko,
            standard_name_en=row.standard_name_en,
            old_names_ko=tuple(row.old_names_ko),
            old_names_en=tuple(row.old_names_en),
            normalized_name_ko=row.normalized_name_ko,
            normalized_name_en=row.normalized_name_en,
        )
        for row in rows
    ]


def _labeling_zip_paths(input_root: Path) -> list[Path]:
    paths = [
        p
        for d in _LABELING_DIRNAMES
        for p in sorted((input_root / d / _LABELING_SUBDIR).glob("*.zip"))
    ]
    if not paths:
        raise RuntimeError(f"라벨링데이터 zip을 찾지 못했습니다: {input_root}")
    return paths


async def _run(input_root: Path, output_dir: Path) -> None:
    candidates = await _load_candidates()
    runner = NiaIngredientRelevanceRunner(candidates)
    mentions, summaries, stats = runner.run(_labeling_zip_paths(input_root))
    print(runner.write_outputs(mentions, summaries, stats, output_dir))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True, help="'2.데이터(NIA)' 폴더")
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    asyncio.run(_run(args.input_root, args.output_dir))
