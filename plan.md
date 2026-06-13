# Implementation Plan — Session 10 Computer-Use Agent

## Overview

Build a `computer_use` skill module that plugs into the Session 9 skill catalogue, drives three real Windows desktop tasks using `cua-driver`, and records every run as a trajectory. All LLM calls route through the V9 gateway with a free-first, paid-last API key strategy.

---

## Chosen Tasks

| # | Task | Layer | Constraint covered |
|---|------|-------|--------------------|
| 1 | Calculator arithmetic | 2a deterministic | Zero vision |
| 2 | VS Code file creation | Electron / CDP | Electron page path |
| 3 | Browser game (2048) | 3 vision | Vision required |

---

## File Structure

```
D:\EAG\EAG\Class 13 Jun\
├── computer_use/
│   ├── __init__.py
│   ├── skill.py                  # S9 catalogue entry; CLI runner
│   ├── driver.py                 # cua-driver socket client
│   ├── llm_client.py             # V9 gateway calls, key rotation
│   ├── recording.py              # start/stop recording helpers
│   ├── layers/
│   │   ├── __init__.py
│   │   ├── layer1_extract.py     # Read AX tree / clipboard
│   │   ├── layer2a_deterministic.py   # Hotkey recipes
│   │   ├── layer2b_ally.py       # AX tree + cheap LLM loop
│   │   └── layer3_vision.py      # Screenshot + set-of-marks + vision LLM
│   └── tasks/
│       ├── __init__.py
│       ├── task_calculator.py    # Task 1
│       ├── task_vscode.py        # Task 2
│       └── task_browser_game.py  # Task 3
├── prompts/
│   └── computer_use.md           # S9 catalogue prompt file
├── recordings/                   # Gitignored; trajectory output
├── requirements.txt
├── .env                          # Symlink / copy of shared .env
├── README.md
└── plan.md
```

---

## Step-by-Step Implementation

### Step 1 — Project scaffold

- [ ] Create the directory tree above.
- [ ] Write `requirements.txt`:
  ```
  python-dotenv>=1.0
  pillow>=10.0          # set-of-marks overlay
  requests>=2.31
  google-generativeai>=0.7
  ```
- [ ] Copy / symlink `.env` from `D:\EAG\EAG\06JuneAssignment\cc33f915-5cf0-4ca5-b7ad-8d8e786736e8\.env`.

---

### Step 2 — `driver.py` — cua-driver socket wrapper

Wrap every `cua-driver` JSON-over-socket call in a single `call(tool, args)` function.

Key responsibilities:
- Ensure daemon is running (`cua-driver status`; if not, `cua-driver serve`).
- Send JSON request, receive JSON response.
- Raise `DriverError` on non-zero `error` field.
- Expose typed helpers: `get_window_state`, `click`, `type_text`, `press_key`, `hotkey`, `take_screenshot`, `launch_app`, `page`.

```python
# driver.py skeleton
import subprocess, socket, json, time

SOCKET_PATH = r"\\.\pipe\cua-driver"  # Windows named pipe

def ensure_daemon():
    if subprocess.run(["cua-driver", "status"], capture_output=True).returncode != 0:
        subprocess.Popen(["cua-driver", "serve"])
        time.sleep(0.8)

def call(tool: str, args: dict) -> dict:
    ensure_daemon()
    payload = json.dumps({"tool": tool, "args": args})
    # ... socket send/recv ...
    response = json.loads(raw)
    if response.get("error"):
        raise DriverError(response["error"])
    return response
```

---

### Step 3 — `llm_client.py` — V9 gateway with key rotation

**Priority order (free → paid):**

```
gemini (keys 0-5)  →  groq  →  cerebras  →  nvidia  →  github  →  openrouter  →  openai
```

**Gemini key rotation logic:**

```python
import os, itertools

def _load_gemini_keys():
    keys = []
    for suffix in ["", "_1", "_2", "_3", "_4", "_5"]:
        v = os.getenv(f"GEMINI_API_KEY{suffix}", "").strip()
        if v:
            keys.append(v)
    return keys

GEMINI_KEYS = _load_gemini_keys()
_gemini_cycle = itertools.cycle(GEMINI_KEYS)

def get_next_gemini_key() -> str:
    return next(_gemini_cycle)
```

**Provider fallback logic:**

```python
PROVIDER_ORDER = ["gemini", "groq", "cerebras", "nvidia", "github", "openrouter", "openai"]

def chat(prompt: str, system: str = "", model_hint: str = "text") -> str:
    for provider in PROVIDER_ORDER:
        try:
            return _call_provider(provider, prompt, system)
        except RateLimitError:
            continue   # try next
        except Exception as e:
            if provider == "openai":
                raise
            continue
    raise RuntimeError("All providers exhausted")
```

**Vision call** (Layer 3) always goes to Gemini vision model first (free), falls back to OpenAI vision last resort.

---

### Step 4 — `layers/layer1_extract.py`

```python
def extract_text(pid: int, window_id: int) -> str | None:
    state = driver.get_window_state(pid, window_id)
    if state["element_count"] == 0:
        return None
    # return full AX tree markdown for caller to parse
    return state["markdown"]
```

