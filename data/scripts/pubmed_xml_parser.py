"""PubMed EFetch XML(`retmode=xml`)을 `PubmedRecord` 로 바꾸는 순수 파서. 네트워크 없음."""

import xml.etree.ElementTree as ET
from datetime import date

from data.scripts.evidence_collector_schemas import PubmedRecord

_MONTHS = {
    name: index
    for index, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}
_DEFAULT_MONTH = 1
_DEFAULT_DAY = 1


class PubmedXmlParser:
    def parse(self, xml_text: str) -> list[PubmedRecord]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            raise RuntimeError(f"PubMed EFetch XML 파싱 실패: {e}") from e

        records: list[PubmedRecord] = []
        for article in root.iter("PubmedArticle"):
            record = self._parse_article(article)
            if record is not None:
                records.append(record)
        return records

    def _parse_article(self, article: ET.Element) -> PubmedRecord | None:
        pmid = self._text(article.find("./MedlineCitation/PMID"))
        # PMID 가 없으면 document 자연키를 만들 수 없어 버린다
        if not pmid:
            return None

        return PubmedRecord(
            pmid=pmid,
            doi=self._find_doi(article),
            title=self._text(article.find("./MedlineCitation/Article/ArticleTitle")),
            abstract=self._abstract(article),
            journal=self._text(article.find("./MedlineCitation/Article/Journal/Title")) or None,
            publication_date=self._publication_date(article),
            publication_types=[
                self._text(node)
                for node in article.findall(".//PublicationTypeList/PublicationType")
            ],
            mesh_terms=[
                self._text(node)
                for node in article.findall(".//MeshHeadingList/MeshHeading/DescriptorName")
            ],
            authors=self._authors(article),
        )

    def _text(self, node: ET.Element | None) -> str:
        # <i>/<sub> 같은 인라인 태그 안의 글자까지 원문 그대로 이어 붙인다
        return "".join(node.itertext()).strip() if node is not None else ""

    def _abstract(self, article: ET.Element) -> str | None:
        parts: list[str] = []
        for node in article.findall("./MedlineCitation/Article/Abstract/AbstractText"):
            text = self._text(node)
            if not text:
                continue
            label = node.get("Label")
            # 구조화 초록의 섹션 라벨은 원문의 일부라 그대로 남긴다
            parts.append(f"{label}: {text}" if label else text)
        return "\n".join(parts) or None

    def _find_doi(self, article: ET.Element) -> str | None:
        for node in article.findall("./PubmedData/ArticleIdList/ArticleId"):
            if node.get("IdType") == "doi":
                return self._text(node) or None
        return None

    def _authors(self, article: ET.Element) -> list[str]:
        authors: list[str] = []
        for node in article.findall("./MedlineCitation/Article/AuthorList/Author"):
            collective = self._text(node.find("CollectiveName"))
            if collective:
                authors.append(collective)
                continue
            name = " ".join(
                part
                for part in (self._text(node.find("LastName")), self._text(node.find("Initials")))
                if part
            )
            if name:
                authors.append(name)
        return authors

    def _publication_date(self, article: ET.Element) -> date | None:
        pub_date = article.find("./MedlineCitation/Article/Journal/JournalIssue/PubDate")
        parsed = self._date_from(pub_date)
        if parsed is not None:
            return parsed
        return self._date_from(article.find("./MedlineCitation/Article/ArticleDate"))

    def _date_from(self, node: ET.Element | None) -> date | None:
        if node is None:
            return None
        year_text = self._text(node.find("Year"))
        if not year_text:
            # `<MedlineDate>1998 Dec-1999 Jan</MedlineDate>` 형태는 앞 4자리 연도만 신뢰한다
            medline = self._text(node.find("MedlineDate"))
            year_text = medline[:4]
        if not year_text.isdigit():
            return None
        month_text = self._text(node.find("Month")).lower()
        month = _MONTHS.get(month_text[:3]) or (int(month_text) if month_text.isdigit() else None)
        day_text = self._text(node.find("Day"))
        try:
            return date(
                int(year_text),
                month or _DEFAULT_MONTH,
                int(day_text) if day_text.isdigit() else _DEFAULT_DAY,
            )
        except ValueError:
            # 존재하지 않는 날짜(예: 2월 30일)는 추측하지 않고 날짜 없음으로 남긴다
            return None
