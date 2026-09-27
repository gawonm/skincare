/**
 * 채팅 답변에 딸린 제품 추천 카드 목록.
 *
 * `ChatTurnResponse.sections`의 `product_list` 섹션(`docs/contracts/front-to-backend.md`
 * "응답 확장: 섹션")을 받아 역할별로 묶어 카드로 그린다. 카드 모양은 홈 화면 상품 카드
 * (`HomePage.tsx`의 `ProductCard`: 썸네일 + 이름 + 브랜드·가격)와 같은 언어를 쓴다 — 채팅
 * 카드 전용 시안이 아직 없어(`docs/front/README.md` "결정이 필요한 것") 이미 확정된 화면의
 * 시각 언어를 그대로 빌려 왔다. 이미지·브랜드·가격은 backend가 product 테이블에서 보강한
 * 값이라 없을 수 있다(개발용 fixture 등) — 그 경우 해당 자리를 비워 두고 이름·순위만 보여 준다.
 */

import { Link } from "react-router-dom";

import { buildProductDetailPath, formatPriceWon } from "../constants/product";
import type { ChatProductListSection, ProductCardView } from "../schemas/chat";

function ProductMetaLine({ card }: { card: ProductCardView }) {
  const parts = [card.brand, card.lowest_price !== null ? formatPriceWon(card.lowest_price) : null].filter(
    (part): part is string => part !== null,
  );
  if (parts.length === 0) {
    return null;
  }
  return <p className="truncate text-[10px] leading-[1.45] text-ink-soft">{parts.join(" · ")}</p>;
}

function ProductCandidateCard({ card }: { card: ProductCardView }) {
  return (
    <Link
      to={buildProductDetailPath(card.product_id)}
      className="flex items-center gap-2 rounded-xl border border-hairline bg-surface p-2"
    >
      <div className="flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-moss-tint">
        {card.image_url !== null ? (
          <img src={card.image_url} alt={card.name} className="size-full object-cover" />
        ) : null}
      </div>
      <div className="flex min-w-0 flex-col gap-0.5">
        <p className="truncate text-[12px] font-bold leading-[1.45] text-ink">
          {card.rank}. {card.name}
        </p>
        <ProductMetaLine card={card} />
        {card.reasons.length > 0 ? (
          <p className="truncate text-[10px] leading-[1.45] text-moss-deep">
            {card.reasons.join(", ")}
          </p>
        ) : null}
        {card.cautions.length > 0 ? (
          <p className="truncate text-[10px] leading-[1.45] text-clay">{card.cautions.join(", ")}</p>
        ) : null}
      </div>
    </Link>
  );
}

export function ChatProductCandidates({ section }: { section: ChatProductListSection }) {
  return (
    <div className="flex flex-col gap-2">
      {section.groups.map((group, groupIndex) => (
        <div key={group.role_label ?? groupIndex} className="flex flex-col gap-1">
          {group.role_label !== null ? (
            <p className="text-[11px] font-bold leading-[1.45] text-ink-soft">{group.role_label}</p>
          ) : null}
          <ul className="flex flex-col gap-1.5">
            {group.items.map((card) => (
              <li key={card.product_id}>
                <ProductCandidateCard card={card} />
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