No LLM involved. Returns `None` if the tree is empty so the cascade escalates.

---

### Step 5 — `layers/layer2a_deterministic.py`

Stores a registry of hotkey recipes keyed by `(app_name, goal_pattern)`.

```python
RECIPES = {
    "calculator": {
        "arithmetic": lambda expr: _build_calc_sequence(expr)
    }
}

def try_deterministic(app_name: str, goal: str, pid: int) -> bool:
    recipe = _match_recipe(app_name, goal)
    if recipe is None:
        return False          # no recipe → escalate
    for key in recipe:
        driver.press_key(pid, key)
        driver.get_window_state(pid)   # re-scan invariant
    return True
```

Calculator key mapping: digits `0-9`, `+`, `-`, `*`, `/`, `Enter` (=), `Escape` (clear).

---

### Step 6 — `layers/layer2b_ally.py`

Scan → LLM act → verify loop. Max 10 turns before giving up.

```python
def run_ally_loop(pid: int, window_id: int, goal: str, max_turns: int = 10):
    for turn in range(max_turns):
        state = driver.get_window_state(pid, window_id)
        if state["element_count"] == 0:
            raise EscalateToVision("element_count 0 in Layer 2b")

        prompt = build_action_prompt(state["markdown"], goal)
        response = llm_client.chat(prompt, system=ACTION_SYSTEM_PROMPT)
        action = json.loads(response)

        if action["verdict"] == "done":
            return action.get("result")
        elif action["verdict"] == "escalate":
            raise EscalateToVision(action["reason"])

        # dispatch action
        dispatch(pid, action)
        # always re-scan after action (invariant 2)
```

The LLM prompt asks for JSON: `{"verdict": "act|done|escalate", "element_index": N, "action": "click|type|hotkey", "value": "..."}`.

---

### Step 7 — `layers/layer3_vision.py`

```python
from PIL import Image, ImageDraw

def run_vision(pid: int, goal: str):
    raw = driver.take_screenshot(pid)
    img = Image.open(io.BytesIO(raw))
    marked, regions = draw_set_of_marks(img)  # numbered boxes
    vision_response = llm_client.vision(marked, goal, regions)
    # vision_response: {"mark": N, "action": "click|key", "value": "..."}
    x, y = regions[vision_response["mark"]]["center"]
    driver.click_at(pid, x, y)
    # verify: re-screenshot, check state changed
```

`draw_set_of_marks`: divide screenshot into a grid or detect UI regions, draw numbered yellow boxes with 8 px padding, return region list with center coordinates.

---

### Step 8 — `tasks/task_calculator.py`

```python
def run(expression: str):
    recording.start("calculator")
    try:
        pid = driver.launch_app("Microsoft.WindowsCalculator_8wekyb3d8bbwe")
        driver.bring_to_front(pid)  # Windows: bring_to_front works
        time.sleep(0.3)
        # Layer 2a
        layer2a.try_deterministic("calculator", expression, pid)
        # Layer 1: read result
        state = driver.get_window_state(pid)
        result = parse_display_value(state["markdown"])
        print(f"Result: {result}")
        return result
    finally:
        recording.stop()
```

Expression parser: tokenise `"127 × 43 − 58"` → key list using regex. Handle Unicode `×` → `*`, `÷` → `/`, `−` → `-`.

---

### Step 9 — `tasks/task_vscode.py`

```python
ELECTRON_BUNDLE = "com.microsoft.VSCode"
DEBUGGING_PORT = 9222

def run():
    recording.start("vscode")
    try:
        # Check if VS Code is an Electron app (it always is)
        pid = driver.launch_app(ELECTRON_BUNDLE,
                                electron_debugging_port=DEBUGGING_PORT)
        time.sleep(1.5)   # Chromium needs time to open debug socket

        # Use CDP page tool — no AX needed
        driver.page(pid, action="hotkey", value="Ctrl+N")          # New file
        driver.page(pid, action="type",
                    value="print('Hello from the Computer-Use Agent!')\n")
        driver.page(pid, action="hotkey", value="Ctrl+S")          # Save
        # Type filename in save dialog (VS Code untitled save prompt)
        driver.page(pid, action="type", value="hello_agent.py")
        driver.page(pid, action="hotkey", value="Enter")

        # Verify: AX tree tab title
        state = driver.get_window_state(pid)
        assert "hello_agent.py" in state["markdown"]
        print("VS Code task complete.")
    finally:
        recording.stop()
```

---

### Step 10 — `tasks/task_browser_game.py`

```python
GAME_URL = "https://play2048.co"

def run():
    recording.start("browser_game")
    try:
        pid = driver.launch_app("chrome", args=[GAME_URL])
        time.sleep(2.0)

        # Layer 1/2 attempt
        state = driver.get_window_state(pid)
        if state["element_count"] == 0:
            # Escalate to Layer 3
            move = layer3.run_vision(pid, "What is the best arrow key to press next in 2048?")
            driver.press_key(pid, move["value"])  # e.g. "ArrowUp"

        # Verify: re-screenshot, score should have changed
        time.sleep(0.5)
        state2 = driver.get_window_state(pid)
        print("Browser game move complete.")
    finally:
        recording.stop()
```

