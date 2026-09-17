"""`reference.statement_links` 자동 연결은 비활성화한다.

NIA 원문의 `evidence_sources`는 문장 옆에 각주처럼 붙어있는 게 아니라 `info` 블록에
레코드 전체 기준으로 한 번만 나열된다 — 즉 원문 구조상 "이 reference가 정확히 이
문장의 근거다"를 가리키는 위치 정보가 없다.

이전 버전은 "placeholder가 아닌 reference 1개 + 성분 관련 statement 1개"일 때만
연결했지만, 이는 개수(cardinality)만 보는 것이지 원문 안에서 실제로 그 reference와
그 statement가 연관됐다는 local context 근거가 아니다(unit test로 실제 오연결
가능성을 확인함). false positive link가 unlinked보다 훨씬 위험하므로, 이번 단계에서는
연결하지 않는다 — reference는 record-level metadata로만 보존하고,
`statement_links`는 항상 빈 리스트로 유지한다. local context 기반 linking은
이번 범위 밖이다(향후 별도 설계 필요).
"""


class NiaReferenceLinker:
    def link(self, references: list[dict], statements: list[dict]) -> list[dict]:
        return references
