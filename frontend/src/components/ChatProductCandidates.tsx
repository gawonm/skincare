/**
 * 채팅 답변에 딸린 제품 추천 목록.
 *
 * `ChatTurnResponse.artifacts`의 `ProductCandidateSet`을 받아 제품명을 상세페이지
 * 링크로 그린다. `product_id`는 이미 agent가 내려주고 있었고(`agent/nodes.py`), 여기서는
 * 그걸 꺼내 쓰기만 한다 — 백엔드·에이전트 쪽 추가 작업은 없었다(2026-09-23 확정).
 */

import { Link } from "react-router-dom";

import { buildProductDetailPath } from "../constants/product";
import type { ProductCandidateSet } from "../schemas/chat";

export function ChatProductCandidates({ candidateSet }: { candidateSet: ProductCandidateSet }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {candidateSet.candidates.map((candidate) => (
        <li key={candidate.product.product_id}>
          <Link
            to={buildProductDetailPath(candidate.product.product_id)}
            className="text-[13px] font-medium text-moss-deep underline underline-offset-2"
          >
            {candidate.rank}. {candidate.product.name}
          </Link>
        </li>
      ))}
    </ul>
  );
}
