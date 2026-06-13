"""
Layer 2a — Deterministic
Pre-programmed hotkey recipes. Zero LLM cost.
"""
import re
import time
from computer_use import recording
from computer_use.logger import log


def calculator(pid: int, expression: str) -> str:
    """
    Drive Windows Calculator via keyboard SendInput.

    Using keyboard input instead of UIA element-index clicks avoids
    cua-driver's window-handle issues with UWP/MSIX apps.  Calculator
    responds to standard keyboard input when it has focus.
    """
    from computer_use import windows_native as nat

    # Normalise unicode operators and strip spaces
    expr = (expression
            .replace("×", "*").replace("÷", "/")
            .replace("−", "-").replace("–", "-")
            .replace(" ", ""))

    log.info(f"Layer 2a: Calculator keyboard  expr={expr!r}")

    allowed = set("0123456789.+-*/%()")
    for ch in expr:
        if ch not in allowed:
            raise ValueError(f"Unsupported character in expression: {ch!r}")

    # Ensure Calculator window has focus before we send keys
    nat.bring_window_to_front(pid, title_hint="Calculator", retries=8, wait=0.4)
    time.sleep(0.4)

    # Clear any previous result (Escape key)
    nat.send_key("Escape")
    time.sleep(0.15)

    # Type each character of the expression
    for ch in expr:
        nat.send_key(ch)          # _VK table covers 0-9, +, -, *, /, ., %
        time.sleep(0.08)

    # Press Enter to evaluate (= button)
    nat.send_key("Return")
    time.sleep(0.3)

    recording.log_action("calc_keyboard", expr)
    log.success(f"Layer 2a: keyboard sequence complete for {expr!r}")
    return expr


# ── Generic hotkey recipe registry ───────────────────────────────────────────

_RECIPES: dict[str, dict[str, list]] = {
    "vscode": {
        "new_file":  [["ctrl", "n"]],
        "save":      [["ctrl", "s"]],
        "close_tab": [["ctrl", "w"]],
        "open_file": [["ctrl", "p"]],
    },
    "notepad": {
        "new":       [["ctrl", "n"]],
        "save":      [["ctrl", "s"]],
    },
}


def run_recipe(pid: int, app: str, action: str) -> bool:
    """Execute a named hotkey recipe.  Returns False if no recipe found."""
    app_recipes = _RECIPES.get(app.lower(), {})
    seq = app_recipes.get(action.lower())
    if seq is None:
        return False
    for keys in seq:
        driver.hotkey(pid, keys)
        recording.log_action("hotkey", "+".join(keys))
    return True
