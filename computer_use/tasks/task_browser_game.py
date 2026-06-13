"""
Task 3 — Browser Game (2048)
Layer path: Layer 3 vision (canvas renderer, no AX nodes).

Goal: detect the current board state and make the best available move.
Loops for a configurable number of moves.
"""
import os
import subprocess
import time

from computer_use import driver, recording, windows_native as nat
from computer_use.driver import _discover_window, _WIN_IDS, _WIN_HINTS
from computer_use.layers import layer3_vision
from computer_use.logger import log

GAME_URL = "https://play2048.co"
MOVES    = 5

_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def _find_chrome() -> str:
    for p in _CHROME_PATHS:
        if os.path.exists(p):
            return p
    return "chrome.exe"


def run(moves: int = MOVES) -> dict:
    """
    Run the browser-game vision task.

    Returns:
        {"moves_made": int, "layer": "3_vision", "status": "ok"}
    """
    log.info(f"=== Task 3: Browser Game (2048)  moves={moves} ===")

    with recording.session("browser_game"):
        # ── Launch Chrome in an isolated profile so it stays separate from any
        #    Chrome windows the user already has open.  This lets us close only
        #    our instance at the end without touching the user's browser.
        import tempfile
        chrome_exe = _find_chrome()
        _chrome_profile = tempfile.mkdtemp(prefix="chrome_agent_")
        log.info(f"Launching Chrome: {chrome_exe}  profile={_chrome_profile}")
        proc = subprocess.Popen([
            chrome_exe,
            "--new-window",
            f"--user-data-dir={_chrome_profile}",
            "--no-first-run",
            "--no-default-browser-check",
            GAME_URL,
        ])
        pid = proc.pid
        log.info(f"Chrome pid={pid}")
        recording.log_action("launch", f"Chrome pid={pid} url={GAME_URL}")
        time.sleep(4.0)   # wait for page to load

        # ── Discover Chrome window via cua-driver title search ────────────────
        wid = 0
        for title_hint in ("2048", "Chrome", "Google"):
            found = _discover_window(pid, title_hint, wait=4.0)
            if found:
                actual_pid, wid = found
                _WIN_IDS[pid]        = wid
                _WIN_IDS[actual_pid] = wid
                _WIN_HINTS[pid]      = title_hint
                pid = actual_pid
                log.info(f"Chrome window found: pid={pid} wid={wid} hint={title_hint!r}")
                break

        if not wid:
            log.warning("Could not discover Chrome window_id — vision may still work")

        driver.bring_to_front(pid)
        time.sleep(0.5)

        moves_made = 0
        for i in range(moves):
            log.info(f"Move {i+1}/{moves}")

            # ── Check AX tree ─────────────────────────────────────────────────
            state = driver.get_window_state(pid)
            elem_count = state.get("element_count", 0)
            if elem_count > 0:
                log.debug(f"AX tree has {elem_count} elements; using vision anyway")

            # ── Layer 3: vision ───────────────────────────────────────────────
            action = layer3_vision.run(
                pid,
                goal=(
                    "This is the 2048 browser game. "
                    "Identify the board and determine the best arrow key to press "
                    "(ArrowUp, ArrowDown, ArrowLeft, or ArrowRight) to merge tiles. "
                    'Return {"action": "key", "key": "<direction>", "reason": "<brief>"}.'
                ),
                task_name=f"game_move_{i+1}",
            )

            if action.get("action") == "done":
                log.success("Vision LLM says game is done")
                break

            time.sleep(0.4)
            moves_made += 1

        log.success(f"Browser game task complete. Moves made: {moves_made}")

        # ── Close only the agent's Chrome instance (kill process tree by pid) ─
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        # Clean up the temporary profile directory
        import shutil as _shutil
        _shutil.rmtree(_chrome_profile, ignore_errors=True)
        recording.log_action("close", f"Chrome pid={pid} closed")

        return {
            "moves_made": moves_made,
            "layer":      "3_vision",
            "status":     "ok",
        }
