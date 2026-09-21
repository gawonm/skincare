"""CIR status 페이지에서 발견한 report 후보 중 성분별로 최신 authoritative 한 건만 고른다.

한 성분에 원본(2003)과 amended(2025)처럼 여러 "Published Report"가 함께 있을 수 있고, 재검토
(re-review) 항목은 "다시 열지 않음" 결정이라 안전성 평가 본문이 아니다. 그래서 FINAL/AMENDED_FINAL
만 후보로 삼고, 그중 가장 최신 하나만 적재한다 - 과거 버전을 전부 적재하지 않는다.
"""

from uuid import UUID

from data.scripts.evidence_collector_schemas import CirReportCandidate
from models.evidence_document import EvidenceDocumentStatus

# status 페이지 라벨 -> enum. 실측한 라벨(`CIR_PDF_INGESTION_FEASIBILITY.md` 3.2절)만 매핑하고
# 모르는 라벨은 UNKNOWN 으로 두어 production 근거로 쓰지 않는다.
_PUBLISHED_REPORT_LABEL = "published report"
_REREVIEW_LABEL_KEYWORD = "re-review"
_TENTATIVE_LABEL_KEYWORD = "tentative"
_DRAFT_LABEL_KEYWORD = "draft"

_AUTHORITATIVE_STATUSES = frozenset(
    {EvidenceDocumentStatus.FINAL, EvidenceDocumentStatus.AMENDED_FINAL}
)


class CirReportSelector:
    def map_status(self, candidate: CirReportCandidate) -> EvidenceDocumentStatus:
        label = candidate.status_label.strip().lower()
        if _REREVIEW_LABEL_KEYWORD in label:
            return EvidenceDocumentStatus.REREVIEW
        if _TENTATIVE_LABEL_KEYWORD in label:
            return EvidenceDocumentStatus.TENTATIVE
        if _DRAFT_LABEL_KEYWORD in label:
            return EvidenceDocumentStatus.DRAFT
        if label == _PUBLISHED_REPORT_LABEL:
            return (
                EvidenceDocumentStatus.AMENDED_FINAL
                if candidate.is_amended
                else EvidenceDocumentStatus.FINAL
            )
        return EvidenceDocumentStatus.UNKNOWN

    def select(
        self, candidates: list[CirReportCandidate], requested_ingredient_ids: list[UUID]
    ) -> list[CirReportCandidate]:
        """요청된 성분마다 최신 authoritative report 를 고르고 attachment 기준으로 합친다.

        group review 는 하나의 report 가 여러 성분을 대표하므로, 여러 성분이 같은 report 를
        고르면 한 건으로 합치고 `ingredient_ids` 에 요청된 성분만 남긴다.
        """
        chosen_by_ingredient: dict[UUID, CirReportCandidate] = {}
        for ingredient_id in requested_ingredient_ids:
            eligible = [
                c
                for c in candidates
                if ingredient_id in c.ingredient_ids
                and self.map_status(c) in _AUTHORITATIVE_STATUSES
            ]
            if eligible:
                chosen_by_ingredient[ingredient_id] = max(eligible, key=self._recency_key)

        ingredient_ids_by_attachment: dict[str, list[UUID]] = {}
        selected_by_attachment: dict[str, CirReportCandidate] = {}
        for ingredient_id, candidate in chosen_by_ingredient.items():
            selected_by_attachment[candidate.attachment_id] = candidate
            ingredient_ids_by_attachment.setdefault(candidate.attachment_id, []).append(
                ingredient_id
            )
        return [
            candidate.model_copy(
                update={"ingredient_ids": ingredient_ids_by_attachment[attachment_id]}
            )
            for attachment_id, candidate in selected_by_attachment.items()
        ]

    def _recency_key(self, candidate: CirReportCandidate) -> tuple[int, int, str]:
        # 최신 발행일 → 같은 해면 amended 우선 → attachment_id(재실행 시 결과가 흔들리지 않게)
        year = candidate.document_date.toordinal() if candidate.document_date else 0
        return (year, int(candidate.is_amended), candidate.attachment_id)
