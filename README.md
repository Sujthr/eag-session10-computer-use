# Session 10 — Computer-Use Desktop Agent

A Windows desktop automation agent that drives real applications using a **five-layer cascade** architecture. Built on `cua-driver` for UIA/Win32 perception, with a multi-provider LLM client (Gemini → Groq → Cerebras → NVIDIA → GitHub → OpenRouter → OpenAI) and a live web dashboard.

---

## Architecture: Five-Layer Cascade

The agent always tries the cheapest layer first and escalates only when needed.

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1 — Extract                             Cost: $0      │
│  Read AX tree / clipboard / file directly. No LLM.          │
└────────────────────────┬────────────────────────────────────┘
                         │ tree is empty or goal needs action
┌────────────────────────▼────────────────────────────────────┐
│  Layer 2a — Deterministic                      Cost: $0      │
│  Pre-programmed hotkey / key-sequence recipes. No LLM.       │
│  Used for Calculator, well-known app shortcuts.              │
└────────────────────────┬────────────────────────────────────┘
                         │ no known hotkey recipe
┌────────────────────────▼────────────────────────────────────┐
│  Layer 2b — A11y Tree                          Cost: cents   │
│  AX tree markdown → cheap text LLM → element_index action.  │
│  Workhorse layer. Used for most text-based UI.               │
└────────────────────────┬────────────────────────────────────┘
                         │ AX tree empty or target missing
┌────────────────────────▼────────────────────────────────────┐
│  Electron / CDP                                Cost: cents   │
│  Relaunch with --remote-debugging-port, drive via WebSocket. │
│  Used for VS Code, Slack, Discord (AXWebArea only).          │
└────────────────────────┬────────────────────────────────────┘
                         │ canvas-rendered / no AX at all
┌────────────────────────▼────────────────────────────────────┐
│  Layer 3 — Vision                              Cost: dollars │
│  screenshot → multimodal LLM → best action.                  │
│  Last resort. Canvas apps, games, pixel-painted UIs.         │
└─────────────────────────────────────────────────────────────┘
```

---

## Six Tasks

| # | Task | Layer | App closed after? | File saved |
|---|------|-------|-------------------|------------|
| 1 | Calculator arithmetic | 2a | ✓ | — |
| 2 | VS Code Python script | Electron/CDP | ✓ | `hello_agent_<ts>.py` |
| 3 | 2048 browser game | 3 vision | ✓ | — |
| 4 | Notepad meeting notes | 2b | ✓ | `meeting_notes_<ts>.txt` |
| 5 | Email draft + LLM verify | 2b | ✓ | `email_draft_<ts>.txt` |
| 6 | Multi-app Calculator→Notepad | 2a+2b | ✓ (both) | `expense_report_<ts>.txt` |

Every file-producing task writes a **timestamped filename** (`YYYYMMDD_HHMMSS`) so re-runs never overwrite previous output. Every app is closed automatically at task completion.

---

### Task 1 — Calculator Arithmetic (Layer 2a)

Evaluates an arithmetic expression in Windows Calculator using deterministic key presses. Reads the result from the AX tree (no LLM, no vision). Verifies against Python's own `ast`-based evaluator.

### Task 2 — VS Code Python Script (Electron/CDP)

Connects to VS Code via Chrome DevTools Protocol (`--remote-debugging-port=9222`). Writes a Python script to disk via the integrated terminal, opens the file in the editor, runs it, and captures stdout. Verified by running the script with `subprocess`.

### Task 3 — 2048 Browser Game (Layer 3 Vision)

Launches Chrome in an **isolated profile** (so your existing Chrome windows are never closed). Takes a screenshot of the canvas-rendered game, sends it to a multimodal LLM to get the best move direction, and presses the arrow key. Repeats for N moves. Only task that uses vision.

### Task 4 — Notepad Meeting Notes (Layer 2b)

Opens Notepad, asks a cheap text LLM to type a structured meeting notes template (title, date, attendees, agenda, action items). Saves via clipboard capture (`Ctrl+A → Ctrl+C → write to disk`) — bypasses XAML/UWP Notepad's save dialog entirely.

### Task 5 — Email Draft + Verification (Layer 2b)

Same approach as Task 4 but adds a second LLM pass that reviews the draft and checks all required fields are present (To:, Subject:, Body:, apology, new deadline). Returns `verified: true/false` and a list of any missing fields.

### Task 6 — Multi-App Workflow (Layer 2a + 2b)

Chains two apps: Calculator computes a budget figure (`157 × 24`), copies the result to the clipboard, then Notepad writes a formatted expense report embedding that number. Verifies the computed value appears in the final document.

---

## Web Dashboard

```bash
python main.py --dashboard
```

Live dashboard at `http://127.0.0.1:8765` with:
- Six task cards (click to run)
- Server-sent event log stream
- Status polling every 3 seconds
- `/api/run/<task>` POST endpoints
- `/api/reset` to clear stuck state

