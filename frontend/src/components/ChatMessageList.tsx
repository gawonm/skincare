/**
 * 대화 메시지 목록 + 응답 대기 행 + 다시 시도 버튼(시안 109:76 / 109:118).
 *
 * 새 메시지가 쌓이거나 대기 상태가 바뀔 때마다 맨 아래로 따라 내려간다.
 */

import { useEffect, useRef } from "react";

import { CHAT_PENDING_LABEL, CHAT_RETRY_LABEL } from "../constants/chat";
import type { ChatTurn } from "../hooks/useChat";
import type { Artifact, ProductCandidateSet } from "../schemas/chat";
import { ChatBubble } from "./ChatBubble";
import { ChatProductCandidates } from "./ChatProductCandidates";
import { ChatStageRow } from "./ChatStageRow";

/**
 * `Artifact = ProductCandidateSet | RoutinePlan | EvidenceAnswer`에는 종류를 알려주는
 * 태그 필드가 없다(`schemas/chat.ts` 상단 주석과 같은 이유). `candidate_set_id` 유무로 좁힌다.
 */
function isProductCandidateSet(artifact: Artifact): artifact is ProductCandidateSet {
  return "candidate_set_id" in artifact;
}

function productCandidateSetsOf(turn: ChatTurn): ProductCandidateSet[] {
  return (turn.response?.artifacts ?? []).filter(isProductCandidateSet);
}

interface ChatMessageListProps {
  turns: ChatTurn[];
  /** 응답을 기다리는 중이면 진행 상태 행을 보여 준다. */
  waiting: boolean;
  /** 마지막 실패를 다시 보낼 수 있으면 목록 끝에 "다시 시도" 를 보여 준다. */
  canRetry: boolean;
  onRetry: () => void;
}

export function ChatMessageList({ turns, waiting, canRetry, onRetry }: ChatMessageListProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns, waiting, canRetry]);

  return (
    <div className="flex flex-col gap-3 py-3">
      {turns.map((turn, index) => (
        // 메시지는 append-only 이고 순서가 바뀌지 않으므로 index 를 key 로 써도 안전하다.
        // (재시도로 끝의 실패 안내를 걷어 낼 때도 뒤에서부터 지워서 앞 index 는 그대로다.)
        <ChatBubble key={index} role={turn.role} content={turn.content} tone={turn.tone}>
          {productCandidateSetsOf(turn).map((candidateSet) => (
            <ChatProductCandidates key={candidateSet.candidate_set_id} candidateSet={candidateSet} />
          ))}
        </ChatBubble>
      ))}
      {waiting ? <ChatStageRow label={CHAT_PENDING_LABEL} /> : null}
      {canRetry && !waiting ? (
        <div className="flex justify-start">
          <button
            type="button"
            onClick={onRetry}
            className="rounded-full border border-moss-deep px-4 py-1.5 text-[13px] font-medium text-moss-deep transition hover:bg-surface-2"
          >
            {CHAT_RETRY_LABEL}
          </button>
        </div>
      ) : null}
      <div ref={endRef} />
    </div>
  );
}
