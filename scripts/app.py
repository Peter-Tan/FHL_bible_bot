from __future__ import annotations

"""
app.py — Gradio Chat UI for Bible RAG (Claude backend)
=======================================================
Multi-user: each browser connection gets its own isolated chat history
stored in logs/user_<uuid>.json.  Sessions survive page refreshes within
the same Gradio connection but are independent across users.
"""

import os
import sys
import json
import uuid
import queue
import threading
import time
from pathlib import Path
from datetime import datetime

os.environ["PYTHONUTF8"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gradio as gr
#from claude_bible_rag import bible_query #1 (bacckup)
#from claude_bible_rag_v2 import bible_query  # v2 (links)
from claude_bible_rag_v3 import bible_query  # v3 (parallel tool execution)
from fhl_tools import ALL_TOOLS

HISTORY_DIR = Path(__file__).resolve().parent.parent / "logs"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

CSS = """
#chatbot { height: 75vh !important; }
#chatbot .message { font-size: 13px !important; }
#chatbot .message p, #chatbot .message li { font-size: 13px !important; }
#chatbot .message code { font-size: 12px !important; }
#chatbot .message pre { font-size: 12px !important; }
"""


# ─── Per-user session (one instance per browser connection) ──────────────────

class UserSession:
    def __init__(self, session_id: str | None = None):
        if session_id and (HISTORY_DIR / f"user_{session_id}.json").exists():
            self.user_id = session_id  # returning user — load existing file
        else:
            self.user_id = str(uuid.uuid4())[:8]  # new user
        self.sessions: list[dict] = []
        self.current_idx: int = -1
        self._lock = threading.Lock()
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _path(self) -> Path:
        return HISTORY_DIR / f"user_{self.user_id}.json"

    def _load(self):
        p = self._path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                self.sessions = data.get("sessions", [])
                self.current_idx = data.get("current_idx", -1)
                if self.current_idx >= len(self.sessions):
                    self.current_idx = len(self.sessions) - 1
            except (json.JSONDecodeError, KeyError):
                self.sessions = []
                self.current_idx = -1
        if not self.sessions:
            self._add_session()

    def save(self):
        with self._lock:
            self._path().write_text(
                json.dumps({"sessions": self.sessions, "current_idx": self.current_idx},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # ── session operations ────────────────────────────────────────────────────

    def _add_session(self):
        self.sessions.append({
            "title": "New chat",
            "messages": [],
            "api_history": [],
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        self.current_idx = len(self.sessions) - 1

    def new_session(self):
        self._add_session()
        self.save()

    def get_current(self) -> dict | None:
        if 0 <= self.current_idx < len(self.sessions):
            return self.sessions[self.current_idx]
        return None

    def get_current_messages(self) -> list:
        s = self.get_current()
        return s["messages"] if s else []

    def get_current_api_history(self) -> list:
        s = self.get_current()
        return s.get("api_history", []) if s else []

    def append_turn(self, user_text: str, assistant_display: str, assistant_clean: str):
        s = self.get_current()
        if not s:
            return
        s["messages"].append({"role": "user", "content": user_text})
        s["messages"].append({"role": "assistant", "content": assistant_display})
        s["api_history"].append({"role": "user", "content": user_text})
        s["api_history"].append({"role": "assistant", "content": assistant_clean})
        if s["title"] == "New chat":
            s["title"] = user_text[:30]
        self.save()

    def get_sidebar_labels(self) -> list[str]:
        labels = []
        for i, s in enumerate(self.sessions):
            prefix = ">> " if i == self.current_idx else "   "
            labels.append(f"{prefix}{s['created']}  {s['title']}")
        return labels

    def switch_to(self, idx: int):
        if 0 <= idx < len(self.sessions):
            self.current_idx = idx
            self.save()

    def delete_current(self):
        if 0 <= self.current_idx < len(self.sessions):
            self.sessions.pop(self.current_idx)
            if self.sessions:
                self.current_idx = min(self.current_idx, len(self.sessions) - 1)
            else:
                self.current_idx = -1
            self.save()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _format_log_block(log_lines: list[str]) -> str:
    if not log_lines:
        return ""
    escaped = "\n".join(log_lines)
    tool_count = len([l for l in log_lines if "🔧" in l])
    return f"**🔧 Tool calls** ({tool_count} calls)\n```\n{escaped}\n```"


def _sidebar_choices(state: UserSession):
    labels = state.get_sidebar_labels()
    idx = state.current_idx
    return gr.update(choices=labels, value=labels[idx] if 0 <= idx < len(labels) else None)


def _to_tuples(messages: list) -> list:
    """Convert [{role, content},...] to [(user, assistant)] tuples for gr.Chatbot."""
    pairs = []
    i = 0
    while i < len(messages):
        if messages[i]["role"] == "user":
            user = messages[i]["content"]
            asst = messages[i + 1]["content"] if i + 1 < len(messages) else None
            pairs.append((user, asst))
            i += 2
        else:
            i += 1
    return pairs


# ─── Gradio callbacks (all take/return state) ────────────────────────────────

COOKIE_NAME = "fhl_session_id"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days


def init_user(request: gr.Request):
    session_id = request.cookies.get(COOKIE_NAME)
    state = UserSession(session_id=session_id)
    returning = session_id == state.user_id
    label = f"歡迎回來！已載入 {len(state.sessions)} 個對話。" if returning else ""
    return (
        _to_tuples(state.get_current_messages()),
        _sidebar_choices(state),
        state,
        state.user_id,  # pass session ID to JS for cookie setting
        label,
    )


def respond(text: str, state: UserSession):
    if state is None:
        state = UserSession()
    if not text.strip():
        yield _to_tuples(state.get_current_messages()), _sidebar_choices(state), "", state
        return

    log_lines: list[str] = []
    log_lock = threading.Lock()
    result_holder: list[str | None] = [None]
    error_holder: list[str | None] = [None]
    done_event = threading.Event()
    stream_queue: queue.Queue[str] = queue.Queue()

    def on_log(line: str):
        with log_lock:
            log_lines.append(line)

    def on_stream(chunk: str):
        stream_queue.put(chunk)

    def run_query():
        try:
            api_history = state.get_current_api_history()
            answer = bible_query(
                user_question=text,
                tools=ALL_TOOLS,
                history=api_history if api_history else None,
                verbose=False,
                log_callback=on_log,
                stream_callback=on_stream,
            )
            result_holder[0] = answer
        except Exception as e:
            error_holder[0] = str(e)
        finally:
            done_event.set()

    display_msgs = state.get_current_messages().copy()
    display_msgs.append({"role": "user", "content": text})
    display_msgs.append({"role": "assistant", "content": "⏳ Calling Claude..."})
    yield _to_tuples(display_msgs), _sidebar_choices(state), "", state

    worker = threading.Thread(target=run_query, daemon=True)
    worker.start()

    last_log_count = 0
    streamed_answer = ""
    while not done_event.is_set():
        time.sleep(0.1)
        changed = False

        # Drain streaming text chunks
        chunks = []
        while not stream_queue.empty():
            try:
                chunks.append(stream_queue.get_nowait())
            except queue.Empty:
                break
        if chunks:
            streamed_answer += "".join(chunks)
            tool_log = _format_log_block(log_lines)
            content = (tool_log + "\n\n---\n\n" + streamed_answer) if tool_log else streamed_answer
            display_msgs[-1] = {"role": "assistant", "content": content}
            changed = True

        # Update tool log if new lines arrived
        if not changed:
            with log_lock:
                current_count = len(log_lines)
                if current_count > last_log_count:
                    last_log_count = current_count
                    live_log = _format_log_block(list(log_lines))
                    content = live_log if not streamed_answer else (live_log + "\n\n---\n\n" + streamed_answer)
                    display_msgs[-1] = {"role": "assistant", "content": content}
                    changed = True

        if changed:
            yield _to_tuples(display_msgs), _sidebar_choices(state), "", state

    worker.join()

    if error_holder[0]:
        assistant_display = f"❌ Error: {error_holder[0]}"
        assistant_clean = assistant_display
    else:
        answer = result_holder[0] or ""
        tool_log = _format_log_block(log_lines)
        assistant_display = tool_log + "\n\n---\n\n" + answer if tool_log else answer
        assistant_clean = answer

    state.append_turn(text, assistant_display, assistant_clean)
    yield _to_tuples(state.get_current_messages()), _sidebar_choices(state), "", state


def new_chat(state: UserSession):
    if state is None:
        state = UserSession()
    state.new_session()
    return _to_tuples(state.get_current_messages()), _sidebar_choices(state), state


def switch_chat(selection: str | None, state: UserSession):
    if state is None:
        state = UserSession()
    if selection is None:
        return _to_tuples(state.get_current_messages()), _sidebar_choices(state), state
    labels = state.get_sidebar_labels()
    try:
        idx = labels.index(selection)
    except ValueError:
        return _to_tuples(state.get_current_messages()), _sidebar_choices(state), state
    state.switch_to(idx)
    return _to_tuples(state.get_current_messages()), _sidebar_choices(state), state


def delete_chat(state: UserSession):
    if state is None:
        state = UserSession()
    state.delete_current()
    if not state.sessions:
        state.new_session()
    return _to_tuples(state.get_current_messages()), _sidebar_choices(state), state


# ─── UI layout ───────────────────────────────────────────────────────────────

with gr.Blocks(title="信望愛 AI 聖經助手", css=CSS, theme=gr.themes.Soft()) as demo:
    gr.Markdown("## 📖 信望愛 AI 聖經助手 — Claude × FHL Bible Tools")

    state = gr.State(None)
    session_id_box = gr.Textbox(visible=False)  # holds session ID for JS cookie setter

    with gr.Row():
        with gr.Column(scale=1, min_width=220):
            gr.Markdown("### Chat History")
            welcome_label = gr.Markdown("")
            new_chat_btn = gr.Button("+ New Chat", variant="primary", size="sm")
            history_list = gr.Radio(choices=[], label="", show_label=False)
            delete_btn = gr.Button("🗑️ Delete Chat", variant="secondary", size="sm")

        with gr.Column(scale=4):
            chatbot = gr.Chatbot(value=[], label="", elem_id="chatbot")
            msg_input = gr.Textbox(
                placeholder="問一個聖經問題... (e.g. 約翰福音3:16是什麼意思？)",
                show_label=False,
                lines=1,
            )
            submit_btn = gr.Button("送出", variant="primary")

    # Initialize per-user state on page load, reading cookie if present.
    # .then() runs JS to set the cookie — <script> tags inside gr.HTML() are
    # never executed by the browser (React renders via innerHTML which drops scripts).
    demo.load(
        fn=init_user,
        outputs=[chatbot, history_list, state, session_id_box, welcome_label],
    ).then(
        fn=None,
        inputs=[session_id_box],
        js=(
            f"(sid) => {{"
            f" document.cookie = '{COOKIE_NAME}=' + sid"
            f" + '; path=/; max-age={COOKIE_MAX_AGE}; SameSite=Lax';"
            f" }}"
        ),
    )

    msg_input.submit(
        fn=respond,
        inputs=[msg_input, state],
        outputs=[chatbot, history_list, msg_input, state],
    )
    submit_btn.click(
        fn=respond,
        inputs=[msg_input, state],
        outputs=[chatbot, history_list, msg_input, state],
    )
    new_chat_btn.click(fn=new_chat, inputs=[state], outputs=[chatbot, history_list, state])
    delete_btn.click(fn=delete_chat, inputs=[state], outputs=[chatbot, history_list, state])
    history_list.change(fn=switch_chat, inputs=[history_list, state], outputs=[chatbot, history_list, state])


if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, root_path="/bible_tool_bot")
