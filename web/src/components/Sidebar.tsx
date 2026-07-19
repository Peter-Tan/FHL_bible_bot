import { useEffect, useState } from "react";
import { BarChart3, BookOpen, Plus, Trash2, X } from "lucide-react";
import { getUsage } from "../api/client";
import type {
  ConversationSummary,
  UsageResponse,
  UsageScope,
} from "../api/types";
import type { VerseLinkMode } from "../lib/verseLinks";

interface Props {
  conversations: ConversationSummary[];
  currentId: string | null;
  open: boolean;
  onClose: () => void;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  verseLinkMode: VerseLinkMode;
  onVerseLinkModeChange: (mode: VerseLinkMode) => void;
}

const formatTokens = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n.toLocaleString();

const formatUsd = (n: number) =>
  `$${n.toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;

function UsageBlock({ title, scope }: { title: string; scope: UsageScope }) {
  const m = scope.month;
  const inputTotal =
    m.input_tokens + m.cache_read_tokens + m.cache_write_tokens;
  return (
    <div className="rounded-lg border border-zinc-200 p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-sm font-medium text-zinc-700">{title}</span>
        <span className="text-base font-bold text-blue-600">
          {formatUsd(m.cost_usd)}
        </span>
      </div>
      <dl className="space-y-1 text-xs text-zinc-500">
        <div className="flex justify-between">
          <dt>查詢次數</dt>
          <dd>{m.queries.toLocaleString()}</dd>
        </div>
        <div className="flex justify-between">
          <dt>輸入 tokens（含快取）</dt>
          <dd>{formatTokens(inputTotal)}</dd>
        </div>
        <div className="flex justify-between">
          <dt>輸出 tokens</dt>
          <dd>{formatTokens(m.output_tokens)}</dd>
        </div>
        <div className="flex justify-between border-t border-zinc-100 pt-1">
          <dt>歷史累計費用</dt>
          <dd>{formatUsd(scope.all_time.cost_usd)}</dd>
        </div>
      </dl>
    </div>
  );
}

/** "2026-07" → "2026年7月" */
const formatMonth = (m: string) => {
  const [y, mo] = m.split("-");
  return `${y}年${Number(mo)}月`;
};

function UsageModal({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<UsageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getUsage()
      .then(setData)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : String(e)),
      );
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-xl bg-white p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-1.5 text-base font-semibold text-zinc-800">
            <BarChart3 className="h-4 w-4 text-blue-600" />
            用量統計
          </h2>
          <button
            type="button"
            onClick={onClose}
            title="關閉"
            className="rounded p-1 text-zinc-400 hover:bg-zinc-100"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {error && <p className="py-4 text-center text-sm text-red-600">{error}</p>}
        {!error && !data && (
          <p className="py-4 text-center text-sm text-zinc-400">載入中…</p>
        )}
        {data && (
          <div className="space-y-3">
            <p className="text-xs font-medium text-zinc-500">
              本月統計（{formatMonth(data.month)}，每月 1 日重新計算）
            </p>
            <UsageBlock title="我的用量" scope={data.user} />
            <UsageBlock title="全站用量" scope={data.total} />
            <p className="text-[11px] leading-relaxed text-zinc-400">
              依 Claude Sonnet API 定價估算（美元）。自 2026 年 7 月本功能上線後開始統計。
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export function Sidebar({
  conversations,
  currentId,
  open,
  onClose,
  onSelect,
  onNew,
  onDelete,
  verseLinkMode,
  onVerseLinkModeChange,
}: Props) {
  const [showUsage, setShowUsage] = useState(false);

  return (
    <>
      {/* Mobile backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-20 bg-black/30 md:hidden"
          onClick={onClose}
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-30 flex w-64 shrink-0 transform flex-col border-r border-zinc-200 bg-zinc-50 transition-transform md:static md:z-auto md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center gap-2 p-3">
          <button
            type="button"
            onClick={onNew}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500"
          >
            <Plus className="h-4 w-4" />
            新對話
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-zinc-500 hover:bg-zinc-200 md:hidden"
            title="關閉選單"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 pb-3">
          {conversations.length === 0 && (
            <p className="px-2 py-4 text-center text-xs text-zinc-400">
              尚無對話紀錄
            </p>
          )}
          <ul className="space-y-0.5">
            {conversations.map((c) => (
              <li key={c.id}>
                <div
                  className={`group flex items-center rounded-lg text-sm ${
                    c.id === currentId
                      ? "bg-zinc-200/80 text-zinc-900"
                      : "text-zinc-600 hover:bg-zinc-100"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => onSelect(c.id)}
                    className="min-w-0 flex-1 px-2.5 py-2 text-left"
                  >
                    <span className="block truncate">{c.title}</span>
                    <span className="block text-[11px] text-zinc-400">
                      {c.updated_at.slice(0, 16)}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(c.id)}
                    title="刪除對話"
                    className="mr-1 hidden rounded p-1.5 text-zinc-400 hover:bg-zinc-200 hover:text-red-600 group-hover:block"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </nav>
        <div className="space-y-1 border-t border-zinc-200 p-2">
          <div className="flex items-center gap-2 px-2.5 py-1.5">
            <BookOpen className="h-4 w-4 shrink-0 text-zinc-500" />
            <span className="flex-1 text-sm text-zinc-600">經文連結</span>
            <div className="flex rounded-lg bg-zinc-200/70 p-0.5 text-xs">
              <button
                type="button"
                onClick={() => onVerseLinkModeChange("traditional")}
                title="連結至 bible.fhl.net 傳統閱讀頁"
                className={`rounded-md px-2 py-1 ${
                  verseLinkMode === "traditional"
                    ? "bg-white font-medium text-zinc-900 shadow-sm"
                    : "text-zinc-500 hover:text-zinc-700"
                }`}
              >
                傳統版
              </button>
              <button
                type="button"
                onClick={() => onVerseLinkModeChange("vui")}
                title="連結至 tech.fhl.net/vui 新版界面"
                className={`rounded-md px-2 py-1 ${
                  verseLinkMode === "vui"
                    ? "bg-white font-medium text-zinc-900 shadow-sm"
                    : "text-zinc-500 hover:text-zinc-700"
                }`}
              >
                新版
              </button>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowUsage(true)}
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-zinc-600 hover:bg-zinc-100"
          >
            <BarChart3 className="h-4 w-4" />
            用量統計
          </button>
        </div>
      </aside>
      {showUsage && <UsageModal onClose={() => setShowUsage(false)} />}
    </>
  );
}
