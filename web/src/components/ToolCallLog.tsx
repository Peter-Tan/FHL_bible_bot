import { useState } from "react";
import { ChevronRight, Wrench } from "lucide-react";

interface Props {
  log: string;
  /** Open while the query is still running and no answer text has arrived. */
  autoOpen: boolean;
}

export function ToolCallLog({ log, autoOpen }: Props) {
  // Until the user toggles manually, follow autoOpen (open during tool phase,
  // collapse once the answer starts streaming).
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const open = userOpen ?? autoOpen;
  const lines = log.split("\n").filter((l) => l.trim() !== "");
  const callCount = lines.filter((l) => l.includes("🔧")).length || lines.length;

  return (
    <div className="mb-2 rounded-lg border border-zinc-200 bg-zinc-50 text-xs">
      <button
        type="button"
        onClick={() => setUserOpen(!open)}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left font-medium text-zinc-600 hover:text-zinc-900"
      >
        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <Wrench className="h-3.5 w-3.5 shrink-0" />
        <span>工具呼叫（{callCount}）</span>
      </button>
      {open && (
        <pre className="overflow-x-auto border-t border-zinc-200 px-3 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap text-zinc-600">
          {log}
        </pre>
      )}
    </div>
  );
}
