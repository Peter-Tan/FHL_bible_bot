import { useCallback, useEffect, useRef, useState } from "react";
import { getConversation } from "../api/client";
import {
  getLiveStream,
  startLiveStream,
  stopLiveStream,
  type LiveStream,
} from "../lib/liveStreams";
import type { AnswerStyle, Message } from "../api/types";

/**
 * Owns the message list of the currently selected conversation: loads history
 * on switch, streams new turns with optimistic UI.
 *
 * Streams themselves live in lib/liveStreams so they survive conversation
 * switches — this hook only attaches to (and detaches from) the stream of the
 * conversation currently on screen.
 */
export function useConversation(
  conversationId: string | null,
  onTitleChange: (id: string, title: string) => void,
) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const detachRef = useRef<(() => void) | null>(null);

  const updateLastMessage = (fn: (m: Message) => Message) => {
    setMessages((msgs) =>
      msgs.length > 0
        ? [...msgs.slice(0, -1), fn(msgs[msgs.length - 1])]
        : msgs,
    );
  };

  /** Mirror a live stream into the last (assistant) message until it ends. */
  const attach = useCallback((s: LiveStream) => {
    detachRef.current?.();
    setIsStreaming(true);
    const listener = () => {
      if (s.status === "streaming") {
        updateLastMessage((m) => ({
          ...m,
          content: s.content,
          tool_log: s.toolLog,
        }));
        return;
      }
      // Terminal: apply the final state once, then detach.
      if (s.status === "done") {
        updateLastMessage((m) => ({
          ...m,
          id: s.done?.message_id ?? m.id,
          content: s.content,
          tool_log: s.toolLog,
        }));
      } else if (s.status === "aborted") {
        updateLastMessage((m) => ({
          ...m,
          content: `${s.content}\n\n*（已停止產生）*`,
          tool_log: s.toolLog,
        }));
      } else {
        setError(s.error ?? "未知錯誤");
        updateLastMessage((m) => ({ ...m, content: s.content }));
      }
      setIsStreaming(false);
      s.listeners.delete(listener);
      detachRef.current = null;
    };
    s.listeners.add(listener);
    detachRef.current = () => s.listeners.delete(listener);
  }, []);

  useEffect(() => {
    // Detach from (but do NOT abort) any stream of the previous conversation:
    // it keeps running in liveStreams and can be re-attached later.
    detachRef.current?.();
    detachRef.current = null;
    setError(null);
    setIsStreaming(false);
    setMessages([]);
    if (!conversationId) return;

    // Grab the stream reference now; its fields mutate in place, so after the
    // history fetch we can still see whether it finished in the meantime.
    const live = getLiveStream(conversationId);
    let cancelled = false;
    setIsLoading(true);
    getConversation(conversationId)
      .then((c) => {
        if (cancelled) return;
        let msgs = c.messages;
        if (live && live.status === "streaming") {
          // Re-attach: show the pending turn and keep mirroring it.
          msgs = [
            ...msgs,
            { role: "user", content: live.userText },
            {
              role: "assistant",
              content: live.content,
              tool_log: live.toolLog,
            },
          ];
          attach(live);
        } else if (
          live &&
          live.status === "done" &&
          live.done &&
          !c.messages.some((m) => m.id === live.done!.message_id)
        ) {
          // Finished between our fetch and now — history is missing the turn.
          msgs = [
            ...msgs,
            { role: "user", content: live.userText },
            {
              role: "assistant",
              id: live.done.message_id,
              content: live.content,
              tool_log: live.toolLog,
            },
          ];
        }
        setMessages(msgs);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
      detachRef.current?.();
      detachRef.current = null;
    };
  }, [conversationId, attach]);

  const send = useCallback(
    (text: string, style: AnswerStyle) => {
      if (!conversationId || isStreaming) return;
      if (getLiveStream(conversationId)) return; // one stream per conversation
      setError(null);
      setMessages((msgs) => [
        ...msgs,
        { role: "user", content: text },
        { role: "assistant", content: "", tool_log: "" },
      ]);
      attach(startLiveStream(conversationId, text, style, onTitleChange));
    },
    [conversationId, isStreaming, onTitleChange, attach],
  );

  const stop = useCallback(() => {
    if (conversationId) stopLiveStream(conversationId);
  }, [conversationId]);
  const clearError = useCallback(() => setError(null), []);

  return { messages, isStreaming, isLoading, error, send, stop, clearError };
}
