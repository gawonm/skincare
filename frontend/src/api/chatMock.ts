/**
 * 목 SSE 스트림.
 *
 * 계약서 `docs/contracts/front-to-backend.md` 의 이벤트 순서
 * (stage → token 여러 개 → warning(선택) → sources → done)를 `setTimeout` 지연으로
 * 흉내낸다. 실제 백엔드 호출은 하지 않는다.
 *
 * 실제 연동 시 이 파일을 `api/chat.ts`(fetch + `text/event-stream` 파싱)로 교체하면,
 * `hooks/useChat.ts` 는 import 대상만 바꾸면 되고 나머지 로직은 그대로다.
 */

import { ChatRole, DEFAULT_STAGE_LABEL, SseEventName } from "../constants/chat";
import type { ChatRequest, ChatSseEvent, SourceItem } from "../schemas/chat";

// 목 스트림 지연(ms). 실제 SSE 의 체감 속도를 대충 흉내내는 값이라 의미는 없다.
const STAGE_DELAY_MS = 650;
const TOKEN_DELAY_MS = 85;
const WARNING_DELAY_MS = 220;
const SOURCES_DELAY_MS = 320;

interface MockAnswer {
  /** 토큰 이벤트로 쪼개 보낼 본문 조각. 순서대로 이어 붙이면 완성된 답변이 된다. */
  chunks: string[];
  warning: string | null;
  sources: SourceItem[];
}

// 시안 04B 의 문구를 그대로 가져온 목 답변 두 벌. assistant 턴 수에 따라 번갈아 써서
// '경고 있음 / 없음' 두 UI 상태를 모두 눈으로 확인할 수 있게 한다(목 전용 동작).
const ANSWER_WITH_WARNING: MockAnswer = {
  chunks: [
    "같이 사용할 수 있지만 ",
    "시간대를 나눠 쓰는 걸 권장해요. ",
    "비타민C는 아침, ",
    "레티놀은 저녁에 사용해 보세요.",
  ],
  warning: "동시에 바르면 자극이 커질 수 있어요.",
  sources: [
    { label: "성분 DB", count: 1 },
    { label: "피부과 임상 가이드", count: 2 },
  ],
};

const ANSWER_WITHOUT_WARNING: MockAnswer = {
  chunks: [
    "처음이라면 0.1~0.3%를 ",
    "주 2~3회부터 시작하고, ",
    "자극이 없을 때 천천히 늘려보세요.",
  ],
  warning: null,
  sources: [{ label: "성분 데이터베이스", count: 1 }],
};

/**
 * `setTimeout` 을 Promise 로 감싼다.
 * `signal` 이 끊기면 타이머를 지우고 즉시 reject 하여, 대기 중인 제너레이터가
 * `AbortError` 로 빠져나오게 한다(정지 버튼 대응).
 */
function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("스트림이 중단되었습니다.", "AbortError"));
      return;
    }
    const timerId = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timerId);
        reject(new DOMException("스트림이 중단되었습니다.", "AbortError"));
      },
      { once: true },
    );
  });
}

/** 지금까지 나온 assistant 턴 수가 짝수면 경고 있는 답변, 홀수면 없는 답변. */
function pickAnswer(request: ChatRequest): MockAnswer {
  const assistantTurnCount = request.messages.filter(
    (message) => message.role === ChatRole.Assistant,
  ).length;
  return assistantTurnCount % 2 === 0 ? ANSWER_WITH_WARNING : ANSWER_WITHOUT_WARNING;
}

export async function* streamMockChatResponse(
  request: ChatRequest,
  signal: AbortSignal,
): AsyncGenerator<ChatSseEvent> {
  const answer = pickAnswer(request);

  await delay(STAGE_DELAY_MS, signal);
  yield { event: SseEventName.Stage, data: { label: DEFAULT_STAGE_LABEL } };

  for (const chunk of answer.chunks) {
    await delay(TOKEN_DELAY_MS, signal);
    yield { event: SseEventName.Token, data: { text: chunk } };
  }

  if (answer.warning !== null) {
    await delay(WARNING_DELAY_MS, signal);
    yield { event: SseEventName.Warning, data: { text: answer.warning } };
  }

  await delay(SOURCES_DELAY_MS, signal);
  yield { event: SseEventName.Sources, data: { items: answer.sources } };

  yield { event: SseEventName.Done, data: {} };
}