---

## CLI

```bash
python main.py                          # interactive menu (all 6 tasks)
python main.py --task calculator        # run directly
python main.py --task vscode
python main.py --task browser_game
python main.py --task notepad
python main.py --task email_draft
python main.py --task multiapp
python main.py --task all               # run all six in sequence
python main.py --dashboard              # web dashboard only
python main.py --dashboard --no-browser # dashboard without auto-opening browser
```

---

## Repo Structure

```
.
├── computer_use/
│   ├── config.py             # env vars, provider order, key rotation
│   ├── driver.py             # cua-driver wrapper + Windows-native fallback
│   ├── llm_client.py         # multi-provider LLM with provider fallback
│   ├── windows_native.py     # pywin32/ctypes input + close_app utility
│   ├── recording.py          # session recording / action log
│   ├── layers/
│   │   ├── layer1_extract.py
│   │   ├── layer2a_deterministic.py
│   │   ├── layer2b_ally.py
│   │   └── layer3_vision.py
│   └── tasks/
│       ├── task_calculator.py
│       ├── task_vscode.py
│       ├── task_browser_game.py
│       ├── task_notepad.py
│       ├── task_email_draft.py
│       └── task_multiapp.py
├── dashboard/
│   ├── app.py                # FastAPI + SSE dashboard backend
│   ├── static/app.js
│   └── templates/index.html
├── recordings/               # timestamped output files (gitignored)
├── requirements.txt
├── main.py                   # CLI + interactive launcher
└── .env                      # API keys (never committed)
```

---

## Setup

### Prerequisites

```bash
# cua-driver — Windows UIA/Win32 automation binary
# Download from course materials or:
cargo install cua-driver

# Python dependencies
pip install -r requirements.txt
```

### Environment variables (`.env`)

```
GEMINI_API_KEY=...
GEMINI_API_KEY_1=...   # up to _5 for round-robin rotation
GROQ_API_KEY=...
CEREBRAS_API_KEY=...
NVIDIA_API_KEY=...
GITHUB_ACCESS_TOKEN=...
OPENROUTER_API_KEY=...
OPENAI_API_KEY=...     # paid, last resort only
```

### Quick start

```bash
# Start cua-driver daemon (once per session)
cua-driver serve &

# Interactive launcher
python main.py

# Or jump straight to the dashboard
python main.py --dashboard
```

---

## LLM Provider Priority

| Priority | Provider | Tier | Notes |
|----------|----------|------|-------|
| 1 | Gemini (Google) | Free | Round-robin across up to 6 keys |
| 2 | Groq | Free | Fast inference |
| 3 | Cerebras | Free | |
| 4 | NVIDIA | Free | |
| 5 | GitHub Models | Free | |
| 6 | OpenRouter | Free | |
| 7 | OpenAI | **Paid** | Last resort only |

If a Gemini key hits a 429/503, the client rotates to the next key automatically. If all keys are exhausted, it falls through to the next provider in the chain.

---

## Key Design Decisions

**Why clipboard-capture for Notepad saves?**
Modern Windows 11 Notepad is a XAML/UWP app. `cua-driver`'s UIA hotkey path can't trigger `Ctrl+S` on it. Instead, after typing, the agent does `Ctrl+A → Ctrl+C → write clipboard to disk directly`. No save dialog, no UIA dependency.

**Why isolated Chrome profile for the game task?**
`taskkill /IM chrome.exe /F` kills all Chrome instances — including the user's open tabs. Using `--user-data-dir=<tempdir>` creates a fully isolated Chrome process that can be killed by PID without touching other windows.

**Why timestamped filenames?**
Re-running a task should never destroy previous output. Each run produces `meeting_notes_20260614_022238.txt` rather than overwriting a fixed `meeting_notes.txt`.

**Why `type_text` falls back to clipboard paste?**
MSIX/packaged apps (Calculator, modern Notepad) don't expose a valid window handle to `cua-driver`. When `cua-driver` returns "Invalid window handle", `driver.type_text` falls back to `set_clipboard_text + Ctrl+V`, which works on any app.

---

## Safety Notes

- Run in a **dedicated test user account** — the agent has full desktop access.
- The `.env` file contains real API keys — never commit it.
- `cua-driver shutdown` kills the daemon immediately if a run goes wrong.
- The browser game task uses an isolated Chrome profile; your regular Chrome windows are safe.
