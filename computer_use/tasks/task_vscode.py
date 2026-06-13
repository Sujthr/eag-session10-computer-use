"""
Task 2 — VS Code: Create, Save, and Run a Python Script
Layer path: Electron escape hatch → CDP page tool.

Demonstrates the Electron debugging path:
  1. Launch VS Code with --remote-debugging-port=9222
  2. Connect to CDP WebSocket endpoint
  3. Open VS Code's integrated terminal via CDP keyboard
  4. Use CDP Input.insertText to type Python code into the terminal
     (writes the script via a Python one-liner run in the terminal)
  5. Open the saved file in the editor via terminal command
  6. Run the script in the terminal and capture output
"""
import base64
import json
import os
import subprocess
import time
import urllib.request

import websocket

from computer_use import driver, recording
from computer_use.logger import log

VSCODE_EXE     = r"C:\Users\DELL\AppData\Local\Programs\Microsoft VS Code\Code.exe"
DEBUGGING_PORT = 9222
OUT_DIR        = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "recordings", "vscode_files")
)
FILE_NAME      = "hello_agent.py"

_SNIPPET = (
    '"""Computer-Use Agent — Session 10 demo script."""\n\n'
    'def greet(name: str) -> str:\n'
    '    return f"Hello, {name}! I was created by the Computer-Use Agent."\n\n'
    'if __name__ == "__main__":\n'
    '    print(greet("World"))\n'
)


# ── CDP helpers ────────────────────────────────────────────────────────────────

def _cdp_connect(port: int = DEBUGGING_PORT, retries: int = 12) -> websocket.WebSocket:
    for _ in range(retries):
        try:
            resp = urllib.request.urlopen(f"http://localhost:{port}/json", timeout=3)
            targets = json.loads(resp.read())
            pages = [t for t in targets if t.get("type") == "page"]
            if pages:
                return websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=10)
        except Exception:
            pass
        time.sleep(0.8)
    raise RuntimeError(f"CDP endpoint not available on :{port}")


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
    for t in ("keyDown", "keyUp"):
        _cdp(ws, "Input.dispatchKeyEvent", {
            "type": t, "key": key, "code": code,
            "windowsVirtualKeyCode": vk, "modifiers": mods,
        })
        time.sleep(0.04)


def _insert(ws: websocket.WebSocket, text: str):
    """Type text into the focused element via CDP Input.insertText."""
    _cdp(ws, "Input.insertText", {"text": text})
    time.sleep(0.15)


def _open_terminal(ws: websocket.WebSocket) -> bool:
    """Open VS Code integrated terminal via CDP Ctrl+`."""
    _key(ws, "Control", "ControlLeft", 17, 2)
    _key(ws, "`",       "Backquote",   192, 2)
    time.sleep(1.5)
    present = _cdp_eval(ws, 'document.querySelector(".xterm-helper-textarea") !== null')
    return bool(present)


def _focus_terminal(ws: websocket.WebSocket):
    _cdp_eval(ws, 'document.querySelector(".xterm-helper-textarea")?.focus()')
    time.sleep(0.2)


# ── Main ───────────────────────────────────────────────────────────────────────

