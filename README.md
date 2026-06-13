# Session 10 — Computer-Use Desktop Agent

A Computer-Use skill that integrates with the Session 9 skill catalogue and drives real desktop applications on Windows using the five-layer cascade architecture. Built on `cua-driver` as the perception/action substrate.

---

## Architecture: Five Layers

The cascade tries each layer in order and escalates only when the cheaper layer cannot proceed.

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1 — Extract                             Cost: $0      │
│  Read AX tree / clipboard / file directly.                   │
│  No LLM. Try this first for any read-only goal.              │
└────────────────────────┬────────────────────────────────────┘
                         │ tree is empty or goal needs action
┌────────────────────────▼────────────────────────────────────┐
│  Layer 2a — Deterministic                      Cost: $0      │
│  Pre-programmed hotkey / key-sequence recipes.               │
│  No LLM. Used for Calculator, well-known app shortcuts.      │
└────────────────────────┬────────────────────────────────────┘
                         │ no known hotkey recipe for goal
┌────────────────────────▼────────────────────────────────────┐
│  Layer 2b — A11y Tree                          Cost: cents   │
│  get_window_state → AX tree markdown →                       │
│  cheap text LLM (Gemini Flash-Lite) → element_index action   │
│  Workhorse layer. Used for most UI navigation.               │
└────────────────────────┬────────────────────────────────────┘
                         │ AX tree empty / target missing
┌────────────────────────▼────────────────────────────────────┐
│  Layer 3 — Vision                              Cost: dollars │
│  screenshot → set-of-marks → vision LLM → (x,y) click       │
│  Last resort. Canvas apps, games, Figma, pixel-painted UIs.  │
└─────────────────────────────────────────────────────────────┘
```

**Electron special case** sits between Layer 2b and Layer 3. When AX returns a single opaque `AXWebArea` (VS Code, Slack, Discord…), relaunch with `electron_debugging_port` and drive via CDP `page` tool.

---

## Three Tasks

### Task 1 — Calculator Arithmetic (Layer 2a, zero vision)

**Goal:** Evaluate a natural-language arithmetic expression (e.g., `"127 × 43 − 58"`) using Windows Calculator.

**Layer path:** Layer 2a — deterministic hotkey sequence.

**How it works:**
1. Ensure `cua-driver` daemon is running.
2. Launch `Microsoft.WindowsCalculator_8wekyb3d8bbwe` via `launch_app`.
3. Parse the expression into a sequence of `press_key` calls (`1`, `2`, `7`, `*`, `4`, `3`, `-`, `5`, `8`, `Enter`).
4. `get_window_state` → read the display value from the AX tree (no LLM).
5. Verify the result matches expected output.

**Zero vision:** the result is read from the AX tree. No screenshot is taken.

**Cascade discipline visible:** the skill checks for a hotkey recipe first; only if no recipe exists does it escalate to Layer 2b.

---

### Task 2 — VS Code File Creation (Electron / CDP path)

**Goal:** Open VS Code, create a new file `hello_agent.py`, type a Python hello-world snippet, and save.

**Layer path:** Electron escape hatch → CDP `page` tool.

**How it works:**
1. Check `list_apps` for VS Code; pattern-match against known Electron bundle IDs.
2. Launch VS Code with `electron_debugging_port: 9222`.
3. Use `page` tool with CSS selectors to trigger `File → New File` (`.action-label[aria-label="New File"]`).
4. Type content via `page` action `type`.
5. Save with `page` action `hotkey` (`Ctrl+S`).
6. Verify: re-scan AX tree for the tab title containing `hello_agent.py`.

**Why Electron path:** VS Code's AX tree exposes a single `AXWebArea`. Without the debugging port the agent is blind.

---

### Task 3 — Browser Game (Layer 3 vision)

**Goal:** Play one move in the browser game [2048](https://play2048.co) (or a locally served equivalent) by identifying the board state and pressing the best-direction key.

**Layer path:** Layer 3 — screenshot + set-of-marks + vision LLM.

**How it works:**
1. Launch Chrome and navigate to the game URL.
2. `get_window_state` → `element_count: 0` (canvas renderer, no AX nodes).
3. Escalate to Layer 3: `take_screenshot` → draw numbered marks over board cells.
4. Send screenshot to V9 `/v1/vision` endpoint (Gemini vision model).
5. Vision LLM returns the best move direction.
6. `press_key` the arrow key.
7. Re-screenshot to verify the board changed (score incremented).

**Why vision is forced:** the game canvas paints its own pixels; no AX tree is available.

---

## Cascade Decision Log

| Turn | App | AX elements | Layer chosen | Reason |
|------|-----|------------|--------------|--------|
| Calculator | Windows Calculator | 237 | 2a | known hotkey recipe |
| VS Code | VS Code | 1 (AXWebArea) | Electron/CDP | Electron bundle detected |
| 2048 | Chrome (canvas) | 0 | 3 vision | element_count = 0, canvas renderer |

---

## Failure Modes Encountered

| Symptom | Root cause | Fix applied |
|---------|-----------|-------------|
| `element_count: 0` on VS Code without flag | Electron app, single `AXWebArea` | Relaunched with `electron_debugging_port: 9222` |
| Cache miss on Calculator click | UI reflowed after digit entry | Added `get_window_state` before every digit press |
| Vision LLM returns wrong coordinate | Set-of-marks regions too small | Increased mark box padding to 8 px |
| Calculator result off-by-one | `press_key("Enter")` triggered `=` then re-evaluated | Changed to read AX tree without pressing `=` again |

---

## Repo Structure

```
.
├── computer_use/
│   ├── skill.py              # Session 9 catalogue entry point
│   ├── driver.py             # cua-driver JSON socket wrapper
│   ├── llm_client.py         # V9 gateway client, key rotation
│   ├── layers/
│   │   ├── layer1_extract.py
│   │   ├── layer2a_deterministic.py
│   │   ├── layer2b_ally.py
│   │   └── layer3_vision.py
│   └── tasks/
│       ├── task_calculator.py
│       ├── task_vscode.py
│       └── task_browser_game.py
├── prompts/
│   └── computer_use.md       # Skill description for S9 catalogue
├── recordings/               # Trajectory directories (gitignored raw data)
├── requirements.txt
├── .env                      # Symlink to shared .env (never committed)
└── README.md
```

---

## API Key Strategy

All LLM and vision calls go through the **V9 gateway** (Session 9). The gateway is configured with a priority chain — free providers first, paid as last resort.

### Provider Priority

| Priority | Provider | Keys | Notes |
|----------|----------|------|-------|
| 1 | Gemini (Google) | `GEMINI_API_KEY` + `_1` … `_5` | Round-robin rotation; free tier |
| 2 | Groq | `GROQ_API_KEY` | Free tier, fast inference |
| 3 | Cerebras | `CEREBRAS_API_KEY` | Free tier |
| 4 | NVIDIA | `NVIDIA_API_KEY` | Free tier |
| 5 | GitHub Models | `GITHUB_ACCESS_TOKEN` | Free via GitHub |
| 6 | OpenRouter | `OPEN_ROUTER_API_KEY` | Free tier models |
| 7 | OpenAI | `OPENAI_API_KEY` | **Paid — last resort only** |

### Gemini Key Rotation

The `llm_client.py` keeps a round-robin iterator over all non-empty Gemini keys. When a `429 ResourceExhausted` or `503` is received, it rotates to the next key automatically before retrying:

```python
GEMINI_KEYS = [v for k, v in os.environ.items()
               if k.startswith("GEMINI_API_KEY") and v]
