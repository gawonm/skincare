/** 상품 상세 조회 훅. `GET /products/{id}` 결과를 TanStack Query로 감싼다. */

import { useQuery } from "@tanstack/react-query";

import { ProductApi } from "../api/product";

export function useProductDetail(productId: string | undefined) {
  return useQuery({
    queryKey: ["products", "detail", productId],
    queryFn: () => ProductApi.getDetail(productId as string),
    enabled: productId !== undefined,
  });
}
