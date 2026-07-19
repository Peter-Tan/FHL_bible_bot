import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, Menu, X } from "lucide-react";
import fhlLogo from "./FHLLOGO.webp";
import {
  createConversation,
  deleteConversation,
  listConversations,
} from "./api/client";
import type { ConversationSummary } from "./api/types";
import { stopLiveStream } from "./lib/liveStreams";
import {
  loadVerseLinkMode,
  saveVerseLinkMode,
  type VerseLinkMode,
} from "./lib/verseLinks";
import { useConversation } from "./hooks/useConversation";
import type { AnswerStyle } from "./api/types";
import { ChatInput } from "./components/ChatInput";
import { ChatMessage } from "./components/ChatMessage";
import { Sidebar } from "./components/Sidebar";

const STYLE_STORAGE_KEY = "fhl_answer_style";

function loadStyle(): AnswerStyle {
  const saved = localStorage.getItem(STYLE_STORAGE_KEY);
  return saved === "comprehensive" ? "comprehensive" : "brief";
}

export default function App() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [appError, setAppError] = useState<string | null>(null);
  const [answerStyle, setAnswerStyle] = useState<AnswerStyle>(loadStyle);
  const [verseLinkMode, setVerseLinkMode] =
    useState<VerseLinkMode>(loadVerseLinkMode);

  const handleStyleChange = (s: AnswerStyle) => {
    setAnswerStyle(s);
    localStorage.setItem(STYLE_STORAGE_KEY, s);
  };

  const handleVerseLinkModeChange = (m: VerseLinkMode) => {
    setVerseLinkMode(m);
    saveVerseLinkMode(m);
  };

  const handleTitleChange = useCallback((id: string, title: string) => {
    setConversations((cs) =>
      cs.map((c) => (c.id === id ? { ...c, title } : c)),
    );
  }, []);

  const { messages, isStreaming, isLoading, error, send, stop, clearError } =
    useConversation(currentId, handleTitleChange);

  // Initial load: fetch sidebar, create a first conversation if none exist.
  useEffect(() => {
    (async () => {
      try {
        let list = await listConversations();
        if (list.length === 0) {
          list = [await createConversation()];
        }
        setConversations(list);
        setCurrentId(list[0].id);
      } catch (e: unknown) {
        setAppError(
          `無法連線到伺服器：${e instanceof Error ? e.message : String(e)}`,
        );
      }
    })();
  }, []);

  const handleNew = async () => {
    try {
      const c = await createConversation();
      setConversations((cs) => [c, ...cs]);
      setCurrentId(c.id);
      setSidebarOpen(false);
    } catch (e: unknown) {
      setAppError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm("確定要刪除這個對話嗎？")) return;
    try {
      stopLiveStream(id);
      await deleteConversation(id);
      const remaining = conversations.filter((c) => c.id !== id);
      setConversations(remaining);
      if (currentId === id) {
        if (remaining.length > 0) {
          setCurrentId(remaining[0].id);
        } else {
          const c = await createConversation();
          setConversations([c]);
          setCurrentId(c.id);
        }
      }
    } catch (e: unknown) {
      setAppError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleSelect = (id: string) => {
    setCurrentId(id);
    setSidebarOpen(false);
  };

  // Auto-scroll, pinned to bottom unless the user has scrolled up.
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };
  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const toastError = error ?? appError;

  return (
    <div className="flex h-dvh flex-col bg-white text-zinc-900">
      <header className="flex items-center gap-2 border-b border-zinc-200 px-3 py-2.5">
        <button
          type="button"
          onClick={() => setSidebarOpen(true)}
          className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-100 md:hidden"
          title="開啟選單"
        >
          <Menu className="h-5 w-5" />
        </button>
        <img src={fhlLogo} alt="信望愛" className="h-7 w-7 rounded" />
        <h1 className="leading-tight">
          <span className="block text-lg font-bold">信望愛 AI 聖經助手</span>
          <span className="block text-xs font-normal text-zinc-400">
            Claude × FHL Bible Tools
          </span>
        </h1>
      </header>

      <div className="flex min-h-0 flex-1">
        <Sidebar
          conversations={conversations}
          currentId={currentId}
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          onSelect={handleSelect}
          onNew={handleNew}
          onDelete={handleDelete}
          verseLinkMode={verseLinkMode}
          onVerseLinkModeChange={handleVerseLinkModeChange}
        />

        <main className="flex min-w-0 flex-1 flex-col">
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto px-4 py-4"
          >
            <div className="mx-auto max-w-4xl space-y-4">
              {isLoading && (
                <p className="py-8 text-center text-sm text-zinc-400">
                  載入中…
                </p>
              )}
              {!isLoading && messages.length === 0 && (
                <div className="py-14 text-center">
                  <BookOpen className="mx-auto h-10 w-10 text-zinc-300" />
                  <p className="mt-4 text-base text-zinc-600">
                    這是一個基於信望愛聖經工具的 AI 聖經助手。
                  </p>
                  <p className="mt-1 text-[15px] text-zinc-500">
                    你可以問任何聖經相關問題，例如：「約翰福音3:16是什麼意思？」
                  </p>
                </div>
              )}
              {messages.map((m, i) => (
                <ChatMessage
                  key={m.id ?? `local-${i}`}
                  message={m}
                  verseLinkMode={verseLinkMode}
                  isStreaming={
                    isStreaming &&
                    i === messages.length - 1 &&
                    m.role === "assistant"
                  }
                />
              ))}
            </div>
          </div>

          <ChatInput
            disabled={currentId === null}
            isStreaming={isStreaming}
            style={answerStyle}
            onStyleChange={handleStyleChange}
            onSend={(text) => send(text, answerStyle)}
            onStop={stop}
          />
        </main>
      </div>

      {toastError && (
        <div className="fixed bottom-20 left-1/2 z-40 flex -translate-x-1/2 items-center gap-2 rounded-lg bg-red-600 px-4 py-2.5 text-sm text-white shadow-lg">
          <span className="max-w-md truncate">{toastError}</span>
          <button
            type="button"
            onClick={() => {
              clearError();
              setAppError(null);
            }}
            title="關閉"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  );
}
