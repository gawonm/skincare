from pathlib import Path
from uuid import UUID

import pytest

from data.scripts.nia_case_rag.claim_export_schemas import (
    ClaimExportManifest,
    ClaimExportRecord,
    ClaimExportRequest,
    ClaimIngestionDecisionRecord,
)
from data.scripts.nia_case_rag.claim_exporter import (
    ClaimExporter,
    ClaimExportError,
    ClaimExportErrorCode,
)
from data.scripts.nia_claim_ingestion_policy import (
    NiaClaimIngestionDecision,
    NiaClaimPriority,
)
from data.scripts.nia_labeling_schemas import NiaLabelingDocument

_INGREDIENT_ID = UUID("f90ba1bc-346b-4627-a387-8cf3759dbd7b")


class TestClaimExporter:
    def test_annotation과_decision을_statement_단위_Claim으로_변환한다(
        self, tmp_path: Path
    ) -> None:
        annotations = tmp_path / "annotations.jsonl"
        decisions = tmp_path / "decisions.jsonl"
        output = tmp_path / "claims.jsonl"
        manifest_path = tmp_path / "claims.manifest.json"
        document = self._document()
        annotations.write_text(f"{document.model_dump_json()}\n", encoding="utf-8")
        decision_rows = [
            ClaimIngestionDecisionRecord(
                record_id="CASE-1",
                statement_id="CASE-1-S001",
                statement_type="case_observation",
                decision=NiaClaimIngestionDecision.INGESTIBLE_FREE_TEXT,
                priority=NiaClaimPriority.PRIMARY,
            ),
            ClaimIngestionDecisionRecord(
                record_id="CASE-1",
                statement_id="CASE-1-S002",
                statement_type="ingredient_effect_claim",
                decision=NiaClaimIngestionDecision.INGESTIBLE_STRUCTURED,
                priority=NiaClaimPriority.PRIMARY,
            ),
        ]
        decisions.write_text(
            "".join(f"{row.model_dump_json()}\n" for row in decision_rows),
            encoding="utf-8",
        )

        result = ClaimExporter().export(
            ClaimExportRequest(
                annotations_path=annotations,
                decisions_path=decisions,
                output_path=output,
                manifest_path=manifest_path,
            )
        )

        record = ClaimExportRecord.model_validate_json(output.read_text(encoding="utf-8"))
        manifest = ClaimExportManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        assert record.source_record_id == "CASE-1"
        assert record.statements[0].content == "여드름/뾰루지 피지가 많습니다."
        assert record.statements[1].content == "성분: 나이아신아마이드 효과: 피지 조절"
        assert record.statements[1].ingredient_refs[0].ingredient_id == _INGREDIENT_ID
        assert manifest.document_count == 1
        assert manifest.statement_count == 2
        assert manifest.ingestible_statement_count == 2
        assert result.manifest == manifest

    def test_statement_decision이_누락되면_출력하지_않는다(self, tmp_path: Path) -> None:
        annotations = tmp_path / "annotations.jsonl"
        decisions = tmp_path / "decisions.jsonl"
        output = tmp_path / "claims.jsonl"
        manifest_path = tmp_path / "claims.manifest.json"
        annotations.write_text(f"{self._document().model_dump_json()}\n", encoding="utf-8")
        decisions.write_text("", encoding="utf-8")

        with pytest.raises(ClaimExportError) as error:
            ClaimExporter().export(
                ClaimExportRequest(
                    annotations_path=annotations,
                    decisions_path=decisions,
                    output_path=output,
                    manifest_path=manifest_path,
                )
            )

        assert error.value.code is ClaimExportErrorCode.DECISION_MISMATCH
        assert not output.exists()
        assert not manifest_path.exists()

    def _document(self) -> NiaLabelingDocument:
        return NiaLabelingDocument.model_validate(
            {
                "schema_version": "1.1",
                "annotation_version": "llm-production-test",
                "is_example": False,
                "is_partial_annotation": True,
                "production_ready": False,
                "annotator_count": 1,
                "source": {
                    "kind": "training_zip_record",
                    "record_id": "CASE-1",
                    "source_archive": "TL_여드름_뾰루지.zip",
                    "source_hash": None,
                    "dataset_split": "training",
                    "info_target_concern": "여드름/뾰루지",
                    "archive_name_target_concern_mismatch": False,
                },
                "case_context": {
                    "age_raw": 20,
                    "age_text_raw": None,
                    "gender_raw": "여성",
                    "skin_type_raw": "지성",
                    "skin_concerns_raw": ["여드름/뾰루지"],
                    "initial_skin_condition_raw": "피지가 많습니다.",
                },
                "statements": [
                    {
                        "statement_id": "CASE-1-S001",
                        "statement_type": "case_observation",
                        "source_spans": [
                            {
                                "json_path": "$.info.question",
                                "quote": "피지가 많습니다.",
                                "start": 0,
                                "end": 9,
                            }
                        ],
                        "annotation_status": "pending_review",
                        "support_status": "unverified",
                        "note": None,
                        "subject": "피지가 많습니다.",
                    },
                    {
                        "statement_id": "CASE-1-S002",
                        "statement_type": "ingredient_effect_claim",
                        "source_spans": [
                            {
                                "json_path": "$.info.answer",
                                "quote": "나이아신아마이드",
                                "start": 0,
                                "end": 8,
                            }
                        ],
                        "annotation_status": "pending_review",
                        "support_status": "unverified",
                        "note": None,
                        "subject": {
                            "raw_name": "Niacinamide",
                            "raw_name_ko": "나이아신아마이드",
                            "ingredient_id": str(_INGREDIENT_ID),
                            "matching_status": "matched",
                        },
                        "object": "피지 조절",
                        "concentration_raw": None,
                    },
                ],
                "references": [],
                "notes": ["LLM 자동 라벨링 결과, 사람 검토 전(pending_review)."],
            }
        )
