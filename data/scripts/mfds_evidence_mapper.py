"""legacy `evidence`(MFDS) row를 `EvidenceDocumentPlan`/`EvidenceChunkStagingRecord`로
변환하는 순수 로직. DB 세션에 의존하지 않아 단위 테스트에서 그대로 검증할 수 있다.

## Document 경계를 jurisdiction으로 잡은 이유

legacy MFDS 데이터는 8,288건 전부 `source_title`/`source_url`이 동일하고, 원본 MFDS API
응답 자체에 문서 식별자(게시글ID 등)가 없다(`import_mfds_restricted_ingredients.py`,
`mfds_client.py` 실측 확인). 대신 `jurisdiction`(관할 국가, 11종)이 legacy row를 자연스럽게
나누는 유일한 축이고, `EvidenceDocument.jurisdiction`이 단일값 컬럼이라 여러 국가를 문서
하나에 욱여넣을 수 없다. 그래서 jurisdiction별로 `EvidenceDocument` 1건을 만든다(사용자
확정, 2026-09-17).

## source_id가 "진짜" 자연키가 아니라는 점

MFDS 원본에는 문서 단위 식별자가 없으므로 `source_id`는 우리가 jurisdiction으로부터
결정적으로 만들어낸 값이다(`_RESTRICTED_INGREDIENT_SOURCE_ID_PREFIX`). PMID/CIR 성분코드처럼
원 출처가 발급한 식별자가 아니라는 사실을 잃지 않도록 이 주석에 남긴다 - 같은 jurisdiction
문자열이 항상 같은 source_id를 만들어내므로(deterministic) 재실행해도 같은 11개
`EvidenceDocument`를 다시 찾아간다(idempotent get-or-create).

## chunk 자연키에 legacy evidence.id를 그대로 쓰는 이유

legacy row 8,288건 중 229개 그룹(콘텐츠 완전 동일)이 존재한다 - 같은 성분·jurisdiction·
고시원료명·CAS 번호·규제유형·조건인데 legacy `evidence.id`만 다른 행들이다(원본 MFDS API
자체의 중복으로 확인, 재수집/재적재 흔적 아님). 이 중복을 임의로 제거하면 legacy row와
`EvidenceChunk`의 1:1 추적성이 깨지고 정보 손실 여부를 판단할 근거도 사라지므로, dedup하지
않고 legacy row 1건당 chunk 1건을 그대로 만든다(사용자 확정). 대신 `chunk_id`
자연키(`{document_source_id}:{legacy_evidence_id}`)에 legacy `evidence.id`를 직접 넣어
콘텐츠가 같아도 유일성이 깨지지 않게 한다 - 문서 템플릿의 `chunk_index`(순번)만으로는
콘텐츠 중복 시에도 유일하긴 하지만, 어떤 legacy row에서 왔는지 chunk_id만 보고 알 수 없다.
"""

import hashlib
from collections import defaultdict

from models.evidence_document import EvidenceClaimTopic, EvidenceDocumentSourceType, EvidenceLevel

from data.scripts.mfds_evidence_backfill_schemas import (
    EvidenceChunkStagingRecord,
    EvidenceDocumentPlan,
    LegacyEvidenceRow,
    MfdsEvidenceBackfillFailure,
)

_RESTRICTED_INGREDIENT_SOURCE_ID_PREFIX = "restricted_ingredient"
PARSER_VERSION = "mfds-evidence-backfill-v1"


def build_document_source_id(jurisdiction: str) -> str:
    """jurisdiction으로부터 결정적 `EvidenceDocument.source_id`를 만든다."""
    return f"{_RESTRICTED_INGREDIENT_SOURCE_ID_PREFIX}:{jurisdiction}"


def build_chunk_natural_key(document_source_id: str, legacy_evidence_id: object) -> str:
    return f"{document_source_id}:{legacy_evidence_id}"


