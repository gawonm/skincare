from typing import Any
from uuid import uuid4

from data.scripts.ingredient_schemas import IngredientCandidate
from data.scripts.nia_ingredient_relevance import (
    NiaCaseInput,
    NiaIngredientMentionExtractor,
    NiaIngredientRelevanceAggregator,
    NiaIngredientRelevanceRunner,
)
from data.scripts.nia_original_age_filter import NiaOriginalAgeFilter
from data.scripts.nia_original_schemas import NiaOriginalEntry, NiaOriginalRecord, NiaRecordSource

NIACIN = uuid4()
HA = uuid4()
HA_NA = uuid4()
RETINOL = uuid4()
DUP_A = uuid4()
DUP_B = uuid4()
WATER = uuid4()


def _cand(ingredient_id, ko, en, old_ko=(), old_en=()) -> IngredientCandidate:
    return IngredientCandidate(
        ingredient_id=ingredient_id,
        standard_name_ko=ko,
        standard_name_en=en,
        old_names_ko=tuple(old_ko),
        old_names_en=tuple(old_en),
        normalized_name_ko=ko.replace(" ", ""),
        normalized_name_en=en.lower().replace(" ", "") if en else None,
    )


CANDIDATES = [
    _cand(NIACIN, "나이아신아마이드", "Niacinamide"),
    _cand(HA, "히알루론산", "Hyaluronic Acid"),
    _cand(HA_NA, "히알루론산나트륨", "Sodium Hyaluronate"),
    _cand(RETINOL, "레티놀", "Retinol", old_ko=["비타민A알코올"]),
    _cand(DUP_A, "듀프이름", "DupA", old_en=["Shared Name"]),
    _cand(DUP_B, "듀프이름2", "DupB", old_en=["Shared Name"]),
    _cand(WATER, "정제수", "Water"),
]


def _extractor() -> NiaIngredientMentionExtractor:
    return NiaIngredientMentionExtractor(CANDIDATES)


def _ids(text: str) -> list:
    return [h.ingredient_id for h in _extractor().extract(text)]


def _case(question="", answer="", cot="", concern="모공", case_id="c1") -> NiaCaseInput:
    return NiaCaseInput(
        case_id=case_id, target_concern=concern, question=question, answer=answer, cot=cot
    )


def test_case_count_is_one_but_mention_count_counts_repeats() -> None:
    agg = NiaIngredientRelevanceAggregator(_extractor())
    mentions = agg.mentions_of_case(
        _case(
            question="Niacinamide 어때요",
            answer="나이아신아마이드 추천",
            cot="niacinamide, NIACINAMIDE",
        )
    )
    assert len(mentions) == 1
    m = mentions[0]
    assert (m.mention_count, m.found_in_question, m.found_in_answer, m.found_in_cot) == (
        4, True, True, True,
    )  # fmt: skip


def test_english_case_insensitive_korean_and_old_name() -> None:
    assert _ids("NiAcInAmIdE") == [NIACIN]
    assert _ids("나이아신아마이드를 씁니다") == [NIACIN]  # 조사가 붙어도 매칭
    assert _ids("비타민A알코올") == [RETINOL]


def test_longest_alias_wins_and_no_substring_false_positive() -> None:
    assert _ids("히알루론산나트륨") == [HA_NA]
    assert _ids("hyaluronic acid") == [HA]
    assert _ids("xniacinamide") == []  # 영문은 단어 경계
    assert _ids("고농도나이아신아마이드") == []  # 한국어 왼쪽 경계


def test_ambiguous_alias_is_not_resolved() -> None:
    extractor = _extractor()
    hits = extractor.extract("shared name")
    assert [h.ingredient_id for h in hits] == [None]
    assert "shared name" in extractor.ambiguous_aliases
    agg = NiaIngredientRelevanceAggregator(extractor)
    assert agg.mentions_of_case(_case(answer="shared name")) == []
    assert agg.ambiguous_alias_hits["shared name"] == 1


def test_generic_alias_is_rejected() -> None:
    extractor = _extractor()
    assert "water" in extractor.rejected_aliases
    assert extractor.extract("water") == []


def test_target_concern_counted_once_per_case() -> None:
    agg = NiaIngredientRelevanceAggregator(_extractor())
    mentions = agg.mentions_of_case(
        _case(question="레티놀 레티놀", answer="레티놀", concern="주름")
    )
    mentions += agg.mentions_of_case(_case(answer="레티놀", concern="주름", case_id="c2"))
    mentions += agg.mentions_of_case(_case(answer="레티놀", concern="모공", case_id="c3"))
    ref = {i.ingredient_id: _ref(i) for i in CANDIDATES}
    (summary,) = agg.summarize(mentions, ref)
    assert summary.case_count == 3
    assert summary.mention_count == 5
    assert summary.target_concern_distribution == {"주름": 2, "모공": 1}
    assert summary.answer_case_count == 3 and summary.question_case_count == 1


def _ref(candidate: IngredientCandidate):
    from data.scripts.nia_ingredient_relevance import NiaIngredientRef

    return NiaIngredientRef(
        ingredient_id=candidate.ingredient_id,
        standard_name_en=candidate.standard_name_en,
        standard_name_ko=candidate.standard_name_ko,
    )


def _entry(record_id: str, age: int, answer: str) -> NiaOriginalEntry:
    raw: dict[str, Any] = {
        "info": {
            "id": record_id, "source_survey_id": "1", "target_concern": "모공",
            "question": "q", "answer": answer, "evidence_sources": [],
        },
        "meta": {
            "gender": "여성", "age": age, "initial_skin_condition": "x",
            "skin_type": "지성", "skin_concerns": [], "image_filename": "1.jpg",
        },
        "external": [],
        "chain_of_thought": [{"step": 1, "title": "t", "content": "레티놀"}],
    }  # fmt: skip
    return NiaOriginalEntry(
        record=NiaOriginalRecord.model_validate(raw),
        source=NiaRecordSource(input_path="x.jsonl", line_number=1),
    )


class _FakeLoader:
    def __init__(self, entries: list[NiaOriginalEntry]) -> None:
        self._entries = entries

    def iter_entries(self, input_paths):
        return iter(self._entries)


def test_runner_uses_canonical_age_filter_and_excludes_out_of_range() -> None:
    entries = [
        _entry("a", 9, "레티놀"),
        _entry("b", 10, "레티놀"),
        _entry("c", 39, "x"),
        _entry("d", 40, "레티놀"),
    ]
    runner = NiaIngredientRelevanceRunner(CANDIDATES, loader=_FakeLoader(entries))
    assert isinstance(runner._age_filter, NiaOriginalAgeFilter)
    mentions, summaries, stats = runner.run([])
    assert (stats.total_records, stats.filtered_records) == (4, 2)
    assert {m.case_id for m in mentions} == {"b", "c"}  # c 는 CoT 에만 등장
    assert summaries[0].case_count == 2
    assert summaries[0].cot_case_count == 2 and summaries[0].answer_case_count == 1
