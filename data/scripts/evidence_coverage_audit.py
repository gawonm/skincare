"""PubMed/CIR scientific evidence coverage 를 NIA relevance·confirmed product 와 교차해 수집 우선순위를 낸다.

읽기 전용이다: DB write, 외부 API 호출, embedding, 신규 수집을 하지 않는다. MFDS 는 규제 근거라
scientific coverage 에 세지 않는다.

사용법:
    uv run python -m data.scripts.evidence_coverage_audit \
        --database-url postgresql+asyncpg://app:app@localhost:5432/skincare_v4_final \
        --nia-summary <nia_ingredient_relevance_summary.csv> --output-dir data/outputs/evidence_coverage
"""

import argparse
import asyncio
import csv
import sys
from collections import defaultdict
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from data.scripts.evidence_coverage_schemas import (
    GAP_TOPICS,
    CoverageRow,
    CoverageStatus,
    IngredientName,
    NiaRelevance,
    PriorityTier,
    ScientificDocumentLink,
    ScientificSource,
    TopicSourceRow,
)
from data.scripts.nia_product_backed_relevance import (
    ProductBackedIngredientCount,
    ProductBackedIngredientReader,
)
from models.evidence_chunk import EvidenceChunk, evidence_chunk_ingredient
from models.evidence_document import EvidenceClaimTopic, EvidenceDocument
from models.ingredient import IngredientMaster

# NIA 언급 case 수의 75 분위(NIA 에 언급된 102개 성분 기준). 절대 기준이 아니라 "상위 4분의 1"을 높음으로 본다.
NIA_HIGH_MIN_CASES = 170
# confirmed 제품 수 "높음"의 기준. 상위권 성분(수백~천 단위)과 꼬리를 가르는 경계로 잡았다.
PRODUCT_HIGH_MIN = 100

_MATRIX_FILENAME = "ingredient_scientific_evidence_coverage.csv"
_TOPIC_SOURCE_FILENAME = "ingredient_topic_source_coverage.csv"
_PRIORITY_FILENAME = "evidence_collection_priority.csv"
_LIST_SEPARATOR = ";"
_MISSING_PREFIX = "missing_"
_SAFETY_LABEL = "safety"  # 저장 topic 은 precaution 이지만 표/문서에서는 safety 로 부른다


