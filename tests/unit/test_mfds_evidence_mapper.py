"""`MfdsEvidenceMapper` 단위 테스트. DB 세션 없이 순수 변환 로직만 검증한다.

legacy `evidence`/`evidence_document`/`evidence_chunk` 스키마 회귀는
`tests/unit/test_evidence_storage_schema.py`가 이미 담당하므로 여기서는 다루지 않는다.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from models.evidence_document import EvidenceClaimTopic, EvidenceDocumentSourceType, EvidenceLevel

from data.scripts.mfds_evidence_backfill_schemas import LegacyEvidenceRow
from data.scripts.mfds_evidence_mapper import (
    MfdsEvidenceMapper,
    build_chunk_content,
    build_chunk_natural_key,
    build_document_source_id,
)

_COLLECTED_AT = datetime(2026, 9, 16, 6, 10, 12, tzinfo=UTC)


def _row(
    *,
    row_id: UUID | None = None,
    ingredient_id: UUID | None = None,
    jurisdiction: str = "한국",
    claim: str = "한국 배합 규제: 금지",
    conditions: str | None = "농도 0.1% 이하",
    notice_ingredient_name: str | None = "니아신아마이드",
    cas_no: str | None = "98-92-0",
    ingredient_synonym: str | None = None,
    collected_at: datetime = _COLLECTED_AT,
) -> LegacyEvidenceRow:
    return LegacyEvidenceRow(
        id=row_id or uuid4(),
        ingredient_id=ingredient_id or uuid4(),
        claim=claim,
        conditions=conditions,
        jurisdiction=jurisdiction,
        regulate_type="prohibited",
        cas_no=cas_no,
        ingredient_synonym=ingredient_synonym,
        notice_ingredient_name=notice_ingredient_name,
        source_title="식품의약품안전처 화장품 사용제한 원료정보",
        source_url="https://www.data.go.kr/data/15111772/openapi.do",
        collected_at=collected_at,
    )


class TestPartitionValidRows:
    def test_valid_rows_pass_through(self) -> None:
        rows = [_row(), _row(jurisdiction="EU")]
        valid, failures = MfdsEvidenceMapper().partition_valid_rows(rows)
        assert len(valid) == 2
        assert failures == []

    def test_blank_jurisdiction_goes_to_failure_queue(self) -> None:
        bad_row = _row(jurisdiction="   ")
        valid, failures = MfdsEvidenceMapper().partition_valid_rows([_row(), bad_row])
        assert len(valid) == 1
        assert len(failures) == 1
        assert failures[0].legacy_evidence_id == bad_row.id
        assert "jurisdiction" in failures[0].reason


class TestBuildDocuments:
    def test_groups_by_jurisdiction(self) -> None:
        rows = [_row(jurisdiction="한국"), _row(jurisdiction="EU"), _row(jurisdiction="한국")]
        plans = MfdsEvidenceMapper().build_documents(rows)
        assert {plan.jurisdiction for plan in plans} == {"한국", "EU"}
        assert len(plans) == 2

    def test_document_fields_match_contract(self) -> None:
        rows = [_row(jurisdiction="한국")]
        plan = MfdsEvidenceMapper().build_documents(rows)[0]
        assert plan.source_type == EvidenceDocumentSourceType.MFDS
        assert plan.source_id == build_document_source_id("한국")
        assert plan.evidence_level == EvidenceLevel.OFFICIAL_REGULATORY
        assert plan.claim_topics == [EvidenceClaimTopic.CONCENTRATION_REGULATION]
        assert plan.language == "ko"
        assert plan.source_title == "식품의약품안전처 화장품 사용제한 원료정보"
        assert plan.url == "https://www.data.go.kr/data/15111772/openapi.do"

    def test_source_id_is_deterministic_across_reruns(self) -> None:
        rows = [_row(jurisdiction="아세안")]
        first = MfdsEvidenceMapper().build_documents(rows)[0].source_id
        second = MfdsEvidenceMapper().build_documents(rows)[0].source_id
        assert first == second == build_document_source_id("아세안")

    def test_retrieved_at_is_earliest_collected_at_in_group(self) -> None:
        earlier = datetime(2026, 1, 1, tzinfo=UTC)
        later = datetime(2026, 6, 1, tzinfo=UTC)
        rows = [_row(collected_at=later), _row(collected_at=earlier)]
        plan = MfdsEvidenceMapper().build_documents(rows)[0]
        assert plan.retrieved_at == earlier

    def test_raw_ingredient_names_deduplicated_and_sorted(self) -> None:
        rows = [
            _row(notice_ingredient_name="가"),
            _row(notice_ingredient_name="나"),
            _row(notice_ingredient_name="가"),
            _row(notice_ingredient_name=None),
        ]
        plan = MfdsEvidenceMapper().build_documents(rows)[0]
        assert plan.raw_ingredient_names == ["가", "나"]


class TestBuildChunks:
    def test_one_chunk_per_legacy_row(self) -> None:
        rows = [_row() for _ in range(5)]
        chunks = MfdsEvidenceMapper().build_chunks(rows)
        assert len(chunks) == 5
        assert {chunk.legacy_evidence_id for chunk in chunks} == {row.id for row in rows}

    def test_chunk_content_includes_claim_and_conditions_but_omits_missing_fields(self) -> None:
        row = _row(conditions=None, cas_no=None, ingredient_synonym=None)
        chunk = MfdsEvidenceMapper().build_chunks([row])[0]
        assert row.claim in chunk.content
        assert "조건:" not in chunk.content
        assert "CAS No:" not in chunk.content
        assert "이명:" not in chunk.content

    def test_duplicate_content_rows_get_distinct_chunk_ids(self) -> None:
        """legacy row 229그룹처럼 콘텐츠가 완전히 같아도 legacy id가 다르면 chunk_id가
        달라야 한다 - dedup하지 않고 1:1 추적성을 유지하기로 확정했다."""
        shared_ingredient_id = uuid4()
        row_a = _row(ingredient_id=shared_ingredient_id)
        row_b = _row(ingredient_id=shared_ingredient_id)
        assert build_chunk_content(row_a) == build_chunk_content(row_b)

        chunks = MfdsEvidenceMapper().build_chunks([row_a, row_b])
        assert len(chunks) == 2
        assert chunks[0].chunk_id != chunks[1].chunk_id
        assert chunks[0].content_hash == chunks[1].content_hash

    def test_chunk_natural_key_embeds_legacy_evidence_id(self) -> None:
        row = _row(jurisdiction="한국")
        chunk = MfdsEvidenceMapper().build_chunks([row])[0]
        expected = build_chunk_natural_key(build_document_source_id("한국"), row.id)
        assert chunk.chunk_id == expected

    def test_chunk_index_is_stable_ordinal_within_document(self) -> None:
        rows = [_row(jurisdiction="한국") for _ in range(3)]
        chunks_first_run = MfdsEvidenceMapper().build_chunks(rows)
        chunks_second_run = MfdsEvidenceMapper().build_chunks(list(reversed(rows)))
        # 입력 순서가 바뀌어도(재실행 시 select 결과 순서가 달라져도) 같은 legacy id는
        # 항상 같은 chunk_index를 받아야 idempotent하다.
        first_by_id = {c.legacy_evidence_id: c.chunk_index for c in chunks_first_run}
        second_by_id = {c.legacy_evidence_id: c.chunk_index for c in chunks_second_run}
        assert first_by_id == second_by_id

    def test_ingredient_id_carried_through_for_link_table(self) -> None:
        ingredient_id = uuid4()
        row = _row(ingredient_id=ingredient_id)
        chunk = MfdsEvidenceMapper().build_chunks([row])[0]
        assert chunk.ingredient_id == ingredient_id

    def test_provenance_fields_preserved_for_citation(self) -> None:
        row = _row(jurisdiction="일본")
        chunk = MfdsEvidenceMapper().build_chunks([row])[0]
        assert chunk.jurisdiction == "일본"
        assert chunk.source_title == row.source_title
        assert chunk.url == row.source_url
        assert chunk.evidence_level == EvidenceLevel.OFFICIAL_REGULATORY


class TestIdempotency:
    def test_rerunning_full_pipeline_on_same_input_is_identical(self) -> None:
        rows = [_row(jurisdiction="한국"), _row(jurisdiction="EU"), _row(jurisdiction="한국")]
        mapper = MfdsEvidenceMapper()

        docs_1 = mapper.build_documents(rows)
        docs_2 = mapper.build_documents(rows)
        assert [d.model_dump() for d in docs_1] == [d.model_dump() for d in docs_2]

        chunks_1 = mapper.build_chunks(rows)
        chunks_2 = mapper.build_chunks(rows)
        assert [c.model_dump() for c in chunks_1] == [c.model_dump() for c in chunks_2]


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
