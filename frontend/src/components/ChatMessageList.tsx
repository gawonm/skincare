/**
 * 대화 메시지 목록(시안 04B) + 응답 중 블록(시안 04C).
 *
 * 새 메시지·토큰이 쌓일 때마다 맨 아래로 따라 내려간다.
 */

import { useEffect, useRef } from "react";

import { ChatRole, DEFAULT_STAGE_LABEL } from "../constants/chat";
import type { ChatTurn, StreamingTurn } from "../hooks/useChat";
import { ChatBubble } from "./ChatBubble";
import { ChatSources } from "./ChatSources";
import { ChatStageRow } from "./ChatStageRow";
import { ChatWarning } from "./ChatWarning";

interface ChatMessageListProps {
  turns: ChatTurn[];
  streaming: StreamingTurn | null;
}

export function ChatMessageList({ turns, streaming }: ChatMessageListProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns, streaming]);

  return (
    <div className="flex flex-col gap-4 px-4 py-4">
      {turns.map((turn, index) => (
        // 메시지는 append-only 이고 순서가 바뀌지 않으므로 index 를 key 로 써도 안전하다.
        <TurnView key={index} turn={turn} />
      ))}
      {streaming !== null ? <StreamingView streaming={streaming} /> : null}
      <div ref={endRef} />
    </div>
  );
}

function TurnView({ turn }: { turn: ChatTurn }) {
  if (turn.role === ChatRole.User) {
    return <ChatBubble role={turn.role} content={turn.content} />;
  }

  return (
    <div className="flex flex-col items-start">
      <ChatBubble role={turn.role} content={turn.content}>
        {turn.warning !== null ? <ChatWarning text={turn.warning} /> : null}
      </ChatBubble>
      {turn.sources !== null ? <ChatSources items={turn.sources} /> : null}
    </div>
  );
}

function StreamingView({ streaming }: { streaming: StreamingTurn }) {
  // 아직 본문 토큰이 없으면 진행 상태 행만 보여주고(04C), 토큰이 오기 시작하면
  // 말풍선으로 전환한다(04B).
  if (streaming.content.length === 0) {
    return <ChatStageRow label={streaming.stageLabel ?? DEFAULT_STAGE_LABEL} />;
  }

  return (
    <div className="flex flex-col items-start">
      <ChatBubble role={ChatRole.Assistant} content={streaming.content}>
        {streaming.warning !== null ? <ChatWarning text={streaming.warning} /> : null}
      </ChatBubble>
      {streaming.sources !== null ? <ChatSources items={streaming.sources} /> : null}
    </div>
  );
}