_key_cycle = itertools.cycle(GEMINI_KEYS)

def get_next_gemini_key() -> str:
    return next(_key_cycle)
```

If all Gemini keys are exhausted in a single session, the client falls through to Groq → Cerebras → NVIDIA → GitHub → OpenRouter before touching the paid OpenAI key.

---

## Setup

### Prerequisites

```bash
# Install cua-driver (Rust binary)
cargo install cua-driver
# or download pre-built from the course materials

# Python deps
pip install -r requirements.txt
```

### Environment

```bash
# Point to shared .env (or copy it here)
cp "D:/EAG/EAG/06JuneAssignment/cc33f915-5cf0-4ca5-b7ad-8d8e786736e8/.env" .env
```

### Run a task

```bash
# Start the cua-driver daemon (once per session)
cua-driver serve &

# Run all three tasks
python -m computer_use.skill --task calculator --expression "127 * 43 - 58"
python -m computer_use.skill --task vscode
python -m computer_use.skill --task browser_game
```

Recordings land in `recordings/<task>/<timestamp>/`.

---

## Recording and Replay

Every run wraps its `cua-driver` calls inside `start_recording` / `stop_recording`:

```python
call("start_recording", {"output_dir": f"recordings/{task}/{session_id}"})
try:
    run_task(goal)
finally:
    call("stop_recording", {})
```

To replay a recorded trajectory:

```bash
cua-driver replay recordings/calculator/20260613_120000/
```

---

## Session 9 Integration

The skill drops into the S9 catalogue with **one line** added to `skills.py`:

```python
if skill.name == "computer":
    return ComputerUseSkill(config).run(goal)
```

The `prompts/computer_use.md` file follows the same prompt-file shape as the Browser skill. All LLM and vision calls reuse the V9 gateway — no new gateway, no new provider pin.

---

## Safety Notes

- Run in a **dedicated test user account** — the agent has full desktop access.
- Keep a backup of any file the agent might touch.
- `cua-driver shutdown` kills the daemon immediately if a run goes wrong.
- `Ctrl+Z` / `kill_app` are the two recovery primitives — test them before recording.
- The `.env` file contains real keys — never commit it.
