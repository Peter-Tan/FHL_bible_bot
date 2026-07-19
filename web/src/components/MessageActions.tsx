import { useState } from "react";
import {
  Check,
  Copy,
  MessageSquare,
  Send,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { sendFeedback } from "../api/client";
import type { Message } from "../api/types";

interface Props {
  message: Message;
}

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // http:// fallback (clipboard API needs a secure context)
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
}

const btnBase =
  "flex items-center gap-1 rounded-md px-1.5 py-1 text-xs transition-colors";

export function MessageActions({ message }: Props) {
  const [copied, setCopied] = useState(false);
  const [rating, setRating] = useState<"good" | "bad" | null>(
    message.rating ?? null,
  );
  const [commentOpen, setCommentOpen] = useState(false);
  const [commentText, setCommentText] = useState("");
  const [commentSent, setCommentSent] = useState(false);

  const messageId = message.id;
  if (messageId == null) return null;

  const log = (action: "copy" | "good" | "bad" | "comment", comment?: string) =>
    sendFeedback(messageId, action, comment).catch(() => {
      /* feedback logging is best-effort; never disturb the chat */
    });

  const handleCopy = async () => {
    try {
      await copyText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
      log("copy");
    } catch {
      /* clipboard unavailable */
    }
  };

  const handleRate = (value: "good" | "bad") => {
    if (rating === value) return;
    setRating(value);
    log(value);
  };

  const submitComment = () => {
    const text = commentText.trim();
    if (!text) return;
    log("comment", text);
    setCommentText("");
    setCommentOpen(false);
    setCommentSent(true);
    setTimeout(() => setCommentSent(false), 2000);
  };

  return (
    <div className="mt-1.5">
      <div className="flex items-center gap-1 text-zinc-400">
        <button
          type="button"
          onClick={handleCopy}
          title="複製回答"
          className={`${btnBase} hover:bg-zinc-100 hover:text-zinc-700`}
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-green-600" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
          {copied ? "已複製" : "複製"}
        </button>
        <button
          type="button"
          onClick={() => handleRate("good")}
          title="有幫助"
          className={`${btnBase} ${
            rating === "good"
              ? "bg-green-50 text-green-600"
              : "hover:bg-zinc-100 hover:text-zinc-700"
          }`}
        >
          <ThumbsUp
            className={`h-3.5 w-3.5 ${rating === "good" ? "fill-current" : ""}`}
          />
        </button>
        <button
          type="button"
          onClick={() => handleRate("bad")}
          title="沒幫助"
          className={`${btnBase} ${
            rating === "bad"
              ? "bg-red-50 text-red-600"
              : "hover:bg-zinc-100 hover:text-zinc-700"
          }`}
        >
          <ThumbsDown
            className={`h-3.5 w-3.5 ${rating === "bad" ? "fill-current" : ""}`}
          />
        </button>
        <button
          type="button"
          onClick={() => setCommentOpen((v) => !v)}
          title="留言回饋"
          className={`${btnBase} ${
            commentOpen
              ? "bg-zinc-100 text-zinc-700"
              : "hover:bg-zinc-100 hover:text-zinc-700"
          }`}
        >
          <MessageSquare className="h-3.5 w-3.5" />
          留言
        </button>
        {commentSent && (
          <span className="text-xs text-green-600">已送出，謝謝回饋！</span>
        )}
      </div>
      {commentOpen && (
        <div className="mt-1.5 flex max-w-md items-end gap-1.5">
          <textarea
            value={commentText}
            onChange={(e) => setCommentText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submitComment();
              }
            }}
            rows={2}
            placeholder="留下你對這則回答的意見…"
            className="flex-1 resize-none rounded-lg border border-zinc-300 px-2.5 py-1.5 text-xs outline-none focus:border-blue-500"
          />
          <button
            type="button"
            onClick={submitComment}
            disabled={commentText.trim() === ""}
            title="送出留言"
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:bg-zinc-300"
          >
            <Send className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
