# CLAUDE.md

## Commit message convention

Prefix every commit subject with its category (same convention as the
fhl-bible-vui repo):

- `UI:` — new features and UI/UX changes（新功能、介面調整）
- `bug:` — bug fixes（修正錯誤）
- `other:` — docs, refactors, tooling, data, tests-only changes（文件、重構、工具）

Subject line 中文為主; the body explains what changed and why.

## Before committing

1. `cd web && npm run build` — typecheck + bundle must pass.
2. `.venv/bin/python -m compileall -q server scripts` — backend must compile.
3. `node e2e/verify-smoke.mjs` — free smoke suite must pass against the
   running server (127.0.0.1:7861).
4. For backend/engine/prompt changes, also `node e2e/verify-chat.mjs`
   (costs one real Claude query) — see CODEBASE.md → Testing & release checklist.

## Never commit

- `.env` (Anthropic API key), `logs/` (real user conversations + chat.db),
  `*.txt` personal notes. All are gitignored — do not force-add them.

## Docs

- `README.md` — product overview, quick start, config cheat-sheet.
- `CODEBASE.md` — architecture, per-file guide, deterministic-vs-probabilistic
  map, testing/release checklist. **Keep it in sync when structure changes.**

## Engine versioning

Never modify `scripts/claude_bible_rag.py` / `_v2` / `_v3` — they are rollback
backups (v3 still powers the legacy Gradio app). To change engine behavior,
copy the current engine to `_vN+1`, edit the copy, then register it in
`ENGINE_MODULES` in `server/chat.py`.

**Which engine runs is config, not code**: `FHL_ENGINE` in `.env` selects it
(unset → `v6`, production). Only the selected module is imported, so an engine
needing infrastructure the box lacks (v8 needs a local vLLM server) is inert
where it is not selected. Never hardcode the import — the cloud deployment and
the local-GPU box both track `main`, and differ only by that one `.env` line.
