"""`/products` 엔드포인트. HTTP만 다루고 조회 로직은 `ProductQueryService`에 맡긴다.

홈 화면(비로그인 인기 상품)이 쓰므로 로그인 없이 호출 가능해야 한다(2026-09-23 확정,
docs/contracts/front-to-backend.md 범위와 달리 이 엔드포인트 자체는 게스트도 쓴다).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse

from backend.api.dependencies import ProductQueryServiceDep
from backend.schemas.product import ProductDetailResponse, ProductListResponse
from models.product import ProductServiceCategory

router = APIRouter(prefix="/products", tags=["products"])

# 홈 화면 한 줄에 보여줄 기본 개수(09-17 확정, 슬라이드로 소량만 노출).
_DEFAULT_LIST_LIMIT = 4
_MAX_LIST_LIMIT = 50


@router.get("", response_model=ProductListResponse)
async def list_products(
    service: ProductQueryServiceDep,
    service_category: ProductServiceCategory | None = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIST_LIMIT)] = _DEFAULT_LIST_LIMIT,
) -> ProductListResponse:
    """인기 상품 목록. `service_category`를 생략하면 전체 인기순이다."""
    return await service.list_popular(service_category=service_category, limit=limit)


@router.get("/{product_id}", response_model=ProductDetailResponse)
async def get_product(product_id: UUID, service: ProductQueryServiceDep) -> ProductDetailResponse:
    detail = await service.get_detail(product_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="상품을 찾을 수 없습니다."
        )
    return detail


@router.get("/{product_id}/image")
async def get_product_image(product_id: UUID, service: ProductQueryServiceDep) -> FileResponse:
    """`local_image_path`가 가리키는 파일을 서빙한다. 원본 CDN URL은 응답에 절대 노출하지 않는다."""
    path = await service.get_image_path(product_id)
    if path is None or not path.is_file():
        # DB엔 있는데 파일이 디스크에 없는 경우도 클라이언트 입장에선 "이미지 없음"과 같다
        # (09-17 확정 사항: 내부 상태 불일치를 500으로 감추지 않는다).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="이미지를 찾을 수 없습니다."
        )
    return FileResponse(path)
