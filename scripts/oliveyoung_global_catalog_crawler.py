"""올리브영 글로벌 Skincare 카테고리(`ctgrNo=1000000008`) 전체를 순회해 `ProductCandidateRow`
목록을 만든다.

`1000000008`은 브라우저로 직접 확인한 결과 Moisturizers/Cleansers/Gift Set/Acne&Blemish
4개 하위 카테고리의 합집합이라, 이 카테고리 하나만 페이지 순회하면 하위 카테고리를 따로
순회하지 않고도 전량을 중복 없이 얻는다(합집합 근거: 4개 하위 카테고리 건수 합이 상위
카테고리 건수보다 커서 겹치는 상품이 있음을 확인함).

이미 성분 키워드 검색으로 모은 상품은 여기서도 걸리면 상세/전성분을 다시 부르지 않고
건너뛴다(호출자가 `existing_product_ids`로 넘긴다) — 재실행 시 이미 처리한 상품을 다시
부르지 않는 것으로 중단·재개를 대신한다(별도 체크포인트 파일 없음).
"""

import html
import time
from collections import Counter
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from scripts.catalog_eligibility_policy import CatalogEligibilityPolicy, CatalogExclusionReason
from scripts.image_downloader import ImageDownloader
from scripts.oliveyoung_global_category_client import OliveYoungGlobalCategoryClient
from scripts.oliveyoung_global_category_schemas import OliveYoungGlobalCategoryHitFields
from scripts.oliveyoung_global_client import OliveYoungGlobalClient
from scripts.product_candidate_schemas import DataSource, MatchStatus, ProductCandidateRow
from scripts.product_price_band_classifier import PriceBandClassifier
from scripts.product_title_translator import ProductTitleTranslator
from scripts.product_volume_parser import ProductVolumeParser


class CatalogCrawlReport(BaseModel):
    """실행 결과 집계. `총 발견 == 수집 + 이미 보유 + 제외 + 실패`가 항상 맞아야 한다 —
    어긋나면 상품을 어딘가에서 조용히 빠뜨렸다는 뜻이다."""

    model_config = ConfigDict(frozen=True)

    total_found: int
    collected: int
    skipped_existing: int
    excluded_by_reason: dict[CatalogExclusionReason, int]
    failed_product_ids: tuple[str, ...]

    def accounted_total(self) -> int:
        return (
            self.collected
            + self.skipped_existing
            + sum(self.excluded_by_reason.values())
            + len(self.failed_product_ids)
        )


