"""
Task 5 — Email Draft Composition with Verification (Layer 2b)
Layer path: Layer 2b (AX tree → cheap LLM → type + re-read → verify).

Demonstrates Layer 2b with strong verification:
  1. Launch Notepad as the composition surface
  2. Layer 2b loop: LLM types a professional email draft
  3. Capture content via clipboard and write to disk
  4. Verification pass: LLM reviews the draft and confirms all required
     fields (To:, Subject:, Body with apology + new timeline) are present
"""
import datetime
import time
from pathlib import Path

from computer_use import driver, llm_client, recording
from computer_use.layers import layer2b_ally
from computer_use.logger import log

OUT_DIR   = Path(__file__).parent.parent.parent / "recordings" / "notepad_files"
FILE_STEM = "email_draft"


def _ts_filename() -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{FILE_STEM}_{ts}.txt"

_COMPOSE_GOAL = (
    "The window is Notepad. element_index 0 is the only text area.\n"
    "STEP 1: Issue exactly ONE type action targeting element_index 0 with this exact text:\n\n"
    "To: team@company.com\n"
    "Subject: Project Delay - Updated Timeline\n\n"
    "Body:\n"
    "I sincerely apologise for the delay in delivering the Q3 module. "
    "We encountered an unexpected technical issue with our API integration. "
    "The revised delivery date is now set for two weeks from today. "
    "Thank you for your patience.\n\n"
    "Best regards,\nThe Engineering Team\n\n"
    "STEP 2: Immediately after that single type action, your next response MUST be "
    '{\"verdict\": \"done\", \"result\": \"email draft typed\"}. '
    "Do NOT type again. Do NOT issue any other action."
)

_VERIFY_SYSTEM = (
    "You are a strict email draft reviewer. "
    "You receive the raw text of an email draft. "
    "Check whether ALL of these are present: "
    "1) a 'To:' line, 2) a 'Subject:' line, 3) a 'Body:' section, "
    "4) an apology in the body, 5) a new deadline or date mentioned. "
    "Respond ONLY with JSON (no markdown fences): "
    '{"verified": true/false, "missing": ["list of missing items or empty list"], '
    '"summary": "one sentence"}'
)

_FALLBACK_DRAFT = """To: team@company.com
Subject: Project Delay Notification — Updated Timeline

Body:
I want to sincerely apologise for the delay in delivering the Q3 module.
We encountered an unexpected technical issue with our third-party API integration
that required a full redesign of the data pipeline.
The revised delivery date is now set for two weeks from today.
Thank you for your patience and understanding.

Best regards,
The Engineering Team
"""


def run() -> dict:
    """
    Compose and verify an email draft in Notepad using Layer 2b.

    Returns:
        {"file": FILE_NAME, "verified": bool, "missing": list, "layer": "2b", "status": "ok"}
    """
    log.info("=== Task 5: Email Draft — Compose + Verify via Layer 2b ===")

    with recording.session("email_draft"):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        file_name = _ts_filename()
        file_path = OUT_DIR / file_name
        file_path.write_text("", encoding="utf-8")

        # ── Launch Notepad ────────────────────────────────────────────────────
        log.info(f"Launching Notepad → {file_path}")
        pid = driver.launch_app("notepad.exe", title_hint="Notepad",
                                args=[str(file_path)])
        time.sleep(1.5)
        driver.bring_to_front(pid, title_hint="Notepad")
        time.sleep(0.3)
        recording.log_action("launch", f"notepad pid={pid}")

        # ── Layer 2b: LLM composes the draft ─────────────────────────────────
        compose_result = ""
        used_fallback = False
        try:
            compose_result = layer2b_ally.run(pid, goal=_COMPOSE_GOAL, max_turns=3)
            log.success(f"Layer 2b compose result: {compose_result!r}")
            recording.log_action("layer2b_compose", f"result={compose_result!r}")
        except layer2b_ally.EscalateToVision:
            log.warning("Layer 2b escalated — using clipboard fallback for draft")
            _clipboard_write(pid, _FALLBACK_DRAFT)
            compose_result = "fallback_written"
            used_fallback = True
            recording.log_action("fallback", "clipboard paste draft")

        # ── Capture content from Notepad and write to disk ────────────────────
        time.sleep(0.5)
        content = _capture_and_save(pid, file_path)
        if not content.strip():
            content = _FALLBACK_DRAFT
            file_path.write_text(content, encoding="utf-8")
            used_fallback = True
        log.info(f"File content ({len(content)} chars)")
        recording.log_action("save", f"captured {len(content)} chars → {file_name}")

        # ── Close Notepad (content already saved to disk) ─────────────────────
        from computer_use import windows_native as nat
        nat.close_app(pid, title_hint="Notepad")
        recording.log_action("close", "Notepad closed")

        # ── Verification pass: LLM reviews the draft ──────────────────────────
        verified = False
        missing: list[str] = []
        verify_summary = ""
        if content.strip():
            log.info("Running LLM verification pass…")
            try:
                verify_prompt = f"Email draft to review:\n\n{content}"
                verdict = llm_client.chat_json(verify_prompt, system=_VERIFY_SYSTEM)
                verified       = bool(verdict.get("verified", False))
                missing        = verdict.get("missing", [])
                verify_summary = verdict.get("summary", "")
                log.info(f"Verification: verified={verified}  missing={missing}")
                log.info(f"Verification summary: {verify_summary}")
                recording.log_action("verify_llm", f"ok={verified} missing={missing}")
            except Exception as e:
                log.warning(f"LLM verification failed: {e}")
                required = ["To:", "Subject:", "Body:"]
                missing  = [r for r in required if r.lower() not in content.lower()]
                verified = len(missing) == 0
        else:
            missing = ["To:", "Subject:", "Body:"]

        if verified:
            log.success("Email draft verified — all required fields present")
        else:
            log.warning(f"Verification failed — missing: {missing}")

        recording.log_action("result", f"verified={verified} chars={len(content)}")

        return {
            "file":          file_name,
            "chars":         len(content),
            "verified":      verified,
            "missing":       missing,
            "summary":       verify_summary,
            "used_fallback": used_fallback,
            "layer":         "2b",
            "status":        "ok",
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

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
