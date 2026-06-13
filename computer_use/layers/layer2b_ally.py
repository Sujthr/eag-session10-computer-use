"""
Layer 2b — A11y Tree
AX tree markdown → cheap LLM → element_index action.
Workhorse layer; most runs should land here.
"""
import json
from computer_use import driver, llm_client, recording
from computer_use.logger import log

MAX_TURNS = 12

_SYSTEM = """
You are a desktop automation agent.
You receive the AX tree of the current window as Markdown.
Every interactive element is tagged [element_index N].

Respond ONLY with a JSON object (no markdown fences) matching one of:

  {"verdict": "act",      "element_index": <int>, "action": "click",    "value": ""}
  {"verdict": "act",      "element_index": <int>, "action": "type",     "value": "<text to type>"}
  {"verdict": "act",      "element_index": <int>, "action": "hotkey",   "value": "<key combo e.g. ctrl+s>"}
  {"verdict": "done",     "result": "<final answer or confirmation>"}
  {"verdict": "escalate", "reason": "<why AX is insufficient>"}

Rules:
- Prefer the lowest element_index that matches the goal.
- Return "done" only when the goal is fully achieved.
- Return "escalate" only if the target is genuinely missing from the tree.
""".strip()


class EscalateToVision(Exception):
    pass


def _dispatch(pid: int, action: dict):
    verdict = action["verdict"]
    if verdict != "act":
        return
    idx = action["element_index"]
    act = action.get("action", "click")
    val = action.get("value", "")

    if act == "click":
        driver.click(pid, idx)
        recording.log_action("click", f"element={idx}")
    elif act == "type":
        driver.type_text(pid, idx, val)
        recording.log_action("type", f"element={idx} text={val!r}")
    elif act == "hotkey":
        keys = [k.strip() for k in val.replace("+", " ").split()]
        driver.hotkey(pid, keys)
        recording.log_action("hotkey", val)
    else:
        log.warning(f"Unknown action {act!r}, skipping")


def run(pid: int, goal: str, window_id: int = 0, max_turns: int = MAX_TURNS) -> str:
    """
    Scan → LLM act → verify loop.
    Returns the final result string on success.
    Raises EscalateToVision if the LLM decides the tree is insufficient.
    """
    log.info(f"Layer 2b: goal={goal!r}")
    last_action_key: tuple | None = None
    repeat_count = 0

    for turn in range(1, max_turns + 1):
        log.debug(f"  turn {turn}/{max_turns}")

        state = driver.get_window_state(pid, window_id)
        if state.get("element_count", 0) == 0:
            raise EscalateToVision("element_count=0 in Layer 2b")

        prompt = f"Goal: {goal}\n\nAX Tree:\n{state['markdown']}"
        action = llm_client.chat_json(prompt, system=_SYSTEM)
        log.debug(f"  LLM verdict: {action}")

        if action["verdict"] == "done":
            result = action.get("result", "done")
            log.success(f"Layer 2b: done  result={result!r}")
            return result

        if action["verdict"] == "escalate":
            reason = action.get("reason", "no reason given")
            log.warning(f"Layer 2b: escalate  reason={reason}")
            raise EscalateToVision(reason)

        # Detect repeated identical actions — means the tree isn't changing
        # (common with UWP/static AX trees that don't reflect typed content)
        action_key = (
            action.get("element_index"),
            action.get("action"),
            action.get("value", "")[:80],  # truncate long text for comparison
        )
        if action_key == last_action_key:
            repeat_count += 1
            if repeat_count >= 2:
                log.warning(f"Layer 2b: same action repeated {repeat_count+1}x — assuming done")
                return action.get("value", "done")
        else:
            repeat_count = 0
        last_action_key = action_key

        _dispatch(pid, action)

    raise EscalateToVision(f"Max turns ({max_turns}) exceeded without completion")
