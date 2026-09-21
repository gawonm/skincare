"""성분 하나에 대해 PubMed 를 검색·선별한다(ESearch → EFetch → 결정적 선별).

질의는 임상 근거 중심 질의를 먼저 보내고, 그래도 예산을 못 채우면 human 질의를 한 번 더
보낸다. 검색 결과는 항상 상한(`_FETCH_LIMIT_PER_QUERY`)까지만 가져오고 전량을 저장하지 않는다.
"""

from data.scripts.evidence_collector_schemas import (
    CollectionIngredient,
    PubmedAssessment,
    PubmedCollectionResult,
    PubmedRecord,
)
from data.scripts.pubmed_client import PubmedSource
from data.scripts.pubmed_selection_policy import PubmedSelectionPolicy

# 선별 예산(최대 4편)의 몇 배 후보만 가져온다. 더 늘려도 relevance 순 하위 결과만 늘어난다.
_FETCH_LIMIT_PER_QUERY = 15


class PubmedEvidenceCollector:
    def __init__(self, source: PubmedSource, policy: PubmedSelectionPolicy) -> None:
        self._source = source
        self._policy = policy

    def collect(self, ingredient: CollectionIngredient) -> PubmedCollectionResult:
        records: dict[str, PubmedRecord] = {}
        queries = [
            self._policy.build_clinical_query(ingredient),
            self._policy.build_human_query(ingredient),
        ]
        assessments: list[PubmedAssessment] = []
        for queries_run, query in enumerate(queries, start=1):
            new_pmids = [
                pmid
                for pmid in self._source.search(query, _FETCH_LIMIT_PER_QUERY)
                if pmid not in records
            ]
            for record in self._source.fetch(new_pmids):
                records.setdefault(record.pmid, record)
            assessments = self._policy.assess(ingredient, list(records.values()))
            result = PubmedCollectionResult(
                ingredient=ingredient, assessments=assessments, queries_run=queries_run
            )
            if len(result.selected) >= self._policy.max_papers_per_ingredient:
                break
        return result
