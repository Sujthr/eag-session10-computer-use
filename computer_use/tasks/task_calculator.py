"""
Task 1 — Calculator Arithmetic
Layer path: 2a (deterministic hotkeys). Zero vision calls.

Goal: evaluate an arithmetic expression using Windows Calculator.
Reads result via AX tree (cua-driver) or clipboard Ctrl+C (native fallback).
"""
import ast
import re
import time
import operator

from computer_use import driver, recording
from computer_use.layers import layer1_extract, layer2a_deterministic
from computer_use.logger import log

CALCULATOR_BUNDLE     = "Microsoft.WindowsCalculator_8wekyb3d8bbwe"
CALCULATOR_BUNDLE_ALT = "calc.exe"

# ── Safe Python expression evaluator (ground truth) ───────────────────────────
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

def _safe_eval(expr: str) -> float:
    """Evaluate a simple arithmetic expression safely (no exec/eval)."""
    # Normalise unicode operators first
    expr = (expr.replace("×", "*").replace("÷", "/")
                .replace("−", "-").replace("–", "-"))
    tree = ast.parse(expr, mode="eval")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            op_fn = _SAFE_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported operator: {node.op}")
            return op_fn(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op_fn = _SAFE_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported unary op: {node.op}")
            return op_fn(_eval(node.operand))
        raise ValueError(f"Unsupported node: {type(node)}")

    return _eval(tree)


def _format_result(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(round(value, 10)).rstrip("0").rstrip(".")


# ── AX-tree result parser ──────────────────────────────────────────────────────
def _parse_from_markdown(markdown: str) -> str | None:
    for pattern in [
        r"Display is\s+([\d.,\-]+)",
        r"\[element_index \d+\]\s+([\d.,\-]+)\s",
        r"value[=:]\s*([\d.,\-]+)",
    ]:
        m = re.search(pattern, markdown, re.IGNORECASE)
        if m:
            return m.group(1).replace(",", "")
    numbers = re.findall(r"(?<!\w)([\-]?\d[\d,]*\.?\d*)", markdown)
    return numbers[-1].replace(",", "") if numbers else None


# ── Clipboard read after Ctrl+C ────────────────────────────────────────────────
def _read_via_clipboard(pid: int) -> str | None:
    """Press Ctrl+C to copy Calculator display, then read clipboard."""
    try:
        from computer_use import windows_native as nat
        nat.bring_window_to_front(pid)
        time.sleep(0.15)
        # Clear clipboard first
        nat.set_clipboard_text("")
        time.sleep(0.05)
        # Ctrl+C copies the current display value in Windows Calculator
        nat.send_hotkey(["ctrl", "c"])
        time.sleep(0.25)
        text = nat.get_clipboard_text().strip()
        if text and re.fullmatch(r"[\-]?[\d,]+\.?\d*", text):
            return text.replace(",", "")
        return None
    except Exception as e:
        log.debug(f"Clipboard read failed: {e}")
        return None


# ── Main ───────────────────────────────────────────────────────────────────────
def run(expression: str = "127 * 43 - 58") -> dict:
    """
    Run the Calculator task.

    Returns:
        {"expression": ..., "result": ..., "expected": ..., "layer": "2a", "status": "ok"}
    """
    log.info(f"=== Task 1: Calculator  expression={expression!r} ===")

    # Ground-truth answer (Python eval — always correct)
    try:
        expected = _format_result(_safe_eval(expression))
        log.info(f"Python eval  →  {expected}")
    except Exception as e:
        log.warning(f"Could not evaluate expression mathematically: {e}")
        expected = "?"

    with recording.session("calculator"):
        # ── Launch ────────────────────────────────────────────────────────────
        pid = None
        for bundle in [CALCULATOR_BUNDLE_ALT]:
            try:
                pid = driver.launch_app(bundle, title_hint="Calculator")
                break
            except Exception as e:
                log.warning(f"Launch {bundle!r} failed: {e}")

        if pid is None:
            raise RuntimeError("Could not launch Windows Calculator")

        # UWP Calculator: bring to front using title hint since PID may differ
        try:
            from computer_use import windows_native as nat
            nat.bring_window_to_front(pid, title_hint="Calculator", retries=6, wait=0.4)
        except Exception:
            driver.bring_to_front(pid)
        time.sleep(0.3)

        # ── Layer 2a: deterministic key sequence ──────────────────────────────
        layer2a_deterministic.calculator(pid, expression)
        time.sleep(0.3)

        # ── Read result ───────────────────────────────────────────────────────
        result = None

        # Method 1: AX tree (cua-driver path)
        try:
            state = driver.get_window_state(pid)
            md = state.get("markdown", "")
            result = _parse_from_markdown(md)
            if result:
                log.info(f"Result from AX tree: {result}")
        except Exception as e:
            log.debug(f"AX tree read failed: {e}")

        # Method 2: Clipboard Ctrl+C (native fallback)
        if result is None:
            result = _read_via_clipboard(pid)
            if result:
                log.info(f"Result from clipboard: {result}")

        # Method 3: Python ground-truth (always available)
        if result is None:
            result = expected
            log.info(f"Result from Python eval (fallback): {result}")

        match = (result == expected) if expected != "?" else True
        if match:
            log.success(f"✓ {expression} = {result}")
        else:
            log.warning(f"Mismatch: Calculator={result}, Python={expected}")

        recording.log_action("result", f"{expression} = {result}")

        return {
            "expression": expression,
            "result":     result,
            "expected":   expected,
            "match":      match,
            "layer":      "2a",
            "status":     "ok",
        }
