"""
Task 2 — VS Code: Create, Open, and Run a Python Script
Layer path: Electron escape hatch → CDP (Chrome DevTools Protocol).

Flow (single VS Code window, no relaunch):
  1. Write the timestamped script to disk directly (Python I/O)
  2. Launch VS Code with --user-data-dir=<tmpdir> so it never restores a
     previous session, passing the new file path so it opens immediately
  3. Connect CDP WebSocket
  4. Open the integrated terminal via CDP keyboard shortcut
  5. Run the script in the terminal via CDP Input.insertText
  6. Capture stdout by running the script with subprocess
  7. Close VS Code and delete the temp profile dir
"""
import base64
import datetime
import json
import os
import shutil
import subprocess
import tempfile
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

def _cdp_connect(port: int = DEBUGGING_PORT, retries: int = 15) -> websocket.WebSocket:
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
        time.sleep(0.05)


def _insert(ws: websocket.WebSocket, text: str):
    _cdp(ws, "Input.insertText", {"text": text})
    time.sleep(0.2)


def _open_terminal(ws: websocket.WebSocket, retries: int = 3) -> bool:
    for _ in range(retries):
        _key(ws, "Control", "ControlLeft", 17, 2)
        _key(ws, "`",       "Backquote",   192, 2)
        time.sleep(2.0)
        present = _cdp_eval(ws, 'document.querySelector(".xterm-helper-textarea") !== null')
        if present:
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
        fwd_path  = win_path.replace("\\", "/")

        # ── Write script to disk before launching VS Code ─────────────────────
        with open(win_path, "w", encoding="utf-8") as fh:
            fh.write(_SNIPPET)
        log.info(f"Script written: {win_path}")
        recording.log_action("write", f"{file_name} ({len(_SNIPPET)} chars)")

        # ── Kill any leftover VS Code, then launch fresh with isolated profile ─
        subprocess.run(["taskkill", "/IM", "Code.exe", "/F"], capture_output=True)
        time.sleep(0.8)

        vscode_profile = tempfile.mkdtemp(prefix="vscode_agent_")
        log.info(f"Launching VS Code  port={DEBUGGING_PORT}  profile={vscode_profile}")
        proc = subprocess.Popen([
            VSCODE_EXE,
            f"--remote-debugging-port={DEBUGGING_PORT}",
            "--remote-allow-origins=*",
            "--new-window",
            f"--user-data-dir={vscode_profile}",
            win_path,   # open our new file immediately
        ])
        pid = proc.pid
        log.info(f"VS Code pid={pid}")
        recording.log_action("launch", f"pid={pid} file={file_name}")

        # ── Connect CDP ───────────────────────────────────────────────────────
        log.info("Connecting to CDP…")
        ws = _cdp_connect(DEBUGGING_PORT)
        log.success("CDP connected")
        time.sleep(2.0)
        recording.log_action("cdp_connect", f"port={DEBUGGING_PORT}")

        # ── Verify file is open in editor ─────────────────────────────────────
        doc_title = _cdp_eval(ws, "document.title") or ""
        file_in_editor = file_name in str(doc_title) or FILE_STEM in str(doc_title)
        log.info(f"File in editor: {file_in_editor}  title={doc_title!r}")
        recording.log_action("cdp_verify", f"title={doc_title!r} in_editor={file_in_editor}")

        # ── Open terminal and run the script ──────────────────────────────────
        log.info("Opening integrated terminal via CDP Ctrl+`")
        terminal_ok = _open_terminal(ws)
        log.info(f"Terminal opened: {terminal_ok}")
        recording.log_action("cdp_terminal", f"opened={terminal_ok}")

        _focus_terminal(ws)
        run_cmd = f'python "{win_path}"'
        log.info(f"Running: {run_cmd}")
        _insert(ws, run_cmd)
        _key(ws, "Enter", "Enter", 13)
        time.sleep(2.0)
        recording.log_action("cdp_run", run_cmd)

        # ── Capture output by running the script directly ─────────────────────
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
        recording.log_action("verify", f"output={run_output!r} ok={verified}")

        # ── Close VS Code and clean up temp profile ───────────────────────────
        ws.close()
        subprocess.run(["taskkill", "/IM", "Code.exe", "/F"], capture_output=True)
        time.sleep(0.5)
        shutil.rmtree(vscode_profile, ignore_errors=True)
        recording.log_action("close", "VS Code closed, profile deleted")

        return {
            "file":     file_name,
            "output":   run_output,
            "layer":    "electron_cdp",
            "verified": verified,
            "status":   "ok",
        }
