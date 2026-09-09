"""전성분 원문의 `[옵션명]` 구간 라벨을, 실제 판매 옵션(`OliveYoungGlobalProductOption`)과
연결한다.

라벨과 옵션명이 문자열로 완전히 같으리라는 보장이 없다(예: 라벨 "[Vita C]" vs 옵션명
"Vita C Porestrix Mask Sheet 1ea"). 그렇다고 느슨한 유사도로 무조건 연결하면 잘못된
연결을 확정된 것처럼 보이게 만든다. 이 클래스는 "라벨이 옵션명 목록 중 정확히 하나와만
겹친다"는 조건이 만족될 때만 `LINKED` 로 확정하고, 그 외에는 전부 `AMBIGUOUS` 로 남긴다
— `candidate_id`나 번역 상품명이 아니라 소스 옵션 식별자(`gds_cd`)로만 연결한다.
"""

from scripts.oliveyoung_global_schemas import OliveYoungGlobalProductOption
from scripts.product_ingredient_parse_schemas import (
    IngredientSectionLinkStatus,
    IngredientSectionParse,
    ProductIngredientParseResult,
)


class ProductIngredientOptionLinker:
    def link(
        self,
        parse_result: ProductIngredientParseResult,
        option_list: tuple[OliveYoungGlobalProductOption, ...],
    ) -> ProductIngredientParseResult:
        linked_sections = tuple(
            self._link_section(section, option_list) for section in parse_result.sections
        )
        return parse_result.model_copy(update={"sections": linked_sections})

    def _link_section(
        self,
        section: IngredientSectionParse,
        option_list: tuple[OliveYoungGlobalProductOption, ...],
    ) -> IngredientSectionParse:
        if section.section_label is None:
            # NO_OPTION_SECTIONS 는 파서가 이미 확정해 둔 상태다 — 여기서 건드리지 않는다.
            return section

        label = section.section_label.strip().lower()
        matches = [
            option for option in option_list if label in option.option_name.lower()
        ]

        if len(matches) == 1:
            return section.model_copy(
                update={
                    "link_status": IngredientSectionLinkStatus.LINKED,
                    "linked_option_gds_cd": matches[0].gds_cd,
                }
            )

        # 0개(옵션명 어디에도 라벨이 안 걸림) 또는 2개 이상(여러 옵션에 걸침) 모두
        # 연결을 확정할 수 없다는 뜻이라 미확정으로 남긴다.
        return section.model_copy(
            update={
                "link_status": IngredientSectionLinkStatus.AMBIGUOUS,
                "linked_option_gds_cd": None,
            }
        )
