import { useEffect, useRef, useState } from "react";
import { Check, Copy, Info } from "lucide-react";
import type { Message } from "../api/types";
import { conversationToClipboard, copyRich } from "../lib/richCopy";
import type { VerseLinkMode } from "../lib/verseLinks";

interface Props {
  title: string;
  messages: Message[];
  /** Copy-all is disabled while an answer is still streaming. */
  disabled: boolean;
  verseLinkMode: VerseLinkMode;
}

const btnBase =
  "flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors";

/** Top-right bar of the chat pane: storage notice + copy whole conversation. */
export function ConversationToolbar({
  title,
  messages,
  disabled,
  verseLinkMode,
}: Props) {
  const [copied, setCopied] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const infoRef = useRef<HTMLDivElement>(null);

  // Close the info popover on any click outside it.
  useEffect(() => {
    if (!infoOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!infoRef.current?.contains(e.target as Node)) setInfoOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [infoOpen]);

  const hasContent = messages.some((m) => m.content);

  const handleCopyAll = async () => {
    const { html, plain } = conversationToClipboard(
      title,
      messages,
      verseLinkMode,
    );
    try {
      await copyRich(html, plain);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className="flex items-center justify-end gap-1 border-b border-zinc-100 px-3 py-1.5 text-zinc-400">
      <div ref={infoRef} className="relative">
        <button
          type="button"
          onClick={() => setInfoOpen((v) => !v)}
          title="對話紀錄保存說明"
          className={`${btnBase} ${
            infoOpen
              ? "bg-zinc-100 text-zinc-700"
              : "hover:bg-zinc-100 hover:text-zinc-700"
          }`}
        >
          <Info className="h-4 w-4" />
        </button>
        {infoOpen && (
          <div className="absolute right-0 z-30 mt-1 w-72 rounded-lg border border-zinc-200 bg-white p-3 text-xs leading-relaxed text-zinc-600 shadow-lg">
            <p className="mb-1 font-medium text-zinc-800">對話紀錄保存說明</p>
            <p>
              本站不需登入，所有對話紀錄是透過您瀏覽器中的 cookie
              辨識與保存（有效期約 180 天）。
            </p>
            <p className="mt-1.5">
              若清除瀏覽器 cookie、使用無痕模式，或換用其他瀏覽器／裝置，將無法再看到先前的對話。
            </p>
            <p className="mt-1.5 font-medium text-zinc-700">
              重要的對話請使用「複製全部」自行複製並備份（例如貼到 Word 保存）。
            </p>
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={handleCopyAll}
        disabled={disabled || !hasContent}
        title="複製整個對話（含經文超連結）"
        className={`${btnBase} hover:bg-zinc-100 hover:text-zinc-700 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent`}
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-green-600" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
        {copied ? "已複製" : "複製全部"}
      </button>
    </div>
  );
}