def build_chunk_content(row: LegacyEvidenceRow) -> str:
    """claim + conditions + 부가 필드를 원문 그대로 결합한다. 요약/LLM 호출 없음."""
    lines = [row.claim]
    if row.conditions:
        lines.append(f"조건: {row.conditions}")
    if row.notice_ingredient_name:
        lines.append(f"고시원료명: {row.notice_ingredient_name}")
    if row.cas_no:
        lines.append(f"CAS No: {row.cas_no}")
    if row.ingredient_synonym:
        lines.append(f"이명: {row.ingredient_synonym}")
    return "\n".join(lines)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class MfdsEvidenceMapper:
    """legacy `evidence` row 목록 -> `EvidenceDocumentPlan`/`EvidenceChunkStagingRecord`."""

    def partition_valid_rows(
        self, rows: list[LegacyEvidenceRow]
    ) -> tuple[list[LegacyEvidenceRow], list[MfdsEvidenceBackfillFailure]]:
        """jurisdiction/ingredient_id가 비어 있는 row를 걸러낸다.

        legacy `evidence.jurisdiction`/`ingredient_id`는 스키마상 NOT NULL이라 실제로는
        걸리는 행이 없어야 정상이지만(Phase D 감사: 8,288/8,288 매칭 완료), 방어적으로
        빈 문자열까지 확인해 조용히 넘어가지 않는다(CLAUDE.md 규칙 7).
        """
        valid: list[LegacyEvidenceRow] = []
        failures: list[MfdsEvidenceBackfillFailure] = []
        for row in rows:
            if not row.jurisdiction or not row.jurisdiction.strip():
                failures.append(
                    MfdsEvidenceBackfillFailure(
                        legacy_evidence_id=row.id, reason="jurisdiction이 비어 있음"
                    )
                )
                continue
            if row.ingredient_id is None:
                failures.append(
                    MfdsEvidenceBackfillFailure(
                        legacy_evidence_id=row.id, reason="ingredient_id가 비어 있음"
                    )
                )
                continue
            valid.append(row)
        return valid, failures

    def build_documents(self, rows: list[LegacyEvidenceRow]) -> list[EvidenceDocumentPlan]:
        """jurisdiction별로 그룹화해 `EvidenceDocumentPlan`을 만든다. 순서는 jurisdiction
        문자열 정렬 순 - 재실행 시 출력 파일 순서가 흔들리지 않게 한다(idempotent)."""
        rows_by_jurisdiction: dict[str, list[LegacyEvidenceRow]] = defaultdict(list)
        for row in rows:
            rows_by_jurisdiction[row.jurisdiction].append(row)

        plans: list[EvidenceDocumentPlan] = []
        for jurisdiction in sorted(rows_by_jurisdiction):
            group = rows_by_jurisdiction[jurisdiction]
            raw_ingredient_names = sorted(
                {row.notice_ingredient_name for row in group if row.notice_ingredient_name}
            )
            retrieved_at = min(row.collected_at for row in group)
            plans.append(
                EvidenceDocumentPlan(
                    source_type=EvidenceDocumentSourceType.MFDS,
                    source_id=build_document_source_id(jurisdiction),
                    source_title=group[0].source_title,
                    url=group[0].source_url,
                    jurisdiction=jurisdiction,
                    language="ko",
                    evidence_level=EvidenceLevel.OFFICIAL_REGULATORY,
                    raw_ingredient_names=raw_ingredient_names,
                    claim_topics=[EvidenceClaimTopic.CONCENTRATION_REGULATION],
                    retrieved_at=retrieved_at,
                    legacy_evidence_ids=sorted((row.id for row in group), key=str),
                )
            )
        return plans

    def build_chunks(
        self, rows: list[LegacyEvidenceRow]
    ) -> list[EvidenceChunkStagingRecord]:
        """row 1건 = chunk 1건(MFDS는 청킹 없음, `EVIDENCE_RAG_DESIGN.md` C절). 콘텐츠가
        같은 행도 dedup하지 않는다(모듈 docstring 참고)."""
        rows_by_jurisdiction: dict[str, list[LegacyEvidenceRow]] = defaultdict(list)
        for row in rows:
            rows_by_jurisdiction[row.jurisdiction].append(row)

        records: list[EvidenceChunkStagingRecord] = []
        for jurisdiction in sorted(rows_by_jurisdiction):
            document_source_id = build_document_source_id(jurisdiction)
            # 같은 document 안 순번은 legacy id 정렬 순으로 고정한다 - 재실행 시 같은
            # legacy row 집합이면 항상 같은 chunk_index를 받는다(idempotent).
            group = sorted(rows_by_jurisdiction[jurisdiction], key=lambda row: str(row.id))
            for chunk_index, row in enumerate(group):
                content = build_chunk_content(row)
                records.append(
                    EvidenceChunkStagingRecord(
                        document_source_id=document_source_id,
                        chunk_id=build_chunk_natural_key(document_source_id, row.id),
                        source_type=EvidenceDocumentSourceType.MFDS,
                        source_title=row.source_title,
                        chunk_index=chunk_index,
                        content=content,
                        content_hash=_content_hash(content),
                        parser_version=PARSER_VERSION,
                        url=row.source_url,
                        jurisdiction=jurisdiction,
                        evidence_level=EvidenceLevel.OFFICIAL_REGULATORY,
                        legacy_evidence_id=row.id,
                        ingredient_id=row.ingredient_id,
                    )
                )
        return records
