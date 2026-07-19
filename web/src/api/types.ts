export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
}

export interface Message {
  id?: number;
  role: "user" | "assistant";
  content: string;
  /** Assistant only: newline-joined tool-call log lines (display only). */
  tool_log?: string | null;
  created_at?: string;
  /** Latest good/bad vote the user gave this message, if any. */
  rating?: "good" | "bad" | null;
}

export type FeedbackAction = "copy" | "good" | "bad" | "comment";

/** Answer style: 簡潔 (default) or 詳盡. Sent with every chat request. */
export type AnswerStyle = "brief" | "comprehensive";

export interface ConversationDetail extends ConversationSummary {
  created_at: string;
  messages: Message[];
}

/** Token/cost totals aggregated from the server's usage_log table. */
export interface UsageTotals {
  queries: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: number;
}

export interface UsageScope {
  /** Totals for the current calendar month. */
  month: UsageTotals;
  /** Totals since tracking began. */
  all_time: UsageTotals;
}

export interface UsageResponse {
  /** Current calendar month, e.g. "2026-07". */
  month: string;
  /** Usage for the current cookie's user. */
  user: UsageScope;
  /** Site-wide usage across all users. */
  total: UsageScope;
}

export interface ChatDoneEvent {
  message_id: number;
  title: string;
  /** Final post-processed answer (verse citations linkified). */
  content: string;
}
