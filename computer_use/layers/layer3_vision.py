"""
Layer 3 — Vision
screenshot → set-of-marks overlay → vision LLM → (x,y) click.
Last resort; ~10× the cost of Layer 2b.
"""
import io
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from computer_use import driver, llm_client, recording
from computer_use.logger import log

_MARK_COLS   = 6    # horizontal grid divisions
_MARK_ROWS   = 5    # vertical grid divisions
_BOX_PADDING = 10   # pixels of padding inside each box
_ACCENT      = "#FFD700"   # gold box colour


def _draw_marks(image: Image.Image) -> tuple[Image.Image, list[dict]]:
    """
    Divide the image into a grid of numbered regions.
    Returns (annotated_image, regions) where each region is:
        {"mark": int, "x1": int, "y1": int, "x2": int, "y2": int, "cx": int, "cy": int}
    """
    w, h = image.size
    cw = w // _MARK_COLS
    ch = h // _MARK_ROWS

    overlay = image.copy().convert("RGBA")
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except Exception:
        font = ImageFont.load_default()

    regions = []
    mark = 0
    for row in range(_MARK_ROWS):
        for col in range(_MARK_COLS):
            x1 = col * cw + _BOX_PADDING
            y1 = row * ch + _BOX_PADDING
            x2 = x1 + cw - 2 * _BOX_PADDING
            y2 = y1 + ch - 2 * _BOX_PADDING
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2

            # Semi-transparent box
            draw.rectangle([x1, y1, x2, y2], outline=_ACCENT, width=2)
            draw.text((x1 + 4, y1 + 2), str(mark), fill=_ACCENT, font=font)

            regions.append({"mark": mark, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "cx": cx, "cy": cy})
            mark += 1

    result = Image.alpha_composite(overlay, Image.new("RGBA", image.size, (0, 0, 0, 0)))
    return result.convert("RGB"), regions


def _save_debug_image(image: Image.Image, task: str):
    debug_dir = Path(__file__).parent.parent.parent / "recordings" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    import time
    path = debug_dir / f"{task}_{time.strftime('%H%M%S')}.png"
    image.save(path)
    log.debug(f"Set-of-marks image saved → {path}")


_VISION_SYSTEM = """
You are controlling a desktop application by analysing a screenshot.
The screenshot has numbered gold boxes overlaid on it (set-of-marks).
Each box has a number in its top-left corner.

Respond ONLY with a JSON object (no markdown fences) in one of these shapes:
  {"action": "click",     "mark": <int>,   "reason": "<brief>"}
  {"action": "key",       "key": "<name>", "reason": "<brief>"}
  {"action": "done",      "result": "<text>"}

- "mark" must be a number from the image.
- "key" values: ArrowUp, ArrowDown, ArrowLeft, ArrowRight, Enter, Escape, Tab, space.
""".strip()


def run(pid: int, goal: str, task_name: str = "vision") -> dict:
    """
    Capture screenshot, overlay set-of-marks, ask vision LLM, execute action.
    Returns the raw action dict from the LLM.
    """
    log.info(f"Layer 3: vision  goal={goal!r}")

    raw_bytes = driver.take_screenshot(pid)
    image = Image.open(io.BytesIO(raw_bytes))
    marked, regions = _draw_marks(image)
    _save_debug_image(marked, task_name)

    prompt = f"Goal: {goal}\n\nAnalyse the screenshot and return the best action."
    response_text = llm_client.vision(marked, prompt, system=_VISION_SYSTEM)

    # Strip markdown fences if any
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    text = text.strip()

    _fallback = {"action": "key", "key": "ArrowRight", "reason": "unparseable LLM response fallback"}

    if not text:
        log.warning("Layer 3: LLM returned empty response — defaulting to ArrowRight")
        action = {"action": "key", "key": "ArrowRight", "reason": "empty LLM response fallback"}
    else:
        action = None
        # Direct parse
        try:
            action = json.loads(text)
        except json.JSONDecodeError:
            pass
        # Regex: extract first {...} block containing "action"
        if action is None:
            for m in re.finditer(r'\{[^{}]+\}', text, re.DOTALL):
                try:
                    candidate = json.loads(m.group(0))
                    if "action" in candidate:
                        action = candidate
                        log.debug(f"Layer 3: extracted JSON from prose: {action}")
                        break
                except json.JSONDecodeError:
                    continue
        if action is None:
            log.warning(f"Layer 3: could not parse JSON from {text[:120]!r} — defaulting to ArrowRight")
            action = _fallback

    log.info(f"Layer 3 LLM action: {action}")

    if action.get("action") == "click":
        mark_idx = action["mark"]
        if 0 <= mark_idx < len(regions):
            r = regions[mark_idx]
            driver.click_at(pid, r["cx"], r["cy"])
            recording.log_action("vision_click", f"mark={mark_idx} ({r['cx']},{r['cy']})")
        else:
            log.warning(f"Vision: mark {mark_idx} out of range")

    elif action.get("action") == "key":
        key = action["key"]
        driver.press_key(pid, key)
        recording.log_action("vision_key", key)

    return action
