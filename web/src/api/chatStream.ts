import { API_BASE } from "./client";
import type { AnswerStyle, ChatDoneEvent } from "./types";

export interface ChatStreamHandlers {
  onToolLog: (line: string) => void;
  onTextDelta: (text: string) => void;
  onDone: (data: ChatDoneEvent) => void;
  onError: (detail: string) => void;
}

/**
 * POST /api/chat and consume the SSE response by hand — native EventSource
 * cannot send a POST body. Events: tool_log | text_delta | done | error.
 */
export async function streamChat(
  conversationId: string,
  message: string,
  style: AnswerStyle,
  handlers: ChatStreamHandlers,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation_id: conversationId, message, style }),
    signal,
  });

  if (res.status === 429) {
    handlers.onError("目前使用人數較多，請稍後再試。");
    return;
  }
  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      dispatchEvent(rawEvent, handlers);
    }
  }
}

function dispatchEvent(raw: string, handlers: ChatStreamHandlers): void {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (dataLines.length === 0) return;

  let data: Record<string, unknown>;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch {
    return; // ignore malformed frames (e.g. SSE comments/keepalives)
  }

  switch (event) {
    case "tool_log":
      handlers.onToolLog(String(data.line ?? ""));
      break;
    case "text_delta":
      handlers.onTextDelta(String(data.text ?? ""));
      break;
    case "done":
      handlers.onDone(data as unknown as ChatDoneEvent);
      break;
    case "error":
      handlers.onError(String(data.detail ?? "未知錯誤"));
      break;
  }
}