---

### Step 11 — `skill.py` — S9 catalogue entry

```python
# computer_use/skill.py
import argparse
from computer_use.tasks import task_calculator, task_vscode, task_browser_game

SKILL_NAME = "computer"
SKILL_DESCRIPTION = "Drive real desktop applications via cua-driver. Supports Calculator, VS Code, and browser game tasks."

def run(goal: str, config: dict = None):
    """Entry point called by Session 9 skills.py dispatcher."""
    if "calculator" in goal.lower():
        return task_calculator.run(goal)
    elif "vscode" in goal.lower() or "vs code" in goal.lower():
        return task_vscode.run()
    elif "game" in goal.lower() or "2048" in goal.lower():
        return task_browser_game.run()
    else:
        raise ValueError(f"No computer-use task matched goal: {goal!r}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["calculator", "vscode", "browser_game"])
    parser.add_argument("--expression", default="127 * 43 - 58")
    args = parser.parse_args()
    run(f"{args.task} {args.expression}")
```

**S9 `skills.py` change (one line):**

```python
# In Session 9 skills.py dispatch function:
if skill.name == "computer":
    from computer_use.skill import run as computer_run
    return computer_run(goal)
```

---

### Step 12 — `prompts/computer_use.md`

Follows the same structure as the Browser skill prompt file in S9:

```markdown
# computer_use

Drive real desktop applications on Windows.

Supports three task types:
- calculator <expression> — evaluate arithmetic in Windows Calculator
- vscode — create hello_agent.py in VS Code
- browser_game — make one move in 2048

The skill uses cua-driver and escalates through layers 2a → 2b → vision as needed.
```

---

### Step 13 — `recording.py`

```python
import time
from computer_use import driver

def start(task_name: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = f"recordings/{task_name}/{ts}"
    driver.call("start_recording", {"output_dir": out_dir})
    return out_dir

def stop():
    driver.call("stop_recording", {})
```

---

## API Key Configuration

The `.env` at `D:\EAG\EAG\06JuneAssignment\cc33f915-5cf0-4ca5-b7ad-8d8e786736e8\.env` is the single source of truth. Copy or symlink it to the project root before running.

| Variable | Provider | Free? | Use |
|----------|----------|-------|-----|
| `GEMINI_API_KEY` + `_1`…`_5` | Google Gemini | Yes (free tier) | Primary text + vision |
| `GROQ_API_KEY` | Groq | Yes | Text fallback #1 |
| `CEREBRAS_API_KEY` | Cerebras | Yes | Text fallback #2 |
| `NVIDIA_API_KEY` | NVIDIA | Yes | Text fallback #3 |
| `GITHUB_ACCESS_TOKEN` | GitHub Models | Yes | Text fallback #4 |
| `OPEN_ROUTER_API_KEY` | OpenRouter | Yes (free models) | Text fallback #5 |
| `OPENAI_API_KEY` | OpenAI | **No — paid** | Last resort only |

`llm_client.py` loads all keys at import time. Gemini keys are pooled into a round-robin cycle. Any `429 / 503` triggers a rotate-and-retry before moving to the next provider.

---

## Testing Checklist

- [ ] `cua-driver status` returns 0 after `cua-driver serve`
- [ ] Calculator: `"127 * 43 - 58"` → `5403`
- [ ] Calculator: `element_count > 0` after launch + `bring_to_front`
- [ ] VS Code: tab title contains `hello_agent.py` after task
- [ ] VS Code: CDP port 9222 is open (`netstat -an | findstr 9222`)
- [ ] Browser game: `element_count == 0` confirmed (canvas), Layer 3 triggered
- [ ] Vision: set-of-marks image saved to `recordings/` for inspection
- [ ] All three `recordings/<task>/*/` directories exist after runs
- [ ] Replay: `cua-driver replay recordings/calculator/<ts>/` completes without error
- [ ] No OpenAI API call made (check gateway logs) unless all free providers fail

---

## Risk Register

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Calculator AX tree empty on first scan | Medium | `bring_to_front` + 300 ms sleep before first scan |
| VS Code debugging port already bound | Low | Kill existing VS Code instance first |
| Gemini free tier quota hit | Medium | 5 key rotation + Groq/Cerebras fallback |
| 2048 URL blocked / CORS | Low | Serve locally: `python -m http.server` + static game HTML |
| cua-driver not on PATH | High | Add install step to README; check in `ensure_daemon()` |
| Vision coordinate off by pixels | Medium | Increase set-of-marks box size; verify by re-screenshot |

---

## Submission Checklist

- [ ] GitHub repo with this README, plan.md, all source files
- [ ] `recordings/` directory with trajectory data for all three tasks
- [ ] YouTube demo showing at least one task live with agent-cursor overlay
- [ ] No API keys committed (`.env` in `.gitignore`)
- [ ] `CUA_DRIVER_GUIDE.md` read before first run
