/**
 * 대화 메시지 목록 + 응답 대기 행 + 다시 시도 버튼(시안 109:76 / 109:118).
 *
 * 새 메시지가 쌓이거나 대기 상태가 바뀔 때마다 맨 아래로 따라 내려간다.
 *
 * 서버 응답이 있는 어시스턴트 턴은 `turn.content`(문단을 이어 붙인 원문) 대신
 * `turn.response.sections`를 순서대로 그린다 — `docs/contracts/front-to-backend.md`
 * "응답 확장: 섹션"의 front 표시 규칙. `content`는 응답이 없는 턴(사용자 턴, 프론트가 만든
 * 실패 안내)에만 쓴다.
 */

import type { ReactNode } from "react";
import { useEffect, useRef } from "react";

import { CHAT_PENDING_LABEL, CHAT_RETRY_LABEL, ChatSectionType } from "../constants/chat";
import type { ChatTurn } from "../hooks/useChat";
import type { ChatSection, ReferenceView } from "../schemas/chat";
import { ChatBubble } from "./ChatBubble";
import { ChatProductCandidates } from "./ChatProductCandidates";
import { ChatSources } from "./ChatSources";
import { ChatStageRow } from "./ChatStageRow";
import { ChatWarning } from "./ChatWarning";

function sectionsOf(turn: ChatTurn): ChatSection[] {
  return turn.response?.sections ?? [];
}

/**
 * 되묻는 질문(`follow_up_question`)은 `message`에는 없을 수 있어(에이전트가 이미 문단에
 * 포함시켰으면 중복 방지로 뺀다, `useChat.ts`의 같은 판단 참고) 섹션에도 없을 수 있다.
 * 어느 섹션 글에도 없을 때만 마지막에 별도 문단으로 보여 준다.
 */
function followUpQuestionOf(turn: ChatTurn): string | null {
  const response = turn.response;
  const question = response?.follow_up_question ?? null;
  if (question === null) {
    return null;
  }
  const alreadyShown = sectionsOf(turn).some((section) =>
    (section.type === ChatSectionType.Notice ? section.detail : section.text).includes(question),
  );
  return alreadyShown ? null : question;
}

/** `ChatSources`가 받는 라벨·건수 모양으로 출처를 `source_title` 기준으로 묶는다. */
function groupReferencesBySourceTitle(
  references: ReferenceView[],
): { label: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const reference of references) {
    counts.set(reference.source_title, (counts.get(reference.source_title) ?? 0) + 1);
  }
  return Array.from(counts, ([label, count]) => ({ label, count }));
}

function renderSection(section: ChatSection, key: string): ReactNode {
  switch (section.type) {
    case ChatSectionType.Text:
    case ChatSectionType.Routine:
      // 루틴은 1차로 원문 문단을 그대로 보여 준다(요일·역할 격자 표시는 필요할 때 2차로).
      return <p key={key}>{section.text}</p>;
    case ChatSectionType.ProductList:
      return <ChatProductCandidates key={key} section={section} />;
    case ChatSectionType.Evidence:
      return (
        <div key={key} className="flex flex-col gap-1">
          <p>{section.text}</p>
          <ChatSources items={groupReferencesBySourceTitle(section.references)} />
        </div>
      );
    case ChatSectionType.Notice:
      return <ChatWarning key={key} text={section.detail} />;
  }
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
      {turns.map((turn, index) => {
        const sections = sectionsOf(turn);
        const followUpQuestion = followUpQuestionOf(turn);
        return (
          // 메시지는 append-only 이고 순서가 바뀌지 않으므로 index 를 key 로 써도 안전하다.
          // (재시도로 끝의 실패 안내를 걷어 낼 때도 뒤에서부터 지워서 앞 index 는 그대로다.)
          <ChatBubble
            key={index}
            role={turn.role}
            content={sections.length > 0 ? null : turn.content}
            tone={turn.tone}
          >
            {sections.map((section, sectionIndex) =>
              renderSection(section, `${index}-${sectionIndex}`),
            )}
            {followUpQuestion !== null ? <p>{followUpQuestion}</p> : null}
          </ChatBubble>
        );
      })}
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
