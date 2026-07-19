import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message } from "../api/types";
import { transformVerseHref, type VerseLinkMode } from "../lib/verseLinks";
import { MessageActions } from "./MessageActions";
import { ToolCallLog } from "./ToolCallLog";

interface Props {
  message: Message;
  /** True only for the assistant message currently being streamed. */
  isStreaming: boolean;
  /** How verse citations should link out (傳統版 read.php or 新版 vui). */
  verseLinkMode: VerseLinkMode;
}

/** Flatten an anchor's React children to plain text (citation like "約翰福音 3:16"). */
function childrenToText(children: ReactNode): string {
  if (typeof children === "string") return children;
  if (typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(childrenToText).join("");
  return "";
}

export function ChatMessage({ message, isStreaming, verseLinkMode }: Props) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-blue-600 px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-white">
          {message.content}
        </div>
      </div>
    );
  }

  const hasText = message.content.length > 0;
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-full">
        {message.tool_log ? (
          <ToolCallLog log={message.tool_log} autoOpen={isStreaming && !hasText} />
        ) : null}
        {hasText ? (
          <div className="prose prose-zinc max-w-none text-[15px] leading-relaxed prose-pre:text-[13px] prose-code:text-[13px]">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                // Verse citations are stored as traditional read.php links;
                // rewritten to the new UI at render time when selected (the
                // verse anchor comes from the citation text, since stored
                // hrefs are chapter-only). Open in a new window so the chat
                // is never navigated away.
                a: ({ node: _node, href, children, ...props }) => (
                  <a
                    {...props}
                    href={transformVerseHref(
                      href,
                      verseLinkMode,
                      childrenToText(children),
                    )}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {children}
                  </a>
                ),
              }}
            >
              {message.content}
            </ReactMarkdown>
            {isStreaming && (
              <span className="ml-0.5 inline-block animate-pulse select-none">▍</span>
            )}
          </div>
        ) : isStreaming && !message.tool_log ? (
          <div className="text-[15px] text-zinc-400">思考中…</div>
        ) : null}
        {!isStreaming && hasText && <MessageActions message={message} />}
      </div>
    </div>
  );
}
