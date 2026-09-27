"""기존 평가 후보를 코퍼스 상대 관련성 재판정용 블라인드 파일로 합친다."""

from pathlib import Path
from typing import ClassVar

from tests.agent.nia_case_semantic_candidate_pool import (
    BlindCandidatePoolEntry,
    BlindCandidatePoolItem,
    CandidatePoolArtifactLoader,
)


class NiaCaseCorpusRelevanceReviewBuilder:
    def build(
        self,
        anchor_items: list[BlindCandidatePoolItem],
        rerank_items: list[BlindCandidatePoolItem],
    ) -> list[BlindCandidatePoolItem]:
        rerank_by_id = {item.evaluation_id: item for item in rerank_items}
        anchor_ids = {item.evaluation_id for item in anchor_items}
        unexpected_ids = set(rerank_by_id) - anchor_ids
        if unexpected_ids:
            raise RuntimeError(
                "reranker 보완 후보에 anchor가 없는 evaluation_id가 있습니다: "
                f"{sorted(unexpected_ids)}"
            )

        return [
            self._merge_item(item, rerank_by_id.get(item.evaluation_id))
            for item in anchor_items
        ]

    def _merge_item(
        self,
        anchor: BlindCandidatePoolItem,
        rerank: BlindCandidatePoolItem | None,
    ) -> BlindCandidatePoolItem:
        merged: dict[str, BlindCandidatePoolEntry] = {
            candidate.review_key: candidate for candidate in anchor.candidates
        }
        if rerank is not None:
            if rerank.query != anchor.query:
                raise RuntimeError(
                    "anchor와 reranker 보완 후보의 질의가 다릅니다: "
                    f"evaluation_id={anchor.evaluation_id}"
                )
            for candidate in rerank.candidates:
                existing = merged.get(candidate.review_key)
                if existing is not None and existing != candidate:
                    raise RuntimeError(
                        "같은 review_key의 블라인드 후보 내용이 다릅니다: "
                        f"review_key={candidate.review_key}"
                    )
                merged[candidate.review_key] = candidate

        # 기존 순위가 판정에 영향을 주지 않도록 검색 순서 대신 익명 review_key로 정렬한다.
        candidates = sorted(merged.values(), key=lambda item: item.review_key)
        return BlindCandidatePoolItem(
            evaluation_id=anchor.evaluation_id,
            query=anchor.query,
            candidate_count=len(candidates),
            candidates=candidates,
        )


class NiaCaseCorpusRelevanceReviewArtifact:
    def write(self, path: Path, items: list[BlindCandidatePoolItem]) -> None:
        try:
            with path.open("w", encoding="utf-8", newline="\n") as destination:
                for item in items:
                    destination.write(item.model_dump_json())
                    destination.write("\n")
        except OSError as error:
            raise RuntimeError(
                f"코퍼스 상대 관련성 블라인드 파일을 쓰지 못했습니다: {path}"
            ) from error


class NiaCaseCorpusRelevanceReviewCli:
    ANCHOR_BLIND_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_anchor_blind_v1.jsonl"
    )
    RERANK_BLIND_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_rerank_unjudged_blind_v1.jsonl"
    )
    OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_corpus_relevance_review_blind_v1.jsonl"
    )

    @classmethod
    def main(cls) -> None:
        loader = CandidatePoolArtifactLoader()
        items = NiaCaseCorpusRelevanceReviewBuilder().build(
            anchor_items=loader.load_blind(cls.ANCHOR_BLIND_PATH),
            rerank_items=loader.load_blind(cls.RERANK_BLIND_PATH),
        )
        NiaCaseCorpusRelevanceReviewArtifact().write(cls.OUTPUT_PATH, items)
        candidate_count = sum(item.candidate_count for item in items)
        print(f"corpus-relative blind review: queries={len(items)}, candidates={candidate_count}")


if __name__ == "__main__":
    NiaCaseCorpusRelevanceReviewCli.main()
