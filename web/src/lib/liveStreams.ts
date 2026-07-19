import { streamChat } from "../api/chatStream";
import type { AnswerStyle, ChatDoneEvent } from "../api/types";

/**
 * Module-level registry of in-flight chat streams, keyed by conversation id.
 *
 * A stream must outlive the component that started it: when the user switches
 * to another conversation (or opens a new chat) mid-answer, the fetch keeps
 * running here in the background, and useConversation re-attaches to it when
 * the user comes back. The backend persists the finished turn independently,
 * so even a page reload only loses the live view, never the answer.
 */

export type LiveStreamStatus = "streaming" | "done" | "aborted" | "error";

export interface LiveStream {
  conversationId: string;
  userText: string;
  /** Accumulated answer text (raw while streaming, linkified once done). */
  content: string;
  toolLog: string;
  status: LiveStreamStatus;
  done?: ChatDoneEvent;
  error?: string;
  controller: AbortController;
  /** Called after every mutation; listeners read the fields directly. */
  listeners: Set<() => void>;
}

const streams = new Map<string, LiveStream>();

export function getLiveStream(conversationId: string): LiveStream | undefined {
  return streams.get(conversationId);
}

export function stopLiveStream(conversationId: string): void {
  streams.get(conversationId)?.controller.abort();
}

export function startLiveStream(
  conversationId: string,
  text: string,
  style: AnswerStyle,
  onTitleChange: (id: string, title: string) => void,
): LiveStream {
  const controller = new AbortController();
  const s: LiveStream = {
    conversationId,
    userText: text,
    content: "",
    toolLog: "",
    status: "streaming",
    controller,
    listeners: new Set(),
  };
  streams.set(conversationId, s);

  const notify = () => {
    // Copy first: terminal-state listeners detach themselves while iterating.
    for (const fn of [...s.listeners]) fn();
  };

  streamChat(
    conversationId,
    text,
    style,
    {
      onToolLog: (line) => {
        s.toolLog = s.toolLog ? `${s.toolLog}\n${line}` : line;
        notify();
      },
      onTextDelta: (chunk) => {
        s.content += chunk;
        notify();
      },
      onDone: (done) => {
        s.status = "done";
        s.done = done;
        if (done.content) s.content = done.content;
        onTitleChange(conversationId, done.title);
      },
      onError: (detail) => {
        s.status = "error";
        s.error = detail;
      },
    },
    controller.signal,
  )
    .catch((e: unknown) => {
      s.status = controller.signal.aborted ? "aborted" : "error";
      if (s.status === "error") {
        s.error = e instanceof Error ? e.message : String(e);
      }
    })
    .finally(() => {
      if (s.status === "streaming") {
        // Stream ended without a done/error event: connection dropped.
        s.status = "error";
        s.error = "連線中斷，請重新整理頁面查看回應。";
      }
      // Remove from the registry BEFORE the final notify: once terminal, the
      // turn lives in the DB (or failed), so history reloads are the truth.
      streams.delete(conversationId);
      notify();
    });

  return s;
}
