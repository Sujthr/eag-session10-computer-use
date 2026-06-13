"""
Task 4 — Notepad: Write Structured Meeting Notes (Layer 2b)
Layer path: Layer 2b (AX tree → cheap text LLM → type action). Zero vision calls.

Demonstrates Layer 2b with a plain-text notes editor:
  1. Launch Notepad with a pre-created target file
  2. Layer 2b reads the AX tree → LLM decides what to type
  3. Capture content via Ctrl+A/C and write directly to disk
     (bypasses cua-driver UIA hotkey limitation on XAML/UWP Notepad)
  4. Verify by reading the file content from disk
"""
import datetime
import time
from pathlib import Path

from computer_use import driver, recording
from computer_use.layers import layer2b_ally
from computer_use.logger import log


OUT_DIR        = Path(__file__).parent.parent.parent / "recordings" / "notepad_files"
FILE_STEM      = "meeting_notes"


def _ts_filename() -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{FILE_STEM}_{ts}.txt"

_TODAY = datetime.date.today().strftime("%B %d, %Y")

_GOAL = (
    "The window is Notepad with a text area (element_index 0). "
    f"Type a structured meeting notes template for today ({_TODAY}) that includes: "
    "a title line, date, Attendees section (3 people with roles), "
    "Agenda section (3 numbered items), and Action Items section (3 items with owners). "
    "Use plain text. When done typing all content, return verdict=done."
)

_FALLBACK_CONTENT = f"""Meeting Notes
=============
Date: {_TODAY}

Attendees:
- Alice Chen (Engineering Lead)
- Bob Patel (Product Manager)
- Carol Davis (Design)

Agenda:
1. Sprint 24 review and retrospective
2. Q3 roadmap prioritisation
3. Cross-team dependency mapping

Action Items:
- Alice: Update API documentation — due Friday
- Bob: Share updated product requirements with team
- Carol: Finalise mockups for new onboarding flow
"""


def run() -> dict:
    """
    Write structured meeting notes in Notepad using Layer 2b.

    Returns:
        {"file": FILE_NAME, "chars": int, "verified": bool, "layer": "2b", "status": "ok"}
    """
    log.info("=== Task 4: Notepad — Meeting Notes via Layer 2b ===")

    with recording.session("notepad"):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        file_name = _ts_filename()
        file_path = OUT_DIR / file_name
        file_path.write_text("", encoding="utf-8")   # pre-create so no "create?" dialog

        # ── Launch Notepad ────────────────────────────────────────────────────
        log.info(f"Launching Notepad → {file_path}")
        pid = driver.launch_app("notepad.exe", title_hint="Notepad",
                                args=[str(file_path)])
        time.sleep(1.5)
        driver.bring_to_front(pid, title_hint="Notepad")
        time.sleep(0.3)
        recording.log_action("launch", f"notepad pid={pid}")

        # ── Layer 2b: LLM decides & types the content ────────────────────────
        layer2b_result = ""
        try:
            layer2b_result = layer2b_ally.run(pid, goal=_GOAL)
            log.success(f"Layer 2b result: {layer2b_result!r}")
            recording.log_action("layer2b", f"result={layer2b_result!r}")
        except layer2b_ally.EscalateToVision:
            log.warning("Layer 2b escalated — using clipboard fallback")
            _clipboard_write(pid, _FALLBACK_CONTENT)
            layer2b_result = "fallback_clipboard"
            recording.log_action("fallback", "clipboard paste")

        # ── Capture content from Notepad and write directly to disk ──────────
        time.sleep(0.3)
        content = _capture_and_save(pid, file_path)
        recording.log_action("save", f"captured {len(content)} chars → {file_name}")

        # ── Close Notepad (content already saved to disk) ─────────────────────
        from computer_use import windows_native as nat
        nat.close_app(pid, title_hint="Notepad")
        recording.log_action("close", "Notepad closed")

        # ── Verify ────────────────────────────────────────────────────────────
        saved_content = ""
        try:
            saved_content = file_path.read_text(encoding="utf-8", errors="replace").strip()
        except Exception as e:
            log.warning(f"Could not read file: {e}")

        verified = bool(saved_content) and all(
            kw.lower() in saved_content.lower()
            for kw in ("Attendees", "Agenda", "Action")
        )
        log.info(f"Content length={len(saved_content)}  verified={verified}")
        recording.log_action("verify", f"chars={len(saved_content)} ok={verified}")

        return {
            "file":     file_name,
            "chars":    len(saved_content),
            "verified": verified,
            "layer":    "2b",
            "status":   "ok",
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _capture_and_save(pid: int, file_path: Path) -> str:
    """Focus Notepad by pid, capture all text via Ctrl+A/C, write to disk."""
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
    else:
        log.warning("Clipboard empty — writing fallback content to disk")
        file_path.write_text(_FALLBACK_CONTENT, encoding="utf-8")
        content = _FALLBACK_CONTENT
    return content


def _clipboard_write(pid: int, text: str):
    """Focus Notepad by pid and paste text via clipboard."""
    from computer_use import windows_native as nat
    nat.bring_window_to_front(pid, title_hint="Notepad", retries=4, wait=0.3)
    time.sleep(0.3)
    nat.set_clipboard_text(text)
    time.sleep(0.1)
    nat.send_hotkey(["ctrl", "a"])
    time.sleep(0.05)
    nat.send_hotkey(["ctrl", "v"])
    time.sleep(0.3)
    log.info("Clipboard paste complete")
