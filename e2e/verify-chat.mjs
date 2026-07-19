// Full chat e2e — COSTS MONEY (one real Claude query, ~US$0.02–0.05).
// Run before production deploys and any RAG-engine / prompt / model change.
//   node e2e/verify-chat.mjs
//   BASE_URL=... node e2e/verify-chat.mjs
//
// Covers the full pipeline: SSE contract (tool_log / text_delta / done),
// deterministic linkification of the probabilistic answer, persistence,
// and usage accounting (usage_log row with cost > 0).
const BASE = process.env.BASE_URL || "http://127.0.0.1:7861/bible_bot";
const QUESTION = "約翰福音3:16是什麼意思？請簡短回答。";

let failed = 0;
const check = (name, ok, extra = "") => {
  console.log(`${ok ? "PASS" : "FAIL"} — ${name}${extra ? ` (${extra})` : ""}`);
  if (!ok) failed++;
};

// session
const health = await fetch(`${BASE}/api/health`);
const cookie = (health.headers.get("set-cookie") || "").split(";")[0];
const call = (path, init = {}) =>
  fetch(`${BASE}/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", cookie, ...(init.headers || {}) },
  });

const usageBefore = await (await call("/usage")).json();
const conv = await (await call("/conversations", { method: "POST" })).json();

// --- stream the chat ---
console.log(`asking: ${QUESTION}  (this consumes real tokens)`);
const t0 = Date.now();
const res = await call("/chat", {
  method: "POST",
  body: JSON.stringify({ conversation_id: conv.id, message: QUESTION, style: "brief" }),
});
check("chat responds 200", res.status === 200);
check("content-type is SSE", (res.headers.get("content-type") || "").includes("text/event-stream"));

// Parse SSE events from the body.
const events = [];
let buf = "";
const decoder = new TextDecoder();
for await (const chunk of res.body) {
  buf += decoder.decode(chunk, { stream: true });
  let idx;
  while ((idx = buf.indexOf("\n\n")) !== -1) {
    const block = buf.slice(0, idx);
    buf = buf.slice(idx + 2);
    const ev = /^event: (.+)$/m.exec(block)?.[1];
    const data = /^data: (.+)$/m.exec(block)?.[1];
    if (ev) events.push({ event: ev, data: data ? JSON.parse(data) : null });
  }
}
const secs = ((Date.now() - t0) / 1000).toFixed(1);

const types = new Set(events.map((e) => e.event));
check("received tool_log events", types.has("tool_log"), `${events.filter(e => e.event === "tool_log").length} lines`);
check("received text_delta events", types.has("text_delta"));
check("no error event", !types.has("error"), JSON.stringify(events.find(e => e.event === "error")?.data ?? ""));
const done = events.find((e) => e.event === "done")?.data;
check("received done event", !!done, `${secs}s`);

if (done) {
  check("done carries message_id", Number.isInteger(done.message_id));
  check("done title set from question", typeof done.title === "string" && done.title.length > 0, done.title);
  // Deterministic linkifier over the probabilistic answer: a question about
  // 約翰福音 should yield at least one read.php link for book 約.
  const linked = /\]\(https:\/\/bible\.fhl\.net\/new\/read\.php\?[^)]*chineses=/.test(done.content);
  check("answer contains deterministic verse link(s)", linked);
  console.log(`answer length: ${done.content.length} chars`);
}

// --- persistence ---
const detail = await (await call(`/conversations/${conv.id}`)).json();
const assistant = detail.messages?.find((m) => m.role === "assistant");
check("turn persisted (assistant message saved)", !!assistant && assistant.content.length > 0);
check("tool_log persisted", typeof assistant?.tool_log === "string" && assistant.tool_log.length > 0);

// --- usage accounting ---
const usageAfter = await (await call("/usage")).json();
const dQueries = usageAfter.user.month.queries - usageBefore.user.month.queries;
const dCost = usageAfter.user.month.cost_usd - usageBefore.user.month.cost_usd;
check("usage_log gained one query", dQueries === 1, `Δqueries=${dQueries}`);
check("cost recorded > 0", dCost > 0, `Δcost=$${dCost.toFixed(6)}`);
check("output tokens recorded > 0", usageAfter.user.month.output_tokens > usageBefore.user.month.output_tokens);

// cleanup
await call(`/conversations/${conv.id}`, { method: "DELETE" });

process.exit(failed ? 1 : 0);
