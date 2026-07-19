import type {
  ConversationDetail,
  ConversationSummary,
  FeedbackAction,
  UsageResponse,
} from "./types";

// BASE_URL is "/bible_tool_bot/" in both dev and prod (vite.config.ts `base`).
export const API_BASE = `${import.meta.env.BASE_URL}api`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}${body ? `: ${body}` : ""}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const listConversations = () =>
  request<ConversationSummary[]>("/conversations");

export const createConversation = () =>
  request<ConversationSummary>("/conversations", { method: "POST" });

export const getConversation = (id: string) =>
  request<ConversationDetail>(`/conversations/${encodeURIComponent(id)}`);

export const deleteConversation = (id: string) =>
  request<void>(`/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

export const getUsage = () => request<UsageResponse>("/usage");

export const sendFeedback = (
  messageId: number,
  action: FeedbackAction,
  comment?: string,
) =>
  request<void>(`/messages/${messageId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ action, comment }),
  });
