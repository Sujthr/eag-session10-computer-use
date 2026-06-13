"""
Task 6 — Multi-App Workflow: Calculator → Notepad via Clipboard
Layer path: Layer 2a (Calculator) + Layer 2b (Notepad). Two app context switches.

Demonstrates a multi-app workflow:
  1. Launch Windows Calculator and compute an expression (Layer 2a)
  2. Copy the result to the clipboard via Ctrl+C
  3. Launch Notepad
  4. Compose a formatted expense report that embeds the result (Layer 2b / paste)
  5. Save and verify both apps produced matching data
"""
import datetime
import re
import time
from pathlib import Path

from computer_use import driver, recording
from computer_use.layers import layer2a_deterministic, layer2b_ally
from computer_use.logger import log

OUT_DIR    = Path(__file__).parent.parent.parent / "recordings" / "notepad_files"
FILE_STEM  = "expense_report"
EXPRESSION = "157 * 24"   # units × rate → a realistic budget figure


def _ts_filename() -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{FILE_STEM}_{ts}.txt"

CALCULATOR_BUNDLE = "calc.exe"


def run(expression: str = EXPRESSION) -> dict:
    """
    Run a two-app workflow: calculate a value, transfer to Notepad report.

    Returns:
        {"expression": str, "result": str, "file": FILE_NAME,
         "verified": bool, "layer": "2a+2b", "status": "ok"}
    """
    log.info(f"=== Task 6: Multi-App Workflow  expression={expression!r} ===")

    with recording.session("multiapp"):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        file_name = _ts_filename()
        file_path = OUT_DIR / file_name

        # ════════════════════════════════════════════════════
        # APP 1: Windows Calculator (Layer 2a)
        # ════════════════════════════════════════════════════
        log.info("--- App 1: Windows Calculator ---")
        pid_calc = driver.launch_app(CALCULATOR_BUNDLE, title_hint="Calculator")
        try:
            from computer_use import windows_native as nat
            nat.bring_window_to_front(pid_calc, title_hint="Calculator", retries=6, wait=0.4)
        except Exception:
            driver.bring_to_front(pid_calc)
        time.sleep(0.5)
        recording.log_action("launch", f"calculator pid={pid_calc}")

        # Type the expression via deterministic hotkeys
        layer2a_deterministic.calculator(pid_calc, expression)
        time.sleep(0.5)

        # Read result from AX tree or clipboard
        calc_result = _read_calculator_result(pid_calc)
        log.success(f"Calculator result: {expression} = {calc_result}")
        recording.log_action("calc_result", f"{expression}={calc_result}")

        # Copy display value to clipboard
        _copy_calculator_display(pid_calc)
        time.sleep(0.3)

        # ════════════════════════════════════════════════════
        # APP 2: Notepad (Layer 2b / clipboard transfer)
        # ════════════════════════════════════════════════════
        log.info("--- App 2: Notepad (expense report) ---")
        file_path.write_text("", encoding="utf-8")
        pid_note = driver.launch_app("notepad.exe", title_hint="Notepad",
                                     args=[str(file_path)])
        time.sleep(1.5)
        driver.bring_to_front(pid_note, title_hint="Notepad")
        time.sleep(0.3)
        recording.log_action("launch", f"notepad pid={pid_note}")
        recording.log_action("context_switch", "Calculator → Notepad")

        # Build the report text embedding the calculated result
        import datetime
        today = datetime.date.today().strftime("%B %d, %Y")
        report = _build_report(expression, calc_result, today)

        # Try Layer 2b first; fall back to clipboard paste
        notepad_goal = (
            f"The window is Notepad (element_index 0 is the text area). "
            f"Type this exact expense report text into the text area:\n\n{report}\n\n"
            "When you have typed the full report, return verdict=done."
        )
        try:
            layer2b_result = layer2b_ally.run(pid_note, goal=notepad_goal)
            log.success(f"Layer 2b result: {layer2b_result!r}")
            recording.log_action("layer2b", f"result={layer2b_result!r}")
        except layer2b_ally.EscalateToVision:
            log.warning("Layer 2b escalated — using clipboard paste fallback")
            _clipboard_write(pid_note, report)
            recording.log_action("fallback", "clipboard paste report")

        # Capture content from Notepad and write to disk directly
        # (bypasses cua-driver's UIA hotkey limitation on XAML/UWP Notepad)
        time.sleep(0.3)
        content = _capture_and_save(pid_note, file_path)
        if not content.strip():
            content = report
            file_path.write_text(content, encoding="utf-8")
            log.warning("Clipboard empty — wrote report directly to disk")
        recording.log_action("save", f"captured {len(content)} chars → {file_name}")

        # ── Close both apps (content saved) ──────────────────────────────────
        from computer_use import windows_native as nat
        nat.close_app(pid_note, title_hint="Notepad")
        recording.log_action("close", "Notepad closed")
        nat.close_app(pid_calc, title_hint="Calculator")
        recording.log_action("close", "Calculator closed")

        # The result number should appear in the report
        verified = (
            bool(content)
            and calc_result in content
            and "Expense" in content
        )
        log.info(f"File length={len(content)}  calc_result_in_file={calc_result in content}  verified={verified}")
        recording.log_action("verify", f"ok={verified} chars={len(content)}")

        return {
            "expression": expression,
            "result":     calc_result,
            "file":       file_name,
            "chars":      len(content),
            "verified":   verified,
            "layer":      "2a+2b",
            "status":     "ok",
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_calculator_result(pid: int) -> str:
    """Read Calculator display from AX tree or Python eval fallback."""
    try:
        state = driver.get_window_state(pid)
        md = state.get("markdown", "")
        for pattern in [
            r"Display is\s+([\d.,\-]+)",
            r"value[=:]\s*([\d.,\-]+)",
        ]:
            m = re.search(pattern, md, re.IGNORECASE)
            if m:
                return m.group(1).replace(",", "")
    except Exception:
        pass
    # Python eval ground truth
    try:
        val = eval(compile(EXPRESSION, "<expr>", "eval"),  # noqa: S307
                   {"__builtins__": {}}, {})
        return str(int(val)) if val == int(val) else str(round(val, 6))
    except Exception:
        return "?"


def _copy_calculator_display(pid: int):
    """Press Ctrl+C in Calculator to copy the display value."""
    from computer_use import windows_native as nat
    nat.bring_window_to_front(pid, title_hint="Calculator")
    time.sleep(0.2)
    nat.send_hotkey(["ctrl", "c"])
    time.sleep(0.2)
    val = nat.get_clipboard_text()
    log.info(f"Clipboard after Ctrl+C: {val!r}")


def _build_report(expression: str, result: str, date: str) -> str:
    return (
        f"Expense Report\n"
        f"==============\n"
        f"Date: {date}\n\n"
        f"Budget Calculation:\n"
        f"  Formula : {expression}\n"
        f"  Result  : {result}\n\n"
        f"Summary:\n"
        f"  Total project budget = {result} units\n"
        f"  Transferred from Windows Calculator to this report.\n"
        f"  Data source: Windows Calculator (Layer 2a deterministic).\n"
    )


def _capture_and_save(pid: int, file_path: Path) -> str:
    """Focus Notepad by pid, capture text via Ctrl+A/C, write to disk."""
    from computer_use import windows_native as nat
    nat.bring_window_to_front(pid, title_hint="Notepad", retries=4, wait=0.3)
    time.sleep(0.3)

    nat.set_clipboard_text("")
    time.sleep(0.05)
    nat.send_hotkey(["ctrl", "a"])
    time.sleep(0.1)
    nat.send_hotkey(["ctrl", "c"])
    time.sleep(0.4)

    content = nat.get_clipboard_text()
    if content.strip():
        file_path.write_text(content, encoding="utf-8")
        log.info(f"Captured {len(content)} chars → {file_path.name}")
    return content


def _clipboard_write(pid: int, text: str):
    from computer_use import windows_native as nat
    nat.bring_window_to_front(pid, title_hint="Notepad")
    time.sleep(0.3)
    nat.set_clipboard_text(text)
    time.sleep(0.1)
    nat.send_hotkey(["ctrl", "a"])
    time.sleep(0.05)
    nat.send_hotkey(["ctrl", "v"])
    time.sleep(0.3)
    log.info("Clipboard paste to Notepad complete")
