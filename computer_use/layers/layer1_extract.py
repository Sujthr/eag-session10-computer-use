"""
Layer 1 — Extract
Read content directly from the AX tree. Zero LLM cost.
"""
from computer_use import driver
from computer_use.logger import log


def extract(pid: int, window_id: int = 0) -> str | None:
    """
    Return the AX tree markdown if the window has elements, else None.
    None signals the cascade to try the next layer.
    """
    state = driver.get_window_state(pid, window_id)
    count = state.get("element_count", 0)

    if count == 0:
        log.debug("Layer 1: element_count=0, cascade to Layer 2a")
        return None

    log.debug(f"Layer 1: {count} elements extracted")
    return state.get("markdown", "")


def find_text(pid: int, search: str, window_id: int = 0) -> str | None:
    """Return a snippet of the AX tree that contains the search string."""
    md = extract(pid, window_id)
    if md is None:
        return None
    lower = md.lower()
    idx = lower.find(search.lower())
    if idx == -1:
        return None
    return md[max(0, idx - 40): idx + 200]