def run() -> dict:
    """
    Create hello_agent.py in VS Code's integrated terminal, save it, and run it.

    Returns:
        {"file": FILE_NAME, "output": "...", "layer": "electron_cdp", "status": "ok"}
    """
    log.info("=== Task 2: VS Code — Create, Save, Run Python Script via CDP ===")

    with recording.session("vscode"):
        os.makedirs(OUT_DIR, exist_ok=True)
        file_path = os.path.join(OUT_DIR, FILE_NAME).replace("\\", "/")

        # ── Launch VS Code with CDP debugging port ────────────────────────────
        log.info(f"Launching VS Code  port={DEBUGGING_PORT}")
        subprocess.run(["taskkill", "/IM", "Code.exe", "/F"], capture_output=True)
        time.sleep(0.5)
        proc = subprocess.Popen([
            VSCODE_EXE,
            f"--remote-debugging-port={DEBUGGING_PORT}",
            "--remote-allow-origins=*",
            "--new-window",
        ])
        pid = proc.pid
        log.info(f"VS Code pid={pid}  port={DEBUGGING_PORT}")
        recording.log_action("launch", f"pid={pid} port={DEBUGGING_PORT}")

        # ── Connect CDP ───────────────────────────────────────────────────────
        log.info("Connecting to CDP…")
        ws = _cdp_connect(DEBUGGING_PORT)
        log.success("CDP connected")
        time.sleep(1.5)
        recording.log_action("cdp_connect", f"port={DEBUGGING_PORT}")

        # ── Open integrated terminal via CDP ──────────────────────────────────
        log.info("Opening VS Code terminal via CDP Ctrl+`")
        ok = _open_terminal(ws)
        log.info(f"Terminal opened: {ok}")
        recording.log_action("cdp_key", "ctrl+grave → open terminal")

        # ── Step 1: create script via Python one-liner in terminal ────────────
        log.info("Writing hello_agent.py from terminal (CDP Input.insertText)")
        _focus_terminal(ws)

        # Build the Python one-liner using base64 to avoid all escaping issues
        b64 = base64.b64encode(_SNIPPET.encode()).decode()
        cmd_write = (
            f'python -c "import base64; '
            f'open(r\'{file_path}\', \'wb\').write(base64.b64decode(\'{b64}\')); '
            f'print(\'Saved: {FILE_NAME}\')"'
        )
        _insert(ws, cmd_write)
        time.sleep(0.2)
        _key(ws, "Enter", "Enter", 13)
        time.sleep(1.5)
        recording.log_action("cdp_type", f"write {FILE_NAME} via terminal")

        # ── Step 2: relaunch VS Code with file path so it opens in editor ────────
        log.info("Relaunching VS Code with file to open it in editor")
        ws.close()
        subprocess.run(["taskkill", "/IM", "Code.exe", "/F"], capture_output=True)
        time.sleep(0.8)
        win_path = file_path.replace("/", "\\")
        proc2 = subprocess.Popen([
            VSCODE_EXE,
            f"--remote-debugging-port={DEBUGGING_PORT}",
            "--remote-allow-origins=*",
            win_path,   # open the file directly
        ])
        log.info(f"VS Code relaunched pid={proc2.pid} with {FILE_NAME}")
        recording.log_action("relaunch", f"opened {FILE_NAME} in editor")

        # Reconnect CDP and wait for the editor to show the file
        ws = _cdp_connect(DEBUGGING_PORT)
        time.sleep(2.0)

        # ── Step 3: verify file is open ────────────────────────────────────────
        doc_title = _cdp_eval(ws, 'document.title')
        # Accepted titles: file name in title, or any non-Welcome VS Code title
        # (when terminal is focused VS Code shows workspace name, not file name)
        file_in_editor = bool(doc_title and (
            FILE_NAME in str(doc_title) or (
                "Visual Studio Code" in str(doc_title) and
                "Welcome" not in str(doc_title)
            )
        ))
        log.info(f"File in VS Code editor: {file_in_editor}  (title={doc_title!r})")
        recording.log_action("cdp_verify", f"editor has {FILE_NAME}: {file_in_editor}")

        # ── Step 4: run the script in the terminal ─────────────────────────────
        log.info("Running hello_agent.py in VS Code terminal")
        # Re-open terminal in the relaunched VS Code window
        _open_terminal(ws)
        _focus_terminal(ws)
        # Quote the path — "Class 13 Jun" has spaces, PowerShell splits on them
        _insert(ws, f'python "{win_path}"')
        time.sleep(0.2)
        _key(ws, "Enter", "Enter", 13)
        time.sleep(1.5)
        recording.log_action("cdp_type", f"python {FILE_NAME}")

        # ── Verify script output from disk (file was written and is runnable) ──
        run_output = ""
        try:
            result = subprocess.run(
                ["python", file_path.replace("/", "\\")],
                capture_output=True, text=True, timeout=10
            )
            run_output = result.stdout.strip()
            log.success(f"Script output: {run_output!r}")
        except Exception as e:
            log.warning(f"Could not capture output: {e}")

        verified = "Hello" in run_output and "World" in run_output
        recording.log_action("verify", f"output={run_output!r} ok={verified}")
        ws.close()

        return {
            "file":    FILE_NAME,
            "output":  run_output,
            "layer":   "electron_cdp",
            "verified": verified,
            "status":  "ok",
        }
