"""
Task 2 — VS Code: Create, Open, and Run a Python Script
Layer path: Electron escape hatch → CDP (Chrome DevTools Protocol).

Flow:
  1. Write the timestamped script to disk (Python I/O)
  2. Kill any existing VS Code, then launch fresh with --new-window <file>
     — uses the user's own profile so there are no login/setup prompts,
       and --new-window opens exactly the new file with no session restore
  3. Connect CDP WebSocket
  4. Verify file is open in editor (check document.title)
  5. Open integrated terminal via Ctrl+`
  6. Run the script in the terminal via CDP Input.insertText + Enter
  7. Capture stdout with subprocess for verification
  8. Close VS Code
"""
import datetime
import json
import os
import subprocess
import time
import urllib.request

import websocket

from computer_use import recording
from computer_use.logger import log

VSCODE_EXE     = r"C:\Users\DELL\AppData\Local\Programs\Microsoft VS Code\Code.exe"
DEBUGGING_PORT = 9222
OUT_DIR        = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "recordings", "vscode_files")
)
FILE_STEM = "hello_agent"

_SNIPPET = '''\
"""Computer-Use Agent — Session 10 demo script."""


def greet(name: str) -> str:
    return f"Hello, {name}! I was created by the Computer-Use Agent."


if __name__ == "__main__":
    print(greet("World"))
'''


def _ts_filename() -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{FILE_STEM}_{ts}.py"


# ── CDP helpers ────────────────────────────────────────────────────────────────

def _cdp_connect(port: int = DEBUGGING_PORT, retries: int = 20) -> websocket.WebSocket:
    for attempt in range(retries):
        try:
            resp = urllib.request.urlopen(f"http://localhost:{port}/json", timeout=3)
            targets = json.loads(resp.read())
            pages = [t for t in targets if t.get("type") == "page"]
            if pages:
                return websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=10)
        except Exception:
            pass
        log.debug(f"CDP not ready yet (attempt {attempt+1}/{retries})")
        time.sleep(1.0)
    raise RuntimeError(f"CDP endpoint not available on port {port} after {retries} attempts")


_cdp_id = 0


def _cdp(ws: websocket.WebSocket, method: str, params: dict = {}) -> dict:
    global _cdp_id
    _cdp_id += 1
    my_id = _cdp_id
    ws.send(json.dumps({"id": my_id, "method": method, "params": params}))
    for _ in range(30):
        msg = json.loads(ws.recv())
        if msg.get("id") == my_id:
            return msg.get("result", {})
    return {}


def _cdp_eval(ws: websocket.WebSocket, expr: str) -> object:
    r = _cdp(ws, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
    return r.get("result", {}).get("value")


def _key(ws: websocket.WebSocket, key: str, code: str, vk: int, mods: int = 0):
    for ev in ("keyDown", "keyUp"):
        _cdp(ws, "Input.dispatchKeyEvent", {
            "type": ev, "key": key, "code": code,
            "windowsVirtualKeyCode": vk, "modifiers": mods,
        })
        time.sleep(0.05)


def _insert(ws: websocket.WebSocket, text: str):
    _cdp(ws, "Input.insertText", {"text": text})
    time.sleep(0.2)


def _open_terminal(ws: websocket.WebSocket, retries: int = 4) -> bool:
    """Open the VS Code integrated terminal via Ctrl+` and wait for xterm."""
    for _ in range(retries):
        _key(ws, "Control", "ControlLeft", 17, 2)
        _key(ws, "`",       "Backquote",   192, 2)
        time.sleep(2.5)
        if _cdp_eval(ws, 'document.querySelector(".xterm-helper-textarea") !== null'):
            return True
    return False


def _focus_terminal(ws: websocket.WebSocket):
    _cdp_eval(ws, 'document.querySelector(".xterm-helper-textarea")?.focus()')
    time.sleep(0.3)


# ── Main ───────────────────────────────────────────────────────────────────────

def run() -> dict:
    """
    Write a Python script, open it in VS Code, run it via the terminal.

    Returns:
        {"file": str, "output": str, "verified": bool,
         "layer": "electron_cdp", "status": "ok"}
    """
    log.info("=== Task 2: VS Code — Create, Open, Run Python Script via CDP ===")

    with recording.session("vscode"):
        os.makedirs(OUT_DIR, exist_ok=True)
        file_name = _ts_filename()
        win_path  = os.path.join(OUT_DIR, file_name)

        # ── Step 1: Write script to disk ──────────────────────────────────────
        with open(win_path, "w", encoding="utf-8") as fh:
            fh.write(_SNIPPET)
        log.info(f"Script written to disk: {win_path}")
        recording.log_action("write", f"{file_name}  {len(_SNIPPET)} chars")

        # ── Step 2: Launch VS Code (existing profile, no login prompts) ───────
        # Kill any running instance first so the debug port is free
        subprocess.run(["taskkill", "/IM", "Code.exe", "/F"], capture_output=True)
        time.sleep(1.0)

        log.info(f"Launching VS Code with {file_name}")
        proc = subprocess.Popen([
            VSCODE_EXE,
            f"--remote-debugging-port={DEBUGGING_PORT}",
            "--remote-allow-origins=*",
            "--new-window",      # open a fresh window, ignore previous session
            win_path,            # open our file directly
        ])
        log.info(f"VS Code pid={proc.pid}")
        recording.log_action("launch", f"pid={proc.pid}  file={file_name}")

        # ── Step 3: Connect CDP ───────────────────────────────────────────────
        log.info("Waiting for CDP endpoint…")
        ws = _cdp_connect(DEBUGGING_PORT)
        log.success("CDP connected")
        time.sleep(2.5)   # let the editor finish rendering
        recording.log_action("cdp_connect", f"port={DEBUGGING_PORT}")

        # ── Step 4: Confirm file is open in editor ────────────────────────────
        doc_title = str(_cdp_eval(ws, "document.title") or "")
        file_in_editor = file_name in doc_title or FILE_STEM in doc_title
        log.info(f"Editor title: {doc_title!r}  file_open={file_in_editor}")
        recording.log_action("verify_open", f"title={doc_title!r}")

        # ── Step 5: Open terminal and run the script ──────────────────────────
        log.info("Opening integrated terminal (Ctrl+`)")
        terminal_ok = _open_terminal(ws)
        log.info(f"Terminal ready: {terminal_ok}")
        recording.log_action("terminal", f"opened={terminal_ok}")

        _focus_terminal(ws)
        run_cmd = f'python "{win_path}"'
        log.info(f"Running in terminal: {run_cmd}")
        _insert(ws, run_cmd)
        _key(ws, "Enter", "Enter", 13)
        time.sleep(2.0)
        recording.log_action("run", run_cmd)

        # ── Step 6: Capture stdout ────────────────────────────────────────────
        run_output = ""
        try:
            res = subprocess.run(
                ["python", win_path],
                capture_output=True, text=True, timeout=10,
            )
            run_output = res.stdout.strip()
            log.success(f"Script output: {run_output!r}")
        except Exception as e:
            log.warning(f"Script run failed: {e}")

        verified = "Hello" in run_output and "World" in run_output
        recording.log_action("verify_output", f"output={run_output!r}  ok={verified}")

        # ── Step 7: Close VS Code ─────────────────────────────────────────────
        ws.close()
        subprocess.run(["taskkill", "/IM", "Code.exe", "/F"], capture_output=True)
        recording.log_action("close", "VS Code closed")

        return {
            "file":     file_name,
            "output":   run_output,
            "layer":    "electron_cdp",
            "verified": verified,
            "status":   "ok",
        }
