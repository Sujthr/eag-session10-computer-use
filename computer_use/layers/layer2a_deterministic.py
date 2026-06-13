"""
Layer 2a — Deterministic
Pre-programmed hotkey recipes. Zero LLM cost.
"""
import re
from computer_use import driver, recording
from computer_use.logger import log

# ── Calculator element-index map (from Windows Calculator UIA tree) ───────────
# Element indices are stable across Calculator sessions.
_CALC_ELEMENTS = {
    "0": 24, "1": 25, "2": 26, "3": 27, "4": 28,
    "5": 29, "6": 30, "7": 31, "8": 32, "9": 33,
    ".": 34,
    "/": 19, "÷": 19,
    "*": 20, "×": 20, "x": 20,
    "-": 21, "−": 21, "–": 21,
    "+": 22,
    "=": 23, "Return": 23, "Enter": 23,
    "%": 12,
    "Clear": 14, "Escape": 14,
    "Backspace": 15,
}


def _tokenise_expression(expr: str) -> list[str]:
    """Convert an arithmetic expression into a list of character tokens."""
    expr = expr.replace("×", "*").replace("÷", "/").replace("−", "-").replace("–", "-")
    expr = re.sub(r"\s+", "", expr)
    tokens = []
    for ch in expr:
        if ch not in _CALC_ELEMENTS:
            raise ValueError(f"Unsupported character in expression: {ch!r}")
        tokens.append(ch)
    tokens.append("=")
    return tokens


def calculator(pid: int, expression: str) -> str:
    """
    Drive Windows Calculator via UIA element clicks (element_index).
    Works with UWP Calculator which ignores injected keystrokes.
    """
    log.info(f"Layer 2a: Calculator expression={expression!r}")
    tokens = _tokenise_expression(expression)
    log.debug(f"  token sequence: {tokens}")

    def _click(idx: int, label: str):
        """Click element; refresh cache and retry once on stale-handle errors."""
        for attempt in range(2):
            try:
                driver.get_window_state(pid)  # always refresh before click
                driver.click(pid, idx)
                recording.log_action("click", label)
                return
            except Exception as e:
                if attempt == 0 and ("Invalid window" in str(e) or "not in cache" in str(e)):
                    log.debug(f"click retry after cache miss: {e}")
                    continue
                raise

    # Clear previous result
    _click(_CALC_ELEMENTS["Clear"], "Clear")

    for tok in tokens:
        _click(_CALC_ELEMENTS[tok], tok)

    log.success("Layer 2a: key sequence complete")
    return " ".join(tokens)


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
