"""NIA 의미 라벨링 고정 파서.

라벨링 JSON 파일(예: `nia/pilot_annotations_v2.json`)과 그 원문 레코드 파일(예:
`nia/pilot_candidate_records.json`)을 받아, schema freeze 리뷰(2026-09-11)에서
합의한 7가지 검증을 전부 수행한다. 이 모듈은 라벨링 결정의 의미적 정확성을
판단하지 않는다 - 정해진 형식·참조·불변조건을 지키는지, 그리고 알려진 실수
패턴(문서 간 ID 충돌, placeholder 오분류, 원문 미보존 등)에 걸리는지만 본다.

`agent/rag/`나 `backend/`에서 이 결과를 어떻게 쓸지는 이 모듈의 책임이 아니다
(agent는 이 모듈을 몰라야 한다 - CLAUDE.md 규칙 11).
"""

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from data.scripts import nia_labeling_schemas as S

KNOWN_PLACEHOLDER_PATTERNS = (
    re.compile(r"^DOI:\s*10\.xxxx/xxxxx$"),
    re.compile(r"^DOI:\s*10\.1234/example$"),
    re.compile(r"^PMID:\s*12345678"),
)


@dataclass
class DocumentReport:
    record_id: str
    schema_errors: tuple[str, ...] = ()
    span_errors: tuple[str, ...] = ()
    invariant_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.schema_errors and not self.span_errors and not self.invariant_errors