class EvidenceCoverageReader:
    """audit 에 필요한 값을 읽기 전용으로 조회한다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def scientific_links(self) -> list[ScientificDocumentLink]:
        # source filter 를 여기서 한 번만 건다: MFDS 는 IN 목록에 없으므로 섞일 수 없다
        statement = (
            select(
                evidence_chunk_ingredient.c.ingredient_id,
                EvidenceDocument.id,
                EvidenceDocument.source_type,
                EvidenceDocument.claim_topics,
                func.count(func.distinct(EvidenceChunk.id)),
            )
            .join(EvidenceChunk, EvidenceChunk.id == evidence_chunk_ingredient.c.evidence_chunk_id)
            .join(EvidenceDocument, EvidenceDocument.id == EvidenceChunk.document_id)
            .where(EvidenceDocument.source_type.in_([s.value for s in ScientificSource]))
            .group_by(
                evidence_chunk_ingredient.c.ingredient_id,
                EvidenceDocument.id,
                EvidenceDocument.source_type,
                EvidenceDocument.claim_topics,
            )
        )
        result = await self._session.execute(statement)
        return [
            ScientificDocumentLink(
                ingredient_id=r[0],
                document_id=r[1],
                source=ScientificSource(getattr(r[2], "value", r[2])),
                claim_topics=tuple(r[3] or ()),
                chunk_count=r[4],
            )
            for r in result.all()
        ]

    async def ingredient_names(self, ids: set[UUID]) -> list[IngredientName]:
        result = await self._session.execute(
            select(
                IngredientMaster.id,
                IngredientMaster.standard_name_en,
                IngredientMaster.standard_name_ko,
            ).where(IngredientMaster.id.in_(ids))
        )
        return [
            IngredientName(ingredient_id=r[0], name_en=r[1], name_ko=r[2]) for r in result.all()
        ]

    async def orphan_link_count(self) -> int:
        """성분 또는 chunk 가 없는 evidence_chunk_ingredient 행 수(0 이어야 정상)."""
        result = await self._session.execute(
            text(
                "SELECT count(*) FROM evidence_chunk_ingredient eci "
                "LEFT JOIN ingredient_master i ON i.id = eci.ingredient_id "
                "LEFT JOIN evidence_chunk c ON c.id = eci.evidence_chunk_id "
                "WHERE i.id IS NULL OR c.id IS NULL"
            )
        )
        return int(result.scalar_one())


class NiaSummaryReader:
    """기존 NIA relevance 산출물(nia_ingredient_relevance_summary.csv)을 재사용한다. 재계산하지 않는다."""

    def read(self, path: Path) -> dict[UUID, NiaRelevance]:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return {
                UUID(r["ingredient_id"]): NiaRelevance(
                    nia_case_count=int(r["case_count"]),
                    nia_answer_case_count=int(r["answer_case_count"]),
                    nia_concern_count=int(r["target_concern_unique_count"]),
                )
                for r in csv.DictReader(f)
            }


class CoverageClassifier:
    """규칙 기반 분류. 점수식 없이 같은 입력이면 같은 tier 가 나온다."""

    def status(self, cir_docs: int, pubmed_docs: int) -> CoverageStatus:
        if cir_docs == 0 and pubmed_docs == 0:
            return CoverageStatus.NO_SCIENTIFIC_EVIDENCE
        if cir_docs > 0 and pubmed_docs > 0:
            return CoverageStatus.HAS_SCIENTIFIC_EVIDENCE
        return CoverageStatus.SINGLE_SOURCE_ONLY

    def priority(
        self, status: CoverageStatus, nia_cases: int, product_count: int, missing: list[str]
    ) -> tuple[PriorityTier, str]:
        nia_high = nia_cases >= NIA_HIGH_MIN_CASES
        product_high = product_count >= PRODUCT_HIGH_MIN
        if status is CoverageStatus.NO_SCIENTIFIC_EVIDENCE:
            if nia_high and product_count >= 1:
                return (
                    PriorityTier.P1,
                    f"근거 0건, NIA {nia_cases}건, confirmed 제품 {product_count}개",
                )
            if nia_high:
                return PriorityTier.P2, f"근거 0건, NIA {nia_cases}건, confirmed 제품 없음"
            return (
                PriorityTier.P4,
                f"근거 0건이나 NIA {nia_cases}건(기준 {NIA_HIGH_MIN_CASES} 미만)",
            )
        if missing and (nia_high or product_high):
            return (
                PriorityTier.P3,
                f"근거는 있으나 {','.join(missing)} 공백, NIA {nia_cases}건/제품 {product_count}개",
            )
        return PriorityTier.P4, "근거 충분하거나 relevance 낮음"


class CoverageBuilder:
    def __init__(self, classifier: CoverageClassifier) -> None:
        self._classifier = classifier

    def build(
        self,
        links: list[ScientificDocumentLink],
        names: list[IngredientName],
        nia: dict[UUID, NiaRelevance],
        products: list[ProductBackedIngredientCount],
    ) -> tuple[list[CoverageRow], list[TopicSourceRow]]:
        by_ingredient: dict[UUID, list[ScientificDocumentLink]] = defaultdict(list)
        for link in links:
            by_ingredient[link.ingredient_id].append(link)
        product_counts = {p.ingredient_id: p.product_count for p in products}

        rows: list[CoverageRow] = []
        topic_rows: list[TopicSourceRow] = []
        for name in names:
            ingredient_links = by_ingredient.get(name.ingredient_id, [])
            display = name.name_en or name.name_ko
            rows.append(self._row(name, display, ingredient_links, nia, product_counts))
            topic_rows.extend(self._topic_rows(name.ingredient_id, display, ingredient_links))
        return rows, topic_rows

    def _row(
        self,
        name: IngredientName,
        display: str,
        links: list[ScientificDocumentLink],
        nia: dict[UUID, NiaRelevance],
        product_counts: dict[UUID, int],
    ) -> CoverageRow:
        docs = {
            s: {link.document_id for link in links if link.source is s} for s in ScientificSource
        }
        chunks = {
            s: sum(link.chunk_count for link in links if link.source is s) for s in ScientificSource
        }
        topic_docs = {
            t: len({link.document_id for link in links if t.value in link.claim_topics})
            for t in EvidenceClaimTopic
        }
        cir, pubmed = len(docs[ScientificSource.CIR]), len(docs[ScientificSource.PUBMED])
        status = self._classifier.status(cir, pubmed)
        missing = [
            _SAFETY_LABEL if t is EvidenceClaimTopic.PRECAUTION else t.value
            for t in GAP_TOPICS
            if topic_docs[t] == 0
        ]
        relevance = nia.get(name.ingredient_id, NiaRelevance())
        product_count = product_counts.get(name.ingredient_id, 0)
        tier, reason = self._classifier.priority(
            status, relevance.nia_case_count, product_count, missing
        )
        present = [s.value for s in ScientificSource if docs[s]]
        return CoverageRow(
            ingredient_id=name.ingredient_id,
            ingredient_name=display,
            nia_case_count=relevance.nia_case_count,
            nia_answer_case_count=relevance.nia_answer_case_count,
            nia_concern_count=relevance.nia_concern_count,
            confirmed_product_count=product_count,
            cir_document_count=cir,
            cir_chunk_count=chunks[ScientificSource.CIR],
            pubmed_document_count=pubmed,
            pubmed_chunk_count=chunks[ScientificSource.PUBMED],
            scientific_document_count=cir + pubmed,
            scientific_chunk_count=sum(chunks.values()),
            source_types_present=_LIST_SEPARATOR.join(present),
            efficacy_count=topic_docs[EvidenceClaimTopic.EFFICACY],
            safety_count=topic_docs[EvidenceClaimTopic.PRECAUTION],
            usage_count=topic_docs[EvidenceClaimTopic.USAGE_INSTRUCTION],
            concentration_count=topic_docs[EvidenceClaimTopic.CONCENTRATION_REGULATION],
            combination_count=topic_docs[EvidenceClaimTopic.COMBINATION],
            missing_topics=_LIST_SEPARATOR.join(_MISSING_PREFIX + m for m in missing),
            coverage_status=status,
            priority_tier=tier,
            priority_reason=reason,
        )

    def _topic_rows(
        self, ingredient_id: UUID, display: str, links: list[ScientificDocumentLink]
    ) -> list[TopicSourceRow]:
        counts: dict[tuple[str, ScientificSource], set[UUID]] = defaultdict(set)
        for link in links:
            for topic in link.claim_topics:
                counts[(topic, link.source)].add(link.document_id)
        return [
            TopicSourceRow(
                ingredient_id=ingredient_id,
                ingredient_name=display,
                claim_topic=topic,
                source=source,
                document_count=len(doc_ids),
            )
            for (topic, source), doc_ids in sorted(
                counts.items(), key=lambda kv: (kv[0][0], kv[0][1].value)
            )
        ]

    def priority_candidates(self, rows: list[CoverageRow]) -> list[CoverageRow]:
        """P1~P3 만, tier → NIA 많은 순 → 제품 많은 순 → 근거 적은 순."""
        picked = [r for r in rows if r.priority_tier is not PriorityTier.P4]
        return sorted(
            picked,
            key=lambda r: (
                r.priority_tier.value,
                -r.nia_case_count,
                -r.confirmed_product_count,
                r.scientific_document_count,
                r.ingredient_name,
            ),
        )


class CoverageCsvWriter:
    def write(self, path: Path, rows: list[BaseModel], model_cls: type[BaseModel]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(model_cls.model_fields))
            writer.writeheader()
            for row in rows:
                writer.writerow(row.model_dump(mode="json"))


class CoverageAuditRunner:
    async def run(self, database_url: str, nia_summary: Path, output_dir: Path) -> None:
        nia = NiaSummaryReader().read(nia_summary)
        engine = create_async_engine(database_url)
        try:
            async with async_sessionmaker(engine)() as session:
                # 읽기 전용 트랜잭션: 실수로라도 write 가 나가지 않게 DB 가 막는다
                await session.execute(text("SET TRANSACTION READ ONLY"))
                reader = EvidenceCoverageReader(session)
                links = await reader.scientific_links()
                products = await ProductBackedIngredientReader(session).list_counts()
                universe = (
                    {p.ingredient_id for p in products}
                    | set(nia)
                    | {link.ingredient_id for link in links}
                )
                names = await reader.ingredient_names(universe)
                orphans = await reader.orphan_link_count()
        finally:
            await engine.dispose()

        builder = CoverageBuilder(CoverageClassifier())
        rows, topic_rows = builder.build(links, names, nia, products)
        rows.sort(key=lambda r: (-r.nia_case_count, -r.confirmed_product_count, r.ingredient_name))
        writer = CoverageCsvWriter()
        writer.write(output_dir / _MATRIX_FILENAME, rows, CoverageRow)
        writer.write(output_dir / _TOPIC_SOURCE_FILENAME, topic_rows, TopicSourceRow)
        writer.write(
            output_dir / _PRIORITY_FILENAME, builder.priority_candidates(rows), CoverageRow
        )
        self._print_checks(rows, links, names, nia, products, orphans)

    def _print_checks(
        self,
        rows: list[CoverageRow],
        links: list[ScientificDocumentLink],
        names: list[IngredientName],
        nia: dict[UUID, NiaRelevance],
        products: list[ProductBackedIngredientCount],
        orphans: int,
    ) -> None:
        ids = [r.ingredient_id for r in rows]
        name_ids = {n.ingredient_id for n in names}
        product_ids = {p.ingredient_id for p in products}
        statuses: dict[str, int] = defaultdict(int)
        tiers: dict[str, int] = defaultdict(int)
        for r in rows:
            statuses[r.coverage_status.value] += 1
            tiers[r.priority_tier.value] += 1
        consistent = all(
            r.scientific_document_count == r.cir_document_count + r.pubmed_document_count
            for r in rows
        )
        print(f"audited={len(rows)} duplicate_ids={len(ids) - len(set(ids))}")
        print(f"status={dict(statuses)} tiers={dict(tiers)}")
        print(f"sci_doc_sum_consistent={consistent}")
        print(f"link_sources={sorted({l.source.value for l in links})} orphan_links={orphans}")
        print(
            f"nia_orphans={len(set(nia) - name_ids)}/{len(nia)} "
            f"product_orphans={len(product_ids - name_ids)}/{len(product_ids)}"
        )
        print(f"nia_with_product={len(set(nia) & product_ids)}/{len(nia)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--nia-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/outputs/evidence_coverage"))
    args = parser.parse_args()
    asyncio.run(CoverageAuditRunner().run(args.database_url, args.nia_summary, args.output_dir))