class OliveYoungGlobalCatalogCrawler:
    # Skincare 전체(브라우저로 확인: found=3700, 하위 4개 카테고리의 합집합).
    _CATEGORY_NO = "1000000008"
    _ROWS_PER_PAGE = 100
    _INTER_REQUEST_DELAY_SECONDS = 0.5
    _LISTING_PAGE_DELAY_SECONDS = 1.0
    _MAX_RETRY_ATTEMPTS = 3
    _RETRY_BACKOFF_BASE_SECONDS = 2.0
    _CANDIDATE_ID_PREFIX = "OYC"
    _IMAGE_CDN_BASE_URL = "https://cdn-image.oliveyoung.com/"
    _PRODUCT_DETAIL_URL_TEMPLATE = "https://global.oliveyoung.com/product/detail?prdtNo={prdt_no}"
    _MALL_NAME = "OLIVE YOUNG Global"
    _PRODUCT_TYPE = "GENERAL_PRODUCT"
    _CATEGORY_PATH_SEPARATOR = ">"
    _CATEGORY_PATH_MAX_PARTS = 3
    _SEARCH_QUERY_LABEL = f"category:{_CATEGORY_NO}"

    def __init__(
        self,
        category_client: OliveYoungGlobalCategoryClient,
        product_client: OliveYoungGlobalClient,
        eligibility_policy: CatalogEligibilityPolicy,
        price_band_classifier: PriceBandClassifier,
        image_downloader: ImageDownloader,
        title_translator: ProductTitleTranslator,
        volume_parser: ProductVolumeParser,
        existing_product_ids: set[str],
        max_new_products: int | None = None,
    ) -> None:
        self._category_client = category_client
        self._product_client = product_client
        self._eligibility_policy = eligibility_policy
        self._price_band_classifier = price_band_classifier
        self._image_downloader = image_downloader
        self._title_translator = title_translator
        self._volume_parser = volume_parser
        self._existing_product_ids = existing_product_ids
        self._max_new_products = max_new_products
        self._row_sequence = 0

    def run(self) -> tuple[list[ProductCandidateRow], CatalogCrawlReport]:
        rows: list[ProductCandidateRow] = []
        excluded_by_reason: Counter[CatalogExclusionReason] = Counter()
        failed_product_ids: list[str] = []
        skipped_existing = 0
        total_found: int | None = None

        page_num = 1
        while True:
            page = self._retry(
                lambda: self._category_client.list_page(
                    self._CATEGORY_NO, page_num, self._ROWS_PER_PAGE
                )
            )
            if total_found is None:
                total_found = page.hits.found
            elif page.hits.found != total_found:
                # 실행 중 상품이 오픈/품절되면 총 건수가 바뀔 수 있다. 실패로 보지 않고
                # 발견 시점 값을 그대로 기준으로 삼되, 눈에 띄게 남긴다.
                print(
                    f"경고: 카테고리 총 건수가 실행 중 바뀌었습니다 "
                    f"({total_found} -> {page.hits.found})"
                )

            hits = page.hits.hit
            if not hits:
                break

            for hit in hits:
                if self._max_new_products is not None and len(rows) >= self._max_new_products:
                    break

                fields = hit.fields
                if fields.prdt_no in self._existing_product_ids:
                    skipped_existing += 1
                    continue

                eligibility = self._eligibility_policy.evaluate(fields)
                if not eligibility.is_eligible:
                    excluded_by_reason.update(eligibility.reasons)
                    continue

                try:
                    row = self._build_row(fields)
                except RuntimeError as error:
                    print(f"상품 처리 실패 (prdtNo={fields.prdt_no}): {error}")
                    failed_product_ids.append(fields.prdt_no)
                    continue

                if row is None:
                    excluded_by_reason[CatalogExclusionReason.OPTION_COUNT_MULTIPLE] += 1
                    continue

                rows.append(row)
                self._existing_product_ids.add(fields.prdt_no)
                time.sleep(self._INTER_REQUEST_DELAY_SECONDS)

            if self._max_new_products is not None and len(rows) >= self._max_new_products:
                break
            if len(hits) < self._ROWS_PER_PAGE:
                break
            page_num += 1
            time.sleep(self._LISTING_PAGE_DELAY_SECONDS)

        report = CatalogCrawlReport(
            total_found=total_found or 0,
            collected=len(rows),
            skipped_existing=skipped_existing,
            excluded_by_reason=dict(excluded_by_reason),
            failed_product_ids=tuple(failed_product_ids),
        )
        return rows, report

    def _build_row(self, fields: OliveYoungGlobalCategoryHitFields) -> ProductCandidateRow | None:
        detail = self._retry(lambda: self._product_client.get_product_detail(fields.prdt_no))
        if self._eligibility_policy.exceeds_option_limit(len(detail.option_list)):
            return None

        raw_ingredients_text = self._retry(
            lambda: self._product_client.get_ingredients_text(fields.prdt_no)
        )

        raw_title = html.unescape(detail.product_name)
        category1, category2, category3 = self._split_category_path(detail.category_path_en)
        lowest_price = detail.sale_amount_krw
        highest_price = detail.normal_amount_krw

        image_url = self._IMAGE_CDN_BASE_URL + detail.image_path
        local_image_path = self._image_downloader.download(
            image_url, file_stem=f"{DataSource.OLIVEYOUNG_GLOBAL.value}_{detail.prdt_no}"
        )
        display_title, title_source = self._title_translator.translate(raw_title)
        volume_value, volume_unit = self._volume_parser.parse(raw_title)

        self._row_sequence += 1
        return ProductCandidateRow(
            candidate_id=f"{self._CANDIDATE_ID_PREFIX}{self._row_sequence:04d}",
            source=DataSource.OLIVEYOUNG_GLOBAL,
            target_group=None,
            search_query=self._SEARCH_QUERY_LABEL,
            source_product_id=detail.prdt_no,
            raw_title=raw_title,
            display_title=display_title,
            title_source=title_source,
            brand=detail.brand_name,
            maker="",
            category1=category1,
            category2=category2,
            category3=category3,
            lowest_price=lowest_price,
            highest_price=highest_price,
            price_band=self._price_band_classifier.classify(lowest_price),
            volume_value=volume_value,
            volume_unit=volume_unit,
            image_url=image_url,
            local_image_path=str(local_image_path),
            raw_ingredients_text=raw_ingredients_text,
            shopping_url=self._PRODUCT_DETAIL_URL_TEMPLATE.format(prdt_no=detail.prdt_no),
            mall_name=self._MALL_NAME,
            product_type=self._PRODUCT_TYPE,
            observed_at=datetime.now().astimezone(),
            match_status=MatchStatus.MANUAL_REVIEW_REQUIRED,
            review_reasons=(),
        )

    def _split_category_path(self, category_path_en: str) -> tuple[str, str, str]:
        parts = [
            part.strip()
            for part in html.unescape(category_path_en).split(self._CATEGORY_PATH_SEPARATOR)
        ]
        padded_parts = parts + [""] * (self._CATEGORY_PATH_MAX_PARTS - len(parts))
        category1, category2, category3 = padded_parts[: self._CATEGORY_PATH_MAX_PARTS]
        return category1, category2, category3

    def _retry(self, call):
        # 기존 클라이언트 메서드는 모두 RuntimeError 하나로 httpx 오류를 감싸 상태 코드를
        # 구분할 수 없다. 원인을 세분화하기보다, 일시적 오류와 영구적 오류를 굳이 나누지
        # 않고 동일하게 짧게 재시도한다 — 수천 건 호출 중 일부 네트워크 hiccup을 흡수하는
        # 용도지, 완전한 장애 복구 전략은 아니다.
        last_error: RuntimeError | None = None
        for attempt in range(1, self._MAX_RETRY_ATTEMPTS + 1):
            try:
                return call()
            except RuntimeError as error:
                last_error = error
                if attempt < self._MAX_RETRY_ATTEMPTS:
                    time.sleep(self._RETRY_BACKOFF_BASE_SECONDS * attempt)
        raise last_error
