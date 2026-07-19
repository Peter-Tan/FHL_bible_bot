import { useEffect, useRef, useState } from "react";
import { SendHorizontal, Square } from "lucide-react";
import type { AnswerStyle } from "../api/types";

interface Props {
  disabled: boolean;
  isStreaming: boolean;
  style: AnswerStyle;
  onStyleChange: (style: AnswerStyle) => void;
  onSend: (text: string) => void;
  onStop: () => void;
}

const STYLE_OPTIONS: { value: AnswerStyle; label: string; title: string }[] = [
  { value: "brief", label: "簡潔", title: "精簡扼要的回答（預設）" },
  { value: "comprehensive", label: "詳盡", title: "包含原文分析與背景的完整回答" },
];

export function ChatInput({
  disabled,
  isStreaming,
  style,
  onStyleChange,
  onSend,
  onStop,
}: Props) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled || isStreaming) return;
    onSend(trimmed);
    setText("");
  };

  return (
    <div className="border-t border-zinc-200 bg-white p-3">
      <div className="mx-auto flex max-w-4xl items-end gap-2">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // isComposing guard: don't submit while a CJK IME is composing
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder="問一個聖經問題…（例：約翰福音3:16是什麼意思？）"
          disabled={disabled}
          className="max-h-40 flex-1 resize-none rounded-xl border border-zinc-300 px-3.5 py-2.5 text-[15px] leading-relaxed outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-zinc-50"
        />
        <div
          className="flex h-10 shrink-0 items-center rounded-xl border border-zinc-300 bg-zinc-50 p-0.5"
          role="radiogroup"
          aria-label="回答風格"
        >
          {STYLE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={style === opt.value}
              title={opt.title}
              disabled={isStreaming}
              onClick={() => onStyleChange(opt.value)}
              className={`rounded-[10px] px-2.5 py-1.5 text-[13px] transition-colors ${
                style === opt.value
                  ? "bg-white font-medium text-blue-700 shadow-sm"
                  : "text-zinc-500 hover:text-zinc-700"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        {isStreaming ? (
          <button
            type="button"
            onClick={onStop}
            title="停止產生"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-zinc-800 text-white hover:bg-zinc-700"
          >
            <Square className="h-4 w-4 fill-current" />
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={disabled || text.trim() === ""}
            title="送出"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white hover:bg-blue-500 disabled:bg-zinc-300"
          >
            <SendHorizontal className="h-4 w-4" />
          </button>
        )}
      </div>
      <p className="mx-auto mt-1.5 max-w-4xl text-center text-xs text-zinc-400">
        Enter 送出，Shift+Enter 換行 · AI 回答僅供參考，請以聖經原文為準
      </p>
    </div>
  );
}
