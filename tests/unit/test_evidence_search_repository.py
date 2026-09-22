"""Evidence SQL이 출처를 LIMIT 전에 제한하는지 검사한다."""

from typing import ClassVar

import pytest

from backend.repositories.evidence_search_repository import EvidenceSearchRepository


class TestEvidenceSearchRepository:
    _SQL_NAMES: ClassVar[tuple[str, ...]] = (
        "_VECTOR_SQL",
        "_TARGETED_VECTOR_SQL",
        "_TEXT_SQL",
        "_TARGETED_TEXT_SQL",
    )

    @pytest.mark.parametrize("sql_name", _SQL_NAMES)
    def test_source_filter_is_applied_before_order_and_limit(self, sql_name: str) -> None:
        sql = " ".join(getattr(EvidenceSearchRepository, sql_name).split())

        source_filter_index = sql.index("evidence_document.source_type = ANY(:source_types)")
        order_index = sql.index("ORDER BY", source_filter_index)
        limit_index = sql.index("LIMIT", order_index)

        assert source_filter_index < order_index < limit_index
