"""
Session 9 catalogue entry point for the computer-use skill.

Drop-in usage (add one line to Session 9 skills.py):

    if skill.name == "computer":
        from computer_use.skill import run as computer_run
        return computer_run(goal)
"""
import re
import sys
import time
import threading
from pathlib import Path
from typing import Callable

from computer_use import driver, config
from computer_use.tasks import task_calculator, task_vscode, task_browser_game
from computer_use.logger import log

SKILL_NAME        = "computer"
SKILL_DESCRIPTION = (
    "Drive real desktop applications on Windows via cua-driver. "
    "Supports: calculator <expr>, vscode, browser_game [<moves>]."
)

# ── Task routing ──────────────────────────────────────────────────────────────

def _route(goal: str) -> tuple[Callable, dict]:
    g = goal.lower().strip()

    if "calculator" in g or re.search(r"[\d\+\-\*\/×÷]", g):
        # Extract the expression if present
        m = re.search(r"calculator\s+(.*)", goal, re.IGNORECASE)
        expr = m.group(1).strip() if m else goal.strip()
        return task_calculator.run, {"expression": expr}

    if "vscode" in g or "vs code" in g or "visual studio" in g:
        return task_vscode.run, {}

    if "game" in g or "2048" in g or "browser" in g:
        m = re.search(r"(\d+)\s*moves?", g)
        moves = int(m.group(1)) if m else 5
        return task_browser_game.run, {"moves": moves}

    raise ValueError(
        f"No computer-use task matched goal: {goal!r}\n"
        "Supported: 'calculator <expr>', 'vscode', 'browser_game [N moves]'"
    )


# ── Status reporting ──────────────────────────────────────────────────────────

def _print_provider_status():
    log.info("API providers available: " + ", ".join(config.PROVIDER_ORDER))
    gemini_count = len(config.GEMINI_KEYS)
    log.info(f"Gemini keys loaded: {gemini_count}")


# ── Public entry point ────────────────────────────────────────────────────────

def run(goal: str, config_override: dict | None = None) -> dict:
    """
    Main entry point.  Maps natural-language goal to a task and runs it.
    Returns the task result dict.
    """
    log.info(f"Computer-use skill: goal={goal!r}")
    _print_provider_status()

    # Ensure cua-driver daemon is running
    try:
        driver.ensure_daemon()
    except driver.CuaNotInstalledError as e:
        log.error(str(e))
        return {"status": "error", "error": str(e)}

    fn, kwargs = _route(goal)

    start = time.monotonic()
    try:
        result = fn(**kwargs)
    except Exception as e:
        log.error(f"Task failed: {e}")
        result = {"status": "error", "error": str(e)}
    finally:
        elapsed = time.monotonic() - start
        log.info(f"Task finished in {elapsed:.2f}s")

    result["elapsed_s"] = round(elapsed, 2)
    return result


# ── CLI shim (python -m computer_use.skill) ───────────────────────────────────

if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="Computer-Use Skill CLI")
    parser.add_argument("goal", nargs="?", default="calculator 127 * 43 - 58",
                        help="Natural-language goal")
    parser.add_argument("--task", choices=["calculator", "vscode", "browser_game"],
                        help="Override task directly")
    parser.add_argument("--expression", default="127 * 43 - 58")
    parser.add_argument("--moves",      type=int, default=5)
    args = parser.parse_args()

    if args.task == "calculator":
        result = task_calculator.run(args.expression)
    elif args.task == "vscode":
        result = task_vscode.run()
    elif args.task == "browser_game":
        result = task_browser_game.run(args.moves)
    else:
        result = run(args.goal)

    print(json.dumps(result, indent=2))