class NiaLabelingParser:
    """라벨링 파일 하나(여러 문서 배열)를 읽어 7가지 검증을 전부 수행한다."""

    def __init__(self) -> None:
        self._verifier = S.NiaLabelingSpanVerifier()

    def parse_file(self, labeling_path: Path, raw_records_path: Path) -> list[DocumentReport]:
        raw_docs = json.loads(labeling_path.read_text(encoding="utf-8"))
        raw_records: dict[str, dict] = json.loads(raw_records_path.read_text(encoding="utf-8"))
        return self._parse(raw_docs, raw_records)

    def _parse(self, raw_docs: list[dict], raw_records: dict[str, dict]) -> list[DocumentReport]:
        reports: list[DocumentReport] = []
        validated_docs: list[tuple[dict, S.NiaLabelingDocument | None, DocumentReport]] = []

        for raw_doc in raw_docs:
            rid = raw_doc.get("source", {}).get("record_id", "<unknown>")
            report = DocumentReport(record_id=rid)
            doc: S.NiaLabelingDocument | None = None
            try:
                doc = S.NiaLabelingDocument.model_validate(raw_doc)
            except Exception as exc:  # noqa: BLE001 - 검증 1: 스키마
                report.schema_errors = (str(exc),)

            if doc is not None:
                raw_record = raw_records.get(rid, {}).get("record")
                if raw_record is None:
                    report.warnings.append(f"원문 레코드를 찾을 수 없음: {rid}")
                else:
                    # 검증 2: source span 원문 재검증
                    report.span_errors = self._verifier.verify_document(doc, raw_record)
                    # 검증 4: archive mismatch인데 notes 설명 없음
                    self._check_mismatch_note(doc, report)
                    # 검증 5: combination_claim subjects 수 vs object 텍스트 교차검증
                    self._check_combination_claim_count(doc, report)
                    # 검증 6: placeholder reference 재확인
                    self._check_reference_placeholder(doc, report)
                    # 검증 7: age_text_raw 원문 리터럴 검증
                    self._check_age_text_literal(doc, raw_record, report)
                # gap audit(2026-09-11)로 추가된 구조적 invariant - semantic 판단 없이
                # deterministic하게 판정 가능한 것만 (원문 불필요, doc만으로 검증됨)
                self._check_duplicate_spans(doc, report)
                self._check_frequency_time_of_day_consistency(doc, report)
                self._check_combination_subject_duplicates(doc, report)
                self._check_matched_requires_ingredient_id(doc, report)
                self._check_concentration_provenance(doc, report)
                self._check_action_id_uniqueness(doc, report)
                self._check_production_ready_consistency(doc, report)

            validated_docs.append((raw_doc, doc, report))
            reports.append(report)

        # 검증 3: statement_id 문서 간(전체 배치) 유일성
        self._check_cross_document_statement_ids(validated_docs, reports)

        return reports

    def _check_mismatch_note(self, doc: S.NiaLabelingDocument, report: DocumentReport) -> None:
        if doc.source.archive_name_target_concern_mismatch and not any(
            "불일치" in note or "mismatch" in note.lower() for note in doc.notes
        ):
            report.warnings.append(
                "archive_name_target_concern_mismatch=True인데 notes에 불일치 설명이 없음"
            )

    def _check_combination_claim_count(
        self, doc: S.NiaLabelingDocument, report: DocumentReport
    ) -> None:
        for stmt in doc.statements:
            if not isinstance(stmt, S.NiaCombinationClaimStatement):
                continue
            quote_text = " ".join(span.quote for span in stmt.source_spans)
            mentioned = sum(
                1
                for subj in stmt.subjects
                if subj.raw_name in quote_text
                or (subj.raw_name_ko and subj.raw_name_ko in quote_text)
            )
            if mentioned < len(stmt.subjects):
                report.warnings.append(
                    f"{stmt.statement_id}: subjects {len(stmt.subjects)}개 중 "
                    f"{mentioned}개만 source_span 텍스트에서 이름이 확인됨 (휴리스틱 - 오탐 가능)"
                )

    def _check_reference_placeholder(
        self, doc: S.NiaLabelingDocument, report: DocumentReport
    ) -> None:
        for ref in doc.references:
            looks_like_placeholder = any(p.match(ref.raw) for p in KNOWN_PLACEHOLDER_PATTERNS)
            if (
                looks_like_placeholder
                and ref.reference_status != S.NiaReferenceStatus.PLACEHOLDER_DETECTED
            ):
                report.warnings.append(
                    f"reference {ref.raw!r}가 알려진 placeholder 패턴과 일치하는데 "
                    f"reference_status={ref.reference_status}로 라벨링됨"
                )
            if (
                not looks_like_placeholder
                and ref.reference_status == S.NiaReferenceStatus.PLACEHOLDER_DETECTED
            ):
                report.warnings.append(
                    f"reference {ref.raw!r}가 placeholder_detected로 라벨링됐지만 "
                    "알려진 placeholder 패턴과 일치하지 않음 (재확인 필요)"
                )

    def _check_duplicate_spans(self, doc: S.NiaLabelingDocument, report: DocumentReport) -> None:
        """같은 statement 안에 완전히 동일한 (json_path, start, end) span이 중복 등장하면
        구조적으로 잘못됐다 - 같은 근거를 두 번 셀 이유가 없다."""
        for stmt in doc.statements:
            keys = [(sp.json_path, sp.start, sp.end) for sp in stmt.source_spans]
            dups = {k for k in keys if keys.count(k) > 1}
            if dups:
                report.invariant_errors.append(
                    f"{stmt.statement_id}: source_spans에 완전 중복 span {dups}"
                )

    def _check_frequency_time_of_day_consistency(
        self, doc: S.NiaLabelingDocument, report: DocumentReport
    ) -> None:
        """period=day인 frequency는 하루 몇 회인지를 뜻한다. time_of_day가 그보다 많은
        서로 다른 시간대를 명시했다면(예: 하루 1회라면서 아침/저녁 둘 다 지정) 구조적 모순이다."""
        for stmt in doc.statements:
            if not isinstance(stmt, S.NiaUsageInstructionStatement) or stmt.frequency is None:
                continue
            if stmt.frequency.period != S.NiaFrequencyPeriod.DAY:
                continue
            distinct_tod = len(set(stmt.time_of_day))
            if distinct_tod > stmt.frequency.max:
                report.invariant_errors.append(
                    f"{stmt.statement_id}: time_of_day {distinct_tod}개(서로 다른 시간대)가 "
                    f"frequency.max({stmt.frequency.max}, period=day)보다 많음"
                )

    def _check_combination_subject_duplicates(
        self, doc: S.NiaLabelingDocument, report: DocumentReport
    ) -> None:
        """combination_claim의 subjects에 같은 raw_name이 두 번 들어가면 원소 중복이다
        (같은 성분을 서로 다른 두 성분처럼 센 것)."""
        for stmt in doc.statements:
            if not isinstance(stmt, S.NiaCombinationClaimStatement):
                continue
            names = [s.raw_name for s in stmt.subjects]
            dups = {n for n in names if names.count(n) > 1}
            if dups:
                report.invariant_errors.append(
                    f"{stmt.statement_id}: subjects에 raw_name 중복 {dups}"
                )

    def _check_matched_requires_ingredient_id(
        self, doc: S.NiaLabelingDocument, report: DocumentReport
    ) -> None:
        """스키마는 'ingredient_id가 있으면 matched여야 함'만 강제한다. 그 역
        - matching_status=matched인데 ingredient_id가 없는 경우 - 는 강제하지 않아 빠져 있었다.
        '매칭됐다'면서 실제 대상 ID가 없는 것은 구조적으로 모순이다."""
        for stmt in doc.statements:
            subs: tuple[S.NiaIngredientSubject, ...]
            if isinstance(stmt, S.NiaIngredientEffectClaimStatement):
                subs = (stmt.subject,)
            elif isinstance(stmt, S.NiaCombinationClaimStatement):
                subs = stmt.subjects
            else:
                continue
            for sub in subs:
                if (
                    sub.matching_status == S.NiaIngredientMatchingStatus.MATCHED
                    and sub.ingredient_id is None
                ):
                    report.invariant_errors.append(
                        f"{stmt.statement_id}: matching_status=matched인데 ingredient_id가 없음 ({sub.raw_name})"
                    )

    def _check_concentration_provenance(
        self, doc: S.NiaLabelingDocument, report: DocumentReport
    ) -> None:
        """concentration_raw는 자유 텍스트 필드라 스키마가 원문 출처를 강제할 수 없다.
        해당 statement의 source_spans 어디에도 그 값이 literal로 없으면, 이 정량값이
        어디서 왔는지 추적할 수 없다는 뜻이다."""
        for stmt in doc.statements:
            if (
                not isinstance(stmt, S.NiaIngredientEffectClaimStatement)
                or not stmt.concentration_raw
            ):
                continue
            quotes = " ".join(sp.quote for sp in stmt.source_spans)
            if stmt.concentration_raw not in quotes:
                report.invariant_errors.append(
                    f"{stmt.statement_id}: concentration_raw={stmt.concentration_raw!r}가 "
                    "source_spans quote 어디에도 literal로 없음 (provenance 추적 불가)"
                )

    def _check_action_id_uniqueness(
        self, doc: S.NiaLabelingDocument, report: DocumentReport
    ) -> None:
        """문서 안에서 action_id는 usage_instruction 하나를 가리키는 식별자다.
        같은 문서 안에서 두 statement가 같은 action_id를 쓰면 같은 행동을 가리키는 것인지
        서로 다른 행동에 실수로 같은 ID를 붙인 것인지 구분할 수 없다."""
        action_ids = [
            stmt.action_id
            for stmt in doc.statements
            if isinstance(stmt, S.NiaUsageInstructionStatement)
        ]
        dups = {a for a in action_ids if action_ids.count(a) > 1}
        if dups:
            report.invariant_errors.append(f"action_id 문서 내 중복: {dups}")

    def _check_production_ready_consistency(
        self, doc: S.NiaLabelingDocument, report: DocumentReport
    ) -> None:
        """production_ready=True는 '이 문서는 그대로 하류(downstream)에 내보내도 된다'는
        선언이다. 그런데 그 안에 아직 검토 대기(pending_review) 또는 반려(rejected) 상태인
        statement가 있다면 선언 자체가 거짓이다 - 의미 판단이 아니라 상태값끼리의 순수한 모순."""
        if not doc.production_ready:
            return
        bad = [
            stmt.statement_id
            for stmt in doc.statements
            if stmt.annotation_status != S.NiaAnnotationStatus.APPROVED
        ]
        if bad:
            report.invariant_errors.append(
                f"production_ready=True인데 annotation_status!=approved인 statement 존재: {bad}"
            )

    def _check_age_text_literal(
        self, doc: S.NiaLabelingDocument, raw_record: dict, report: DocumentReport
    ) -> None:
        age_text = doc.case_context.age_text_raw
        if age_text is None:
            return
        question = raw_record.get("info", {}).get("question", "")
        if age_text not in question:
            report.warnings.append(
                f"case_context.age_text_raw={age_text!r}가 info.question 원문에 리터럴로 없음"
            )

    def _check_cross_document_statement_ids(
        self,
        validated_docs: list[tuple[dict, S.NiaLabelingDocument | None, DocumentReport]],
        reports: list[DocumentReport],
    ) -> None:
        id_owner: dict[str, str] = {}
        counter: Counter[str] = Counter()
        for raw_doc, doc, _ in validated_docs:
            if doc is None:
                continue
            for stmt in doc.statements:
                counter[stmt.statement_id] += 1
                id_owner.setdefault(stmt.statement_id, doc.source.record_id)

        duplicated = {sid for sid, count in counter.items() if count > 1}
        if not duplicated:
            return
        for report in reports:
            for sid in duplicated:
                if id_owner.get(sid) == report.record_id:
                    report.warnings.append(f"statement_id {sid!r}가 배치 내 다른 문서와 충돌함")


def main() -> None:
    # 수동 검토용 스크래치 산출물(data/manual_review/nia/)을 대상으로 한 CLI 진입점.
    # 이 디렉터리는 gitignore 대상이라 로컬에 없으면 이 함수는 실행되지 않는다.
    nia_dir = Path("data/manual_review/nia")
    parser = NiaLabelingParser()
    reports = parser.parse_file(
        nia_dir / "pilot_annotations_v2.json", nia_dir / "pilot_candidate_records.json"
    )

    ok_count = sum(1 for r in reports if r.ok)
    print(f"{ok_count}/{len(reports)}건 하드 검증(스키마+span+invariant) 통과\n")
    for r in reports:
        if r.schema_errors or r.span_errors or r.invariant_errors or r.warnings:
            print(f"[{r.record_id}]")
            for e in r.schema_errors:
                print(f"  SCHEMA_ERROR: {e}")
            for e in r.span_errors:
                print(f"  SPAN_ERROR: {e}")
            for e in r.invariant_errors:
                print(f"  INVARIANT_ERROR: {e}")
            for w in r.warnings:
                print(f"  WARNING: {w}")


if __name__ == "__main__":
    main()
