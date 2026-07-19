// Smoke suite — FREE (no LLM call). Run before every commit.
//   node e2e/verify-smoke.mjs
//   BASE_URL=http://127.0.0.1:7861/bible_bot node e2e/verify-smoke.mjs
//
// Covers (all deterministic code paths):
// 1. /api/health responds ok
// 2. Session cookie is issued and sticks
// 3. Conversation CRUD round-trip (create → list → detail → delete → 404)
// 4. Cross-user isolation (a fresh cookie can't see another user's conversation)
// 5. /api/usage shape (month label + user/total × month/all_time)
// 6. Chat input validation runs BEFORE any LLM cost (empty msg 400,
//    bad style 400, foreign conversation 404)
// 7. SPA serves and references a live JS bundle
import assert from "node:assert";

const BASE = process.env.BASE_URL || "http://127.0.0.1:7861/bible_bot";
let failed = 0;
const check = (name, ok, extra = "") => {
  console.log(`${ok ? "PASS" : "FAIL"} — ${name}${extra ? ` (${extra})` : ""}`);
  if (!ok) failed++;
};

// Minimal cookie jar: one session = one cookie string.
async function client() {
  const res = await fetch(`${BASE}/api/health`);
  const setCookie = res.headers.get("set-cookie") || "";
  const cookie = setCookie.split(";")[0]; // "fhl_session=..."
  const call = (path, init = {}) =>
    fetch(`${BASE}/api${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        cookie,
        ...(init.headers || {}),
      },
    });
  return { call, cookie, healthStatus: res.status };
}

// --- 1. health ---
const userA = await client();
check("health responds 200", userA.healthStatus === 200);
check("session cookie issued", userA.cookie.startsWith("fhl_session="));

// --- 2/3. conversation CRUD round-trip ---
const created = await (await userA.call("/conversations", { method: "POST" })).json();
check("create conversation returns id", typeof created.id === "string" && created.id.length > 0);

const list = await (await userA.call("/conversations")).json();
check("conversation appears in list", list.some((c) => c.id === created.id));

const detail = await (await userA.call(`/conversations/${created.id}`)).json();
check("conversation detail has messages array", Array.isArray(detail.messages));

// --- 4. cross-user isolation ---
const userB = await client();
check("two clients get distinct cookies", userA.cookie !== userB.cookie);
const foreign = await userB.call(`/conversations/${created.id}`);
check("other user's conversation is 404", foreign.status === 404);

// --- 6. chat validation (no tokens are ever consumed by these) ---
const emptyMsg = await userA.call("/chat", {
  method: "POST",
  body: JSON.stringify({ conversation_id: created.id, message: "  ", style: "brief" }),
});
check("empty message → 400", emptyMsg.status === 400);

const badStyle = await userA.call("/chat", {
  method: "POST",
  body: JSON.stringify({ conversation_id: created.id, message: "hi", style: "verbose" }),
});
check("invalid style → 400", badStyle.status === 400);

const foreignChat = await userB.call("/chat", {
  method: "POST",
  body: JSON.stringify({ conversation_id: created.id, message: "hi", style: "brief" }),
});
check("chat on foreign conversation → 404", foreignChat.status === 404);

// --- delete + gone ---
const del = await userA.call(`/conversations/${created.id}`, { method: "DELETE" });
check("delete conversation → 204", del.status === 204);
const gone = await userA.call(`/conversations/${created.id}`);
check("deleted conversation → 404", gone.status === 404);

// --- 5. usage endpoint shape ---
const usage = await (await userA.call("/usage")).json();
check("usage has month label", /^\d{4}-\d{2}$/.test(usage.month));
const shapeOk = ["user", "total"].every((scope) =>
  ["month", "all_time"].every(
    (period) =>
      usage[scope] &&
      typeof usage[scope][period]?.cost_usd === "number" &&
      typeof usage[scope][period]?.queries === "number",
  ),
);
check("usage has user/total × month/all_time totals", shapeOk);
check(
  "site month total ≤ all-time total",
  usage.total.month.cost_usd <= usage.total.all_time.cost_usd + 1e-9,
);

// --- 7. SPA serves current bundle ---
const html = await (await fetch(`${BASE}/`)).text();
const bundleMatch = html.match(/assets\/(index-[\w-]+\.js)/);
check("SPA HTML references a JS bundle", !!bundleMatch, bundleMatch?.[1] || "no match");
if (bundleMatch) {
  const js = await fetch(`${BASE}/assets/${bundleMatch[1]}`);
  check("JS bundle is served", js.status === 200);
}

assert.ok(true); // keep node:assert imported for future use
process.exit(failed ? 1 : 0);
